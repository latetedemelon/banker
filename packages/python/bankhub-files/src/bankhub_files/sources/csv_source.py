# -*- coding: utf-8 -*-
"""CSV statement source.

Reads a delimited statement file and normalises it using a declarative
profile (see ``bankhub/data/banks.yml``).  This replaces the original
``eval``-based transform with a safe, data-driven mapping that can be
extended to a new bank by editing YAML alone.
"""

from __future__ import annotations

import csv
import io
import os
import re
from typing import Dict, Iterator, List, Optional

import yaml

from bankhub.errors import ConfigError, SourceError
from bankhub.models import Transaction
from bankhub.normalize import (clean_text, combined_amount, compute_external_id,
                         parse_amount, parse_date)
from bankhub.registry import register_source
from bankhub.sources.base import Source

_DEFAULT_PROFILES = os.path.join(os.path.dirname(__file__), "..", "data", "banks.yml")


def load_profiles(path: Optional[str] = None) -> Dict[str, dict]:
    """Load the bank profile dictionary from YAML."""
    path = path or _DEFAULT_PROFILES
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@register_source("csv")
class CsvSource(Source):
    """Normalise a bank CSV using a named profile.

    Options
    -------
    file
        Path to the CSV file (mutually exclusive with ``content``).
    content
        Raw CSV text, handy for tests/stdin.
    bank
        Profile name from ``banks.yml`` (default ``"generic"``).
    profiles_path
        Override path to a profiles YAML file.
    Any profile key (``delimiter``, ``date_format``, ``columns`` …) may be
    overridden directly, e.g. ``--source-opt delimiter=;``.
    """

    requires = None

    def __init__(self, file: str = None, content: str = None, bank: str = "generic",
                 profiles_path: str = None, **overrides):
        super().__init__(file=file, content=content, bank=bank, **overrides)
        if not file and content is None:
            raise ConfigError("csv source needs a 'file' or 'content' option")
        self.file = file
        self.content = content
        self.bank = bank
        profiles = load_profiles(profiles_path)
        if bank not in profiles:
            raise ConfigError(
                f"Unknown bank profile {bank!r}. Known: {', '.join(sorted(profiles))}"
            )
        self.profile = {**profiles[bank], **_normalise_overrides(overrides)}
        self.columns = self.profile.get("columns", {})
        if not self.columns:
            raise ConfigError(f"Profile {bank!r} defines no 'columns' mapping")

    @property
    def source_id(self) -> str:
        return f"csv:{self.bank}"

    # -- public API --------------------------------------------------------
    def fetch(self) -> Iterator[Transaction]:
        rows, fieldnames = self._read_rows()
        amount_col, dynamic_currency = self._resolve_dynamic_amount(fieldnames)
        source_name = f"csv:{self.bank}"
        lower = set(self.profile.get("lowercase", []))
        decimal_comma = bool(self.profile.get("decimal_comma", False))
        date_format = self.profile.get("date_format")

        for row in rows:
            if not self._passes_filters(row):
                continue

            currency = dynamic_currency or self._first(row, self.columns.get("currency")) \
                or self.profile.get("default_currency", "")
            if "currency" in lower:
                currency = currency.lower()

            if amount_col:
                amount = parse_amount(row.get(amount_col), decimal_comma=decimal_comma)
            elif self.columns.get("debit") is not None or self.columns.get("credit") is not None:
                # Split "money out"/"money in" columns -> one signed amount.
                amount = combined_amount(
                    self._first(row, self.columns.get("debit")),
                    self._first(row, self.columns.get("credit")),
                    decimal_comma=decimal_comma)
            else:
                amount = parse_amount(self._first(row, self.columns.get("amount")),
                                      decimal_comma=decimal_comma)

            payee = self._first(row, self.columns.get("payee"))
            notes = self._first(row, self.columns.get("notes"))
            category = self._first(row, self.columns.get("category")) or None

            account_id = self._resolve_account(row, currency, lower)

            date_val = self._first(row, self.columns.get("date"))
            if not date_val:
                raise SourceError(f"Row missing date column {self.columns.get('date')!r}")
            date = parse_date(date_val, date_format)

            ext = self._first(row, self.columns.get("id"))
            external_id = ext or compute_external_id(
                source_name, account_id, date, amount, payee, notes)

            yield Transaction(
                external_id=external_id,
                source=source_name,
                account_id=account_id or self.bank,
                date=date,
                amount=amount,
                currency=currency or "",
                payee=payee,
                notes=notes,
                category=category,
                raw=dict(row),
            )

    # -- helpers -----------------------------------------------------------
    def _read_rows(self):
        delimiter = self.profile.get("delimiter", ",")
        encoding = self.profile.get("encoding", "utf-8-sig")
        if self.content is not None:
            handle = io.StringIO(self.content)
        else:
            handle = open(self.file, "r", encoding=encoding, newline="")
        try:
            reader = csv.DictReader(handle, delimiter=delimiter)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
        finally:
            if self.content is None:
                handle.close()
        return rows, fieldnames

    def _resolve_dynamic_amount(self, fieldnames: List[str]):
        spec = self.profile.get("dynamic_amount")
        if not spec:
            return None, None
        pattern = re.compile(spec["header_regex"])
        for name in fieldnames:
            match = pattern.match(name or "")
            if match:
                currency = match.groupdict().get("currency", "")
                return name, currency
        raise SourceError(
            f"No column matched dynamic_amount regex {spec['header_regex']!r}")

    def _passes_filters(self, row: dict) -> bool:
        for flt in self.profile.get("filters", []):
            value = clean_text(row.get(flt["column"], "")).lower()
            if value != str(flt["equals"]).lower():
                return False
        return True

    def _resolve_account(self, row: dict, currency: str, lower: set) -> str:
        account_from = self.profile.get("account_from")
        if account_from == "currency":
            return currency
        account = self._first(row, self.columns.get("account"))
        if "account" in lower:
            account = account.lower()
        return account

    @staticmethod
    def _first(row: dict, spec) -> str:
        """Resolve a column spec (str or list) to the first non-empty value."""
        if spec is None:
            return ""
        names = spec if isinstance(spec, list) else [spec]
        for name in names:
            value = clean_text(row.get(name, ""))
            if value:
                return value
        return ""


def _normalise_overrides(overrides: dict) -> dict:
    """Support dotted CLI overrides like ``columns.payee=Description``."""
    result: dict = {}
    for key, value in overrides.items():
        if "." in key:
            head, tail = key.split(".", 1)
            result.setdefault(head, {})[tail] = value
        else:
            result[key] = value
    return result
