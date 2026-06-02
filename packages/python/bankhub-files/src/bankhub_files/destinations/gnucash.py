# -*- coding: utf-8 -*-
"""GnuCash destination (native, via the optional ``piecash`` library).

Writes transactions straight into a GnuCash **SQLite** book: for each hub
transaction it creates a GnuCash transaction with two splits -- one against the
target account, one against an offset account (e.g. ``Imbalance-USD`` or an
``Expenses`` account). The hub ``external_id`` is stored in the transaction's
``num`` field; de-duplication across runs relies on the local sync store.

Requires ``piecash`` (``pip install "bankhub-files[gnucash]"``) and an existing
GnuCash SQLite book with the target + offset accounts already present.

Maturity: built against the piecash API but exercised only via the local sync
flow -- verify against a copy of your book before trusting it with the real one.
"""

from __future__ import annotations

import datetime as _dt
import os
from decimal import Decimal
from typing import List

from bankhub.errors import ConfigError, MissingDependencyError
from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination


def _find_account(book, name: str):
    """Locate a GnuCash account by full name (``Assets:Bank``) or leaf name."""
    if not name:
        return None
    for acct in book.accounts:
        if acct.fullname == name or acct.name == name:
            return acct
    return None


@register_destination("gnucash")
class GnuCashDestination(Destination):
    """Append transactions to a GnuCash SQLite book.

    Options
    -------
    file
        Path to the GnuCash SQLite book (``$GNUCASH_BOOK``).
    account
        Default target account full-name when a transaction has no mapped
        ``target_account`` (e.g. ``Assets:Checking``).
    offset
        Offset/contra account full-name for the other split
        (default ``Imbalance-USD``).
    """

    requires = "piecash"

    def __init__(self, file: str = None, account: str = None,
                 offset: str = "Imbalance-USD", **options):
        super().__init__(**options)
        self.file = file or os.environ.get("GNUCASH_BOOK")
        self.account = account
        self.offset = offset

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        if not self.file:
            raise ConfigError("gnucash destination needs file=<book.gnucash> "
                              "(option or $GNUCASH_BOOK)")
        if not os.path.exists(self.file):
            raise ConfigError(f"GnuCash book not found: {self.file}")
        try:
            import piecash
            from piecash import Split
            from piecash import Transaction as GncTransaction
        except ImportError:
            raise MissingDependencyError("gnucash", "piecash")

        book = piecash.open_book(self.file, readonly=False, do_backup=False)
        results: List[PushResult] = []
        try:
            offset_acct = _find_account(book, self.offset)
            for txn in transactions:
                target = _find_account(book, txn.target_account or self.account)
                if target is None:
                    results.append(PushResult(txn.external_id, "error",
                                              error=f"account not found: "
                                                    f"{txn.target_account or self.account!r}"))
                    continue
                if offset_acct is None:
                    results.append(PushResult(txn.external_id, "error",
                                              error=f"offset account not found: {self.offset!r}"))
                    continue
                value = Decimal(txn.amount)
                GncTransaction(
                    currency=target.commodity,
                    description=txn.payee or txn.notes or "",
                    post_date=_dt.datetime(txn.date.year, txn.date.month, txn.date.day),
                    num=txn.external_id[:32],
                    notes=txn.notes or "",
                    splits=[
                        Split(account=target, value=value),
                        Split(account=offset_acct, value=-value),
                    ],
                )
                results.append(PushResult(txn.external_id, "created"))
            book.save()
        finally:
            book.close()
        return results
