# -*- coding: utf-8 -*-
"""PDF bank-statement source.

Bank statement PDFs have no universal schema, so this source does what the
various "bank PDF parser" projects do: **extract the tabular rows, then map
columns to fields via a profile**.  Extraction uses ``pdfplumber`` (pure
Python; ``camelot``/``tabula`` are viable alternative backends); the
column-mapping + row-filtering logic is pure and fixture-tested.

Rows whose date/amount don't parse (headers, totals, marketing text) are
skipped automatically, which is what makes noisy PDF tables usable.
"""

from __future__ import annotations

import os
from typing import Dict, Iterator, List, Optional

import yaml

from bankhub.errors import ConfigError, MissingDependencyError
from bankhub.models import Transaction
from bankhub.normalize import (clean_text, combined_amount, compute_external_id,
                         parse_amount, parse_date)
from bankhub.registry import register_source
from bankhub.sources.base import Source

_PROFILES = os.path.join(os.path.dirname(__file__), "..", "data", "pdf_banks.yml")


def _resolve(rowdict: Dict[str, str], spec) -> str:
    """Resolve a column spec (header name or 0-based index) to a cell value."""
    if spec is None:
        return ""
    return rowdict.get(str(spec), "")


def tables_to_rowdicts(tables: List[List[List]], header_row: Optional[int] = 0
                       ) -> List[Dict[str, str]]:
    """Flatten extracted tables into row dicts keyed by both column index
    (``"0"``, ``"1"`` …) and, when present, header name."""
    rowdicts: List[Dict[str, str]] = []
    for table in tables:
        if not table:
            continue
        header = None
        start = 0
        if header_row is not None and header_row >= 0 and len(table) > header_row:
            header = [clean_text(c) for c in table[header_row]]
            start = header_row + 1
        for row in table[start:]:
            rd: Dict[str, str] = {}
            for i, cell in enumerate(row):
                rd[str(i)] = clean_text(cell)
                if header and i < len(header) and header[i]:
                    rd[header[i]] = clean_text(cell)
            rowdicts.append(rd)
    return rowdicts


def rows_to_transactions(rowdicts: List[Dict[str, str]], *, date_col, amount_col=None,
                         payee_col=None, notes_col=None, debit_col=None,
                         credit_col=None, source_name="pdf",
                         account: str = "pdf", currency: str = "usd",
                         date_format: str = None, decimal_comma: bool = False
                         ) -> List[Transaction]:
    """Map row dicts to transactions, skipping rows that aren't transactions.

    Either a single signed ``amount_col`` or a ``debit_col``/``credit_col`` pair
    (split "money out"/"money in" columns) supplies the amount.
    """
    split = amount_col is None and (debit_col is not None or credit_col is not None)
    out: List[Transaction] = []
    for rd in rowdicts:
        raw_date = _resolve(rd, date_col)
        if not raw_date:
            continue
        try:
            date = parse_date(raw_date, date_format)
            if split:
                raw_debit = _resolve(rd, debit_col)
                raw_credit = _resolve(rd, credit_col)
                if not raw_debit and not raw_credit:
                    continue
                amount = combined_amount(raw_debit, raw_credit, decimal_comma=decimal_comma)
            else:
                raw_amount = _resolve(rd, amount_col)
                if not raw_amount:
                    continue
                amount = parse_amount(raw_amount, decimal_comma=decimal_comma)
        except Exception:
            continue  # header / footer / noise row
        payee = clean_text(_resolve(rd, payee_col))
        notes = clean_text(_resolve(rd, notes_col))
        external_id = compute_external_id(source_name, account, date, amount, payee, notes)
        out.append(Transaction(
            external_id=external_id, source=source_name, account_id=account,
            date=date, amount=amount, currency=currency, payee=payee,
            notes=notes, raw=rd))
    return out


def _load_profile(bank: str) -> dict:
    if not os.path.exists(_PROFILES):
        return {}
    with open(_PROFILES, "r", encoding="utf-8") as fh:
        profiles = yaml.safe_load(fh) or {}
    return profiles.get(bank, {})


@register_source("pdf")
class PdfSource(Source):
    """Extract transactions from a PDF bank statement.

    Options
    -------
    file
        Path to the PDF.
    bank
        Profile name from ``bankhub/data/pdf_banks.yml`` (supplies the column
        mapping / date format).  Defaults to ``generic``.
    date_col, amount_col, payee_col, notes_col
        Column header name or 0-based index; overrides the profile.
    header_row
        Index of the header row within each table (``-1`` for none).
    pages
        ``"all"`` (default) or a range like ``"1-3"``.
    date_format, decimal_comma, currency, account
        As for the CSV source.
    """

    requires = "pdfplumber"

    def __init__(self, file: str = None, bank: str = "generic", pages: str = "all",
                 header_row=0, date_col=None, amount_col=None, payee_col=None,
                 notes_col=None, debit_col=None, credit_col=None,
                 date_format: str = None, decimal_comma=False,
                 currency: str = "usd", account: str = "pdf", **options):
        super().__init__(**options)
        if not file:
            raise ConfigError("pdf source needs a 'file' option")
        self.file = file
        self.pages = pages
        profile = _load_profile(bank)
        cols = profile.get("columns", {})
        self.bank = bank
        self.header_row = int(profile.get("header_row", header_row))
        self.date_col = date_col if date_col is not None else cols.get("date")
        self.amount_col = amount_col if amount_col is not None else cols.get("amount")
        self.payee_col = payee_col if payee_col is not None else cols.get("payee")
        self.notes_col = notes_col if notes_col is not None else cols.get("notes")
        self.debit_col = debit_col if debit_col is not None else cols.get("debit")
        self.credit_col = credit_col if credit_col is not None else cols.get("credit")
        self.date_format = date_format or profile.get("date_format")
        self.decimal_comma = _as_bool(profile.get("decimal_comma", decimal_comma))
        self.currency = currency or profile.get("currency", "usd")
        self.account = account
        has_amount = (self.amount_col is not None or self.debit_col is not None
                      or self.credit_col is not None)
        if self.date_col is None or not has_amount:
            raise ConfigError(
                "pdf source needs date_col and an amount source (amount_col, or "
                f"debit_col/credit_col) via options or a profile; none for bank={bank!r}")

    @property
    def source_id(self) -> str:
        return f"pdf:{self.bank}" if self.bank != "generic" else "pdf"

    def _extract_tables(self) -> List[List[List]]:
        try:
            import pdfplumber
        except ImportError:
            raise MissingDependencyError("pdf", "pdfplumber")
        tables: List[List[List]] = []
        with pdfplumber.open(self.file) as pdf:
            for page in _select_pages(pdf.pages, self.pages):
                tables.extend(page.extract_tables() or [])
        return tables

    def fetch(self) -> Iterator[Transaction]:
        rowdicts = tables_to_rowdicts(self._extract_tables(), self.header_row)
        yield from rows_to_transactions(
            rowdicts, date_col=self.date_col, amount_col=self.amount_col,
            payee_col=self.payee_col, notes_col=self.notes_col,
            debit_col=self.debit_col, credit_col=self.credit_col,
            source_name=self.source_id, account=self.account,
            currency=self.currency, date_format=self.date_format,
            decimal_comma=self.decimal_comma)


def _select_pages(pages, spec):
    if not spec or spec == "all":
        return pages
    lo, _, hi = spec.partition("-")
    lo = int(lo) - 1
    hi = int(hi) if hi else lo + 1
    return pages[lo:hi]


def _as_bool(value) -> bool:
    return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
