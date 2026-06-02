# -*- coding: utf-8 -*-
"""Declarative pipeline configuration.

A pipeline file wires sources to destinations so an entire hub can be run
with a single command.  Example::

    store: db/bankhub.db
    account_map: config/accounts.yml      # path or inline mapping
    pipelines:
      - name: revolut-to-lunchmoney
        source:   {type: csv, bank: revolut, file: ~/stmts/revolut.csv}
        destinations:
          - {type: lunchmoney, token: ${LUNCHMONEY_TOKEN}}
          - {type: csv, file: exports/revolut.csv}

``${VAR}`` references are expanded from the environment, and ``~`` is
expanded to the home directory, so secrets never need to live in the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

from .engine import Engine, SyncReport
from .errors import ConfigError
from .mapping import AccountMap
from .registry import build_destination, build_source
from .store import Store


def expand_env(obj: Any) -> Any:
    """Recursively expand ``${VAR}`` and ``~`` in all string values."""
    if isinstance(obj, str):
        return os.path.expanduser(os.path.expandvars(obj))
    if isinstance(obj, dict):
        return {k: expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env(v) for v in obj]
    return obj


@dataclass
class PipelineSpec:
    name: str
    source: Dict[str, Any]
    destinations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class HubConfig:
    store: str = "db/bankhub.db"
    account_map: Any = None  # path (str) or inline dict
    strict_mapping: bool = False
    pipelines: List[PipelineSpec] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "HubConfig":
        with open(path, "r", encoding="utf-8") as fh:
            data = expand_env(yaml.safe_load(fh) or {})
        if "pipelines" not in data:
            raise ConfigError("pipeline config must define a 'pipelines' list")
        pipelines = []
        for raw in data["pipelines"]:
            if "source" not in raw:
                raise ConfigError(f"pipeline {raw.get('name')!r} has no 'source'")
            pipelines.append(PipelineSpec(
                name=raw.get("name", raw["source"].get("type", "pipeline")),
                source=raw["source"],
                destinations=raw.get("destinations", []),
            ))
        return cls(
            store=data.get("store", "db/bankhub.db"),
            account_map=data.get("account_map"),
            strict_mapping=bool(data.get("strict_mapping", False)),
            pipelines=pipelines,
        )

    def build_account_map(self) -> AccountMap:
        if isinstance(self.account_map, dict):
            return AccountMap(self.account_map, strict=self.strict_mapping)
        if isinstance(self.account_map, str):
            return AccountMap.from_file(self.account_map, strict=self.strict_mapping)
        return AccountMap(strict=self.strict_mapping)


def _split_type(block: Dict[str, Any]):
    block = dict(block)
    plugin_type = block.pop("type", None)
    if not plugin_type:
        raise ConfigError(f"config block missing 'type': {block}")
    return plugin_type, block


def run_config(path: str, dry_run: bool = False) -> List[SyncReport]:
    """Load a pipeline file and execute every pipeline in it."""
    config = HubConfig.load(path)
    store = Store(config.store)
    engine = Engine(store, config.build_account_map(), dry_run=dry_run)
    reports = []
    try:
        for spec in config.pipelines:
            src_type, src_opts = _split_type(spec.source)
            source = build_source(src_type, **src_opts)
            destinations = []
            for dest_block in spec.destinations:
                dest_type, dest_opts = _split_type(dest_block)
                destinations.append(build_destination(dest_type, **dest_opts))
            reports.append(engine.sync(source, destinations))
    finally:
        store.close()
    return reports
