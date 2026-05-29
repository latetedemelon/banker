# -*- coding: utf-8 -*-
"""JSON / JSON-Lines export destination."""

from __future__ import annotations

import json
import os
from typing import List

from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination


@register_destination("json")
class JsonDestination(Destination):
    """Write transactions to a ``.jsonl`` (default) or ``.json`` file.

    Options
    -------
    file
        Output path (default ``export.jsonl``).
    format
        ``"jsonl"`` (append one object per line, default) or ``"json"``
        (rewrite a single JSON array each push).
    """

    requires = None

    def __init__(self, file: str = "export.jsonl", format: str = "jsonl", **options):
        super().__init__(file=file, format=format, **options)
        self.file = file
        self.format = format

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        directory = os.path.dirname(os.path.abspath(self.file))
        os.makedirs(directory, exist_ok=True)
        results = [PushResult(external_id=t.external_id, status="created")
                   for t in transactions]
        if self.format == "json":
            existing = []
            if os.path.exists(self.file) and os.path.getsize(self.file):
                with open(self.file, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
            existing.extend(t.to_dict() for t in transactions)
            with open(self.file, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2, ensure_ascii=False)
        else:  # jsonl
            with open(self.file, "a", encoding="utf-8") as fh:
                for txn in transactions:
                    fh.write(json.dumps(txn.to_dict(), ensure_ascii=False) + "\n")
        return results
