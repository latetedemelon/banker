# -*- coding: utf-8 -*-
"""Stripe Financial Connections source.

Reads bank-account transactions Stripe has linked via Financial Connections
(``/v1/financial_connections/transactions``).  Only ``requests`` is needed.

Sign convention: Stripe Financial Connections reports outflow as a **negative**
``amount`` (in the smallest currency unit), which already matches the hub
convention, so we don't flip it -- we just scale by 100.  Amounts are assumed
to be in 1/100 units (true for most currencies; zero-decimal currencies such
as JPY would need adjustment).  Verify against your data.
"""

from __future__ import annotations

import datetime as _dt
import os
from decimal import Decimal
from typing import Any, Dict, Iterator

from bankhub.errors import ConfigError, MissingDependencyError, SourceError
from bankhub.models import Transaction
from bankhub.normalize import clean_text
from bankhub.registry import register_source
from bankhub.sources.base import Source

API_BASE = "https://api.stripe.com/v1"


def stripe_fc_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from a Financial Connections transaction to ``Transaction``."""
    amount = Decimal(str(raw.get("amount", 0))) / 100  # already signed; cents
    ts = raw.get("transacted_at") or raw.get("created")
    date = _dt.datetime.utcfromtimestamp(int(ts)).date() if ts else _dt.date.today()
    status = raw.get("status")
    return Transaction(
        external_id=str(raw["id"]),
        source="stripe",
        account_id=str(raw.get("account", "")),
        date=date,
        amount=amount,
        currency=str(raw.get("currency", "usd")).lower(),
        payee=clean_text(raw.get("description")),
        notes=clean_text(raw.get("description")),
        status="pending" if status == "pending" else "posted",
        raw=raw,
    )


@register_source("stripe")
class StripeFinancialConnectionsSource(Source):
    """Fetch bank transactions from Stripe Financial Connections.

    Options
    -------
    api_key
        Stripe secret key (falls back to ``$STRIPE_API_KEY`` / ``$STRIPE_SECRET_KEY``).
    account
        Financial Connections account id (``fca_...``) to read
        (``$STRIPE_FC_ACCOUNT``).
    """

    requires = "requests"

    def __init__(self, api_key: str = None, account: str = None, **options):
        super().__init__(**options)
        self.api_key = (api_key or os.environ.get("STRIPE_API_KEY")
                        or os.environ.get("STRIPE_SECRET_KEY"))
        self.account = account or os.environ.get("STRIPE_FC_ACCOUNT")

    @property
    def source_id(self) -> str:
        return f"stripe:{self.account}" if self.account else "stripe"

    def fetch(self) -> Iterator[Transaction]:
        if not self.api_key:
            raise ConfigError("Stripe source needs api_key (option or $STRIPE_API_KEY)")
        if not self.account:
            raise ConfigError("Stripe Financial Connections needs account=fca_... "
                              "(option or $STRIPE_FC_ACCOUNT)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("stripe", "requests")

        url = f"{API_BASE}/financial_connections/transactions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"account": self.account, "limit": 100}
        while True:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
            if resp.status_code >= 400:
                raise SourceError(f"Stripe error HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            page = data.get("data", [])
            for raw in page:
                yield stripe_fc_to_transaction(raw)
            if not page or not data.get("has_more"):
                break
            params["starting_after"] = page[-1]["id"]
