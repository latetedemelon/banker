# -*- coding: utf-8 -*-
"""Command-line interface for the bankhub.

Run ``python -m bankhub --help`` (or ``python main.py --help``) for usage.
The three legacy commands (``data-import``, ``lunchmoney-id``,
``data-export``) are preserved as thin wrappers over the new engine.
"""

from __future__ import annotations

import calendar
import sys
from typing import Dict, List, Tuple

import click

from . import __version__
from .config import run_config
from .engine import Engine
from .errors import BankhubError
from .mapping import AccountMap
from .registry import (available_destinations, available_sources,
                       build_destination, build_source, get_destination_class,
                       get_source_class)
from .store import Store

DEFAULT_STORE = "db/bankhub.db"
DEFAULT_ACCOUNT_MAP = "config/accounts.yml"


# --------------------------------------------------------------------------
# option parsing helpers
# --------------------------------------------------------------------------
def _parse_kv(pairs: Tuple[str, ...]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value
    return out


def _parse_scoped(pairs: Tuple[str, ...], names: List[str]):
    """Split ``name.key=value`` opts into per-destination dicts.

    A bare ``key=value`` (or one whose prefix isn't a known dest name)
    applies to every destination.
    """
    globals_: Dict[str, str] = {}
    scoped: Dict[str, Dict[str, str]] = {n: {} for n in names}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if "." in key:
            prefix, rest = key.split(".", 1)
            if prefix in scoped:
                scoped[prefix][rest] = value
                continue
        globals_[key] = value
    merged = {}
    for name in names:
        merged[name] = {**globals_, **scoped[name]}
    return merged


def _is_available(cls) -> bool:
    if not cls.requires:
        return True
    try:
        __import__(cls.requires)
        return True
    except ImportError:
        return False


def _account_map(path: str, strict: bool) -> AccountMap:
    import os
    if path and os.path.exists(path):
        return AccountMap.from_file(path, strict=strict)
    return AccountMap(strict=strict)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
@click.group()
@click.version_option(__version__, prog_name="bankhub")
def cli():
    """bankhub -- a universal hub for personal-finance data.

    Many sources (CSV, Plaid, Flinks, Lunchmoney) feed one normalised model
    that fans out to many destinations (Lunchmoney, YNAB, Actual, CSV, JSON).
    """


@cli.command("sources")
def list_sources():
    """List available source adapters."""
    click.echo("Sources:")
    for name in available_sources():
        cls = get_source_class(name)
        mark = "" if _is_available(cls) else f"  (needs '{cls.requires}')"
        click.echo(f"  {name}{mark}")


@cli.command("destinations")
def list_destinations():
    """List available destination adapters."""
    click.echo("Destinations:")
    for name in available_destinations():
        cls = get_destination_class(name)
        mark = "" if _is_available(cls) else f"  (needs '{cls.requires}')"
        click.echo(f"  {name}{mark}")


@cli.command("sync")
@click.option("--source", "source_name", required=True, help="Source adapter name")
@click.option("--source-opt", "source_opts", multiple=True, metavar="KEY=VALUE",
              help="Source option (repeatable)")
@click.option("--dest", "dest_names", multiple=True, required=True,
              help="Destination adapter name (repeatable)")
@click.option("--dest-opt", "dest_opts", multiple=True, metavar="[DEST.]KEY=VALUE",
              help="Destination option; prefix with 'name.' to scope it")
@click.option("--store", "store_path", default=DEFAULT_STORE, show_default=True)
@click.option("--account-map", "account_map_path", default=DEFAULT_ACCOUNT_MAP,
              show_default=True, help="YAML mapping source accounts -> dest accounts")
@click.option("--strict-map", is_flag=True, help="Error on unmapped accounts")
@click.option("--since", default=None, help="Only deliver transactions on/after this ISO date")
@click.option("--dry-run", is_flag=True, help="Report what would happen, change nothing")
def sync(source_name, source_opts, dest_names, dest_opts, store_path,
         account_map_path, strict_map, since, dry_run):
    """Ingest from one SOURCE and deliver to one or more DESTinations."""
    source_kwargs = _parse_kv(source_opts)
    dest_kwargs = _parse_scoped(dest_opts, list(dest_names))
    store = Store(store_path)
    engine = Engine(store, _account_map(account_map_path, strict_map), dry_run=dry_run)
    try:
        source = build_source(source_name, **source_kwargs)
        destinations = [build_destination(name, **dest_kwargs[name])
                        for name in dest_names]
        if since and not dry_run:
            # `since` only narrows delivery, so run the steps explicitly.
            click.echo(_fmt(engine.ingest(source)))
            for dest in destinations:
                click.echo(_fmt(engine.deliver(dest, source=source.source_id,
                                               since=since)))
        else:
            report = engine.sync(source, destinations)
            click.echo(_fmt(report.ingest))
            for delivery in report.deliveries:
                click.echo(_fmt(delivery))
    finally:
        store.close()


@cli.command("run")
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Report what would happen, change nothing")
def run(config_path, dry_run):
    """Run every pipeline defined in a CONFIG file."""
    reports = run_config(config_path, dry_run=dry_run)
    for report in reports:
        click.echo(_fmt(report.ingest))
        for delivery in report.deliveries:
            click.echo("  " + _fmt(delivery))


@cli.command("accounts")
@click.option("--source", "source_name", required=True)
@click.option("--source-opt", "source_opts", multiple=True, metavar="KEY=VALUE")
def accounts(source_name, source_opts):
    """List accounts exposed by a SOURCE (if it supports discovery)."""
    source = build_source(source_name, **_parse_kv(source_opts))
    found = source.list_accounts()
    if not found:
        click.echo("(this source does not expose account discovery)")
        return
    for acct in found:
        click.echo(f"  {acct.id}\t{acct.name}\t{acct.currency}\t{acct.balance}")


@cli.command("stats")
@click.option("--store", "store_path", default=DEFAULT_STORE, show_default=True)
def stats(store_path):
    """Show counts of ingested and delivered transactions."""
    store = Store(store_path)
    try:
        data = store.stats()
    finally:
        store.close()
    click.echo(f"Total stored: {data['total']}")
    click.echo("By source:")
    for source, count in sorted(data["by_source"].items()):
        click.echo(f"  {source}: {count}")
    click.echo("Delivered by destination:")
    for dest, count in sorted(data["synced_by_destination"].items()):
        click.echo(f"  {dest}: {count}")


# --------------------------------------------------------------------------
# legacy commands (backwards compatibility with the original CLI)
# --------------------------------------------------------------------------
@cli.command("data-import")
@click.option("--bank-type", type=click.Choice(["kh", "revolut", "n26", "otp"]),
              required=True)
@click.option("--file-path", required=True, type=click.Path(exists=True))
@click.option("--store", "store_path", default=DEFAULT_STORE, show_default=True)
def data_import(bank_type, file_path, store_path):
    """[legacy] Import a bank CSV into the local store."""
    store = Store(store_path)
    engine = Engine(store)
    try:
        source = build_source("csv", bank=bank_type, file=file_path)
        click.echo(_fmt(engine.ingest(source)))
    finally:
        store.close()


@cli.command("data-export")
@click.option("--token", help="Lunchmoney API token")
@click.option("--store", "store_path", default=DEFAULT_STORE, show_default=True)
@click.option("--account-map", "account_map_path", default=DEFAULT_ACCOUNT_MAP,
              show_default=True)
def data_export(token, store_path, account_map_path):
    """[legacy] Push not-yet-synced transactions to Lunchmoney."""
    store = Store(store_path)
    engine = Engine(store, _account_map(account_map_path, strict=False))
    try:
        dest = build_destination("lunchmoney", token=token) if token \
            else build_destination("lunchmoney")
        click.echo(_fmt(engine.deliver(dest)))
    finally:
        store.close()


@cli.command("lunchmoney-id")
@click.option("--token", help="Lunchmoney API token")
@click.option("--year", required=True)
@click.option("--month", required=True, help="e.g. 05")
@click.option("--store", "store_path", default=DEFAULT_STORE, show_default=True)
def lunchmoney_id(token, year, month, store_path):
    """[legacy] Reconcile Lunchmoney remote ids back into the store."""
    last_day = calendar.monthrange(int(year), int(month))[1]
    start = f"{year}-{month}-01"
    end = f"{year}-{month}-{last_day}"
    source = build_source("lunchmoney", token=token, start_date=start, end_date=end) \
        if token else build_source("lunchmoney", start_date=start, end_date=end)
    store = Store(store_path)
    linked = 0
    try:
        for txn in source.fetch():
            # The external_id we sent equals our stored external_id.
            ext = txn.raw.get("external_id") if isinstance(txn.raw, dict) else None
            if ext and store.link_remote_id(ext, "lunchmoney", txn.external_id):
                linked += 1
    finally:
        store.close()
    click.echo(f"Reconciled {linked} Lunchmoney ids")


def _fmt(result) -> str:
    return str(result)


def main(argv=None):
    try:
        cli(args=argv)
    except BankhubError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
