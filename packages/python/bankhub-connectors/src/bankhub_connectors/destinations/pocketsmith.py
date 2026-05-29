# -*- coding: utf-8 -*-
"""PocketSmith destination.

Creates transactions in PocketSmith via its REST API
(``POST /v2/transaction_accounts/{id}/transactions``), authenticated with a
developer key.

Sign convention matches the hub: PocketSmith ``amount`` is positive for
credits and negative for debits, so the signed amount is sent as-is. The
target PocketSmith *transaction account* id comes from the transaction's
mapped ``target_account``. PocketSmith has no import-id, so de-duplication
relies on the local sync store.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from bankhub.errors import ConfigError, MissingDependencyError
from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination

API_BASE = "https://api.pocketsmith.com/v2"


def transaction_to_pocketsmith(txn: Transaction) -> Dict[str, Any]:
    """Pure mapping from a :class:`Transaction` to a PocketSmith payload."""
    return {
        "payee": txn.payee or txn.notes or "(no payee)",
        "amount": float(txn.amount),
        "date": txn.date.isoformat(),
        "note": txn.notes or None,
        "category_title": txn.category or None,
        "needs_review": False,
    }


@register_destination("pocketsmith")
class PocketSmithDestination(Destination):
    """Create transactions in PocketSmith.

    Options
    -------
    key
        PocketSmith developer key (``$POCKETSMITH_KEY``).
    account
        Default transaction-account id when a transaction has no mapped
        ``target_account`` (``$POCKETSMITH_ACCOUNT``).
    """

    requires = "requests"

    def __init__(self, key: str = None, account: str = None, **options):
        super().__init__(**options)
        self.key = key or os.environ.get("POCKETSMITH_KEY")
        self.account = account or os.environ.get("POCKETSMITH_ACCOUNT")

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        if not self.key:
            raise ConfigError("PocketSmith destination needs key (option or "
                              "$POCKETSMITH_KEY)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("pocketsmith", "requests")

        headers = {"X-Developer-Key": self.key, "Accept": "application/json"}
        results: List[PushResult] = []
        for txn in transactions:
            acct = txn.target_account or self.account
            if not acct:
                results.append(PushResult(txn.external_id, "error",
                                          error="no transaction account (map "
                                                "target_account or set account=)"))
                continue
            url = f"{API_BASE}/transaction_accounts/{acct}/transactions"
            try:
                resp = requests.post(url, json=transaction_to_pocketsmith(txn),
                                     headers=headers, timeout=60)
            except Exception as exc:
                results.append(PushResult(txn.external_id, "error", error=str(exc)))
                continue
            if resp.status_code >= 400:
                results.append(PushResult(txn.external_id, "error",
                                          error=f"HTTP {resp.status_code}: {resp.text[:200]}"))
            else:
                remote = resp.json().get("id") if resp.text else None
                results.append(PushResult(txn.external_id, "created",
                                          remote_id=str(remote) if remote else None))
        return results
