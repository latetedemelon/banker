# -*- coding: utf-8 -*-
"""Keeps the shared spec (../../../spec) honest against the Python reference
implementation: the JSON Schemas must match what the model emits, and the
``external_id`` conformance vector in SPEC.md must reproduce exactly."""

import datetime as dt
import json
import os
import unittest
from decimal import Decimal

import bankhub
from bankhub.normalize import clean_text, compute_external_id

SPEC_SCHEMAS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "spec", "schemas"))


def _schema(name):
    with open(os.path.join(SPEC_SCHEMAS, name), encoding="utf-8") as fh:
        return json.load(fh)


class SpecParityTests(unittest.TestCase):
    def test_external_id_conformance_vector(self):
        # Must match SPEC.md §2 exactly, or the Node port can't dedup-match.
        got = compute_external_id("csv:revolut", "eur", dt.date(2024, 1, 15),
                                  Decimal("-12.34"), "Coffee", "", "")
        self.assertEqual(got, "cc5d73ab8c0c76615f8b177fa656a156e6b0d958")

    def test_clean_text_contract(self):
        self.assertEqual(clean_text("  Coffee   Shop "), "Coffee Shop")
        self.assertEqual(clean_text(None), "")

    def test_transaction_keys_match_schema(self):
        # Dependency-free guard: the serialised keys are exactly the schema's
        # properties (additionalProperties is false), so neither can drift.
        txn = bankhub.Transaction(external_id="a", source="s", account_id="c",
                                  date=dt.date(2024, 1, 1), amount=Decimal("1"))
        schema = _schema("transaction.schema.json")
        self.assertEqual(set(txn.to_dict().keys()), set(schema["properties"].keys()))

    def test_required_fields_present(self):
        schema = _schema("transaction.schema.json")
        txn = bankhub.Transaction(external_id="a", source="s", account_id="c",
                                  date=dt.date(2024, 1, 1), amount=Decimal("1"))
        for req in schema["required"]:
            self.assertIn(req, txn.to_dict())


try:
    import jsonschema  # noqa: F401
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


@unittest.skipUnless(_HAS_JSONSCHEMA, "jsonschema not installed")
class SchemaValidationTests(unittest.TestCase):
    def test_transaction_validates(self):
        import jsonschema
        full = bankhub.Transaction(
            external_id="abc", source="csv:revolut", account_id="eur",
            date=dt.date(2024, 1, 15), amount=Decimal("-12.34"), currency="USD",
            payee="Coffee", notes="latte", category="Dining", status="pending",
            posted_date=dt.date(2024, 1, 16), balance=Decimal("100.00"), raw={"x": 1})
        jsonschema.validate(full.to_dict(), _schema("transaction.schema.json"))
        minimal = bankhub.Transaction(external_id="m", source="ofx",
                                      account_id="a", date=dt.date(2024, 2, 1),
                                      amount=Decimal("5"))
        jsonschema.validate(minimal.to_dict(), _schema("transaction.schema.json"))

    def test_push_result_and_account_validate(self):
        import jsonschema
        jsonschema.validate({"external_id": "abc", "status": "created",
                             "remote_id": "r1", "error": None},
                            _schema("push-result.schema.json"))
        jsonschema.validate({"id": "eur", "name": "Revolut EUR", "currency": "eur",
                             "type": "checking", "balance": "100.00"},
                            _schema("account.schema.json"))


if __name__ == "__main__":
    unittest.main()
