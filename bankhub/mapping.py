# -*- coding: utf-8 -*-
"""Account mapping: source account ids -> destination account ids.

Generalises the original ``assets.yml`` (which mapped bank account numbers
to Lunchmoney asset ids) to *any* destination.  A mapping file looks like::

    lunchmoney:
      "eur": 4501            # revolut EUR account -> Lunchmoney asset 4501
      "3771874088": 2008
      "*": skip              # drop anything not listed (optional)
    ynab:
      "eur": "a1b2-...-guid"
    actual:
      default: "Checking"    # fallback for unmapped accounts (optional)

The special value ``skip`` drops a transaction for that account; ``"*"`` is a
catch-all and ``default`` is an explicit fallback.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import yaml

from .errors import MappingError

SKIP = "__skip__"


class AccountMap:
    """Resolves a source ``account_id`` to a destination account id."""

    def __init__(self, mapping: Optional[Dict[str, Dict[str, Any]]] = None,
                 strict: bool = False):
        self.mapping = mapping or {}
        #: When true, an unmapped account raises instead of passing through.
        self.strict = strict

    @classmethod
    def from_file(cls, path: Optional[str], strict: bool = False) -> "AccountMap":
        if not path:
            return cls({}, strict=strict)
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data, strict=strict)

    def has_destination(self, destination: str) -> bool:
        return destination in self.mapping

    def resolve(self, destination: str, account_id: str) -> Optional[str]:
        """Return the destination account id, ``SKIP``, or the original
        ``account_id`` when no mapping is configured for the destination.

        Raises :class:`MappingError` in strict mode for an unmapped account.
        """
        table = self.mapping.get(destination)
        if not table:
            # No mapping configured for this destination -> pass through.
            return account_id

        if account_id in table:
            value = table[account_id]
        elif "*" in table:
            value = table["*"]
        elif "default" in table:
            value = table["default"]
        elif self.strict:
            raise MappingError(
                f"No mapping for account {account_id!r} -> destination "
                f"{destination!r} (strict mode)")
        else:
            return account_id

        if isinstance(value, str) and value.lower() == "skip":
            return SKIP
        return value if value is None else str(value)
