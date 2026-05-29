# -*- coding: utf-8 -*-
"""Plaid source.

Talks to Plaid's ``/transactions/sync`` endpoint directly over HTTPS (only
``requests`` required -- no heavyweight SDK).  The pure parser
:func:`plaid_to_transaction` is unit-tested against a fixture; the live
``fetch`` requires real Plaid credentials and an ``access_token``.

Sign convention: Plaid amounts are *positive when money leaves the account*.
We negate them so outflow is negative, matching the hub convention.
"""

from __future__ import annotations

import datetime as _dt
import os
from decimal import Decimal
from typing import Any, Dict, Iterator

from ..errors import ConfigError, MissingDependencyError, SourceError
from ..models import Transaction
from ..normalize import clean_text
from ..registry import register_source
from .base import Source

_ENV_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def plaid_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from a Plaid transaction object to :class:`Transaction`."""
    amount = -Decimal(str(raw.get("amount", "0")))  # Plaid: +ve = outflow
    currency = (raw.get("iso_currency_code")
                or raw.get("unofficial_currency_code") or "usd")
    date = raw.get("date") or raw.get("authorized_date")
    payee = raw.get("merchant_name") or raw.get("name") or ""
    category = None
    pfc = raw.get("personal_finance_category")
    if isinstance(pfc, dict):
        category = pfc.get("primary")
    elif raw.get("category"):
        category = raw["category"][0] if isinstance(raw["category"], list) else raw["category"]
    return Transaction(
        external_id=str(raw["transaction_id"]),
        source="plaid",
        account_id=str(raw.get("account_id", "")),
        date=_dt.date.fromisoformat(str(date)[:10]),
        amount=amount,
        currency=str(currency).lower(),
        payee=clean_text(payee),
        notes=clean_text(raw.get("name")),
        category=category,
        status="pending" if raw.get("pending") else "posted",
        raw=raw,
    )


@register_source("plaid")
class PlaidSource(Source):
    """Fetch transactions from Plaid via ``/transactions/sync``.

    Options
    -------
    client_id, secret
        Plaid credentials (fall back to ``$PLAID_CLIENT_ID`` / ``$PLAID_SECRET``).
    access_token
        Item access token (``$PLAID_ACCESS_TOKEN``).
    env
        ``sandbox`` (default), ``development`` or ``production``.
    cursor
        Optional starting sync cursor; omit to fetch from the beginning
        (dedup makes repeated full fetches safe).
    include_pending
        Include pending transactions (default true).
    """

    requires = "requests"

    def __init__(self, client_id: str = None, secret: str = None,
                 access_token: str = None, env: str = "sandbox",
                 cursor: str = None, include_pending=True, **options):
        super().__init__(**options)
        self.client_id = client_id or os.environ.get("PLAID_CLIENT_ID")
        self.secret = secret or os.environ.get("PLAID_SECRET")
        self.access_token = access_token or os.environ.get("PLAID_ACCESS_TOKEN")
        self.env = env
        self.cursor = cursor
        self.include_pending = str(include_pending).lower() not in ("0", "false", "no")

    def fetch(self) -> Iterator[Transaction]:
        if not (self.client_id and self.secret and self.access_token):
            raise ConfigError(
                "Plaid source needs client_id, secret and access_token "
                "(options or $PLAID_CLIENT_ID/$PLAID_SECRET/$PLAID_ACCESS_TOKEN)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("plaid", "requests")

        host = _ENV_HOSTS.get(self.env)
        if not host:
            raise ConfigError(f"Unknown Plaid env {self.env!r}")
        url = f"{host}/transactions/sync"

        cursor = self.cursor
        has_more = True
        while has_more:
            body = {
                "client_id": self.client_id,
                "secret": self.secret,
                "access_token": self.access_token,
                "count": 500,
            }
            if cursor:
                body["cursor"] = cursor
            resp = requests.post(url, json=body, timeout=60)
            if resp.status_code >= 400:
                raise SourceError(f"Plaid error HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            for raw in data.get("added", []) + data.get("modified", []):
                if not self.include_pending and raw.get("pending"):
                    continue
                yield plaid_to_transaction(raw)
            cursor = data.get("next_cursor")
            has_more = bool(data.get("has_more"))
