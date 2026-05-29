# -*- coding: utf-8 -*-
"""Yodlee source (Envestnet | Yodlee aggregation).

Reads ``/transactions``.

Sign convention: Yodlee reports an unsigned ``amount.amount`` plus a
``baseType`` of DEBIT/CREDIT; we derive the sign (DEBIT => negative).
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, Iterator

from bankhub.errors import ConfigError, MissingDependencyError, SourceError
from bankhub.models import Transaction
from bankhub.normalize import clean_text, parse_date
from bankhub.registry import register_source
from bankhub.sources.base import Source


def yodlee_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from a Yodlee transaction to :class:`Transaction`."""
    amt = raw.get("amount", {})
    magnitude = abs(Decimal(str(amt.get("amount", "0"))))
    is_debit = str(raw.get("baseType", "")).upper() == "DEBIT"
    amount = -magnitude if is_debit else magnitude
    desc = raw.get("description", {}) or {}
    payee = clean_text(desc.get("simple") or desc.get("original"))
    date = raw.get("date") or raw.get("transactionDate") or raw.get("postDate")
    category = raw.get("category")
    return Transaction(
        external_id=str(raw["id"]),
        source="yodlee",
        account_id=str(raw.get("accountId", "")),
        date=parse_date(str(date)[:10]),
        amount=amount,
        currency=str(amt.get("currency", "usd")).lower(),
        payee=payee,
        notes=clean_text(desc.get("original")),
        category=clean_text(category) or None,
        status="pending" if str(raw.get("status", "")).upper() == "PENDING" else "posted",
        raw=raw,
    )


@register_source("yodlee")
class YodleeSource(Source):
    """Fetch transactions from Yodlee.

    Options
    -------
    access_token
        User access token (``$YODLEE_ACCESS_TOKEN``).
    base_url
        API base, e.g. ``https://<host>/ysl`` (``$YODLEE_BASE_URL``).
    account_id
        Optional accountId filter.
    api_version
        Api-Version header (default ``1.1``).
    """

    requires = "requests"

    def __init__(self, access_token: str = None, base_url: str = None,
                 account_id: str = None, api_version: str = "1.1", **options):
        super().__init__(**options)
        self.access_token = access_token or os.environ.get("YODLEE_ACCESS_TOKEN")
        self.base_url = (base_url or os.environ.get("YODLEE_BASE_URL") or "").rstrip("/")
        self.account_id = account_id or os.environ.get("YODLEE_ACCOUNT_ID")
        self.api_version = api_version

    def fetch(self) -> Iterator[Transaction]:
        if not (self.access_token and self.base_url):
            raise ConfigError("Yodlee needs access_token and base_url")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("yodlee", "requests")
        headers = {"Authorization": f"Bearer {self.access_token}",
                   "Api-Version": self.api_version, "Accept": "application/json"}
        params = {"accountId": self.account_id} if self.account_id else {}
        resp = requests.get(f"{self.base_url}/transactions", headers=headers,
                            params=params, timeout=120)
        if resp.status_code >= 400:
            raise SourceError(f"Yodlee error HTTP {resp.status_code}: {resp.text[:200]}")
        for raw in resp.json().get("transaction", []):
            yield yodlee_to_transaction(raw)
