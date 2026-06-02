# -*- coding: utf-8 -*-
"""Lunchmoney source: pull transactions back out of Lunchmoney.

Useful for reconciliation (learning the remote ids of transactions we
pushed) and for fanning Lunchmoney data out to other destinations.
"""

from __future__ import annotations

import datetime as _dt
import os
from decimal import Decimal
from typing import Any, Dict, Iterator, List

from bankhub.errors import ConfigError, MissingDependencyError
from bankhub.models import POSTED, Transaction
from bankhub.normalize import clean_text
from bankhub.registry import register_source
from bankhub.sources.base import Source

API_URL = "https://dev.lunchmoney.app/v1/transactions"


def lunchmoney_to_transaction(raw: Dict[str, Any], *, flip_sign: bool = False) -> Transaction:
    """Pure mapping from a Lunchmoney transaction dict to :class:`Transaction`.

    ``flip_sign`` negates the amount.  Lunchmoney's sign handling depends on
    the account/`debit_as_negative` settings; flip if outflows arrive as
    positive numbers for your setup.
    """
    amount = Decimal(str(raw.get("amount", "0")))
    if flip_sign:
        amount = -amount
    account = raw.get("asset_id") or raw.get("plaid_account_id") or ""
    status = "posted" if raw.get("status") in ("cleared", "posted") else "pending"
    return Transaction(
        external_id=str(raw.get("id")),
        source="lunchmoney",
        account_id=str(account),
        date=_dt.date.fromisoformat(str(raw["date"])[:10]),
        amount=amount,
        currency=str(raw.get("currency", "usd")).lower(),
        payee=clean_text(raw.get("payee")),
        notes=clean_text(raw.get("notes")),
        category=str(raw["category_id"]) if raw.get("category_id") else None,
        status=status,
        raw=raw,
    )


@register_source("lunchmoney")
class LunchmoneySource(Source):
    """Fetch transactions from Lunchmoney within a date range.

    Options
    -------
    token
        API token (falls back to ``$LUNCHMONEY_TOKEN``).
    start_date, end_date
        ISO dates.  Default: the current month.
    flip_sign
        Negate amounts (see :func:`lunchmoney_to_transaction`).
    """

    requires = "requests"

    def __init__(self, token: str = None, start_date: str = None,
                 end_date: str = None, flip_sign: bool = False, **options):
        super().__init__(**options)
        self.token = token or os.environ.get("LUNCHMONEY_TOKEN") \
            or os.environ.get("LUNCHMONEY_API_KEY")
        self.start_date = start_date
        self.end_date = end_date
        self.flip_sign = str(flip_sign).lower() in ("1", "true", "yes", "on") \
            if not isinstance(flip_sign, bool) else flip_sign

    def fetch(self) -> Iterator[Transaction]:
        if not self.token:
            raise ConfigError(
                "Lunchmoney source needs a token (--source-opt token=... or "
                "$LUNCHMONEY_TOKEN)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("lunchmoney", "requests")

        start, end = self._date_window()
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"start_date": start, "end_date": end}
        resp = requests.get(API_URL, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        for raw in payload.get("transactions", []):
            yield lunchmoney_to_transaction(raw, flip_sign=self.flip_sign)

    def _date_window(self):
        if self.start_date and self.end_date:
            return self.start_date, self.end_date
        today = _dt.date.today()
        first = today.replace(day=1)
        return (self.start_date or first.isoformat(),
                self.end_date or today.isoformat())
