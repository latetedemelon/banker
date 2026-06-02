# -*- coding: utf-8 -*-
"""Pure helpers for turning messy source data into canonical values.

Everything here is deterministic and side-effect free so it can be unit
tested without any I/O.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from .errors import SourceError


_WS_RE = re.compile(r"\s+")


def parse_amount(value, *, decimal_comma: bool = False, thousands: str = None) -> Decimal:
    """Parse a monetary value from a string/number into a :class:`Decimal`.

    Handles surrounding whitespace, currency symbols, thousands separators,
    parenthesised negatives ``(12.34)`` and European ``1.234,56`` notation
    (when ``decimal_comma=True``).
    """
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    # Strip anything that is not a digit, separator or sign.
    text = re.sub(r"[^0-9,.\-+]", "", text)

    if decimal_comma:
        # 1.234,56 -> 1234.56
        text = text.replace(".", "").replace(",", ".")
    else:
        if thousands:
            text = text.replace(thousands, "")
        elif "," in text and "." not in text:
            # Ambiguous: "12,50" is a decimal comma but "1,000" is grouping.
            # Standard heuristic: exactly 3 digits after the last comma means
            # thousands grouping; otherwise treat the comma as a decimal point.
            frac = text.rpartition(",")[2]
            if len(frac) == 3:
                text = text.replace(",", "")
            else:
                text = text.replace(",", ".")
        else:
            text = text.replace(",", "")

    if text in ("", "+", "-", "."):
        return Decimal("0")

    try:
        result = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise SourceError(f"Could not parse amount {value!r}") from exc
    return -result if negative else result


def combined_amount(debit, credit, *, decimal_comma: bool = False) -> Decimal:
    """Combine separate *debit* (money out) and *credit* (money in) cells into a
    single signed amount: positive = inflow, negative = outflow.

    Each column is treated as a magnitude — its sign is ignored and an empty
    cell counts as zero — which matches statements that split amounts across
    "Money out"/"Money in" (or "Debit"/"Credit", "Withdrawals"/"Deposits")
    columns instead of one signed column.
    """
    out = abs(parse_amount(debit, decimal_comma=decimal_comma))
    inn = abs(parse_amount(credit, decimal_comma=decimal_comma))
    return inn - out


def parse_date(value, fmt: Optional[str] = None) -> _dt.date:
    """Parse a date string. With ``fmt`` use :func:`strptime`; otherwise try
    ISO-8601 and a handful of common fallbacks."""
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value).strip()
    if fmt:
        return _dt.datetime.strptime(text, fmt).date()
    # Fallback: ISO first, then common formats.
    try:
        return _dt.date.fromisoformat(text[:10])
    except ValueError:
        pass
    for candidate in ("%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
                      "%Y.%m.%d", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    raise SourceError(f"Could not parse date {value!r}")


def clean_text(value) -> str:
    """Collapse runs of whitespace and strip; ``None`` becomes ``""``."""
    if value is None:
        return ""
    return _WS_RE.sub(" ", str(value)).strip()


def compute_external_id(source: str, account_id: str, date, amount,
                        payee: str = "", notes: str = "", extra: str = "") -> str:
    """Deterministic dedup id for sources that don't expose a stable one.

    The same logical transaction always hashes to the same value, so
    re-importing a statement never creates duplicates.
    """
    date_str = date.isoformat() if hasattr(date, "isoformat") else str(date)
    parts = [source, str(account_id), date_str, str(amount),
             clean_text(payee), clean_text(notes), str(extra)]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest
