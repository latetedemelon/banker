# -*- coding: utf-8 -*-
"""OFX / QFX export destination.

Writes an OFX statement file that Quicken, Quicken Simplifi, GnuCash and most
finance apps can import.  Defaults to OFX 1.0.2 (SGML), the most widely
accepted flavour; set ``version=2`` for OFX 2.x (XML).  Provide ``intu_bid``
to emit a Quicken-flavoured ``.qfx``.

Unlike the CSV/JSON/XLSX destinations, an OFX file is a structured snapshot, so
each run **overwrites** the target with the transactions delivered that run
(the engine only hands over not-yet-delivered rows). Point it at a fresh path
per run, or re-import.
"""

from __future__ import annotations

import datetime as _dt
import os
from collections import defaultdict
from typing import List

from bankhub.models import PushResult, Transaction
from bankhub.registry import register_destination
from bankhub.destinations.base import Destination


def _esc(value) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_ofx(transactions: List[Transaction], *, version: int = 1,
              default_currency: str = "USD", bankid: str = "0",
              accttype: str = "CHECKING", intu_bid: str = None) -> str:
    """Render transactions as an OFX document (pure; SGML for v1, XML for v2)."""
    sgml = int(version) == 1

    def leaf(tag: str, val) -> str:
        return f"<{tag}>{_esc(val)}" + ("" if sgml else f"</{tag}>")

    now = _dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    if sgml:
        head = ("OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\n"
                "ENCODING:USASCII\nCHARSET:1252\nCOMPRESSION:NONE\n"
                "OLDFILEUID:NONE\nNEWFILEUID:NONE\n\n")
    else:
        head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<?OFX OFXHEADER="200" VERSION="211" SECURITY="NONE" '
                'OLDFILEUID="NONE" NEWFILEUID="NONE"?>\n')

    out = [head, "<OFX>"]
    # Sign-on.
    out.append("<SIGNONMSGSRSV1><SONRS><STATUS>"
               + leaf("CODE", 0) + leaf("SEVERITY", "INFO") + "</STATUS>"
               + leaf("DTSERVER", now) + leaf("LANGUAGE", "ENG"))
    if intu_bid:
        out.append("<FI>" + leaf("ORG", "banker") + leaf("FID", intu_bid) + "</FI>"
                   + leaf("INTU.BID", intu_bid))
    out.append("</SONRS></SIGNONMSGSRSV1>")

    # One statement per account.
    by_account = defaultdict(list)
    for txn in transactions:
        by_account[txn.target_account or "0"].append(txn)

    out.append("<BANKMSGSRSV1>")
    for uid, (acctid, txns) in enumerate(sorted(by_account.items()), start=1):
        dates = [t.date for t in txns]
        curdef = (txns[0].currency or default_currency).upper()
        out.append("<STMTTRNRS>" + leaf("TRNUID", uid) + "<STATUS>"
                   + leaf("CODE", 0) + leaf("SEVERITY", "INFO") + "</STATUS>")
        out.append("<STMTRS>" + leaf("CURDEF", curdef)
                   + "<BANKACCTFROM>" + leaf("BANKID", bankid) + leaf("ACCTID", acctid)
                   + leaf("ACCTTYPE", accttype) + "</BANKACCTFROM>")
        out.append("<BANKTRANLIST>" + leaf("DTSTART", min(dates).strftime("%Y%m%d"))
                   + leaf("DTEND", max(dates).strftime("%Y%m%d")))
        for t in txns:
            out.append("<STMTTRN>"
                       + leaf("TRNTYPE", "DEBIT" if t.amount < 0 else "CREDIT")
                       + leaf("DTPOSTED", t.date.strftime("%Y%m%d"))
                       + leaf("TRNAMT", t.amount)
                       + leaf("FITID", t.external_id)
                       + leaf("NAME", (t.payee or "")[:32])
                       + (leaf("MEMO", t.notes) if t.notes else "")
                       + "</STMTTRN>")
        out.append("</BANKTRANLIST>"
                   + "<LEDGERBAL>" + leaf("BALAMT", "0.00") + leaf("DTASOF", now)
                   + "</LEDGERBAL>")
        out.append("</STMTRS></STMTTRNRS>")
    out.append("</BANKMSGSRSV1></OFX>\n")
    return "\n".join(out)


@register_destination("ofx")
class OfxDestination(Destination):
    """Write transactions to an OFX/QFX file (Quicken/Simplifi/GnuCash import).

    Options
    -------
    file
        Output path (default ``export.ofx``).
    version
        ``1`` for OFX 1.0.2 SGML (default), ``2`` for OFX 2.x XML.
    bankid, accttype, intu_bid
        Optional ``BANKID`` / account type / Quicken ``INTU.BID`` (for ``.qfx``).
    """

    requires = None

    def __init__(self, file: str = "export.ofx", version="1", bankid: str = "0",
                 accttype: str = "CHECKING", intu_bid: str = None, **options):
        super().__init__(file=file, **options)
        self.file = file
        self.version = int(version)
        self.bankid = bankid
        self.accttype = accttype
        self.intu_bid = intu_bid

    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        if not transactions:
            return []
        directory = os.path.dirname(os.path.abspath(self.file))
        os.makedirs(directory, exist_ok=True)
        doc = build_ofx(transactions, version=self.version, bankid=self.bankid,
                        accttype=self.accttype, intu_bid=self.intu_bid)
        with open(self.file, "w", encoding="utf-8") as fh:
            fh.write(doc)
        return [PushResult(external_id=t.external_id, status="created")
                for t in transactions]
