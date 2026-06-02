# -*- coding: utf-8 -*-
"""Copilot Money destination (CSV import format).

Copilot has no public write API, but its apps can import a CSV. This writes a
CSV with the columns Copilot's importer recognises; you map/confirm them in
Copilot on import. Appending is idempotent (the engine only hands over
not-yet-delivered rows).

Amount sign matches Copilot: negative = expense, positive = income.
"""

from __future__ import annotations

import csv
import os
from typing import List

from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination

_FIELDS = ["date", "name", "amount", "status", "category", "account", "note", "type"]


def _row(txn: Transaction) -> dict:
    return {
        "date": txn.date.isoformat(),
        "name": txn.payee or txn.notes or "",
        "amount": str(txn.amount),
        "status": "posted" if txn.status == "posted" else "pending",
        "category": txn.category or "",
        "account": txn.target_account,
        "note": txn.notes or "",
        "type": "income" if txn.amount > 0 else "regular",
    }


@register_destination("copilot")
class CopilotDestination(Destination):
    """Append transactions to a Copilot-import CSV.

    Options
    -------
    file
        Output path (default ``copilot.csv``).
    mode
        ``"append"`` (default) or ``"overwrite"``.
    """

    requires = None

    def __init__(self, file: str = "copilot.csv", mode: str = "append", **options):
        super().__init__(file=file, mode=mode, **options)
        self.file = file
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
                writer.writerow(_row(txn))
                results.append(PushResult(external_id=txn.external_id, status="created"))
        return results
