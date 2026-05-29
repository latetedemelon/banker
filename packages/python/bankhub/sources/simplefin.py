# -*- coding: utf-8 -*-
"""SimpleFIN source (https://www.simplefin.org/protocol.html).

SimpleFIN is a tiny, privacy-friendly read-only protocol: a one-time *setup
token* is claimed for an *access URL* (with embedded credentials), and a GET
on ``{access_url}/accounts`` returns accounts with their transactions.

The parser is pure and fixture-tested; ``fetch`` needs a real access URL (or
a setup token to claim).

Sign convention: SimpleFIN amounts are already signed (negative = outflow).
"""

from __future__ import annotations

import base64
import datetime as _dt
from decimal import Decimal
from typing import Dict, Iterator, List, Tuple

from ..errors import ConfigError, MissingDependencyError, SourceError
from ..models import Account, Transaction
from ..normalize import clean_text
from ..registry import register_source
from .base import Source


def iter_simplefin(payload: Dict) -> Iterator[Tuple[Dict, Dict]]:
    """Yield ``(raw_txn, account)`` pairs from a SimpleFIN /accounts body."""
    for account in payload.get("accounts", []):
        for txn in account.get("transactions", []):
            yield txn, account


def simplefin_to_transaction(raw: Dict, account: Dict) -> Transaction:
    """Pure mapping from a SimpleFIN transaction to :class:`Transaction`."""
    posted = raw.get("posted") or raw.get("transacted_at") or 0
    date = _dt.datetime.utcfromtimestamp(int(posted)).date()
    currency = str(account.get("currency", "usd")).lower()
    payee = clean_text(raw.get("payee") or raw.get("description"))
    return Transaction(
        external_id=str(raw["id"]),
        source="simplefin",
        account_id=str(account.get("id", "")),
        date=date,
        amount=Decimal(str(raw.get("amount", "0"))),
        currency=currency,
        payee=payee,
        notes=clean_text(raw.get("memo") or raw.get("description")),
        status="pending" if raw.get("pending") else "posted",
        raw=raw,
    )


@register_source("simplefin")
class SimpleFinSource(Source):
    """Fetch accounts + transactions from a SimpleFIN bridge.

    Options
    -------
    access_url
        Full access URL incl. credentials (``$SIMPLEFIN_ACCESS_URL``).
    setup_token
        One-time base64 setup token to claim an access URL instead.
    start_date, end_date
        ISO dates limiting the window (optional).
    include_pending
        Include pending transactions (default true).
    """

    requires = "requests"

    def __init__(self, access_url: str = None, setup_token: str = None,
                 start_date: str = None, end_date: str = None,
                 include_pending=True, **options):
        super().__init__(**options)
        import os
        self.access_url = access_url or os.environ.get("SIMPLEFIN_ACCESS_URL")
        self.setup_token = setup_token or os.environ.get("SIMPLEFIN_SETUP_TOKEN")
        self.start_date = start_date
        self.end_date = end_date
        self.include_pending = str(include_pending).lower() not in ("0", "false", "no")

    def _claim(self, requests) -> str:
        claim_url = base64.b64decode(self.setup_token).decode("utf-8")
        resp = requests.post(claim_url, timeout=60)
        if resp.status_code >= 400:
            raise SourceError(f"SimpleFIN claim failed HTTP {resp.status_code}")
        return resp.text.strip()

    def _payload(self) -> Dict:
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("simplefin", "requests")
        access_url = self.access_url
        if not access_url and self.setup_token:
            access_url = self._claim(requests)
        if not access_url:
            raise ConfigError(
                "SimpleFIN needs access_url or setup_token "
                "(options or $SIMPLEFIN_ACCESS_URL/$SIMPLEFIN_SETUP_TOKEN)")
        params: Dict[str, object] = {"pending": 1 if self.include_pending else 0}
        if self.start_date:
            params["start-date"] = _to_epoch(self.start_date)
        if self.end_date:
            params["end-date"] = _to_epoch(self.end_date)
        resp = requests.get(access_url.rstrip("/") + "/accounts",
                            params=params, timeout=120)
        if resp.status_code >= 400:
            raise SourceError(f"SimpleFIN error HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def fetch(self) -> Iterator[Transaction]:
        payload = self._payload()
        for raw, account in iter_simplefin(payload):
            yield simplefin_to_transaction(raw, account)

    def list_accounts(self) -> List[Account]:
        payload = self._payload()
        out = []
        for acct in payload.get("accounts", []):
            bal = acct.get("balance")
            out.append(Account(
                id=str(acct.get("id", "")), name=clean_text(acct.get("name")),
                currency=str(acct.get("currency", "")).lower(),
                balance=Decimal(str(bal)) if bal is not None else None))
        return out


def _to_epoch(iso_date: str) -> int:
    return int(_dt.datetime.fromisoformat(iso_date).replace(
        tzinfo=_dt.timezone.utc).timestamp())
