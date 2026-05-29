# -*- coding: utf-8 -*-
"""bankhub -- a universal hub for personal-finance data.

Many *sources* (CSV, Plaid, Flinks, Lunchmoney, …) feed a single normalised
:class:`~bankhub.models.Transaction` model, which is de-duplicated and then
delivered to many *destinations* (Lunchmoney, YNAB, Actual, CSV, JSON, …).

See :mod:`bankhub.engine` for the orchestration and :mod:`bankhub.registry`
for the plugin system.
"""

from .models import Account, PushResult, Transaction
from .registry import (available_destinations, available_sources,
                       build_destination, build_source, register_destination,
                       register_source)

__version__ = "0.2.0"

__all__ = [
    "Transaction",
    "PushResult",
    "Account",
    "register_source",
    "register_destination",
    "build_source",
    "build_destination",
    "available_sources",
    "available_destinations",
    "__version__",
]
