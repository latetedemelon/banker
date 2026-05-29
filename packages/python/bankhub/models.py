# -*- coding: utf-8 -*-
"""Canonical data model shared by every source and destination.

The :class:`Transaction` is the *interlingua* of the hub: every source
converts its native records into ``Transaction`` objects, and every
destination consumes ``Transaction`` objects.  As long as a plugin speaks
this model, it can be wired to any other plugin.

Sign convention
---------------
``amount`` is a signed :class:`~decimal.Decimal`.  **Negative means money
leaving the account (a debit/outflow); positive means money arriving (a
credit/inflow).**  This matches Lunchmoney's ``debit_as_negative`` and the
convention used by most personal-finance tools.  Each source adapter is
responsible for normalising its native sign convention to this one.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any, Dict, Optional


# Transaction lifecycle states.
POSTED = "posted"
PENDING = "pending"


@dataclass
class Transaction:
    """A single normalised financial transaction."""

    # --- identity / deduplication ----------------------------------------
    external_id: str
    """Stable, deterministic id used for dedup across runs.  When the source
    exposes its own immutable id (Plaid ``transaction_id``, Lunchmoney
    ``id``) use it; otherwise compute one with
    :func:`bankhub.normalize.compute_external_id`."""

    source: str
    """Name of the source that produced this record, e.g. ``"csv:revolut"``."""

    account_id: str
    """Source-side account identifier (account number, currency, Plaid
    ``account_id`` …).  Mapped to destination accounts by
    :class:`bankhub.mapping.AccountMap`."""

    # --- core financial fields -------------------------------------------
    date: _dt.date
    """Posting/booking date."""

    amount: Decimal
    """Signed amount.  Negative = outflow, positive = inflow."""

    currency: str = "usd"
    """ISO-4217 currency code, lower-cased."""

    payee: str = ""
    notes: str = ""
    category: Optional[str] = None
    status: str = POSTED

    # --- optional richer fields ------------------------------------------
    posted_date: Optional[_dt.date] = None
    balance: Optional[Decimal] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    """Original source record, retained for debugging and re-processing."""

    dest_account: Optional[str] = None
    """Transient: destination-side account id resolved by the engine just
    before a push.  Not persisted (see :meth:`to_dict`).  Destinations should
    read ``dest_account or account_id``."""

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            self.amount = Decimal(str(self.amount))
        if self.balance is not None and not isinstance(self.balance, Decimal):
            self.balance = Decimal(str(self.balance))
        if self.currency:
            self.currency = str(self.currency).lower()

    # --- serialisation ----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """JSON-friendly representation (Decimals -> str, dates -> isoformat)."""
        data = asdict(self)
        data["amount"] = str(self.amount)
        data["balance"] = None if self.balance is None else str(self.balance)
        data["date"] = self.date.isoformat()
        data["posted_date"] = (
            self.posted_date.isoformat() if self.posted_date else None
        )
        # dest_account is a transient, per-destination value -- never persist.
        data.pop("dest_account", None)
        return data

    @property
    def target_account(self) -> str:
        """The account id a destination should use for this transaction."""
        return self.dest_account or self.account_id

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transaction":
        """Inverse of :meth:`to_dict`."""
        data = dict(data)
        data["amount"] = Decimal(str(data["amount"]))
        if data.get("balance") is not None:
            data["balance"] = Decimal(str(data["balance"]))
        data["date"] = _parse_iso_date(data["date"])
        if data.get("posted_date"):
            data["posted_date"] = _parse_iso_date(data["posted_date"])
        else:
            data["posted_date"] = None
        # Drop unknown keys defensively so older stores stay loadable.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def is_outflow(self) -> bool:
        return self.amount < 0

    @property
    def is_inflow(self) -> bool:
        return self.amount > 0


def _parse_iso_date(value: Any) -> _dt.date:
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value)[:10])


@dataclass
class PushResult:
    """Outcome of delivering a single transaction to a destination."""

    external_id: str
    status: str  # "created" | "skipped" | "error"
    remote_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in ("created", "skipped")


@dataclass
class Account:
    """A logical account exposed by a source (used by ``list-accounts``)."""

    id: str
    name: str = ""
    currency: str = ""
    type: str = ""
    balance: Optional[Decimal] = None
