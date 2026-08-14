"""Deterministic in-memory market-data repository."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence
from uuid import UUID

from .domain import AdjustmentFactor, Bar, BatchStatus, DataQualityResult, DatasetBatch, DatasetSnapshot, MarketDataEvent
from .errors import RepositoryConflict, SnapshotNotFound


class InMemoryMarketDataRepository:
    def __init__(self) -> None:
        self.batches: dict[UUID, DatasetBatch] = {}
        self._keys: dict[tuple[str, str], UUID] = {}
        self.bars: list[Bar] = []
        self.factors: list[AdjustmentFactor] = []
        self.results: dict[UUID, tuple[DataQualityResult, ...]] = {}
        self.snapshots: dict[UUID, DatasetSnapshot] = {}
        self.events: list[MarketDataEvent] = []

    def find_batch(self, source: str, checksum: str) -> DatasetBatch | None:
        batch_id = self._keys.get((source.strip().lower(), checksum.strip()))
        return self.batches.get(batch_id) if batch_id else None

    def get_batch(self, batch_id: UUID) -> DatasetBatch | None:
        return self.batches.get(batch_id)

    def save_rejected(self, batch: DatasetBatch, results: Sequence[DataQualityResult]) -> None:
        rejected = replace(batch, status=BatchStatus.REJECTED)
        self._insert_batch(rejected)
        self.results[batch.batch_id] = tuple(results)

    def publish(self, batch: DatasetBatch, bars: Sequence[Bar], event: MarketDataEvent) -> None:
        published = replace(batch, status=BatchStatus.PUBLISHED, record_count=len(bars))
        self._insert_batch(published)
        self.bars.extend(bars)
        self.events.append(event)

    def save_factors(self, batch: DatasetBatch, factors: Sequence[AdjustmentFactor], event: MarketDataEvent) -> None:
        published = replace(batch, status=BatchStatus.PUBLISHED, record_count=len(factors))
        self._insert_batch(published)
        self.factors.extend(factors)
        self.events.append(event)

    def _insert_batch(self, batch: DatasetBatch) -> None:
        key = (batch.source, batch.checksum)
        if key in self._keys:
            raise RepositoryConflict("batch source/checksum already exists")
        self._keys[key] = batch.batch_id
        self.batches[batch.batch_id] = batch

    def create_snapshot(self, snapshot: DatasetSnapshot) -> None:
        if snapshot.snapshot_id in self.snapshots:
            raise RepositoryConflict("snapshot already exists")
        if any(self.batches.get(value, None) is None or self.batches[value].status is not BatchStatus.PUBLISHED for value in snapshot.batch_ids):
            raise RepositoryConflict("snapshot may contain only published batches")
        self.snapshots[snapshot.snapshot_id] = snapshot

    def get_snapshot(self, snapshot_id: UUID) -> DatasetSnapshot | None:
        return self.snapshots.get(snapshot_id)

    def _batch_set(self, snapshot_id: UUID) -> set[UUID]:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise SnapshotNotFound(str(snapshot_id))
        return set(snapshot.batch_ids)

    def bars_for_snapshot(self, snapshot_id: UUID) -> Sequence[Bar]:
        batches = self._batch_set(snapshot_id)
        return tuple(value for value in self.bars if value.batch_id in batches)

    def factors_for_snapshot(self, snapshot_id: UUID) -> Sequence[AdjustmentFactor]:
        batches = self._batch_set(snapshot_id)
        return tuple(value for value in self.factors if value.batch_id in batches)

    def quality_results(self, batch_id: UUID) -> Sequence[DataQualityResult]:
        return self.results.get(batch_id, ())

