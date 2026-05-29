# -*- coding: utf-8 -*-
"""Plugin registry for sources and destinations.

Plugins self-register with the :func:`register_source` /
:func:`register_destination` decorators.  Importing :mod:`bankhub` triggers
discovery (see :func:`load_plugins`), after which the CLI and engine can
look plugins up by name.

Registering a plugin must stay cheap: heavyweight third-party SDKs (plaid,
actualpy, …) are imported lazily inside the plugin's methods, never at
module import time, so ``list-sources`` works even when an integration's
dependency isn't installed.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Dict, List, Type

from .errors import PluginError


_SOURCES: Dict[str, Type] = {}
_DESTINATIONS: Dict[str, Type] = {}
_LOADED = False


def register_source(name: str):
    """Class decorator registering a :class:`~bankhub.sources.base.Source`."""

    def decorator(cls):
        cls.name = name
        _SOURCES[name] = cls
        return cls

    return decorator


def register_destination(name: str):
    """Class decorator registering a
    :class:`~bankhub.destinations.base.Destination`."""

    def decorator(cls):
        cls.name = name
        _DESTINATIONS[name] = cls
        return cls

    return decorator


def _discover(package_name: str) -> None:
    """Import every submodule of ``package_name`` so decorators run."""
    package = importlib.import_module(package_name)
    for mod in pkgutil.iter_modules(package.__path__):
        if mod.name.startswith("_") or mod.name == "base":
            continue
        importlib.import_module(f"{package_name}.{mod.name}")


def load_plugins() -> None:
    """Discover all built-in source and destination plugins (idempotent)."""
    global _LOADED
    if _LOADED:
        return
    _discover("bankhub.sources")
    _discover("bankhub.destinations")
    _LOADED = True


def available_sources() -> List[str]:
    load_plugins()
    return sorted(_SOURCES)


def available_destinations() -> List[str]:
    load_plugins()
    return sorted(_DESTINATIONS)


def get_source_class(name: str) -> Type:
    load_plugins()
    try:
        return _SOURCES[name]
    except KeyError:
        raise PluginError(
            f"Unknown source {name!r}. Available: {', '.join(available_sources())}"
        )


def get_destination_class(name: str) -> Type:
    load_plugins()
    try:
        return _DESTINATIONS[name]
    except KeyError:
        raise PluginError(
            f"Unknown destination {name!r}. "
            f"Available: {', '.join(available_destinations())}"
        )


def build_source(name: str, **options):
    """Instantiate a source plugin by name."""
    return get_source_class(name)(**options)


def build_destination(name: str, **options):
    """Instantiate a destination plugin by name."""
    return get_destination_class(name)(**options)
