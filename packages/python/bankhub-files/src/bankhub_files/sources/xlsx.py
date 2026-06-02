# -*- coding: utf-8 -*-
"""Excel (.xlsx) source.

Reads a spreadsheet statement and maps its columns to the canonical model,
the same way the CSV source does but for Excel workbooks (via the optional
``openpyxl`` library).  Columns are referenced by header name (when
``header_row`` >= 0) or by 0-based index.

The row-mapping logic is split out as :func:`xlsx_rows_to_transactions` so it
can be unit-tested without ``openpyxl`` or a real file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterator, List

from bankhub.errors import ConfigError, MissingDependencyError
from bankhub.models import Transaction
from bankhub.normalize import (clean_text, compute_external_id, parse_amount,
                               parse_date)
from bankhub.registry import register_source
from bankhub.sources.base import Source


def xlsx_rows_to_transactions(rows: List[Dict[str, Any]], *, columns: Dict[str, Any],
                              source: str, account_id: str = "",
                              date_format: str = None, decimal_comma: bool = False,
                              currency: str = "usd") -> List[Transaction]:
    """Pure mapping from already-extracted row dicts to transactions.

    ``columns`` maps canonical fields (``date``/``amount``/``payee``/``notes``)
    to a row key (header name or column index).
    """
    out: List[Transaction] = []
    for row in rows:
        raw_date = row.get(columns["date"])
        raw_amount = row.get(columns["amount"])
        if raw_date in (None, "") and raw_amount in (None, ""):
            continue  # skip blank rows
        date = parse_date(raw_date, date_format)
        amount = parse_amount(raw_amount, decimal_comma=decimal_comma)
        payee = clean_text(row.get(columns.get("payee", ""), ""))
        notes = clean_text(row.get(columns.get("notes", ""), ""))
        out.append(Transaction(
            external_id=compute_external_id(source, account_id, date, amount, payee, notes),
            source=source,
            account_id=account_id,
            date=date,
            amount=amount,
            currency=currency.lower(),
            payee=payee,
            notes=notes,
            raw=row,
        ))
    return out


def _read_sheet(path: str, sheet, header_row: int) -> List[Dict[str, Any]]:
    """Read a worksheet into a list of row dicts keyed by header or index."""
    try:
        import openpyxl
    except ImportError:
        raise MissingDependencyError("xlsx", "openpyxl")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    # A sheet ref may be an index (0, "0") or a worksheet name ("Transactions").
    if isinstance(sheet, int) or (isinstance(sheet, str) and sheet.lstrip("-").isdigit()):
        ws = wb.worksheets[int(sheet)]
    else:
        ws = wb[sheet]
    grid = [list(r) for r in ws.iter_rows(values_only=True)]
    if header_row is not None and header_row >= 0:
        headers = [clean_text(h) for h in grid[header_row]]
        body = grid[header_row + 1:]
        return [{headers[i]: v for i, v in enumerate(row) if i < len(headers)}
                for row in body]
    return [{i: v for i, v in enumerate(row)} for row in grid]


@register_source("xlsx")
class XlsxSource(Source):
    """Read transactions from an Excel ``.xlsx`` workbook.

    Options
    -------
    file
        Path to the ``.xlsx`` file (required).
    sheet
        Worksheet name or 0-based index (default ``0``).
    header_row
        Header row index, or ``-1`` for headerless/index-mapped (default ``0``).
    date, amount, payee, notes
        Column references (header name or 0-based index). ``date`` and
        ``amount`` are required; ``payee``/``notes`` optional.
    date_format, decimal_comma, currency, account, bank
        As for the CSV source.
    """

    requires = "openpyxl"

    def __init__(self, file: str = None, sheet="0", header_row="0",
                 date=None, amount=None, payee=None, notes=None,
                 date_format: str = None, decimal_comma=False, currency: str = "usd",
                 account: str = "", bank: str = "", **options):
        super().__init__(**options)
        self.file = file
        self.sheet = sheet
        self.header_row = int(header_row)
        self.columns = {"date": date, "amount": amount, "payee": payee, "notes": notes}
        self.date_format = date_format
        self.decimal_comma = str(decimal_comma).lower() in ("1", "true", "yes")
        self.currency = currency
        self.account_id = account
        self.bank = bank

    @property
    def source_id(self) -> str:
        return f"xlsx:{self.bank}" if self.bank else "xlsx"

    def fetch(self) -> Iterator[Transaction]:
        if not self.file:
            raise ConfigError("xlsx source needs file=<path.xlsx>")
        if not os.path.exists(self.file):
            raise ConfigError(f"xlsx file not found: {self.file}")
        if self.columns["date"] is None or self.columns["amount"] is None:
            raise ConfigError("xlsx source needs at least date= and amount= column refs")
        # Index columns may be passed as strings on the CLI; coerce when headerless.
        cols = dict(self.columns)
        if self.header_row < 0:
            cols = {k: (int(v) if v is not None and str(v).lstrip("-").isdigit() else v)
                    for k, v in cols.items()}
        rows = _read_sheet(self.file, self.sheet, self.header_row)
        yield from xlsx_rows_to_transactions(
            rows, columns=cols, source=self.source_id, account_id=self.account_id,
            date_format=self.date_format, decimal_comma=self.decimal_comma,
            currency=self.currency)
