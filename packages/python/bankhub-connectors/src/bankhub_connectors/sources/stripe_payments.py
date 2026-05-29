# -*- coding: utf-8 -*-
"""Stripe payments source (balance transactions).

For people running a business on Stripe: reads your Stripe *balance
transactions* (``/v1/balance_transactions``) -- charges, refunds, payouts,
fees -- rather than linked bank data. Only ``requests`` is needed.

Sign convention: a Stripe balance transaction ``amount`` is **positive when
funds are added to your balance** (e.g. a charge) and negative when removed
(e.g. a payout), which already matches the hub convention. Amounts are in the
smallest currency unit, scaled by 100 here (verify for zero-decimal
currencies).
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


def balance_txn_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from a Stripe balance transaction to ``Transaction``."""
    amount = Decimal(str(raw.get("amount", 0))) / 100  # already signed; cents
    ts = raw.get("created")
    date = _dt.datetime.utcfromtimestamp(int(ts)).date() if ts else _dt.date.today()
    payee = raw.get("description") or raw.get("type") or ""
    return Transaction(
        external_id=str(raw["id"]),
        source="stripe_payments",
        account_id="stripe",
        date=date,
        amount=amount,
        currency=str(raw.get("currency", "usd")).lower(),
        payee=clean_text(payee),
        notes=clean_text(raw.get("type")),
        status="posted" if raw.get("status") == "available" else "pending",
        raw=raw,
    )


@register_source("stripe_payments")
class StripePaymentsSource(Source):
    """Fetch Stripe balance transactions (merchant activity).

    Options
    -------
    api_key
        Stripe secret key (``$STRIPE_API_KEY`` / ``$STRIPE_SECRET_KEY``).
    txn_type
        Optional Stripe ``type`` filter (e.g. ``charge``, ``payout``).
    """

    requires = "requests"

    def __init__(self, api_key: str = None, txn_type: str = None, **options):
        super().__init__(**options)
        self.api_key = (api_key or os.environ.get("STRIPE_API_KEY")
                        or os.environ.get("STRIPE_SECRET_KEY"))
        self.txn_type = txn_type

    def fetch(self) -> Iterator[Transaction]:
        if not self.api_key:
            raise ConfigError("Stripe source needs api_key (option or $STRIPE_API_KEY)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("stripe_payments", "requests")

        url = f"{API_BASE}/balance_transactions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params: Dict[str, Any] = {"limit": 100}
        if self.txn_type:
            params["type"] = self.txn_type
        while True:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
            if resp.status_code >= 400:
                raise SourceError(f"Stripe error HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            for raw in data.get("data", []):
                yield balance_txn_to_transaction(raw)
            if not data.get("has_more"):
                break
            params["starting_after"] = data["data"][-1]["id"]
