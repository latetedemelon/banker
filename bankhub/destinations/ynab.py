# -*- coding: utf-8 -*-
"""YNAB (You Need A Budget) destination.

YNAB stores amounts in *milliunits* (1000 = one currency unit) and dedups on
``import_id`` (<=36 chars, unique per account).  We derive ``import_id`` from
the transaction's ``external_id`` so re-pushes are detected as duplicates by
YNAB itself, on top of our local sync store.
"""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List

from ..errors import ConfigError, MissingDependencyError
from ..models import PushResult, Transaction
from ..registry import register_destination
from .base import Destination

API_BASE = "https://api.ynab.com/v1"


def to_milliunits(amount: Decimal) -> int:
    """Convert a decimal amount to YNAB milliunits (banker's-safe rounding)."""
    return int((Decimal(amount) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def import_id_for(external_id: str) -> str:
    """YNAB import_id: stable, unique per account, <=36 chars."""
    return external_id[:36]


def transaction_to_ynab(txn: Transaction) -> Dict[str, Any]:
    """Pure mapping from a :class:`Transaction` to a YNAB transaction dict."""
    return {
        "account_id": txn.target_account,
        "date": txn.date.isoformat(),
        "amount": to_milliunits(txn.amount),
        "payee_name": (txn.payee or None),
        "memo": (txn.notes or None),
        "cleared": "cleared" if txn.status == "posted" else "uncleared",
        "import_id": import_id_for(txn.external_id),
    }


@register_destination("ynab")
class YnabDestination(Destination):
    """Create transactions in a YNAB budget.

    Options
    -------
    token
        YNAB personal access token (``$YNAB_TOKEN``).
    budget_id
        Target budget id, or ``"last-used"`` (default) / ``"default"``
        (``$YNAB_BUDGET_ID``).
    """

    requires = "requests"

    def __init__(self, token: str = None, budget_id: str = "last-used", **options):
        super().__init__(**options)
        self.token = token or os.environ.get("YNAB_TOKEN") \
            or os.environ.get("YNAB_ACCESS_TOKEN")
        self.budget_id = budget_id or os.environ.get("YNAB_BUDGET_ID") or "last-used"

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        if not self.token:
            raise ConfigError("YNAB destination needs a token (--dest-opt token=... "
                              "or $YNAB_TOKEN)")
        missing = [t for t in transactions if not t.target_account]
        if missing:
            raise ConfigError(
                "YNAB requires a destination account id per transaction; map "
                "source accounts to YNAB account GUIDs (account map 'ynab:').")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("ynab", "requests")

        url = f"{API_BASE}/budgets/{self.budget_id}/transactions"
        headers = {"Authorization": f"Bearer {self.token}"}
        body = {"transactions": [transaction_to_ynab(t) for t in transactions]}
        import_map = {import_id_for(t.external_id): t.external_id for t in transactions}

        try:
            resp = requests.post(url, json=body, headers=headers, timeout=60)
        except Exception as exc:
            return [PushResult(t.external_id, "error", error=str(exc)) for t in transactions]
        if resp.status_code >= 400:
            detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return [PushResult(t.external_id, "error", error=detail) for t in transactions]

        data = resp.json().get("data", {})
        dupes = set(data.get("duplicate_import_ids", []))
        # Map created server ids back to our transactions by import_id.
        created_remote = {}
        for created in data.get("transactions", []):
            iid = created.get("import_id")
            if iid in import_map:
                created_remote[import_map[iid]] = created.get("id")

        results = []
        for txn in transactions:
            iid = import_id_for(txn.external_id)
            if iid in dupes:
                results.append(PushResult(txn.external_id, "skipped",
                                          error="duplicate_import_id"))
            else:
                results.append(PushResult(txn.external_id, "created",
                                          remote_id=created_remote.get(txn.external_id)))
        return results
