# -*- coding: utf-8 -*-
"""Base class for every input adapter (a *source*)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Iterator, List

from ..models import Account, Transaction


class Source(ABC):
    """Pulls native records from somewhere and yields :class:`Transaction`.

    A source's ``__init__`` receives keyword options (CLI ``--source-opt``,
    or a pipeline config block).  Keep ``__init__`` light and defer any
    network/SDK work to :meth:`fetch` so unsupported integrations can still
    be listed and introspected.
    """

    #: Set by :func:`bankhub.registry.register_source`.
    name: str = ""

    #: Optional third-party package this source needs (used for nicer errors
    #: and ``list-sources`` output).  ``None`` means stdlib-only.
    requires: str = None

    def __init__(self, **options):
        self.options = options

    @property
    def source_id(self) -> str:
        """The value this source stamps on ``Transaction.source``.

        Defaults to the plugin name; adapters that namespace their output
        (e.g. CSV by bank) override this so delivery can filter precisely.
        """
        return self.name

    @abstractmethod
    def fetch(self) -> Iterator[Transaction]:
        """Yield normalised transactions. May be a generator."""
        raise NotImplementedError

    def list_accounts(self) -> List[Account]:
        """Optional: enumerate accounts this source exposes."""
        return []

    # Convenience so callers can always treat the result as a list.
    def fetch_all(self) -> List[Transaction]:
        return list(self.fetch())

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Source {self.name!r}>"


def as_list(transactions: Iterable[Transaction]) -> List[Transaction]:
    return list(transactions)
