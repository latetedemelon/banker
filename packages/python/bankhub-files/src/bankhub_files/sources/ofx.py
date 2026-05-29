# -*- coding: utf-8 -*-
"""OFX / QFX statement source.

Parses both OFX 1.x (SGML, unclosed leaf tags) and OFX 2.x (XML) as well as
Quicken's QFX variant, which is OFX with a few extra proprietary tags we
simply ignore.  Pure and fixture-tested.

Sign convention: OFX ``<TRNAMT>`` is already signed (negative = debit), which
matches the hub convention, so no flipping is needed.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, Iterator, List

from bankhub.errors import ConfigError
from bankhub.models import Transaction
from bankhub.normalize import clean_text, compute_external_id, parse_amount
from bankhub.registry import register_source
from bankhub.sources.base import Source

# Matches, in document order: an account id, a default currency, or a whole
# transaction aggregate.  ACCTID covers both BANKACCTFROM and CCACCTFROM.
_TOKEN_RE = re.compile(
    r"<STMTTRN>(?P<trn>.*?)</STMTTRN>"
    r"|<ACCTID>(?P<acct>[^<\r\n]*)"
    r"|<CURDEF>(?P<cur>[^<\r\n]*)",
    re.IGNORECASE | re.DOTALL,
)


def _leaf(tag: str, block: str) -> str:
    match = re.search(rf"<{tag}>([^<\r\n]*)", block, re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def _ofx_date(value: str) -> _dt.date:
    digits = re.sub(r"[^0-9]", "", value)[:8]
    return _dt.datetime.strptime(digits, "%Y%m%d").date()


def parse_ofx(text: str) -> List[Dict]:
    """Extract transaction records from OFX/QFX text (pure)."""
    body = text
    idx = text.upper().find("<OFX>")
    if idx != -1:
        body = text[idx:]

    account = ""
    currency = ""
    records: List[Dict] = []
    for match in _TOKEN_RE.finditer(body):
        if match.group("acct") is not None:
            account = clean_text(match.group("acct"))
        elif match.group("cur") is not None:
            currency = clean_text(match.group("cur")).lower()
        else:
            block = match.group("trn")
            payee = _leaf("NAME", block) or _leaf("MEMO", block)
            records.append({
                "fitid": _leaf("FITID", block),
                "account_id": account,
                "currency": currency,
                "date": _leaf("DTPOSTED", block),
                "amount": _leaf("TRNAMT", block),
                "payee": payee,
                "memo": _leaf("MEMO", block),
                "trntype": _leaf("TRNTYPE", block),
                "checknum": _leaf("CHECKNUM", block),
            })
    return records


def ofx_record_to_transaction(rec: Dict) -> Transaction:
    date = _ofx_date(rec["date"])
    amount = parse_amount(rec["amount"])
    account_id = rec.get("account_id") or "ofx"
    external_id = rec.get("fitid") or compute_external_id(
        "ofx", account_id, date, amount, rec.get("payee", ""), rec.get("memo", ""))
    return Transaction(
        external_id=external_id,
        source="ofx",
        account_id=account_id,
        date=date,
        amount=amount,
        currency=rec.get("currency") or "usd",
        payee=clean_text(rec.get("payee")),
        notes=clean_text(rec.get("memo")),
        raw=rec,
    )


@register_source("ofx")
class OfxSource(Source):
    """Read an OFX or QFX statement file.

    Options
    -------
    file
        Path to the .ofx/.qfx file (mutually exclusive with ``content``).
    content
        Raw OFX text (handy for tests / stdin).
    encoding
        File encoding (default ``utf-8``; OFX is often latin-1).
    """

    requires = None

    def __init__(self, file: str = None, content: str = None,
                 encoding: str = "utf-8", **options):
        super().__init__(file=file, content=content, **options)
        if not file and content is None:
            raise ConfigError("ofx source needs a 'file' or 'content' option")
        self.file = file
        self.content = content
        self.encoding = encoding

    def fetch(self) -> Iterator[Transaction]:
        if self.content is not None:
            text = self.content
        else:
            with open(self.file, "r", encoding=self.encoding, errors="replace") as fh:
                text = fh.read()
        for rec in parse_ofx(text):
            yield ofx_record_to_transaction(rec)
