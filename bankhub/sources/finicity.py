# -*- coding: utf-8 -*-
"""Finicity (Mastercard Open Banking) source.

Reads ``/aggregation/v3/customers/{cid}/accounts/{aid}/transactions``.

Sign convention: Finicity ``amount`` is already signed (negative = debit),
so it maps straight through.  Dates are epoch seconds.
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

BASE_URL = "https://api.finicity.com"


def finicity_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from a Finicity transaction to :class:`Transaction`."""
    amount = Decimal(str(raw.get("amount", "0")))
    epoch = raw.get("postedDate") or raw.get("transactionDate") or 0
    date = _dt.datetime.utcfromtimestamp(int(epoch)).date()
    return Transaction(
        external_id=str(raw["id"]),
        source="finicity",
        account_id=str(raw.get("accountId", "")),
        date=date,
        amount=amount,
        currency=str(raw.get("currencySymbol", "usd")).lower(),
        payee=clean_text(raw.get("description")),
        notes=clean_text(raw.get("memo")),
        category=clean_text(raw.get("categorization", {}).get("category")
                            if isinstance(raw.get("categorization"), dict) else None) or None,
        status="pending" if str(raw.get("status", "")).lower() == "pending" else "posted",
        raw=raw,
    )


@register_source("finicity")
class FinicitySource(Source):
    """Fetch transactions from Finicity.

    Options
    -------
    app_key, app_token
        Finicity-App-Key / Finicity-App-Token headers
        (``$FINICITY_APP_KEY`` / ``$FINICITY_APP_TOKEN``).
    customer_id, account_id
        Identifiers for the account to read.
    from_date, to_date
        ISO dates bounding the query (Finicity requires a window;
        defaults to the last 120 days).
    """

    requires = "requests"

    def __init__(self, app_key: str = None, app_token: str = None,
                 customer_id: str = None, account_id: str = None,
                 from_date: str = None, to_date: str = None,
                 base_url: str = BASE_URL, **options):
        super().__init__(**options)
        self.app_key = app_key or os.environ.get("FINICITY_APP_KEY")
        self.app_token = app_token or os.environ.get("FINICITY_APP_TOKEN")
        self.customer_id = customer_id or os.environ.get("FINICITY_CUSTOMER_ID")
        self.account_id = account_id or os.environ.get("FINICITY_ACCOUNT_ID")
        self.from_date = from_date
        self.to_date = to_date
        self.base_url = base_url.rstrip("/")

    def _window(self):
        today = _dt.date.today()
        start = self.from_date or (today - _dt.timedelta(days=120)).isoformat()
        end = self.to_date or today.isoformat()
        to_epoch = lambda d: int(_dt.datetime.fromisoformat(d).replace(
            tzinfo=_dt.timezone.utc).timestamp())
        return to_epoch(start), to_epoch(end)

    def fetch(self) -> Iterator[Transaction]:
        if not (self.app_key and self.app_token and self.customer_id and self.account_id):
            raise ConfigError("Finicity needs app_key, app_token, customer_id and account_id")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("finicity", "requests")
        headers = {"Finicity-App-Key": self.app_key, "Finicity-App-Token": self.app_token,
                   "Accept": "application/json"}
        from_epoch, to_epoch = self._window()
        url = (f"{self.base_url}/aggregation/v3/customers/{self.customer_id}/accounts/"
               f"{self.account_id}/transactions")
        start = 1
        while True:
            params = {"fromDate": from_epoch, "toDate": to_epoch, "start": start, "limit": 1000}
            resp = requests.get(url, headers=headers, params=params, timeout=120)
            if resp.status_code >= 400:
                raise SourceError(f"Finicity error HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            txns = data.get("transactions", [])
            for raw in txns:
                yield finicity_to_transaction(raw)
            if len(txns) < 1000 or not data.get("moreAvailable", "false") in (True, "true"):
                break
            start += 1000
