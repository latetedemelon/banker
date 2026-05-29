# -*- coding: utf-8 -*-
"""Teller source (https://teller.io).

Reads ``/accounts/{id}/transactions``.

Sign convention: Teller ``amount`` is a signed string (negative = outflow),
so it maps straight through.  Auth is the access token as HTTP Basic username
(empty password), plus optional mTLS client cert/key.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, Iterator

from ..errors import ConfigError, MissingDependencyError, SourceError
from ..models import Transaction
from ..normalize import clean_text, parse_date
from ..registry import register_source
from .base import Source

BASE_URL = "https://api.teller.io"


def teller_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from a Teller transaction to :class:`Transaction`."""
    amount = Decimal(str(raw.get("amount", "0")))
    details = raw.get("details", {}) or {}
    counterparty = (details.get("counterparty", {}) or {}).get("name") \
        if isinstance(details.get("counterparty"), dict) else None
    payee = clean_text(counterparty or raw.get("description"))
    return Transaction(
        external_id=str(raw["id"]),
        source="teller",
        account_id=str(raw.get("account_id", "")),
        date=parse_date(str(raw["date"])[:10]),
        amount=amount,
        currency="usd",
        payee=payee,
        notes=clean_text(raw.get("description")),
        category=clean_text(details.get("category")) or None,
        status="pending" if str(raw.get("status", "")).lower() == "pending" else "posted",
        raw=raw,
    )


@register_source("teller")
class TellerSource(Source):
    """Fetch one account's transactions from Teller.

    Options
    -------
    access_token
        Teller access token (``$TELLER_ACCESS_TOKEN``).
    account_id
        Teller account id (``$TELLER_ACCOUNT_ID``).
    cert, key
        Paths to the mTLS client certificate and key (Teller requires mTLS
        outside the sandbox).
    """

    requires = "requests"

    def __init__(self, access_token: str = None, account_id: str = None,
                 cert: str = None, key: str = None, base_url: str = BASE_URL, **options):
        super().__init__(**options)
        self.access_token = access_token or os.environ.get("TELLER_ACCESS_TOKEN")
        self.account_id = account_id or os.environ.get("TELLER_ACCOUNT_ID")
        self.cert = cert or os.environ.get("TELLER_CERT")
        self.key = key or os.environ.get("TELLER_KEY")
        self.base_url = base_url.rstrip("/")

    def fetch(self) -> Iterator[Transaction]:
        if not (self.access_token and self.account_id):
            raise ConfigError("Teller needs access_token and account_id")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("teller", "requests")
        client_cert = (self.cert, self.key) if self.cert and self.key else self.cert
        url = f"{self.base_url}/accounts/{self.account_id}/transactions"
        resp = requests.get(url, auth=(self.access_token, ""), cert=client_cert, timeout=120)
        if resp.status_code >= 400:
            raise SourceError(f"Teller error HTTP {resp.status_code}: {resp.text[:200]}")
        for raw in resp.json():
            yield teller_to_transaction(raw)
