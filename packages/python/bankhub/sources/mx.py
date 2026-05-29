# -*- coding: utf-8 -*-
"""MX Platform API source.

Reads ``/users/{user_guid}/accounts/{account_guid}/transactions``.

Sign convention: MX reports an unsigned ``amount`` plus a ``type`` of
DEBIT/CREDIT; we derive the sign (DEBIT => negative).
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

BASE_URL = "https://api.mx.com"


def mx_to_transaction(raw: Dict[str, Any]) -> Transaction:
    """Pure mapping from an MX transaction to :class:`Transaction`."""
    magnitude = abs(Decimal(str(raw.get("amount", "0"))))
    is_debit = str(raw.get("type", "")).upper() == "DEBIT"
    amount = -magnitude if is_debit else magnitude
    date = raw.get("date") or raw.get("transacted_at") or raw.get("posted_at")
    return Transaction(
        external_id=str(raw["guid"]),
        source="mx",
        account_id=str(raw.get("account_guid", "")),
        date=parse_date(str(date)[:10]),
        amount=amount,
        currency=str(raw.get("currency_code", "usd")).lower(),
        payee=clean_text(raw.get("description") or raw.get("merchant_guid")),
        notes=clean_text(raw.get("memo") or raw.get("original_description")),
        category=clean_text(raw.get("top_level_category") or raw.get("category")) or None,
        status="pending" if str(raw.get("status", "")).upper() == "PENDING" else "posted",
        raw=raw,
    )


@register_source("mx")
class MxSource(Source):
    """Fetch transactions from MX.

    Options
    -------
    client_id, api_key
        MX credentials for HTTP Basic auth
        (``$MX_CLIENT_ID`` / ``$MX_API_KEY``).
    user_guid, account_guid
        Identifiers for the account to read
        (``$MX_USER_GUID`` / ``$MX_ACCOUNT_GUID``).
    base_url
        Override API base (default production).
    """

    requires = "requests"

    def __init__(self, client_id: str = None, api_key: str = None,
                 user_guid: str = None, account_guid: str = None,
                 base_url: str = BASE_URL, **options):
        super().__init__(**options)
        self.client_id = client_id or os.environ.get("MX_CLIENT_ID")
        self.api_key = api_key or os.environ.get("MX_API_KEY")
        self.user_guid = user_guid or os.environ.get("MX_USER_GUID")
        self.account_guid = account_guid or os.environ.get("MX_ACCOUNT_GUID")
        self.base_url = base_url.rstrip("/")

    def fetch(self) -> Iterator[Transaction]:
        if not (self.client_id and self.api_key and self.user_guid and self.account_guid):
            raise ConfigError("MX needs client_id, api_key, user_guid and account_guid")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("mx", "requests")
        headers = {"Accept": "application/vnd.mx.api.v1+json"}
        url = (f"{self.base_url}/users/{self.user_guid}/accounts/"
               f"{self.account_guid}/transactions")
        page = 1
        while True:
            resp = requests.get(url, headers=headers, params={"page": page, "records_per_page": 100},
                                auth=(self.client_id, self.api_key), timeout=120)
            if resp.status_code >= 400:
                raise SourceError(f"MX error HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            for raw in data.get("transactions", []):
                yield mx_to_transaction(raw)
            pagination = data.get("pagination", {})
            if page >= pagination.get("total_pages", page):
                break
            page += 1
