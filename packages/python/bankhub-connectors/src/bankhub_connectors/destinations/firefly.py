# -*- coding: utf-8 -*-
"""Firefly III destination.

Pushes transactions to a self-hosted Firefly III instance via its REST API
(``POST /api/v1/transactions``) using a Personal Access Token.

Firefly is double-entry: every transaction has a *type* and a source +
destination account.  We map the hub's signed amount to a Firefly type:

* amount < 0 (money out)  -> ``withdrawal``: source = your asset account,
  destination = the payee (an expense account, created by name).
* amount >= 0 (money in)  -> ``deposit``: source = the payee (a revenue
  account), destination = your asset account.

The asset account is the transaction's mapped ``target_account`` (a Firefly
account name or id).  ``external_id`` is sent through so re-pushes are caught
by Firefly's duplicate detection on top of the local store.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, List

from bankhub.errors import ConfigError, MissingDependencyError
from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination


def transaction_to_firefly(txn: Transaction, asset_account: str) -> Dict[str, Any]:
    """Pure mapping from a :class:`Transaction` to a Firefly transaction split."""
    outflow = txn.amount < 0
    split: Dict[str, Any] = {
        "type": "withdrawal" if outflow else "deposit",
        "date": txn.date.isoformat(),
        "amount": str(abs(txn.amount)),
        "description": txn.payee or txn.notes or "(no description)",
        "currency_code": (txn.currency or "").upper() or None,
        "notes": txn.notes or None,
        "external_id": txn.external_id,
        "category_name": txn.category or None,
    }
    payee = txn.payee or "(unknown)"
    if outflow:
        split["source_name"] = asset_account
        split["destination_name"] = payee
    else:
        split["source_name"] = payee
        split["destination_name"] = asset_account
    return split


@register_destination("firefly")
class FireflyDestination(Destination):
    """Create transactions in Firefly III.

    Options
    -------
    url
        Base URL of the Firefly instance (``$FIREFLY_URL``), e.g.
        ``https://firefly.example.com``.
    token
        Personal Access Token (``$FIREFLY_TOKEN``).
    account
        Default asset-account name/id when a transaction has no mapped
        ``target_account`` (``$FIREFLY_ACCOUNT``).
    """

    requires = "requests"

    def __init__(self, url: str = None, token: str = None, account: str = None,
                 **options):
        super().__init__(**options)
        self.url = (url or os.environ.get("FIREFLY_URL") or "").rstrip("/")
        self.token = token or os.environ.get("FIREFLY_TOKEN")
        self.account = account or os.environ.get("FIREFLY_ACCOUNT")

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        if not (self.url and self.token):
            raise ConfigError("Firefly destination needs url and token "
                              "(options or $FIREFLY_URL/$FIREFLY_TOKEN)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("firefly", "requests")

        endpoint = f"{self.url}/api/v1/transactions"
        headers = {"Authorization": f"Bearer {self.token}",
                   "Accept": "application/json"}
        results: List[PushResult] = []
        for txn in transactions:
            asset = txn.target_account or self.account
            if not asset:
                results.append(PushResult(txn.external_id, "error",
                                          error="no asset account (map target_account "
                                                "or set account=)"))
                continue
            body = {"error_if_duplicate_hash": True,
                    "transactions": [transaction_to_firefly(txn, asset)]}
            try:
                resp = requests.post(endpoint, json=body, headers=headers, timeout=60)
            except Exception as exc:
                results.append(PushResult(txn.external_id, "error", error=str(exc)))
                continue
            if resp.status_code == 422 and "duplicate" in resp.text.lower():
                results.append(PushResult(txn.external_id, "skipped",
                                          error="duplicate"))
            elif resp.status_code >= 400:
                results.append(PushResult(txn.external_id, "error",
                                          error=f"HTTP {resp.status_code}: {resp.text[:200]}"))
            else:
                remote = resp.json().get("data", {}).get("id")
                results.append(PushResult(txn.external_id, "created", remote_id=remote))
        return results
