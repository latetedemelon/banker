# -*- coding: utf-8 -*-
"""Flinks source (Canadian bank aggregator).

Parses Flinks' ``GetAccountsDetail`` response, which nests transactions
under each account.  Flinks splits amounts into separate ``Debit`` and
``Credit`` fields; we combine them into a single signed amount
(credit = inflow positive, debit = outflow negative).

The pure parsers are unit-tested against a fixture; the live ``fetch``
requires Flinks credentials (instance, customer id, login id).
"""

from __future__ import annotations

import datetime as _dt
import os
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Tuple

from ..errors import ConfigError, MissingDependencyError, SourceError
from ..models import Transaction
from ..normalize import clean_text, compute_external_id
from ..registry import register_source
from .base import Source


def flinks_amount(raw: Dict[str, Any]) -> Decimal:
    """Signed amount from a Flinks transaction's Debit/Credit fields."""
    credit = raw.get("Credit") or 0
    debit = raw.get("Debit") or 0
    return Decimal(str(credit)) - Decimal(str(debit))


def flinks_to_transaction(raw: Dict[str, Any], account_id: str,
                          currency: str = "cad") -> Transaction:
    """Pure mapping from one Flinks transaction to :class:`Transaction`."""
    amount = flinks_amount(raw)
    date = _dt.date.fromisoformat(str(raw["Date"])[:10])
    payee = clean_text(raw.get("Description"))
    external = raw.get("Id")
    external_id = str(external) if external else compute_external_id(
        "flinks", account_id, date, amount, payee, "", raw.get("Code", ""))
    balance = raw.get("Balance")
    return Transaction(
        external_id=external_id,
        source="flinks",
        account_id=str(account_id),
        date=date,
        amount=amount,
        currency=str(currency or "cad").lower(),
        payee=payee,
        notes=clean_text(raw.get("Code")),
        balance=Decimal(str(balance)) if balance is not None else None,
        raw=raw,
    )


def iter_flinks_transactions(payload: Dict[str, Any]) -> Iterator[Tuple[Dict, str, str]]:
    """Yield ``(raw_txn, account_id, currency)`` from a GetAccountsDetail body."""
    accounts: List[Dict] = payload.get("Accounts") or []
    for account in accounts:
        account_id = str(account.get("Id") or account.get("AccountNumber") or "")
        currency = account.get("Currency") or "cad"
        for raw in account.get("Transactions") or []:
            yield raw, account_id, currency


@register_source("flinks")
class FlinksSource(Source):
    """Fetch transactions from Flinks' ``GetAccountsDetail`` endpoint.

    Options
    -------
    instance
        Flinks instance name (``$FLINKS_INSTANCE``).
    customer_id
        Flinks customer id (``$FLINKS_CUSTOMER_ID``).
    login_id
        The authorised login/request id (``$FLINKS_LOGIN_ID``).
    base_url
        Override the full base URL (otherwise derived from instance).
    most_recent_cached
        Use Flinks' cached data instead of a live refresh (default true).
    """

    requires = "requests"

    def __init__(self, instance: str = None, customer_id: str = None,
                 login_id: str = None, base_url: str = None,
                 most_recent_cached=True, **options):
        super().__init__(**options)
        self.instance = instance or os.environ.get("FLINKS_INSTANCE")
        self.customer_id = customer_id or os.environ.get("FLINKS_CUSTOMER_ID")
        self.login_id = login_id or os.environ.get("FLINKS_LOGIN_ID")
        self.base_url = base_url
        self.most_recent_cached = str(most_recent_cached).lower() not in ("0", "false", "no")

    def fetch(self) -> Iterator[Transaction]:
        if not (self.customer_id and self.login_id and (self.instance or self.base_url)):
            raise ConfigError(
                "Flinks source needs instance, customer_id and login_id "
                "(options or $FLINKS_INSTANCE/$FLINKS_CUSTOMER_ID/$FLINKS_LOGIN_ID)")
        try:
            import requests
        except ImportError:
            raise MissingDependencyError("flinks", "requests")

        base = self.base_url or \
            f"https://{self.instance}-api.private.fin.ag/v3/{self.customer_id}"
        url = f"{base}/BankingServices/GetAccountsDetail"
        body = {"LoginId": self.login_id, "MostRecentCached": self.most_recent_cached}
        resp = requests.post(url, json=body, timeout=120)
        if resp.status_code >= 400:
            raise SourceError(f"Flinks error HTTP {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        for raw, account_id, currency in iter_flinks_transactions(payload):
            yield flinks_to_transaction(raw, account_id, currency)
