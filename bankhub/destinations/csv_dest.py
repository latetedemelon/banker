# -*- coding: utf-8 -*-
"""CSV export destination.

Writes normalised transactions to a CSV file.  Because the engine only ever
hands a destination transactions it hasn't delivered yet, appending to the
file is naturally idempotent across runs.
"""

from __future__ import annotations

import csv
import os
from typing import List

from ..models import PushResult, Transaction
from ..registry import register_destination
from .base import Destination

_FIELDS = ["external_id", "date", "amount", "currency", "payee", "notes",
           "category", "account", "source", "status"]


@register_destination("csv")
class CsvDestination(Destination):
    """Append transactions to a CSV file.

    Options
    -------
    file
        Output path (default ``export.csv``).
    mode
        ``"append"`` (default) or ``"overwrite"``.
    """

    requires = None

    def __init__(self, file: str = "export.csv", mode: str = "append", **options):
        super().__init__(file=file, mode=mode, **options)
        self.file = file
        self.mode = mode

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        directory = os.path.dirname(os.path.abspath(self.file))
        os.makedirs(directory, exist_ok=True)
        write_header = self.mode == "overwrite" or not os.path.exists(self.file) \
            or os.path.getsize(self.file) == 0
        open_mode = "w" if self.mode == "overwrite" else "a"
        results = []
        with open(self.file, open_mode, newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            if write_header:
                writer.writeheader()
            for txn in transactions:
                writer.writerow({
                    "external_id": txn.external_id,
                    "date": txn.date.isoformat(),
                    "amount": str(txn.amount),
                    "currency": txn.currency,
                    "payee": txn.payee,
                    "notes": txn.notes,
                    "category": txn.category or "",
                    "account": txn.target_account,
                    "source": txn.source,
                    "status": txn.status,
                })
                results.append(PushResult(external_id=txn.external_id,
                                          status="created"))
        return results
