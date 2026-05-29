# -*- coding: utf-8 -*-
"""Tests for the API integrations' pure parsers/builders, the registry, and
the pipeline config runner.  None of these touch the network."""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bankhub.destinations.lunchmoney import (build_request_body,
                                             transaction_to_lunchmoney)
from bankhub.destinations.ynab import (import_id_for, to_milliunits,
                                       transaction_to_ynab)
from bankhub.destinations.actual import to_minor_units
from bankhub.models import Transaction
from bankhub.registry import (available_destinations, available_sources,
                              build_source, get_source_class)
from bankhub.errors import PluginError
from bankhub.sources.flinks import (flinks_amount, flinks_to_transaction,
                                     iter_flinks_transactions)
from bankhub.sources.lunchmoney import lunchmoney_to_transaction
from bankhub.sources.plaid import plaid_to_transaction

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _load(name):
    with open(os.path.join(FIX, name)) as fh:
        return json.load(fh)


def _txn(**kw):
    base = dict(external_id="e1", source="s", account_id="a",
                date=dt.date(2024, 1, 1), amount=Decimal("-12.34"), currency="usd")
    base.update(kw)
    return Transaction(**base)


class RegistryTests(unittest.TestCase):
    def test_all_plugins_present(self):
        self.assertEqual(set(available_sources()), {
            # aggregators / APIs
            "plaid", "flinks", "lunchmoney", "simplefin", "yodlee",
            "gocardless", "truelayer", "mx", "finicity", "teller", "saltedge",
            # file formats
            "csv", "ofx", "qif", "mt940", "camt", "pdf",
        })
        self.assertEqual(set(available_destinations()),
                         {"csv", "json", "lunchmoney", "ynab", "actual"})

    def test_unknown_plugin_raises(self):
        with self.assertRaises(PluginError):
            get_source_class("nope")

    def test_requires_metadata(self):
        self.assertIsNone(get_source_class("csv").requires)
        self.assertEqual(get_source_class("plaid").requires, "requests")


class PlaidTests(unittest.TestCase):
    def test_parser_sign_flip_and_fields(self):
        added = _load("plaid_sync.json")["added"]
        spend = plaid_to_transaction(added[0])
        # Plaid +12.34 (outflow) -> normalised -12.34
        self.assertEqual(spend.amount, Decimal("-12.34"))
        self.assertEqual(spend.payee, "Coffee Shop")
        self.assertEqual(spend.currency, "usd")
        self.assertEqual(spend.category, "FOOD_AND_DRINK")
        self.assertEqual(spend.status, "posted")
        self.assertEqual(spend.external_id, "plaid-txn-001")

        income = plaid_to_transaction(added[1])
        self.assertEqual(income.amount, Decimal("2000.00"))  # -(-2000)
        self.assertEqual(income.status, "pending")
        self.assertEqual(income.category, "Transfer")  # from list fallback


class FlinksTests(unittest.TestCase):
    def test_amount_debit_credit(self):
        self.assertEqual(flinks_amount({"Debit": 54.20, "Credit": None}),
                         Decimal("-54.20"))
        self.assertEqual(flinks_amount({"Debit": None, "Credit": 2500.0}),
                         Decimal("2500.0"))

    def test_iter_and_parse(self):
        payload = _load("flinks_accounts.json")
        rows = list(iter_flinks_transactions(payload))
        self.assertEqual(len(rows), 2)
        raw, account_id, currency = rows[0]
        txn = flinks_to_transaction(raw, account_id, currency)
        self.assertEqual(txn.account_id, "flinks-acct-1")
        self.assertEqual(txn.amount, Decimal("-54.20"))
        self.assertEqual(txn.currency, "cad")
        self.assertEqual(txn.payee, "GROCERY STORE")
        self.assertEqual(txn.balance, Decimal("945.80"))


class LunchmoneyTests(unittest.TestCase):
    def test_source_parser(self):
        raw = _load("lunchmoney_transactions.json")["transactions"]
        t0 = lunchmoney_to_transaction(raw[0])
        self.assertEqual(t0.external_id, "9001")
        self.assertEqual(t0.account_id, "4501")
        self.assertEqual(t0.amount, Decimal("85.50"))
        self.assertEqual(t0.status, "posted")
        t1 = lunchmoney_to_transaction(raw[1], flip_sign=True)
        self.assertEqual(t1.amount, Decimal("20.00"))  # flipped from -20
        self.assertEqual(t1.account_id, "plaid-acct-9")
        self.assertEqual(t1.status, "pending")

    def test_destination_payload(self):
        txn = _txn(payee="Shop", notes="memo", account_id="4501")
        d = transaction_to_lunchmoney(txn)
        self.assertEqual(d["amount"], "-12.34")
        self.assertEqual(d["asset_id"], 4501)  # numeric account -> asset_id
        self.assertEqual(d["external_id"], "e1")
        body = build_request_body([txn])
        self.assertTrue(body["debit_as_negative"])
        self.assertEqual(len(body["transactions"]), 1)

    def test_destination_plaid_account(self):
        txn = _txn()
        txn.dest_account = "plaid-xyz"
        d = transaction_to_lunchmoney(txn)
        self.assertEqual(d["plaid_account_id"], "plaid-xyz")
        self.assertNotIn("asset_id", d)


class YnabActualTests(unittest.TestCase):
    def test_ynab_milliunits(self):
        self.assertEqual(to_milliunits(Decimal("-12.34")), -12340)
        self.assertEqual(to_milliunits(Decimal("0.005")), 5)

    def test_ynab_payload(self):
        txn = _txn(payee="Shop", notes="m")
        txn.dest_account = "acct-guid"
        d = transaction_to_ynab(txn)
        self.assertEqual(d["account_id"], "acct-guid")
        self.assertEqual(d["amount"], -12340)
        self.assertEqual(d["cleared"], "cleared")
        self.assertEqual(d["import_id"], import_id_for("e1"))
        self.assertLessEqual(len(d["import_id"]), 36)

    def test_actual_minor_units(self):
        self.assertEqual(to_minor_units(Decimal("-12.34")), -1234)
        self.assertEqual(to_minor_units(Decimal("100")), 10000)


class ConfigRunnerTests(unittest.TestCase):
    def test_run_config_end_to_end(self):
        from bankhub.config import run_config
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "pipe.yml")
        out = os.path.join(tmp, "out.csv")
        with open(cfg, "w") as fh:
            fh.write(f"""
store: {tmp}/hub.db
account_map:
  csv:
    eur: REMOTE-EUR
pipelines:
  - name: t
    source: {{type: csv, bank: revolut, file: {DATA}/revolut.csv}}
    destinations:
      - {{type: csv, file: {out}}}
""")
        reports = run_config(cfg)
        self.assertEqual(reports[0].ingest.new, 4)
        self.assertEqual(reports[0].deliveries[0].created, 4)
        with open(out) as fh:
            body = fh.read()
        self.assertIn("REMOTE-EUR", body)  # account remapped

    def test_env_expansion(self):
        from bankhub.config import expand_env
        os.environ["BANKHUB_TEST_TOKEN"] = "secret123"
        self.assertEqual(expand_env("${BANKHUB_TEST_TOKEN}"), "secret123")
        self.assertEqual(expand_env({"t": "${BANKHUB_TEST_TOKEN}"})["t"], "secret123")


if __name__ == "__main__":
    unittest.main()
