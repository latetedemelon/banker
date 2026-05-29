# -*- coding: utf-8 -*-
"""Plugin registry for sources and destinations.

Adapters self-register with the :func:`register_source` /
:func:`register_destination` decorators.  Discovery (:func:`load_plugins`)
finds them two ways:

* **Entry points** -- any installed distribution may advertise an adapter
  package in the ``bankhub.plugins`` group; loading that entry point imports
  the package and runs its decorators.  This is how the first-party
  ``bankhub-files`` and ``bankhub-connectors`` distributions plug in, and how
  a third party adds its own adapters.
* **In-tree scan** -- any module dropped directly into ``bankhub.sources`` /
  ``bankhub.destinations`` is imported too (handy for vendoring an adapter).

Either way, registering must stay cheap: heavyweight third-party SDKs (plaid,
actualpy, pdfplumber, …) are imported lazily inside the adapter's methods,
never at import time, so the ``sources`` / ``destinations`` listings work even
when an integration's dependency isn't installed.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import pkgutil
import warnings
from typing import Dict, List, Type

from .errors import PluginError

#: Entry-point group under which an adapter distribution advertises its
#: package(s).  e.g. ``[project.entry-points."bankhub.plugins"]  files = "bankhub_files"``
PLUGIN_GROUP = "bankhub.plugins"

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


def _plugin_entry_points():
    """Entry points in the ``bankhub.plugins`` group (works on py3.9-3.12)."""
    eps = importlib.metadata.entry_points()
    if hasattr(eps, "select"):  # importlib.metadata >= 3.10 selectable API
        return list(eps.select(group=PLUGIN_GROUP))
    return list(eps.get(PLUGIN_GROUP, []))  # 3.9 dict API


def _scan_package(package_name: str) -> None:
    """Import every adapter submodule of a package so its decorators run."""
    try:
        package = importlib.import_module(package_name)
    except ImportError:  # pragma: no cover - package always present in core
        return
    for mod in pkgutil.iter_modules(package.__path__):
        if mod.name.startswith("_") or mod.name == "base":
            continue
        importlib.import_module(f"{package_name}.{mod.name}")


def load_plugins() -> None:
    """Discover all installed source/destination adapters (idempotent)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True  # set first so a re-entrant import can't recurse
    # 1. Entry-point plugins (bankhub-files, bankhub-connectors, third parties).
    for ep in _plugin_entry_points():
        try:
            ep.load()  # imports the adapter package -> its decorators register
        except Exception as exc:  # pragma: no cover - a broken plugin is non-fatal
            warnings.warn(f"bankhub: could not load plugin {ep.name!r}: {exc}")
    # 2. Anything vendored directly into core's own adapter packages.
    _scan_package("bankhub.sources")
    _scan_package("bankhub.destinations")


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
