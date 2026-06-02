# -*- coding: utf-8 -*-
"""Hardening tests: split debit/credit columns (CSV + PDF) and mock-based
HTTP flow tests for the API adapters (request URL, auth, pagination, and the
created/duplicate/error paths) -- the validation that doesn't need live creds."""

import datetime as dt
import json
import unittest
from decimal import Decimal
from unittest import mock

import bankhub
from bankhub.normalize import combined_amount


def _txn(**kw):
    base = dict(external_id="x1", source="s", account_id="acct1",
                date=dt.date(2024, 1, 15), amount=Decimal("-12.34"),
                currency="usd", payee="Coffee", notes="latte")
    base.update(kw)
    return bankhub.Transaction(**base)


class FakeResp:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        return self._payload


# --------------------------------------------------------------------------
# Split debit / credit columns
# --------------------------------------------------------------------------
class CombinedAmountTests(unittest.TestCase):
    def test_magnitude_combination(self):
        self.assertEqual(combined_amount("12.34", ""), Decimal("-12.34"))   # out
        self.assertEqual(combined_amount("", "100"), Decimal("100"))        # in
        self.assertEqual(combined_amount("", ""), Decimal("0"))             # neither
        self.assertEqual(combined_amount("-5", ""), Decimal("-5"))          # sign ignored
        self.assertEqual(combined_amount("1.234,56", "", decimal_comma=True),
                         Decimal("-1234.56"))


class CsvSplitColumnTests(unittest.TestCase):
    def test_generic_split_profile(self):
        content = ("Date,Debit,Credit,Description,Account\n"
                   "2024-01-15,12.34,,Coffee,chk\n"
                   "2024-01-16,,100.00,Salary,chk\n")
        txns = bankhub.build_source("csv", content=content, bank="generic_split").fetch_all()
        self.assertEqual([t.amount for t in txns], [Decimal("-12.34"), Decimal("100.00")])
        self.assertEqual(txns[0].payee, "Coffee")


class PdfSplitColumnTests(unittest.TestCase):
    def test_rows_to_transactions_split(self):
        from bankhub_files.sources.pdf import rows_to_transactions
        rows = [
            {"Date": "15 Jan 24", "Paid out": "12.34", "Paid in": "",
             "Payment type and details": "Coffee"},
            {"Date": "16 Jan 24", "Paid out": "", "Paid in": "100.00",
             "Payment type and details": "Salary"},
            {"Date": "", "Paid out": "", "Paid in": ""},  # noise row -> skipped
        ]
        out = rows_to_transactions(rows, date_col="Date", debit_col="Paid out",
                                   credit_col="Paid in",
                                   payee_col="Payment type and details",
                                   date_format="%d %b %y")
        self.assertEqual([t.amount for t in out], [Decimal("-12.34"), Decimal("100.00")])
        self.assertEqual(out[0].date, dt.date(2024, 1, 15))


# --------------------------------------------------------------------------
# Mock HTTP flow: Stripe (FC + payments), Firefly, PocketSmith
# --------------------------------------------------------------------------
class StripeFlowTests(unittest.TestCase):
    @mock.patch("requests.get")
    def test_fc_request_auth_and_parse(self, mget):
        mget.return_value = FakeResp(200, {"data": [
            {"id": "f1", "amount": -1234, "currency": "usd", "status": "posted",
             "transacted_at": 1705276800, "account": "fca_1"}], "has_more": False})
        txns = bankhub.build_source("stripe", api_key="sk_test_x",
                                    account="fca_1").fetch_all()
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].amount, Decimal("-12.34"))     # outflow kept negative
        self.assertIn("financial_connections/transactions", mget.call_args[0][0])
        self.assertEqual(mget.call_args.kwargs["headers"]["Authorization"], "Bearer sk_test_x")
        self.assertEqual(mget.call_args.kwargs["params"]["account"], "fca_1")

    @mock.patch("requests.get")
    def test_fc_pagination(self, mget):
        mget.side_effect = [
            FakeResp(200, {"data": [{"id": "a", "amount": 100, "currency": "usd",
                                     "status": "posted", "transacted_at": 1705276800}],
                           "has_more": True}),
            FakeResp(200, {"data": [{"id": "b", "amount": -50, "currency": "usd",
                                     "status": "posted", "transacted_at": 1705276800}],
                           "has_more": False}),
        ]
        txns = bankhub.build_source("stripe", api_key="k", account="fca_1").fetch_all()
        self.assertEqual([t.external_id for t in txns], ["a", "b"])
        self.assertEqual(mget.call_count, 2)

    @mock.patch("requests.get")
    def test_fc_empty_page_with_has_more_does_not_crash(self, mget):
        # Regression: has_more True but an empty page must not IndexError.
        mget.return_value = FakeResp(200, {"data": [], "has_more": True})
        self.assertEqual(bankhub.build_source("stripe", api_key="k",
                                              account="fca_1").fetch_all(), [])

    @mock.patch("requests.get")
    def test_payments_balance_transaction(self, mget):
        mget.return_value = FakeResp(200, {"data": [
            {"id": "bt_1", "amount": 2500, "currency": "usd", "type": "charge",
             "status": "available", "created": 1705276800}], "has_more": False})
        txns = bankhub.build_source("stripe_payments", api_key="sk").fetch_all()
        self.assertEqual(txns[0].amount, Decimal("25.00"))      # positive = into balance
        self.assertEqual(txns[0].status, "posted")

    @mock.patch("requests.get")
    def test_http_error_raises(self, mget):
        mget.return_value = FakeResp(401, {}, text="unauthorized")
        from bankhub.errors import SourceError
        with self.assertRaises(SourceError):
            bankhub.build_source("stripe", api_key="bad", account="fca_1").fetch_all()


class FireflyFlowTests(unittest.TestCase):
    @mock.patch("requests.post")
    def test_withdrawal_payload_and_created(self, mpost):
        mpost.return_value = FakeResp(200, {"data": {"id": "99"}})
        res = bankhub.build_destination("firefly", url="https://f.example/",
                                        token="tok").push(
            [_txn(amount=Decimal("-12.34"), account_id="Assets:Checking", payee="Coffee")])
        self.assertEqual(res[0].status, "created")
        self.assertEqual(res[0].remote_id, "99")
        self.assertEqual(mpost.call_args[0][0], "https://f.example/api/v1/transactions")
        self.assertEqual(mpost.call_args.kwargs["headers"]["Authorization"], "Bearer tok")
        body = mpost.call_args.kwargs["json"]["transactions"][0]
        self.assertEqual(body["type"], "withdrawal")
        self.assertEqual(body["amount"], "12.34")             # always positive
        self.assertEqual(body["source_name"], "Assets:Checking")
        self.assertEqual(body["destination_name"], "Coffee")
        self.assertEqual(body["external_id"], "x1")

    @mock.patch("requests.post")
    def test_duplicate_is_skipped(self, mpost):
        mpost.return_value = FakeResp(422, {}, text='{"message":"Duplicate of transaction #5"}')
        res = bankhub.build_destination("firefly", url="https://f.example",
                                        token="t").push([_txn(account_id="A")])
        self.assertEqual(res[0].status, "skipped")

    @mock.patch("requests.post")
    def test_server_error_is_error(self, mpost):
        mpost.return_value = FakeResp(500, {}, text="boom")
        res = bankhub.build_destination("firefly", url="https://f.example",
                                        token="t").push([_txn(account_id="A")])
        self.assertEqual(res[0].status, "error")


class PocketSmithFlowTests(unittest.TestCase):
    @mock.patch("requests.post")
    def test_request_and_created(self, mpost):
        mpost.return_value = FakeResp(201, {"id": 123})
        res = bankhub.build_destination("pocketsmith", key="dev").push(
            [_txn(amount=Decimal("-12.34"), account_id="555")])
        self.assertEqual(res[0].status, "created")
        self.assertEqual(res[0].remote_id, "123")
        self.assertEqual(mpost.call_args[0][0],
                         "https://api.pocketsmith.com/v2/transaction_accounts/555/transactions")
        self.assertEqual(mpost.call_args.kwargs["headers"]["X-Developer-Key"], "dev")
        body = mpost.call_args.kwargs["json"]
        self.assertEqual(body["amount"], -12.34)              # signed: negative = debit
        self.assertEqual(body["date"], "2024-01-15")


if __name__ == "__main__":
    unittest.main()
