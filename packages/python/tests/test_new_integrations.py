# -*- coding: utf-8 -*-
"""Tests for the newer adapters: Stripe, Firefly III, PocketSmith, XLSX, the
OFX/QFX writer, and the Copilot/Tiller export formats."""

import calendar
import datetime as dt
import unittest
from decimal import Decimal

import bankhub
from bankhub_connectors.sources.stripe_fc import stripe_fc_to_transaction
from bankhub_connectors.sources.stripe_payments import balance_txn_to_transaction
from bankhub_connectors.destinations.firefly import transaction_to_firefly
from bankhub_connectors.destinations.pocketsmith import transaction_to_pocketsmith
from bankhub_files.destinations.ofx_dest import build_ofx
from bankhub_files.destinations.copilot import _row as copilot_row
from bankhub_files.destinations.tiller import _row as tiller_row
from bankhub_files.sources.ofx import parse_ofx
from bankhub_files.sources.xlsx import xlsx_rows_to_transactions


def _txn(**kw):
    base = dict(external_id="x1", source="s", account_id="acct1",
                date=dt.date(2024, 1, 15), amount=Decimal("-12.34"),
                currency="usd", payee="Coffee", notes="latte")
    base.update(kw)
    return bankhub.Transaction(**base)


_UTC_20240115 = calendar.timegm(dt.datetime(2024, 1, 15, 12, 0, 0).timetuple())


class StripeFinancialConnectionsTests(unittest.TestCase):
    def test_outflow_kept_negative_and_scaled(self):
        t = stripe_fc_to_transaction({
            "id": "fctxn_1", "amount": -1234, "currency": "USD",
            "description": "Coffee Shop", "status": "posted",
            "transacted_at": _UTC_20240115, "account": "fca_1"})
        self.assertEqual(t.external_id, "fctxn_1")
        self.assertEqual(t.amount, Decimal("-12.34"))
        self.assertEqual(t.currency, "usd")
        self.assertEqual(t.account_id, "fca_1")
        self.assertEqual(t.date, dt.date(2024, 1, 15))
        self.assertEqual(t.payee, "Coffee Shop")

    def test_pending_status(self):
        t = stripe_fc_to_transaction({"id": "f2", "amount": 500, "currency": "eur",
                                      "status": "pending", "transacted_at": _UTC_20240115})
        self.assertEqual(t.status, "pending")
        self.assertEqual(t.amount, Decimal("5.00"))


class StripePaymentsTests(unittest.TestCase):
    def test_balance_transaction(self):
        t = balance_txn_to_transaction({
            "id": "txn_1", "amount": 2500, "currency": "usd", "type": "charge",
            "description": "Order 99", "status": "available", "created": _UTC_20240115})
        self.assertEqual(t.amount, Decimal("25.00"))     # positive = into balance
        self.assertEqual(t.status, "posted")
        self.assertEqual(t.payee, "Order 99")
        self.assertEqual(t.source, "stripe_payments")


class FireflyMappingTests(unittest.TestCase):
    def test_withdrawal_for_outflow(self):
        split = transaction_to_firefly(_txn(amount=Decimal("-12.34")), "Assets:Checking")
        self.assertEqual(split["type"], "withdrawal")
        self.assertEqual(split["amount"], "12.34")            # always positive
        self.assertEqual(split["source_name"], "Assets:Checking")
        self.assertEqual(split["destination_name"], "Coffee")  # payee = expense
        self.assertEqual(split["external_id"], "x1")

    def test_deposit_for_inflow(self):
        split = transaction_to_firefly(_txn(amount=Decimal("100"), payee="Payroll"),
                                       "Assets:Checking")
        self.assertEqual(split["type"], "deposit")
        self.assertEqual(split["source_name"], "Payroll")
        self.assertEqual(split["destination_name"], "Assets:Checking")


class PocketSmithMappingTests(unittest.TestCase):
    def test_signed_amount_passthrough(self):
        body = transaction_to_pocketsmith(_txn(amount=Decimal("-12.34")))
        self.assertEqual(body["amount"], -12.34)   # negative = debit, as PocketSmith wants
        self.assertEqual(body["date"], "2024-01-15")
        self.assertEqual(body["payee"], "Coffee")


class OfxWriterTests(unittest.TestCase):
    def _roundtrip(self, version):
        txns = [_txn(external_id="A1", amount=Decimal("-12.34"), payee="Coffee"),
                _txn(external_id="B2", amount=Decimal("100.00"), payee="Payroll", notes="")]
        parsed = parse_ofx(build_ofx(txns, version=version))
        return {r["fitid"]: r for r in parsed}

    def test_sgml_roundtrip(self):
        got = self._roundtrip(1)
        self.assertEqual(set(got), {"A1", "B2"})
        self.assertEqual(got["A1"]["amount"], "-12.34")
        self.assertEqual(got["B2"]["amount"], "100.00")

    def test_xml_roundtrip(self):
        got = self._roundtrip(2)
        self.assertEqual(got["A1"]["amount"], "-12.34")

    def test_debit_credit_trntype(self):
        doc = build_ofx([_txn(amount=Decimal("-5"))], version=1)
        self.assertIn("<TRNTYPE>DEBIT", doc)
        doc2 = build_ofx([_txn(amount=Decimal("5"))], version=1)
        self.assertIn("<TRNTYPE>CREDIT", doc2)

    def test_amp_escaped(self):
        doc = build_ofx([_txn(payee="Tom & Jerry")], version=2)
        self.assertIn("Tom &amp; Jerry", doc)


class XlsxMapperTests(unittest.TestCase):
    def test_basic_mapping(self):
        rows = [{"Date": "2024-01-15", "Amt": "-9.99", "Desc": "Tea"}]
        out = xlsx_rows_to_transactions(
            rows, columns={"date": "Date", "amount": "Amt", "payee": "Desc"},
            source="xlsx", currency="gbp")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].amount, Decimal("-9.99"))
        self.assertEqual(out[0].currency, "gbp")
        self.assertEqual(out[0].payee, "Tea")

    def test_blank_rows_skipped_and_decimal_comma(self):
        rows = [{"d": "", "a": ""},
                {"d": "2024-02-01", "a": "1.234,56"}]
        out = xlsx_rows_to_transactions(
            rows, columns={"date": "d", "amount": "a"}, source="xlsx",
            decimal_comma=True)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].amount, Decimal("1234.56"))


class ExportFormatTests(unittest.TestCase):
    def test_copilot_row(self):
        r = copilot_row(_txn(amount=Decimal("-12.34")))
        self.assertEqual(r["amount"], "-12.34")
        self.assertEqual(r["type"], "regular")          # expense
        self.assertEqual(r["account"], "acct1")
        self.assertEqual(copilot_row(_txn(amount=Decimal("9")))["type"], "income")

    def test_tiller_row(self):
        r = tiller_row(_txn(amount=Decimal("-12.34")), institution="Acme")
        self.assertEqual(r["Transaction ID"], "x1")
        self.assertEqual(r["Amount"], "-12.34")
        self.assertEqual(r["Institution"], "Acme")
        self.assertEqual(r["Date"], "2024-01-15")


try:
    import openpyxl  # noqa: F401
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False


@unittest.skipUnless(_HAS_OPENPYXL, "openpyxl not installed")
class XlsxRoundTripTests(unittest.TestCase):
    """Exercises the real openpyxl read/write path (regression: a numeric
    sheet ref like the default "0" must mean index 0, not a sheet named "0")."""

    def test_write_then_read_default_sheet(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "out.xlsx")
        bankhub.build_destination("xlsx", file=path).push([_txn(amount=Decimal("-12.34"))])
        back = bankhub.build_source("xlsx", file=path, date="date",
                                    amount="amount", payee="payee").fetch_all()
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].amount, Decimal("-12.34"))
        self.assertEqual(back[0].payee, "Coffee")

    def test_read_by_sheet_name(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "out.xlsx")
        bankhub.build_destination("xlsx", file=path).push([_txn()])
        back = bankhub.build_source("xlsx", file=path, sheet="Transactions",
                                    date="date", amount="amount").fetch_all()
        self.assertEqual(len(back), 1)


class RegistrationTests(unittest.TestCase):
    def test_new_adapters_registered(self):
        srcs, dests = bankhub.available_sources(), bankhub.available_destinations()
        for name in ("stripe", "stripe_payments", "xlsx"):
            self.assertIn(name, srcs)
        for name in ("firefly", "pocketsmith", "xlsx", "ofx", "copilot",
                     "tiller", "gnucash"):
            self.assertIn(name, dests)

    def test_optional_dep_hints(self):
        self.assertEqual(bankhub.get_source_class("xlsx").requires, "openpyxl")
        self.assertEqual(bankhub.get_destination_class("gnucash").requires, "piecash")


if __name__ == "__main__":
    unittest.main()
