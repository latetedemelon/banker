# -*- coding: utf-8 -*-
"""Core tests: normalize, models, CSV source, mapping, store, engine.

Run from the repo root, e.g.::

    python -m unittest discover -s test -t . -p 'test_*.py'
"""

import datetime as dt
import os
import sys
import tempfile
import unittest
from decimal import Decimal

# Ensure the repo root (which contains the bankhub package) is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bankhub.engine import Engine
from bankhub.mapping import SKIP, AccountMap
from bankhub.errors import MappingError
from bankhub.models import Transaction
from bankhub.normalize import (compute_external_id, parse_amount, parse_date)
from bankhub.registry import build_destination, build_source
from bankhub_files.sources.csv_source import CsvSource
from bankhub.store import Store

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class NormalizeTests(unittest.TestCase):
    def test_parse_amount_plain(self):
        self.assertEqual(parse_amount("-129.81"), Decimal("-129.81"))
        self.assertEqual(parse_amount("8306.54"), Decimal("8306.54"))
        self.assertEqual(parse_amount(""), Decimal("0"))
        self.assertEqual(parse_amount(42), Decimal("42"))

    def test_parse_amount_thousands_and_parens(self):
        self.assertEqual(parse_amount("1,234.56"), Decimal("1234.56"))
        self.assertEqual(parse_amount("(50.00)"), Decimal("-50.00"))
        self.assertEqual(parse_amount("$1,000"), Decimal("1000"))

    def test_parse_amount_decimal_comma(self):
        self.assertEqual(parse_amount("1.234,56", decimal_comma=True), Decimal("1234.56"))
        self.assertEqual(parse_amount("12,50", decimal_comma=True), Decimal("12.50"))

    def test_parse_date_formats(self):
        self.assertEqual(parse_date("2020.01.01", "%Y.%m.%d"), dt.date(2020, 1, 1))
        self.assertEqual(parse_date("2020-01-01 00:00:00", "%Y-%m-%d %H:%M:%S"),
                         dt.date(2020, 1, 1))
        self.assertEqual(parse_date("2020-01-01"), dt.date(2020, 1, 1))  # auto

    def test_external_id_is_deterministic(self):
        a = compute_external_id("csv:x", "acct", dt.date(2020, 1, 1), "-10", "Shop", "n")
        b = compute_external_id("csv:x", "acct", dt.date(2020, 1, 1), "-10", "Shop", "n")
        c = compute_external_id("csv:x", "acct", dt.date(2020, 1, 2), "-10", "Shop", "n")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class ModelTests(unittest.TestCase):
    def _txn(self, **kw):
        base = dict(external_id="e1", source="csv:x", account_id="a",
                    date=dt.date(2020, 1, 1), amount=Decimal("-10.00"), currency="EUR")
        base.update(kw)
        return Transaction(**base)

    def test_roundtrip(self):
        txn = self._txn(payee="Shop", notes="n", balance=Decimal("5"))
        again = Transaction.from_dict(txn.to_dict())
        self.assertEqual(again.amount, Decimal("-10.00"))
        self.assertEqual(again.currency, "eur")  # lower-cased in __post_init__
        self.assertEqual(again.balance, Decimal("5"))
        self.assertEqual(again.date, dt.date(2020, 1, 1))

    def test_sign_and_target_account(self):
        out = self._txn(amount=Decimal("-1"))
        inn = self._txn(amount=Decimal("1"))
        self.assertTrue(out.is_outflow)
        self.assertTrue(inn.is_inflow)
        self.assertEqual(out.target_account, "a")
        out.dest_account = "REMOTE"
        self.assertEqual(out.target_account, "REMOTE")
        self.assertNotIn("dest_account", out.to_dict())  # transient


class CsvSourceTests(unittest.TestCase):
    """Port of the original per-bank assertions onto the new CsvSource."""

    def _fetch(self, bank):
        return CsvSource(file=os.path.join(DATA, f"{bank}.csv"), bank=bank).fetch_all()

    def test_kh(self):
        txns = self._fetch("kh")
        self.assertEqual(len(txns), 3)
        for t in txns:
            self.assertEqual(t.date, dt.date(2020, 4, 30))
            self.assertEqual(t.payee, "TEST PAYEE")
            self.assertEqual(t.notes, "TEST NOTES")
            self.assertEqual(t.currency, "huf")
            self.assertEqual(t.source, "csv:kh")

    def test_revolut_filters_completed_only(self):
        txns = self._fetch("revolut")
        self.assertEqual(len(txns), 4)  # non-COMPLETED rows excluded
        self.assertTrue(all(t.account_id == "eur" for t in txns))
        self.assertTrue(all(t.currency == "eur" for t in txns))

    def test_n26_dynamic_currency(self):
        txns = self._fetch("n26")
        self.assertEqual(len(txns), 7)
        self.assertTrue(all(t.currency == "eur" for t in txns))
        self.assertTrue(all(t.account_id == "eur" for t in txns))  # account_from currency

    def test_otp_payee_fallback_and_accounts(self):
        txns = self._fetch("otp")
        self.assertEqual(len(txns), 5)
        self.assertEqual({t.account_id for t in txns}, {"1782100073", "3894175921"})
        for t in txns:
            self.assertEqual(t.payee, "TEST PAYEE")

    def test_inline_content_and_override(self):
        content = "When,Who,How much\n2021-05-01,Acme,-9.99\n"
        src = CsvSource(content=content, bank="generic",
                        **{"columns.date": "When", "columns.payee": "Who",
                           "columns.amount": "How much"})
        txns = src.fetch_all()
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].payee, "Acme")
        self.assertEqual(txns[0].amount, Decimal("-9.99"))


class MappingTests(unittest.TestCase):
    def test_passthrough_when_unconfigured(self):
        m = AccountMap({})
        self.assertEqual(m.resolve("ynab", "abc"), "abc")

    def test_remap_skip_wildcard_default(self):
        m = AccountMap({
            "lunchmoney": {"eur": 4501, "old": "skip", "*": 9999},
            "ynab": {"default": "guid-default"},
        })
        self.assertEqual(m.resolve("lunchmoney", "eur"), "4501")
        self.assertEqual(m.resolve("lunchmoney", "old"), SKIP)
        self.assertEqual(m.resolve("lunchmoney", "unknown"), "9999")  # wildcard
        self.assertEqual(m.resolve("ynab", "anything"), "guid-default")

    def test_strict_raises(self):
        m = AccountMap({"ynab": {"eur": "g"}}, strict=True)
        with self.assertRaises(MappingError):
            m.resolve("ynab", "missing")


class StoreEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "hub.db"))

    def tearDown(self):
        self.store.close()

    def _src(self, bank="revolut"):
        return build_source("csv", bank=bank, file=os.path.join(DATA, f"{bank}.csv"))

    def test_upsert_dedups(self):
        first = self.store.upsert(self._src().fetch())
        self.assertEqual(len(first["new"]), 4)
        second = self.store.upsert(self._src().fetch())
        self.assertEqual(len(second["new"]), 0)
        self.assertEqual(len(second["existing"]), 4)

    def test_engine_fanout_idempotent(self):
        engine = Engine(self.store)
        d1 = build_destination("csv", file=os.path.join(self.tmp, "a.csv"))
        d2 = build_destination("json", file=os.path.join(self.tmp, "a.jsonl"))
        report = engine.sync(self._src(), [d1, d2])
        self.assertEqual(report.ingest.new, 4)
        self.assertEqual([d.created for d in report.deliveries], [4, 4])
        # second run: nothing new, nothing re-delivered
        report2 = engine.sync(self._src(), [d1, d2])
        self.assertEqual(report2.ingest.new, 0)
        self.assertEqual([d.created for d in report2.deliveries], [0, 0])
        # the CSV file has 4 data rows + 1 header == 5 lines
        with open(os.path.join(self.tmp, "a.csv")) as fh:
            self.assertEqual(len(fh.read().splitlines()), 5)

    def test_deliver_with_skip_mapping(self):
        engine = Engine(self.store, AccountMap({"csv": {"eur": "skip"}}))
        d = build_destination("csv", file=os.path.join(self.tmp, "b.csv"))
        report = engine.sync(self._src("revolut"), [d])
        self.assertEqual(report.deliveries[0].skipped, 4)
        self.assertEqual(report.deliveries[0].created, 0)

    def test_dry_run_writes_nothing(self):
        engine = Engine(self.store, dry_run=True)
        d = build_destination("csv", file=os.path.join(self.tmp, "c.csv"))
        report = engine.sync(self._src(), [d])
        self.assertEqual(report.ingest.new, 4)        # would-be new
        self.assertEqual(report.deliveries[0].created, 4)  # would-be created
        self.assertEqual(self.store.stats()["total"], 0)   # but nothing stored
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "c.csv")))


if __name__ == "__main__":
    unittest.main()
