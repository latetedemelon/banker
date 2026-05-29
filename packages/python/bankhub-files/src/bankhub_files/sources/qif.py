# -*- coding: utf-8 -*-
"""QIF (Quicken Interchange Format) statement source.

QIF is a line-based format: each field is a single-letter code followed by a
value, and ``^`` ends a record.  ``!Account`` / ``!Type:`` headers switch
context.  Pure and fixture-tested.

Sign convention: the ``T`` amount is already signed (negative = outflow).
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, Iterator, List, Optional

from bankhub.errors import ConfigError
from bankhub.models import Transaction
from bankhub.normalize import clean_text, compute_external_id, parse_amount
from bankhub.registry import register_source
from bankhub.sources.base import Source

_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y",
                 "%Y-%m-%d", "%Y/%m/%d")


def qif_date(value: str, fmt: Optional[str] = None) -> _dt.date:
    # Quicken writes 2000+ years as 1/15'24 -- normalise the apostrophe.
    text = value.replace("'", "/").replace(".", "/").strip()
    for candidate in ((fmt,) if fmt else _DATE_FORMATS):
        try:
            return _dt.datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    # Last resort: ISO prefix.
    return _dt.date.fromisoformat(text[:10])


def parse_qif(text: str, default_account: str = "") -> List[Dict]:
    """Extract transaction records from QIF text (pure)."""
    records: List[Dict] = []
    current: Dict[str, str] = {}
    account = default_account
    mode = "txn"
    for raw in text.splitlines():
        line = raw.strip("\r\n")
        if not line.strip():
            continue
        if line.startswith("!"):
            header = line[1:].strip().lower()
            if header.startswith("account"):
                mode = "account"
            elif header.startswith("type:"):
                mode = "txn"
            current = {}
            continue
        code, value = line[0], line[1:].strip()
        if code == "^":
            if mode == "account":
                if current.get("N"):
                    account = current["N"]
            elif current:
                current["_account"] = account
                records.append(current)
            current = {}
            continue
        current[code] = value
    return records


def qif_record_to_transaction(rec: Dict, fmt: Optional[str] = None,
                              currency: str = "usd") -> Transaction:
    date = qif_date(rec["D"], fmt)
    amount = parse_amount(rec.get("T") or rec.get("U") or "0")
    payee = clean_text(rec.get("P"))
    notes = clean_text(rec.get("M"))
    account_id = rec.get("_account") or "qif"
    checknum = rec.get("N", "")
    external_id = compute_external_id("qif", account_id, date, amount,
                                      payee, notes, checknum)
    return Transaction(
        external_id=external_id,
        source="qif",
        account_id=account_id,
        date=date,
        amount=amount,
        currency=currency,
        payee=payee,
        notes=notes,
        category=clean_text(rec.get("L")) or None,
        raw=rec,
    )


@register_source("qif")
class QifSource(Source):
    """Read a QIF file.

    Options
    -------
    file / content
        The QIF file path, or raw QIF text.
    date_format
        Override the date parser (e.g. ``%d/%m/%Y`` for non-US files).
    currency
        Currency code for all rows (QIF has none; default ``usd``).
    account
        Default account id when the file has no ``!Account`` block.
    """

    requires = None

    def __init__(self, file: str = None, content: str = None,
                 date_format: str = None, currency: str = "usd",
                 account: str = "", encoding: str = "utf-8", **options):
        super().__init__(file=file, content=content, **options)
        if not file and content is None:
            raise ConfigError("qif source needs a 'file' or 'content' option")
        self.file = file
        self.content = content
        self.date_format = date_format
        self.currency = currency
        self.account = account
        self.encoding = encoding

    def fetch(self) -> Iterator[Transaction]:
        if self.content is not None:
            text = self.content
        else:
            with open(self.file, "r", encoding=self.encoding, errors="replace") as fh:
                text = fh.read()
        for rec in parse_qif(text, default_account=self.account):
            yield qif_record_to_transaction(rec, self.date_format, self.currency)
