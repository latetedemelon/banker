# -*- coding: utf-8 -*-
"""bankhub -- a universal hub for personal-finance data.

Many *sources* (CSV, OFX/QIF/MT940/CAMT, PDF, Plaid, SimpleFIN, Yodlee,
GoCardless, TrueLayer, MX, Finicity, Teller, Salt Edge, Lunchmoney, …) feed a
single normalised :class:`~bankhub.models.Transaction` model, which is
de-duplicated and then delivered to many *destinations* (Lunchmoney, YNAB,
Actual, CSV, JSON, …).

Quick start (as a library)::

    import bankhub

    src = bankhub.build_source("csv", bank="revolut", file="revolut.csv")
    store = bankhub.Store("db/bankhub.db")
    engine = bankhub.Engine(store)
    engine.sync(src, [bankhub.build_destination("json", file="out.jsonl")])

The stable, supported public API is everything exported in :data:`__all__`
below.  :mod:`bankhub.engine`, :mod:`bankhub.store` and
:mod:`bankhub.registry` hold the orchestration and plugin system.
"""

from .config import HubConfig, PipelineSpec, expand_env, run_config
from .destinations.base import Destination
from .engine import (DeliverResult, Engine, IngestResult, SyncReport)
from .errors import (BankhubError, ConfigError, DestinationError,
                     MappingError, MissingDependencyError, PluginError,
                     SourceError)
from .mapping import SKIP, AccountMap
from .models import (PENDING, POSTED, Account, PushResult, Transaction)
from .registry import (available_destinations, available_sources,
                       build_destination, build_source, get_destination_class,
                       get_source_class, load_plugins, register_destination,
                       register_source)
from .sources.base import Source
from .store import Store

__version__ = "0.3.0"

__all__ = [
    # version
    "__version__",
    # core model
    "Transaction",
    "PushResult",
    "Account",
    "POSTED",
    "PENDING",
    # adapter base classes (for writing your own)
    "Source",
    "Destination",
    # plugin registry
    "register_source",
    "register_destination",
    "build_source",
    "build_destination",
    "get_source_class",
    "get_destination_class",
    "available_sources",
    "available_destinations",
    "load_plugins",
    # orchestration
    "Engine",
    "Store",
    "IngestResult",
    "DeliverResult",
    "SyncReport",
    # account mapping
    "AccountMap",
    "SKIP",
    # declarative pipelines
    "HubConfig",
    "PipelineSpec",
    "run_config",
    "expand_env",
    # errors
    "BankhubError",
    "ConfigError",
    "PluginError",
    "MissingDependencyError",
    "SourceError",
    "DestinationError",
    "MappingError",
]
