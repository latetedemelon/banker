# -*- coding: utf-8 -*-
"""Pure-parser tests for the aggregator sources.  No network: each asserts the
provider's sign convention and field mapping on a minimal record."""

import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bankhub.registry import available_sources
from bankhub.sources.finicity import finicity_to_transaction
from bankhub.sources.gocardless import (gocardless_to_transaction,
                                        iter_gocardless)
from bankhub.sources.mx import mx_to_transaction
from bankhub.sources.saltedge import saltedge_to_transaction
from bankhub.sources.teller import teller_to_transaction
from bankhub.sources.truelayer import truelayer_to_transaction
from bankhub.sources.yodlee import yodlee_to_transaction


class GoCardlessTests(unittest.TestCase):
    def test_signed_and_payee(self):
        raw = {"transactionId": "g1", "bookingDate": "2024-01-15",
               "transactionAmount": {"amount": "-12.34", "currency": "EUR"},
               "creditorName": "Coffee Shop",
               "remittanceInformationUnstructured": "Latte"}
        t = gocardless_to_transaction(raw, "acc-eu")
        self.assertEqual(t.amount, Decimal("-12.34"))
        self.assertEqual(t.currency, "eur")
        self.assertEqual(t.payee, "Coffee Shop")  # outflow -> creditorName
        self.assertEqual(t.notes, "Latte")
        self.assertEqual(t.date, dt.date(2024, 1, 15))

    def test_iter_booked_pending(self):
        payload = {"transactions": {"booked": [{"transactionId": "b"}],
                                    "pending": [{"transactionId": "p"}]}}
        statuses = [s for _, s in iter_gocardless(payload)]
        self.assertEqual(statuses, ["posted", "pending"])


class TrueLayerTests(unittest.TestCase):
    def test_debit_credit_sign(self):
        debit = truelayer_to_transaction(
            {"transaction_id": "t1", "timestamp": "2024-01-15T10:00:00Z",
             "amount": 12.34, "currency": "GBP", "transaction_type": "DEBIT",
             "merchant_name": "Coffee Shop", "description": "COFFEE"}, "acc")
        self.assertEqual(debit.amount, Decimal("-12.34"))
        self.assertEqual(debit.payee, "Coffee Shop")
        self.assertEqual(debit.currency, "gbp")
        credit = truelayer_to_transaction(
            {"transaction_id": "t2", "timestamp": "2024-01-16T00:00:00Z",
             "amount": 50, "transaction_type": "CREDIT", "description": "Refund"}, "acc")
        self.assertEqual(credit.amount, Decimal("50"))


class YodleeTests(unittest.TestCase):
    def test_basetype_sign(self):
        t = yodlee_to_transaction(
            {"id": 1, "amount": {"amount": 12.34, "currency": "USD"},
             "date": "2024-01-15", "baseType": "DEBIT", "accountId": 99,
             "description": {"simple": "Coffee", "original": "COFFEE #1"}})
        self.assertEqual(t.amount, Decimal("-12.34"))
        self.assertEqual(t.payee, "Coffee")
        self.assertEqual(t.account_id, "99")
        credit = yodlee_to_transaction(
            {"id": 2, "amount": {"amount": 10, "currency": "USD"},
             "date": "2024-01-16", "baseType": "CREDIT",
             "description": {"simple": "Pay"}})
        self.assertEqual(credit.amount, Decimal("10"))


class MxTests(unittest.TestCase):
    def test_type_sign(self):
        t = mx_to_transaction({"guid": "TRN-1", "amount": 12.34, "type": "DEBIT",
                               "date": "2024-01-15", "description": "Coffee",
                               "account_guid": "ACC", "currency_code": "USD"})
        self.assertEqual(t.amount, Decimal("-12.34"))
        self.assertEqual(t.external_id, "TRN-1")
        self.assertEqual(t.payee, "Coffee")


class FinicityTests(unittest.TestCase):
    def test_signed_epoch(self):
        t = finicity_to_transaction({"id": 501, "amount": -12.34,
                                     "postedDate": 1705276800, "description": "Coffee",
                                     "accountId": "55", "currencySymbol": "USD"})
        self.assertEqual(t.amount, Decimal("-12.34"))
        self.assertEqual(t.date, dt.date(2024, 1, 15))
        self.assertEqual(t.account_id, "55")


class TellerTests(unittest.TestCase):
    def test_signed_string_counterparty(self):
        t = teller_to_transaction(
            {"id": "txn_1", "account_id": "acc_1", "amount": "-12.34",
             "date": "2024-01-15", "description": "COFFEE",
             "details": {"category": "dining", "counterparty": {"name": "Coffee Shop"}},
             "status": "posted"})
        self.assertEqual(t.amount, Decimal("-12.34"))
        self.assertEqual(t.payee, "Coffee Shop")
        self.assertEqual(t.category, "dining")


class SaltEdgeTests(unittest.TestCase):
    def test_signed_payee(self):
        t = saltedge_to_transaction(
            {"id": "se1", "account_id": "a1", "amount": -12.34, "currency_code": "EUR",
             "made_on": "2024-01-15", "description": "COFFEE",
             "extra": {"payee": "Coffee Shop"}, "status": "posted"})
        self.assertEqual(t.amount, Decimal("-12.34"))
        self.assertEqual(t.payee, "Coffee Shop")
        self.assertEqual(t.currency, "eur")


class RegistryTests(unittest.TestCase):
    def test_all_aggregators_registered(self):
        srcs = set(available_sources())
        for name in ("simplefin", "yodlee", "gocardless", "truelayer", "mx",
                     "finicity", "teller", "saltedge", "plaid", "flinks"):
            self.assertIn(name, srcs)


if __name__ == "__main__":
    unittest.main()
