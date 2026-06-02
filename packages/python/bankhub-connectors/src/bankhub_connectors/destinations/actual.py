# -*- coding: utf-8 -*-
"""Actual Budget destination.

Uses the optional ``actualpy`` library to talk to a self-hosted Actual
server.  Actual stores amounts as integer minor units (cents) with negative
= outflow, and dedups imports on ``imported_id`` (we use ``external_id``).

The amount conversion is pure/testable; the live push requires ``actualpy``
and a reachable Actual server.
"""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from bankhub.errors import ConfigError, MissingDependencyError
from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination


def to_minor_units(amount: Decimal) -> int:
    """Convert a decimal amount to integer cents (negative = outflow)."""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@register_destination("actual")
class ActualDestination(Destination):
    """Import transactions into an Actual Budget file.

    Options
    -------
    server_url
        Actual server URL (``$ACTUAL_SERVER_URL``).
    password
        Server password (``$ACTUAL_PASSWORD``).
    budget
        Budget/sync id or name (``$ACTUAL_BUDGET``).
    encryption_password
        Optional end-to-end encryption password (``$ACTUAL_ENCRYPTION_PASSWORD``).

    Map source accounts to Actual account names/ids via the account map
    (``actual:`` section).
    """

    requires = "actualpy"

    def __init__(self, server_url: str = None, password: str = None,
                 budget: str = None, encryption_password: str = None, **options):
        super().__init__(**options)
        self.server_url = server_url or os.environ.get("ACTUAL_SERVER_URL")
        self.password = password or os.environ.get("ACTUAL_PASSWORD")
        self.budget = budget or os.environ.get("ACTUAL_BUDGET")
        self.encryption_password = encryption_password \
            or os.environ.get("ACTUAL_ENCRYPTION_PASSWORD")

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        if not (self.server_url and self.password and self.budget):
            raise ConfigError(
                "Actual destination needs server_url, password and budget "
                "(options or $ACTUAL_SERVER_URL/$ACTUAL_PASSWORD/$ACTUAL_BUDGET)")
        try:
            from actual import Actual
            from actual.queries import create_transaction
        except ImportError:
            raise MissingDependencyError("actual", "actualpy")

        missing = [t for t in transactions if not t.target_account]
        if missing:
            raise ConfigError(
                "Actual requires a destination account per transaction; map "
                "source accounts to Actual account names/ids (account map 'actual:').")

        results: List[PushResult] = []
        try:
            with Actual(base_url=self.server_url, password=self.password,
                        file=self.budget,
                        encryption_password=self.encryption_password) as actual:
                for txn in transactions:
                    create_transaction(
                        actual.session,
                        date=txn.date,
                        account=txn.target_account,
                        payee=txn.payee or "",
                        notes=txn.notes or "",
                        amount=Decimal(txn.amount),
                        imported_id=txn.external_id,
                        cleared=(txn.status == "posted"),
                    )
                    results.append(PushResult(txn.external_id, "created"))
                actual.commit()
        except Exception as exc:  # surface a clean per-batch error
            return [PushResult(t.external_id, "error", error=str(exc))
                    for t in transactions]
        return results
