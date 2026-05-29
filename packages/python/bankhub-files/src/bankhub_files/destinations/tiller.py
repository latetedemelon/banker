# -*- coding: utf-8 -*-
"""Tiller destination (Transactions-sheet CSV).

Tiller is a Google Sheets product that pulls its own bank feeds, so there's no
push API. This writes a CSV matching Tiller's *Transactions* sheet columns,
which you can paste/import into the sheet. Appending is idempotent.

Amount sign matches Tiller: negative = expense, positive = income. A stable
``Transaction ID`` (the hub's ``external_id``) is included so re-imports can be
de-duplicated.
"""

from __future__ import annotations

import csv
import os
from typing import List

from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination

_FIELDS = ["Date", "Description", "Category", "Amount", "Account",
           "Institution", "Transaction ID"]


def _row(txn: Transaction, institution: str) -> dict:
    return {
        "Date": txn.date.isoformat(),
        "Description": txn.payee or txn.notes or "",
        "Category": txn.category or "",
        "Amount": str(txn.amount),
        "Account": txn.target_account,
        "Institution": institution or txn.source,
        "Transaction ID": txn.external_id,
    }


@register_destination("tiller")
class TillerDestination(Destination):
    """Append transactions to a Tiller-format CSV.

    Options
    -------
    file
        Output path (default ``tiller.csv``).
    institution
        Value for the ``Institution`` column (defaults to the source name).
    mode
        ``"append"`` (default) or ``"overwrite"``.
    """

    requires = None

    def __init__(self, file: str = "tiller.csv", institution: str = "",
                 mode: str = "append", **options):
        super().__init__(file=file, mode=mode, **options)
        self.file = file
        self.institution = institution
        self.mode = mode

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        os.makedirs(os.path.dirname(os.path.abspath(self.file)), exist_ok=True)
        write_header = (self.mode == "overwrite" or not os.path.exists(self.file)
                        or os.path.getsize(self.file) == 0)
        open_mode = "w" if self.mode == "overwrite" else "a"
        results = []
        with open(self.file, open_mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            if write_header:
                writer.writeheader()
            for txn in transactions:
                writer.writerow(_row(txn, self.institution))
                results.append(PushResult(external_id=txn.external_id, status="created"))
        return results
