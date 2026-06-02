# -*- coding: utf-8 -*-
"""GoCardless Bank Account Data source (formerly Nordigen).

Popular, free, PSD2/open-banking access across Europe + UK.  Reads one
account's transactions from ``/api/v2/accounts/{id}/transactions/``.

Sign convention: ``transactionAmount.amount`` is already signed
(negative = outflow), so it maps straight through.
"""

from __future__ import annotations

import datetime as _dt
import os
from decimal import Decimal
from typing import Any, Dict, Iterator, List

from bankhub.errors import ConfigError, MissingDependencyError, SourceError
from bankhub.models import Transaction
from bankhub.normalize import clean_text
from bankhub.registry import register_source
from bankhub.sources.base import Source

BASE_URL = "https://bankaccountdata.gocardless.com"


def _remittance(raw: Dict[str, Any]) -> str:
    info = raw.get("remittanceInformationUnstructured")
    if not info:
        arr = raw.get("remittanceInformationUnstructuredArray") or []
        info = " ".join(arr)
    return clean_text(info)


def gocardless_to_transaction(raw: Dict[str, Any], account_id: str,
                              status: str = "posted") -> Transaction:
    """Pure mapping from a GoCardless transaction to :class:`Transaction`."""
    amt = raw.get("transactionAmount", {})
    amount = Decimal(str(amt.get("amount", "0")))
    currency = str(amt.get("currency", "eur")).lower()
    date = raw.get("bookingDate") or raw.get("valueDate")
    notes = _remittance(raw)
    payee = clean_text(raw.get("creditorName") if amount < 0
                       else raw.get("debtorName")) or notes
    ext = (raw.get("transactionId") or raw.get("internalTransactionId")
           or raw.get("entryReference") or "")
    return Transaction(
        external_id=str(ext),
        source="gocardless",
        account_id=str(account_id),
        date=_dt.date.fromisoformat(str(date)[:10]),
        amount=amount,
        currency=currency,
        payee=payee,
        notes=notes,
        status=status,
        raw=raw,
    )


def iter_gocardless(payload: Dict[str, Any]):
    """Yield ``(raw, status)`` for booked + pending transactions."""
    txns = payload.get("transactions", payload)
    for raw in txns.get("booked", []):
        yield raw, "posted"
    for raw in txns.get("pending", []):
        yield raw, "pending"


@register_source("gocardless")
class GoCardlessSource(Source):
    """Fetch one account's transactions from GoCardless Bank Account Data.

    Options
    -------
    access_token
        Bearer token (``$GOCARDLESS_ACCESS_TOKEN``); or supply ``secret_id``
        and ``secret_key`` to mint one.
    account_id
        GoCardless account id (``$GOCARDLESS_ACCOUNT_ID``).
    base_url
        Override API base.
    include_pending
        Include pending transactions (default true).
    """

    requires = "requests"

    def __init__(self, access_token: str = None, secret_id: str = None,
                 secret_key: str = None, account_id: str = None,
                 base_url: str = BASE_URL, include_pending=True, **options):
        super().__init__(**options)
        self.access_token = access_token or os.environ.get("GOCARDLESS_ACCESS_TOKEN")
        self.secret_id = secret_id or os.environ.get("GOCARDLESS_SECRET_ID")
        self.secret_key = secret_key or os.environ.get("GOCARDLESS_SECRET_KEY")
        self.account_id = account_id or os.environ.get("GOCARDLESS_ACCOUNT_ID")
        self.base_url = base_url.rstrip("/")
        self.include_pending = str(include_pending).lower() not in ("0", "false", "no")

    def _token(self, requests) -> str:
        if self.access_token:
            return self.access_token
        if not (self.secret_id and self.secret_key):
            raise ConfigError("GoCardless needs access_token or secret_id+secret_key")
        resp = requests.post(f"{self.base_url}/api/v2/token/new/",
                             json={"secret_id": self.secret_id,
                                   "secret_key": self.secret_key}, timeout=60)
        resp.raise_for_status()
        return resp.json()["access"]

    def fetch(self) -> Iterator[Transaction]:
        if not self.account_id:
            raise ConfigError("GoCardless needs an account_id")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("gocardless", "requests")
        headers = {"Authorization": f"Bearer {self._token(requests)}",
                   "Accept": "application/json"}
        url = f"{self.base_url}/api/v2/accounts/{self.account_id}/transactions/"
        resp = requests.get(url, headers=headers, timeout=120)
        if resp.status_code >= 400:
            raise SourceError(f"GoCardless error HTTP {resp.status_code}: {resp.text[:200]}")
        for raw, status in iter_gocardless(resp.json()):
            if status == "pending" and not self.include_pending:
                continue
            yield gocardless_to_transaction(raw, self.account_id, status)
