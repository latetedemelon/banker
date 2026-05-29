# -*- coding: utf-8 -*-
"""Local persistence: deduplication + per-destination sync state.

This is what makes the hub a *hub*.  Transactions are ingested once (keyed
by their ``external_id``); each delivery to a destination is recorded in a
separate :class:`SyncRecord`.  A transaction can therefore fan out to many
destinations, and re-running a pipeline never imports or pushes a duplicate.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Iterable, List, Optional

from peewee import (CharField, DateField, DateTimeField, DecimalField,
                    ForeignKeyField, Model, SqliteDatabase, TextField)

from .models import Transaction

# A single database is bound per process; the CLI points it at the configured
# path before use.  Tests may use ":memory:" or a temp file.
_db = SqliteDatabase(None)


class _JSONText(TextField):
    """A TextField that transparently (de)serialises JSON, avoiding any
    dependency on SQLite's optional json1 extension."""

    def db_value(self, value):
        return None if value is None else json.dumps(value)

    def python_value(self, value):
        return None if value in (None, "") else json.loads(value)


class _Base(Model):
    class Meta:
        database = _db


class StoredTransaction(_Base):
    external_id = CharField(unique=True, index=True)
    source = CharField(index=True)
    account_id = CharField(index=True)
    date = DateField()
    amount = DecimalField(max_digits=20, decimal_places=4)
    currency = CharField()
    payee = CharField(default="")
    notes = TextField(default="")
    category = CharField(null=True)
    status = CharField(default="posted")
    data = _JSONText()
    created_at = DateTimeField(default=datetime.utcnow)


class SyncRecord(_Base):
    transaction = ForeignKeyField(StoredTransaction, backref="syncs",
                                  on_delete="CASCADE")
    destination = CharField(index=True)
    remote_id = CharField(null=True)
    status = CharField(default="created")  # created | skipped | error
    detail = TextField(null=True)
    synced_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        # One row per (transaction, destination): the idempotency guarantee.
        indexes = ((("transaction", "destination"), True),)


class Store:
    """SQLite-backed transaction + sync store."""

    def __init__(self, path: str = "db/bankhub.db"):
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        if path != ":memory:" and directory:
            os.makedirs(directory, exist_ok=True)
        _db.init(path, pragmas={"journal_mode": "wal", "foreign_keys": 1})
        _db.connect(reuse_if_open=True)
        _db.create_tables([StoredTransaction, SyncRecord], safe=True)

    def close(self) -> None:
        if not _db.is_closed():
            _db.close()

    # -- ingest ------------------------------------------------------------
    def upsert(self, transactions: Iterable[Transaction]) -> dict:
        """Insert previously unseen transactions; skip known ``external_id``s.

        Returns ``{"new": [...], "existing": [...]}`` of external ids.
        """
        new, existing = [], []
        with _db.atomic():
            for txn in transactions:
                if StoredTransaction.get_or_none(
                        StoredTransaction.external_id == txn.external_id):
                    existing.append(txn.external_id)
                    continue
                StoredTransaction.create(
                    external_id=txn.external_id,
                    source=txn.source,
                    account_id=txn.account_id,
                    date=txn.date,
                    amount=txn.amount,
                    currency=txn.currency,
                    payee=txn.payee,
                    notes=txn.notes,
                    category=txn.category,
                    status=txn.status,
                    data=txn.to_dict(),
                )
                new.append(txn.external_id)
        return {"new": new, "existing": existing}

    # -- query -------------------------------------------------------------
    def get(self, external_id: str) -> Optional[StoredTransaction]:
        return StoredTransaction.get_or_none(
            StoredTransaction.external_id == external_id)

    def unsynced(self, destination: str, source: str = None,
                 since=None) -> List[StoredTransaction]:
        """Transactions never successfully delivered to ``destination``."""
        synced = (SyncRecord
                  .select(SyncRecord.transaction)
                  .where((SyncRecord.destination == destination)
                         & (SyncRecord.status != "error")))
        query = (StoredTransaction
                 .select()
                 .where(StoredTransaction.id.not_in(synced))
                 .order_by(StoredTransaction.date, StoredTransaction.id))
        if source:
            query = query.where(StoredTransaction.source == source)
        if since:
            query = query.where(StoredTransaction.date >= since)
        return list(query)

    def all_transactions(self, source: str = None) -> List[StoredTransaction]:
        query = StoredTransaction.select().order_by(StoredTransaction.date)
        if source:
            query = query.where(StoredTransaction.source == source)
        return list(query)

    # -- sync state --------------------------------------------------------
    def record_sync(self, stored: StoredTransaction, destination: str,
                    remote_id: str = None, status: str = "created",
                    detail: str = None) -> None:
        existing = SyncRecord.get_or_none(
            (SyncRecord.transaction == stored)
            & (SyncRecord.destination == destination))
        if existing:
            existing.remote_id = remote_id
            existing.status = status
            existing.detail = detail
            existing.synced_at = datetime.utcnow()
            existing.save()
        else:
            SyncRecord.create(transaction=stored, destination=destination,
                              remote_id=remote_id, status=status, detail=detail)

    def link_remote_id(self, external_id: str, destination: str,
                       remote_id: str) -> bool:
        """Backfill the remote id for an already-ingested transaction
        (used to reconcile ids fetched back from a destination)."""
        stored = self.get(external_id)
        if not stored:
            return False
        self.record_sync(stored, destination, remote_id=remote_id,
                         status="created")
        return True

    # -- reporting ---------------------------------------------------------
    def stats(self) -> dict:
        total = StoredTransaction.select().count()
        by_source = {}
        for row in (StoredTransaction
                    .select(StoredTransaction.source)
                    .distinct()):
            by_source[row.source] = (StoredTransaction
                                     .select()
                                     .where(StoredTransaction.source == row.source)
                                     .count())
        by_dest = {}
        for row in SyncRecord.select(SyncRecord.destination).distinct():
            by_dest[row.destination] = (SyncRecord
                                        .select()
                                        .where((SyncRecord.destination == row.destination)
                                               & (SyncRecord.status != "error"))
                                        .count())
        return {"total": total, "by_source": by_source, "synced_by_destination": by_dest}

    @staticmethod
    def to_transaction(stored: StoredTransaction) -> Transaction:
        """Reconstruct a normalised :class:`Transaction` from a stored row."""
        return Transaction.from_dict(stored.data)
