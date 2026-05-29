# -*- coding: utf-8 -*-
"""MT940 (SWIFT bank statement) source.

Parses the common subset of MT940: ``:25:`` account, ``:60F:`` opening
balance (for the currency), ``:61:`` statement lines and ``:86:`` narrative.
Handles multi-line tags and German-style structured ``:86:`` subfields.
Pure and fixture-tested.

Sign convention: the ``:61:`` debit/credit mark sets the sign (D = outflow
=> negative, C = inflow => positive; an R prefix flips it for reversals).
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, Iterator, List, Tuple

from ..errors import ConfigError
from ..models import Transaction
from ..normalize import clean_text, compute_external_id, parse_amount
from ..registry import register_source
from .base import Source

_TAG_RE = re.compile(r"^:(\d{2}[A-Z]?):(.*)$")
_61_RE = re.compile(
    r"^(?P<vdate>\d{6})(?P<edate>\d{4})?"
    r"(?P<dc>RD|RC|ED|EC|D|C)"
    r"(?P<funds>[A-Za-z])?"
    r"(?P<amount>[\d,]+)"
    r"(?P<swift>[A-Z][A-Z0-9]{3})?"
    r"(?P<ref>.*)$"
)
_60_RE = re.compile(r"^[CD]\d{6}(?P<cur>[A-Z]{3})")


def _yymmdd(value: str) -> _dt.date:
    return _dt.date(2000 + int(value[0:2]), int(value[2:4]), int(value[4:6]))


def _parse_86(text: str) -> Tuple[str, str]:
    """Return ``(payee, notes)`` from a :86: narrative."""
    text = text.strip()
    if re.match(r"^\d{3}\?", text):  # structured (German banks)
        fields: Dict[str, str] = {}
        for m in re.finditer(r"\?(\d{2})([^?]*)", text):
            fields[m.group(1)] = fields.get(m.group(1), "") + m.group(2)
        name = clean_text(fields.get("32", "") + " " + fields.get("33", ""))
        purpose = clean_text(" ".join(fields[c] for c in sorted(fields)
                                      if c.startswith("2")))
        return name or purpose, purpose or name
    cleaned = clean_text(text)
    return cleaned, cleaned


def parse_mt940(text: str) -> List[Dict]:
    """Extract transaction records from MT940 text (pure)."""
    # Accumulate tags, joining continuation lines into the previous tag.
    tags: List[Tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line:
            continue
        m = _TAG_RE.match(line)
        if m:
            tags.append((m.group(1), m.group(2)))
        elif tags:
            tags[-1] = (tags[-1][0], tags[-1][1] + " " + line.strip())

    records: List[Dict] = []
    account = ""
    currency = ""
    pending = None
    for tag, value in tags:
        if tag == "25":
            account = clean_text(value)
        elif tag in ("60F", "60M"):
            mb = _60_RE.match(value.strip())
            if mb:
                currency = mb.group("cur").lower()
        elif tag == "61":
            if pending:
                records.append(pending)
            m = _61_RE.match(value.strip())
            if not m:
                pending = None
                continue
            mark = m.group("dc")
            sign = -1 if mark[-1] == "D" else 1
            if mark.startswith("R"):
                sign = -sign
            amount = sign * parse_amount(m.group("amount"), decimal_comma=True)
            pending = {
                "account_id": account,
                "currency": currency,
                "date": _yymmdd(m.group("vdate")),
                "amount": amount,
                "reference": clean_text(m.group("ref")),
                "payee": "",
                "notes": "",
            }
        elif tag == "86" and pending is not None:
            payee, notes = _parse_86(value)
            pending["payee"] = payee
            pending["notes"] = notes
            records.append(pending)
            pending = None
    if pending:
        records.append(pending)
    return records


def mt940_record_to_transaction(rec: Dict) -> Transaction:
    account_id = rec.get("account_id") or "mt940"
    external_id = compute_external_id(
        "mt940", account_id, rec["date"], rec["amount"],
        rec.get("payee", ""), rec.get("notes", ""), rec.get("reference", ""))
    return Transaction(
        external_id=external_id,
        source="mt940",
        account_id=account_id,
        date=rec["date"],
        amount=rec["amount"],
        currency=rec.get("currency") or "eur",
        payee=rec.get("payee", ""),
        notes=rec.get("notes", "") or rec.get("reference", ""),
        raw={k: (str(v) if isinstance(v, _dt.date) else v) for k, v in rec.items()},
    )


@register_source("mt940")
class Mt940Source(Source):
    """Read an MT940 (.sta/.mt940) statement file.

    Options
    -------
    file / content
        The MT940 file path, or raw MT940 text.
    encoding
        File encoding (default ``utf-8``).
    """

    requires = None

    def __init__(self, file: str = None, content: str = None,
                 encoding: str = "utf-8", **options):
        super().__init__(file=file, content=content, **options)
        if not file and content is None:
            raise ConfigError("mt940 source needs a 'file' or 'content' option")
        self.file = file
        self.content = content
        self.encoding = encoding

    def fetch(self) -> Iterator[Transaction]:
        if self.content is not None:
            text = self.content
        else:
            with open(self.file, "r", encoding=self.encoding, errors="replace") as fh:
                text = fh.read()
        for rec in parse_mt940(text):
            yield mt940_record_to_transaction(rec)
