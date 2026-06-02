# -*- coding: utf-8 -*-
"""Base class for every output adapter (a *destination*)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import PushResult, Transaction


class Destination(ABC):
    """Delivers :class:`Transaction` objects to a target system.

    Implementations should be **idempotent where possible** (carry the
    transaction's ``external_id`` through to the remote system so re-runs
    don't duplicate), and must return one :class:`PushResult` per input
    transaction, in the same order.
    """

    #: Set by :func:`bankhub.registry.register_destination`.
    name: str = ""

    #: Optional third-party package this destination needs.
    requires: str = None

    def __init__(self, **options):
        self.options = options

    @abstractmethod
    def push(self, transactions: List[Transaction]) -> List[PushResult]:
        """Deliver ``transactions`` and report per-transaction outcomes."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Destination {self.name!r}>"
