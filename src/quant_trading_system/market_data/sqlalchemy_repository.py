"""Transactional SQLAlchemy Core market-data repository."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import RowMapping

from .domain import AdjustmentFactor, Bar, BarFrequency, BatchStatus, DataQualityResult, DatasetBatch, DatasetSnapshot, MarketDataEvent, QualitySeverity
from .errors import RepositoryConflict, SnapshotNotFound
from .tables import adjustment_factors, bars, dataset_batches, market_data_events, quality_results, snapshot_batches, snapshots


class SqlAlchemyMarketDataRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def find_batch(self, source: str, checksum: str) -> DatasetBatch | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(dataset_batches).where(dataset_batches.c.source == source.strip().lower(), dataset_batches.c.checksum == checksum.strip())).mappings().one_or_none()
        return self._batch(row) if row else None

    def get_batch(self, batch_id: UUID) -> DatasetBatch | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(dataset_batches).where(dataset_batches.c.batch_id == batch_id)).mappings().one_or_none()
        return self._batch(row) if row else None

    def save_rejected(self, batch: DatasetBatch, results: Sequence[DataQualityResult]) -> None:
        value = replace(batch, status=BatchStatus.REJECTED)
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(dataset_batches).values(self._batch_values(value)))
                connection.execute(insert(quality_results), [self._quality_values(value.batch_id, x) for x in results])
        except IntegrityError as exc:
            raise RepositoryConflict(str(exc.orig)) from exc

    def publish(self, batch: DatasetBatch, values: Sequence[Bar], event: MarketDataEvent) -> None:
        published = replace(batch, status=BatchStatus.PUBLISHED, record_count=len(values))
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(dataset_batches).values(self._batch_values(published)))
                connection.execute(insert(bars), [self._bar_values(x) for x in values])
                connection.execute(insert(market_data_events).values(self._event_values(event)))
        except IntegrityError as exc:
            raise RepositoryConflict(str(exc.orig)) from exc

    def save_factors(self, batch: DatasetBatch, values: Sequence[AdjustmentFactor], event: MarketDataEvent) -> None:
        published = replace(batch, status=BatchStatus.PUBLISHED, record_count=len(values))
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(dataset_batches).values(self._batch_values(published)))
                connection.execute(insert(adjustment_factors), [self._factor_values(x) for x in values])
                connection.execute(insert(market_data_events).values(self._event_values(event)))
        except IntegrityError as exc:
            raise RepositoryConflict(str(exc.orig)) from exc

    def create_snapshot(self, snapshot: DatasetSnapshot) -> None:
        try:
            with self.engine.begin() as connection:
                statuses = connection.execute(select(dataset_batches.c.status).where(dataset_batches.c.batch_id.in_(snapshot.batch_ids))).scalars().all()
                if len(statuses) != len(snapshot.batch_ids) or any(x != BatchStatus.PUBLISHED.value for x in statuses):
                    raise RepositoryConflict("snapshot may contain only published batches")
                connection.execute(insert(snapshots).values(snapshot_id=snapshot.snapshot_id, content_hash=snapshot.content_hash, created_at=snapshot.created_at))
                connection.execute(insert(snapshot_batches), [{"snapshot_id": snapshot.snapshot_id, "batch_id": x} for x in snapshot.batch_ids])
        except IntegrityError as exc:
            raise RepositoryConflict(str(exc.orig)) from exc

    def get_snapshot(self, snapshot_id: UUID) -> DatasetSnapshot | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(snapshots).where(snapshots.c.snapshot_id == snapshot_id)).mappings().one_or_none()
            if row is None:
                return None
            batch_ids = connection.execute(select(snapshot_batches.c.batch_id).where(snapshot_batches.c.snapshot_id == snapshot_id)).scalars().all()
        return DatasetSnapshot(tuple(batch_ids), row["content_hash"], self._aware(row["created_at"]), row["snapshot_id"])

    def bars_for_snapshot(self, snapshot_id: UUID) -> Sequence[Bar]:
        if self.get_snapshot(snapshot_id) is None:
            raise SnapshotNotFound(str(snapshot_id))
        with self.engine.connect() as connection:
            rows = connection.execute(select(bars).join(snapshot_batches, bars.c.batch_id == snapshot_batches.c.batch_id).where(snapshot_batches.c.snapshot_id == snapshot_id)).mappings().all()
        return tuple(self._bar(x) for x in rows)

    def factors_for_snapshot(self, snapshot_id: UUID) -> Sequence[AdjustmentFactor]:
        if self.get_snapshot(snapshot_id) is None:
            raise SnapshotNotFound(str(snapshot_id))
        with self.engine.connect() as connection:
            rows = connection.execute(select(adjustment_factors).join(snapshot_batches, adjustment_factors.c.batch_id == snapshot_batches.c.batch_id).where(snapshot_batches.c.snapshot_id == snapshot_id)).mappings().all()
        return tuple(self._factor(x) for x in rows)

    def quality_results(self, batch_id: UUID) -> Sequence[DataQualityResult]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(quality_results).where(quality_results.c.batch_id == batch_id)).mappings().all()
        return tuple(DataQualityResult(x["rule"], QualitySeverity(x["severity"]), x["message"], x["record_index"], x["result_id"]) for x in rows)

    @staticmethod
    def _aware(value):
        from datetime import timezone
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @staticmethod
    def _batch_values(x: DatasetBatch) -> dict[str, Any]:
        return {"batch_id": x.batch_id, "source": x.source, "checksum": x.checksum, "raw_uri": x.raw_uri, "received_at": x.received_at, "status": x.status.value, "record_count": x.record_count}

    @classmethod
    def _batch(cls, x: RowMapping) -> DatasetBatch:
        return DatasetBatch(x["source"], x["checksum"], x["raw_uri"], cls._aware(x["received_at"]), BatchStatus(x["status"]), x["record_count"], x["batch_id"])

    @staticmethod
    def _bar_values(x: Bar) -> dict[str, Any]:
        return {name: getattr(x, name) for name in ("bar_id", "batch_id", "instrument_id", "trading_date", "bar_end_at", "available_at", "open", "high", "low", "close", "volume", "turnover", "revision")} | {"frequency": x.frequency.value}

    @classmethod
    def _bar(cls, x: RowMapping) -> Bar:
        return Bar(x["instrument_id"], BarFrequency(x["frequency"]), x["trading_date"], cls._aware(x["bar_end_at"]), cls._aware(x["available_at"]), Decimal(x["open"]), Decimal(x["high"]), Decimal(x["low"]), Decimal(x["close"]), None if x["volume"] is None else Decimal(x["volume"]), None if x["turnover"] is None else Decimal(x["turnover"]), x["batch_id"], x["revision"], x["bar_id"])

    @staticmethod
    def _factor_values(x: AdjustmentFactor) -> dict[str, Any]:
        return {name: getattr(x, name) for name in ("factor_id", "batch_id", "instrument_id", "trading_date", "factor", "factor_version", "definition", "available_at")}

    @classmethod
    def _factor(cls, x: RowMapping) -> AdjustmentFactor:
        return AdjustmentFactor(x["instrument_id"], x["trading_date"], Decimal(x["factor"]), x["factor_version"], x["definition"], cls._aware(x["available_at"]), x["batch_id"], x["factor_id"])

    @staticmethod
    def _quality_values(batch_id: UUID, x: DataQualityResult) -> dict[str, Any]:
        return {"result_id": x.result_id, "batch_id": batch_id, "rule": x.rule, "severity": x.severity.value, "message": x.message, "record_index": x.record_index}

    @staticmethod
    def _event_values(x: MarketDataEvent) -> dict[str, Any]:
        return {"event_id": x.event_id, "event_type": x.event_type, "batch_id": x.batch_id, "occurred_at": x.occurred_at, "payload": dict(x.payload)}

