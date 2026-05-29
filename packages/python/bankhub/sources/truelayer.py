# -*- coding: utf-8 -*-
"""TrueLayer Data API source (UK / EU open banking).

Reads ``/data/v1/accounts/{id}/transactions``.

Sign convention: TrueLayer reports an unsigned ``amount`` plus a
``transaction_type`` of DEBIT/CREDIT; we derive the sign from the type so
outflow is negative regardless of how the field is populated.
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

BASE_URL = "https://api.truelayer.com"


def truelayer_to_transaction(raw: Dict[str, Any], account_id: str) -> Transaction:
    """Pure mapping from a TrueLayer transaction to :class:`Transaction`."""
    magnitude = abs(Decimal(str(raw.get("amount", "0"))))
    is_debit = str(raw.get("transaction_type", "")).upper() == "DEBIT"
    amount = -magnitude if is_debit else magnitude
    payee = clean_text(raw.get("merchant_name") or raw.get("description"))
    category = None
    cats = raw.get("transaction_classification")
    if isinstance(cats, list) and cats:
        category = cats[0]
    elif raw.get("transaction_category"):
        category = raw["transaction_category"]
    return Transaction(
        external_id=str(raw.get("transaction_id") or raw.get("normalised_provider_transaction_id")),
        source="truelayer",
        account_id=str(account_id),
        date=parse_date(str(raw["timestamp"])[:10]),
        amount=amount,
        currency=str(raw.get("currency", "gbp")).lower(),
        payee=payee,
        notes=clean_text(raw.get("description")),
        category=category,
        raw=raw,
    )


@register_source("truelayer")
class TrueLayerSource(Source):
    """Fetch one account's transactions from TrueLayer.

    Options
    -------
    access_token
        OAuth bearer token (``$TRUELAYER_ACCESS_TOKEN``).
    account_id
        TrueLayer account id (``$TRUELAYER_ACCOUNT_ID``).
    base_url
        Override API base (e.g. sandbox).
    """

    requires = "requests"

    def __init__(self, access_token: str = None, account_id: str = None,
                 base_url: str = BASE_URL, **options):
        super().__init__(**options)
        self.access_token = access_token or os.environ.get("TRUELAYER_ACCESS_TOKEN")
        self.account_id = account_id or os.environ.get("TRUELAYER_ACCOUNT_ID")
        self.base_url = base_url.rstrip("/")

    def fetch(self) -> Iterator[Transaction]:
        if not (self.access_token and self.account_id):
            raise ConfigError("TrueLayer needs access_token and account_id")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("truelayer", "requests")
        url = f"{self.base_url}/data/v1/accounts/{self.account_id}/transactions"
        resp = requests.get(url, headers={"Authorization": f"Bearer {self.access_token}"},
                            timeout=120)
        if resp.status_code >= 400:
            raise SourceError(f"TrueLayer error HTTP {resp.status_code}: {resp.text[:200]}")
        for raw in resp.json().get("results", []):
            yield truelayer_to_transaction(raw, self.account_id)
