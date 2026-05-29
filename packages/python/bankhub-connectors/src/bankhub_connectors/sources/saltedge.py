# -*- coding: utf-8 -*-
"""Salt Edge source (https://www.saltedge.com).

Reads ``/api/v5/transactions`` for a connection/account, following Salt
Edge's ``next_id`` pagination.

Sign convention: Salt Edge ``amount`` is already signed (negative = outflow),
so it maps straight through.
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

BASE_URL = "https://www.saltedge.com"


def saltedge_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from a Salt Edge transaction to :class:`Transaction`."""
    amount = Decimal(str(raw.get("amount", "0")))
    extra = raw.get("extra", {}) or {}
    payee = clean_text(extra.get("payee") or raw.get("description"))
    return Transaction(
        external_id=str(raw["id"]),
        source="saltedge",
        account_id=str(raw.get("account_id", "")),
        date=parse_date(str(raw["made_on"])[:10]),
        amount=amount,
        currency=str(raw.get("currency_code", "eur")).lower(),
        payee=payee,
        notes=clean_text(raw.get("description")),
        category=clean_text(raw.get("category")) or None,
        status="pending" if str(raw.get("status", "")).lower() == "pending" else "posted",
        raw=raw,
    )


@register_source("saltedge")
class SaltEdgeSource(Source):
    """Fetch transactions from Salt Edge.

    Options
    -------
    app_id, secret
        Salt Edge App-id / Secret headers
        (``$SALTEDGE_APP_ID`` / ``$SALTEDGE_SECRET``).
    connection_id
        Connection to read (``$SALTEDGE_CONNECTION_ID``).
    account_id
        Optional account filter.
    """

    requires = "requests"

    def __init__(self, app_id: str = None, secret: str = None,
                 connection_id: str = None, account_id: str = None,
                 base_url: str = BASE_URL, **options):
        super().__init__(**options)
        self.app_id = app_id or os.environ.get("SALTEDGE_APP_ID")
        self.secret = secret or os.environ.get("SALTEDGE_SECRET")
        self.connection_id = connection_id or os.environ.get("SALTEDGE_CONNECTION_ID")
        self.account_id = account_id or os.environ.get("SALTEDGE_ACCOUNT_ID")
        self.base_url = base_url.rstrip("/")

    def fetch(self) -> Iterator[Transaction]:
        if not (self.app_id and self.secret and self.connection_id):
            raise ConfigError("Salt Edge needs app_id, secret and connection_id")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("saltedge", "requests")
        headers = {"App-id": self.app_id, "Secret": self.secret, "Accept": "application/json"}
        url = f"{self.base_url}/api/v5/transactions"
        next_id = None
        while True:
            params = {"connection_id": self.connection_id}
            if self.account_id:
                params["account_id"] = self.account_id
            if next_id:
                params["from_id"] = next_id
            resp = requests.get(url, headers=headers, params=params, timeout=120)
            if resp.status_code >= 400:
                raise SourceError(f"Salt Edge error HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            for raw in data.get("data", []):
                yield saltedge_to_transaction(raw)
            next_id = (data.get("meta", {}) or {}).get("next_id")
            if not next_id:
                break
