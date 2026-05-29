# -*- coding: utf-8 -*-
"""Lunchmoney destination.

Ports the original Lunchmoney insert path onto the plugin model.  Each
transaction carries its ``external_id`` to Lunchmoney, so Lunchmoney's own
duplicate detection plus our local sync store give two layers of idempotency.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, List

from ..errors import ConfigError, MissingDependencyError
from ..models import PushResult, Transaction
from ..registry import register_destination
from .base import Destination

API_URL = "https://dev.lunchmoney.app/v1/transactions"
_BATCH = 500


def transaction_to_lunchmoney(txn: Transaction) -> Dict[str, Any]:
    """Pure mapping from a :class:`Transaction` to a Lunchmoney insert dict.

    Amount keeps our sign convention (negative = outflow) and is paired with
    ``debit_as_negative: true`` at the request level.
    """
    payload: Dict[str, Any] = {
        "date": txn.date.isoformat(),
        "amount": str(txn.amount),
        "currency": (txn.currency or "usd").lower(),
        "payee": txn.payee or "",
        "notes": txn.notes or "",
        "external_id": txn.external_id,
        "status": "cleared" if txn.status == "posted" else "uncleared",
    }
    account = txn.target_account
    if account:
        # Lunchmoney asset ids are integers; plaid accounts are strings.
        try:
            payload["asset_id"] = int(account)
        except (TypeError, ValueError):
            payload["plaid_account_id"] = account
    return payload


def build_request_body(transactions: List[Transaction],
                       *, debit_as_negative: bool = True,
                       check_for_recurring: bool = True,
                       apply_rules: bool = True,
                       skip_duplicates: bool = True) -> Dict[str, Any]:
    """Build the full Lunchmoney request body (pure / testable)."""
    return {
        "transactions": [transaction_to_lunchmoney(t) for t in transactions],
        "debit_as_negative": debit_as_negative,
        "check_for_recurring": check_for_recurring,
        "skip_duplicates": skip_duplicates,
        "apply_rules": apply_rules,
    }


@register_destination("lunchmoney")
class LunchmoneyDestination(Destination):
    """Insert transactions into Lunchmoney via its REST API.

    Options
    -------
    token
        Lunchmoney API token (falls back to ``$LUNCHMONEY_TOKEN``).
    debit_as_negative, apply_rules, check_for_recurring, skip_duplicates
        Forwarded to the Lunchmoney insert endpoint.
    """

    requires = "requests"

    def __init__(self, token: str = None, debit_as_negative: bool = True,
                 apply_rules: bool = True, check_for_recurring: bool = True,
                 skip_duplicates: bool = True, **options):
        super().__init__(**options)
        self.token = token or os.environ.get("LUNCHMONEY_TOKEN") \
            or os.environ.get("LUNCHMONEY_API_KEY")
        self.debit_as_negative = _as_bool(debit_as_negative)
        self.apply_rules = _as_bool(apply_rules)
        self.check_for_recurring = _as_bool(check_for_recurring)
        self.skip_duplicates = _as_bool(skip_duplicates)

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        if not self.token:
            raise ConfigError(
                "Lunchmoney destination needs a token (--dest-opt token=... "
                "or $LUNCHMONEY_TOKEN)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("lunchmoney", "requests")

        headers = {"Authorization": f"Bearer {self.token}",
                   "Content-Type": "application/json"}
        results: List[PushResult] = []
        for start in range(0, len(transactions), _BATCH):
            chunk = transactions[start:start + _BATCH]
            body = build_request_body(
                chunk, debit_as_negative=self.debit_as_negative,
                check_for_recurring=self.check_for_recurring,
                apply_rules=self.apply_rules, skip_duplicates=self.skip_duplicates)
            results.extend(self._post_chunk(requests, headers, chunk, body))
        return results

    def _post_chunk(self, requests, headers, chunk, body) -> List[PushResult]:
        try:
            resp = requests.post(API_URL, json=body, headers=headers, timeout=60)
        except Exception as exc:  # network error
            return [PushResult(t.external_id, "error", error=str(exc)) for t in chunk]

        if resp.status_code >= 400:
            detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return [PushResult(t.external_id, "error", error=detail) for t in chunk]

        try:
            data = resp.json()
        except ValueError:
            data = {}

        if isinstance(data, dict) and data.get("error"):
            detail = str(data["error"])[:200]
            return [PushResult(t.external_id, "error", error=detail) for t in chunk]

        # Success: Lunchmoney returns {"ids": [...]} in submission order.
        ids = data.get("ids") if isinstance(data, dict) else None
        results = []
        for idx, txn in enumerate(chunk):
            remote_id = str(ids[idx]) if ids and idx < len(ids) else None
            results.append(PushResult(txn.external_id, "created", remote_id=remote_id))
        return results


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")
