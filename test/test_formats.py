# -*- coding: utf-8 -*-
"""Tests for bank file-format sources (OFX/QFX, QIF, MT940, CAMT.053) and
the SimpleFIN aggregator parser.  All offline, fixture-driven."""

import datetime as dt
import json
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bankhub.sources.camt import CamtSource, parse_camt
from bankhub.sources.mt940 import Mt940Source, parse_mt940
from bankhub.sources.ofx import OfxSource, parse_ofx
from bankhub.sources.pdf import rows_to_transactions, tables_to_rowdicts
from bankhub.sources.qif import QifSource, parse_qif
from bankhub.sources.simplefin import iter_simplefin, simplefin_to_transaction

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _path(name):
    return os.path.join(FIX, name)


class OfxTests(unittest.TestCase):
    def test_parse_and_source(self):
        txns = OfxSource(file=_path("sample.ofx")).fetch_all()
        self.assertEqual(len(txns), 2)
        t0, t1 = txns
        self.assertEqual(t0.external_id, "FIT001")
        self.assertEqual(t0.account_id, "123456789")
        self.assertEqual(t0.currency, "usd")
        self.assertEqual(t0.amount, Decimal("-12.34"))
        self.assertEqual(t0.payee, "Coffee Shop")
        self.assertEqual(t0.notes, "Latte")
        self.assertEqual(t0.date, dt.date(2024, 1, 15))
        self.assertEqual(t1.amount, Decimal("2000.00"))
        self.assertEqual(t1.payee, "Payroll Inc")
        self.assertEqual(t1.source, "ofx")

    def test_xml_ofx2(self):
        text = ('<?xml version="1.0"?><?OFX OFXHEADER="200"?><OFX><BANKMSGSRSV1>'
                '<STMTTRNRS><STMTRS><CURDEF>EUR</CURDEF><BANKACCTFROM>'
                '<ACCTID>ACC9</ACCTID></BANKACCTFROM><BANKTRANLIST>'
                '<STMTTRN><DTPOSTED>20240201</DTPOSTED><TRNAMT>-5.00</TRNAMT>'
                '<FITID>X1</FITID><NAME>Shop</NAME></STMTTRN>'
                '</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>')
        recs = parse_ofx(text)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["account_id"], "ACC9")
        self.assertEqual(recs[0]["currency"], "eur")
        self.assertEqual(recs[0]["amount"], "-5.00")


class QifTests(unittest.TestCase):
    def test_source(self):
        txns = QifSource(file=_path("sample.qif")).fetch_all()
        self.assertEqual(len(txns), 2)
        t0, t1 = txns
        self.assertEqual(t0.account_id, "My Checking")
        self.assertEqual(t0.date, dt.date(2024, 1, 15))  # apostrophe year
        self.assertEqual(t0.amount, Decimal("-12.34"))
        self.assertEqual(t0.payee, "Coffee Shop")
        self.assertEqual(t0.notes, "Latte")
        self.assertEqual(t0.category, "Food")
        self.assertEqual(t1.amount, Decimal("2000.00"))  # 2,000.00 grouped
        self.assertEqual(t1.date, dt.date(2024, 1, 16))

    def test_parse_records(self):
        recs = parse_qif("!Type:Bank\nD2024-03-01\nT-1.00\nPx\n^\n")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["P"], "x")


class Mt940Tests(unittest.TestCase):
    def test_source(self):
        txns = Mt940Source(file=_path("sample.mt940")).fetch_all()
        self.assertEqual(len(txns), 2)
        t0, t1 = txns
        self.assertEqual(t0.account_id, "12345678/0001")
        self.assertEqual(t0.currency, "eur")
        self.assertEqual(t0.amount, Decimal("-12.34"))   # D mark
        self.assertEqual(t0.date, dt.date(2024, 1, 15))
        self.assertEqual(t0.payee, "COFFEE SHOP")        # structured :86: ?32
        self.assertEqual(t0.notes, "Latte")              # structured :86: ?20
        self.assertEqual(t1.amount, Decimal("2000.00"))  # C mark
        self.assertEqual(t1.payee, "GEHALT PAYROLL INC")

    def test_reversal_flips_sign(self):
        recs = parse_mt940(":25:ACC\n:60F:C240101EUR0,00\n"
                           ":61:240115D10,00NTRFREF\n:86:test\n")
        self.assertEqual(recs[0]["amount"], Decimal("-10.00"))
        recs = parse_mt940(":25:ACC\n:60F:C240101EUR0,00\n"
                           ":61:240115RD10,00NTRFREF\n:86:test\n")
        self.assertEqual(recs[0]["amount"], Decimal("10.00"))  # reversal


class CamtTests(unittest.TestCase):
    def test_source(self):
        txns = CamtSource(file=_path("sample.camt053.xml")).fetch_all()
        self.assertEqual(len(txns), 2)
        t0, t1 = txns
        self.assertEqual(t0.account_id, "DE89370400440532013000")
        self.assertEqual(t0.currency, "eur")
        self.assertEqual(t0.amount, Decimal("-12.34"))   # DBIT
        self.assertEqual(t0.payee, "Coffee Shop")        # DBIT -> Cdtr
        self.assertEqual(t0.notes, "Latte")
        self.assertEqual(t0.external_id, "ENTRY-1")
        self.assertEqual(t1.amount, Decimal("2000.00"))  # CRDT
        self.assertEqual(t1.payee, "Employer Inc")       # CRDT -> Dbtr

    def test_namespace_agnostic(self):
        # camt.053.001.02 namespace still parses.
        text = ('<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">'
                '<BkToCstmrStmt><Stmt><Acct><Id><IBAN>X1</IBAN></Id></Acct>'
                '<Ntry><Amt Ccy="GBP">9.99</Amt><CdtDbtInd>DBIT</CdtDbtInd>'
                '<BookgDt><Dt>2024-05-01</Dt></BookgDt></Ntry></Stmt>'
                '</BkToCstmrStmt></Document>')
        recs = parse_camt(text)
        self.assertEqual(recs[0]["amount"], Decimal("-9.99"))
        self.assertEqual(recs[0]["currency"], "gbp")


class SimpleFinTests(unittest.TestCase):
    def test_parser(self):
        with open(_path("simplefin_accounts.json")) as fh:
            payload = json.load(fh)
        rows = list(iter_simplefin(payload))
        self.assertEqual(len(rows), 2)
        t0 = simplefin_to_transaction(*rows[0])
        self.assertEqual(t0.external_id, "sf-1")
        self.assertEqual(t0.account_id, "acct-1")
        self.assertEqual(t0.currency, "usd")
        self.assertEqual(t0.amount, Decimal("-12.34"))
        self.assertEqual(t0.payee, "Coffee Shop")
        self.assertEqual(t0.date, dt.date(2024, 1, 15))
        self.assertEqual(t0.status, "posted")
        t1 = simplefin_to_transaction(*rows[1])
        self.assertEqual(t1.payee, "Employer Inc")  # payee field preferred
        self.assertEqual(t1.notes, "Salary")
        self.assertEqual(t1.status, "pending")


class PdfMapperTests(unittest.TestCase):
    """The pdfplumber extraction needs the lib + a real PDF, but the column
    mapping and row filtering -- the part that varies per bank -- is pure."""

    def test_header_based_mapping_and_noise_skipping(self):
        tables = [[
            ["Date", "Description", "Amount"],     # header row
            ["2024-01-15", "Coffee Shop", "-12.34"],
            ["2024-01-16", "Payroll", "2000.00"],
            ["Closing balance", "", ""],            # noise -> skipped
        ]]
        rowdicts = tables_to_rowdicts(tables, header_row=0)
        txns = rows_to_transactions(rowdicts, date_col="Date", amount_col="Amount",
                                    payee_col="Description")
        self.assertEqual(len(txns), 2)
        self.assertEqual(txns[0].amount, Decimal("-12.34"))
        self.assertEqual(txns[0].payee, "Coffee Shop")
        self.assertEqual(txns[0].date, dt.date(2024, 1, 15))

    def test_index_based_mapping(self):
        tables = [[
            ["01/15/2024", "Coffee", "-12.34"],
            ["bogus", "row", "x"],                   # unparseable -> skipped
        ]]
        rowdicts = tables_to_rowdicts(tables, header_row=-1)
        txns = rows_to_transactions(rowdicts, date_col=0, amount_col=2, payee_col=1,
                                    date_format="%m/%d/%Y")
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].payee, "Coffee")
        self.assertEqual(txns[0].amount, Decimal("-12.34"))


if __name__ == "__main__":
    unittest.main()
