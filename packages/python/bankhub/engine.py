# -*- coding: utf-8 -*-
"""The hub engine: orchestrates source -> store -> mapping -> destinations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .destinations.base import Destination
from .mapping import SKIP, AccountMap
from .models import PushResult, Transaction
from .sources.base import Source
from .store import Store


@dataclass
class IngestResult:
    source: str
    fetched: int = 0
    new: int = 0
    existing: int = 0

    def __str__(self) -> str:
        return (f"ingest[{self.source}]: fetched={self.fetched} "
                f"new={self.new} duplicate={self.existing}")


@dataclass
class DeliverResult:
    destination: str
    candidates: int = 0
    created: int = 0
    skipped: int = 0
    errors: int = 0
    dry_run: bool = False
    results: List[PushResult] = field(default_factory=list)

    def __str__(self) -> str:
        prefix = "deliver(dry-run)" if self.dry_run else "deliver"
        return (f"{prefix}[{self.destination}]: candidates={self.candidates} "
                f"created={self.created} skipped={self.skipped} errors={self.errors}")


@dataclass
class SyncReport:
    ingest: Optional[IngestResult] = None
    deliveries: List[DeliverResult] = field(default_factory=list)


class Engine:
    """Wires sources, the dedup store, account mapping and destinations."""

    def __init__(self, store: Store, account_map: AccountMap = None,
                 dry_run: bool = False):
        self.store = store
        self.account_map = account_map or AccountMap()
        self.dry_run = dry_run

    # -- ingest ------------------------------------------------------------
    def ingest(self, source: Source) -> IngestResult:
        """Fetch from a source and store any previously unseen transactions."""
        transactions = list(source.fetch())
        result = IngestResult(source=source.source_id, fetched=len(transactions))
        if self.dry_run:
            # Count how many are new without writing.
            new = sum(1 for t in transactions if not self.store.get(t.external_id))
            result.new, result.existing = new, len(transactions) - new
            return result
        outcome = self.store.upsert(transactions)
        result.new = len(outcome["new"])
        result.existing = len(outcome["existing"])
        return result

    # -- deliver -----------------------------------------------------------
    def deliver(self, destination: Destination, source: str = None,
                since=None) -> DeliverResult:
        """Push everything not yet delivered to ``destination``."""
        stored_rows = self.store.unsynced(destination.name, source=source, since=since)
        result = DeliverResult(destination=destination.name,
                               candidates=len(stored_rows), dry_run=self.dry_run)

        by_external_id = {}
        to_push: List[Transaction] = []
        for stored in stored_rows:
            txn = Store.to_transaction(stored)
            target = self.account_map.resolve(destination.name, txn.account_id)
            if target == SKIP:
                result.skipped += 1
                if not self.dry_run:
                    self.store.record_sync(stored, destination.name,
                                           status="skipped", detail="account mapped to skip")
                continue
            txn.dest_account = target
            by_external_id[txn.external_id] = stored
            to_push.append(txn)

        if self.dry_run:
            result.created = len(to_push)
            return result

        return self._push_and_record(destination, to_push, by_external_id, result)

    def _push_and_record(self, destination, to_push, by_external_id, result):
        if to_push:
            push_results = destination.push(to_push)
            result.results = push_results
            for pr in push_results:
                stored = by_external_id.get(pr.external_id)
                if pr.status == "error":
                    result.errors += 1
                    if stored:
                        self.store.record_sync(stored, destination.name,
                                               status="error", detail=pr.error)
                else:
                    if pr.status == "skipped":
                        result.skipped += 1
                    else:
                        result.created += 1
                    if stored:
                        self.store.record_sync(stored, destination.name,
                                               remote_id=pr.remote_id, status=pr.status)
        return result

    # -- combined ----------------------------------------------------------
    def sync(self, source: Source,
             destinations: List[Destination]) -> SyncReport:
        """Ingest from ``source`` then deliver to each destination."""
        if self.dry_run:
            return self._dry_run_sync(source, destinations)
        report = SyncReport(ingest=self.ingest(source))
        for destination in destinations:
            report.deliveries.append(
                self.deliver(destination, source=source.source_id))
        return report

    def _dry_run_sync(self, source: Source,
                      destinations: List[Destination]) -> SyncReport:
        """Simulate a full sync without writing anything.

        Reports would-be-new ingests and, for each destination, what would be
        delivered: the union of already-stored-but-undelivered transactions
        and the new ones we'd ingest this run.
        """
        fetched = list(source.fetch())
        new = [t for t in fetched if not self.store.get(t.external_id)]
        ingest = IngestResult(source=source.source_id, fetched=len(fetched),
                              new=len(new), existing=len(fetched) - len(new))
        report = SyncReport(ingest=ingest)
        for destination in destinations:
            already = [Store.to_transaction(s) for s in
                       self.store.unsynced(destination.name, source=source.source_id)]
            candidates = already + new
            result = DeliverResult(destination=destination.name,
                                   candidates=len(candidates), dry_run=True)
            for txn in candidates:
                if self.account_map.resolve(destination.name, txn.account_id) == SKIP:
                    result.skipped += 1
                else:
                    result.created += 1
            report.deliveries.append(result)
        return report
