# -*- coding: utf-8 -*-
"""CAMT.053 (ISO 20022 bank statement) source.

Parses the ``BkToCstmrStmt`` document used across SEPA / European banking.
Namespace-agnostic (works across camt.053.001.02 … .08) by matching on local
element names.  One transaction is emitted per booked ``<Ntry>``.  Pure and
fixture-tested.

Sign convention: ``<CdtDbtInd>`` sets the sign (CRDT = inflow => positive,
DBIT = outflow => negative); ``<Amt>`` itself is unsigned.
"""

from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Dict, Iterator, List, Optional

from bankhub.errors import ConfigError
from bankhub.models import PENDING, POSTED, Transaction
from bankhub.normalize import clean_text, compute_external_id
from bankhub.registry import register_source
from bankhub.sources.base import Source


def _lname(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _dchildren(el, name: str) -> List:
    return [c for c in list(el) if _lname(c) == name]


def _dchild(el, name: str):
    found = _dchildren(el, name)
    return found[0] if found else None


def _iter_local(el, name: str) -> List:
    return [c for c in el.iter() if _lname(c) == name]


def _text(el) -> str:
    return clean_text(el.text) if el is not None and el.text else ""


def _date_of(el) -> Optional[_dt.date]:
    if el is None:
        return None
    dt = _dchild(el, "Dt") or _dchild(el, "DtTm")
    return _dt.date.fromisoformat(_text(dt)[:10]) if dt is not None else None


def parse_camt(text: str) -> List[Dict]:
    """Extract transaction records from CAMT.053 XML (pure)."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    records: List[Dict] = []
    for stmt in _iter_local(root, "Stmt"):
        acct = _dchild(stmt, "Acct")
        account_id = ""
        currency = ""
        if acct is not None:
            ident = _dchild(acct, "Id")
            if ident is not None:
                iban = _dchild(ident, "IBAN")
                if iban is not None:
                    account_id = _text(iban)
                else:
                    othr = _iter_local(ident, "Id")
                    account_id = _text(othr[0]) if othr else ""
            ccy = _dchild(acct, "Ccy")
            currency = _text(ccy).lower()

        for ntry in _iter_local(stmt, "Ntry"):
            amt_el = _dchild(ntry, "Amt")
            if amt_el is None:
                continue
            amount = Decimal(_text(amt_el))
            entry_ccy = (amt_el.get("Ccy") or currency or "eur").lower()
            ind = _text(_dchild(ntry, "CdtDbtInd")).upper()
            if ind == "DBIT":
                amount = -amount

            sts_el = _dchild(ntry, "Sts")
            status_code = ""
            if sts_el is not None:
                cd = _dchild(sts_el, "Cd")
                status_code = _text(cd) if cd is not None else _text(sts_el)
            status = PENDING if status_code.upper() == "PDNG" else POSTED

            date = (_date_of(_dchild(ntry, "BookgDt"))
                    or _date_of(_dchild(ntry, "ValDt")))
            ref = _text(_dchild(ntry, "AcctSvcrRef")) or _text(_dchild(ntry, "NtryRef"))

            payee, notes = "", ""
            txdetails = _iter_local(ntry, "TxDtls")
            if txdetails:
                tx = txdetails[0]
                ustrd = _iter_local(tx, "Ustrd")
                notes = clean_text(" ".join(_text(u) for u in ustrd))
                cdtr = _iter_local(tx, "Cdtr")
                dbtr = _iter_local(tx, "Dbtr")
                cdtr_nm = _text(_iter_local(cdtr[0], "Nm")[0]) if cdtr and _iter_local(cdtr[0], "Nm") else ""
                dbtr_nm = _text(_iter_local(dbtr[0], "Nm")[0]) if dbtr and _iter_local(dbtr[0], "Nm") else ""
                payee = (cdtr_nm if ind == "DBIT" else dbtr_nm) or cdtr_nm or dbtr_nm
            if not notes:
                notes = _text(_dchild(ntry, "AddtlNtryInf"))

            records.append({
                "external_id": ref,
                "account_id": account_id,
                "currency": entry_ccy,
                "date": date,
                "amount": amount,
                "payee": payee,
                "notes": notes,
                "status": status,
            })
    return records


def camt_record_to_transaction(rec: Dict) -> Transaction:
    account_id = rec.get("account_id") or "camt"
    date = rec["date"]
    external_id = rec.get("external_id") or compute_external_id(
        "camt", account_id, date, rec["amount"], rec.get("payee", ""), rec.get("notes", ""))
    return Transaction(
        external_id=external_id,
        source="camt",
        account_id=account_id,
        date=date,
        amount=rec["amount"],
        currency=rec.get("currency") or "eur",
        payee=rec.get("payee", ""),
        notes=rec.get("notes", ""),
        status=rec.get("status", POSTED),
        raw={k: (str(v) if isinstance(v, _dt.date) else v) for k, v in rec.items()},
    )


@register_source("camt")
class CamtSource(Source):
    """Read a CAMT.053 (.xml) bank statement.

    Options
    -------
    file / content
        The CAMT.053 file path, or raw XML text.
    encoding
        File encoding (default ``utf-8``).
    """

    requires = None

    def __init__(self, file: str = None, content: str = None,
                 encoding: str = "utf-8", **options):
        super().__init__(file=file, content=content, **options)
        if not file and content is None:
            raise ConfigError("camt source needs a 'file' or 'content' option")
        self.file = file
        self.content = content
        self.encoding = encoding

    def fetch(self) -> Iterator[Transaction]:
        if self.content is not None:
            text = self.content
        else:
            with open(self.file, "r", encoding=self.encoding, errors="replace") as fh:
                text = fh.read()
        for rec in parse_camt(text):
            yield camt_record_to_transaction(rec)
