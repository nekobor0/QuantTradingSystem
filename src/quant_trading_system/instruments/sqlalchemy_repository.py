"""SQLAlchemy Core repository; production schema is PostgreSQL."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import Engine, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import RowMapping

from .domain import (
    AssetType,
    Board,
    DateRange,
    Exchange,
    Instrument,
    InstrumentAlias,
    InstrumentEvent,
    LifecyclePeriod,
    LifecycleStatus,
    SourceRecord,
    TradingSpec,
    normalize_code,
    normalize_source,
)
from .errors import RepositoryConflict
from .tables import (
    instrument_aliases,
    instrument_events,
    instruments,
    lifecycle_periods,
    source_records,
    trading_specs,
)


class SqlAlchemyInstrumentRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_instrument(self, instrument_id: UUID) -> Instrument | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(instruments).where(instruments.c.instrument_id == instrument_id)
            ).mappings().one_or_none()
        return self._instrument(row) if row else None

    def get_source_record(self, source: str, source_record_id: str, revision: str) -> SourceRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(source_records).where(
                    source_records.c.source == normalize_source(source),
                    source_records.c.source_record_id == source_record_id.strip(),
                    source_records.c.revision == revision.strip(),
                )
            ).mappings().one_or_none()
        return self._source_record(row) if row else None

    def resolve_aliases(self, source: str, code: str, as_of: date) -> Sequence[InstrumentAlias]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(instrument_aliases).where(
                    instrument_aliases.c.source == normalize_source(source),
                    instrument_aliases.c.code == normalize_code(code),
                    instrument_aliases.c.valid_from <= as_of,
                    or_(instrument_aliases.c.valid_to.is_(None), instrument_aliases.c.valid_to > as_of),
                )
            ).mappings().all()
        return tuple(self._alias(row) for row in rows)

    def find_alias_overlaps(self, source: str, code: str, validity: DateRange) -> Sequence[InstrumentAlias]:
        end = validity.valid_to or date.max
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(instrument_aliases).where(
                    instrument_aliases.c.source == normalize_source(source),
                    instrument_aliases.c.code == normalize_code(code),
                    instrument_aliases.c.valid_from < end,
                    or_(instrument_aliases.c.valid_to.is_(None), instrument_aliases.c.valid_to > validity.valid_from),
                )
            ).mappings().all()
        return tuple(self._alias(row) for row in rows)

    def get_trading_specs(self, instrument_id: UUID, as_of: date) -> Sequence[TradingSpec]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(trading_specs).where(
                    trading_specs.c.instrument_id == instrument_id,
                    trading_specs.c.valid_from <= as_of,
                    or_(trading_specs.c.valid_to.is_(None), trading_specs.c.valid_to > as_of),
                )
            ).mappings().all()
        return tuple(self._trading_spec(row) for row in rows)

    def get_lifecycle_periods(self, instrument_id: UUID) -> Sequence[LifecyclePeriod]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(lifecycle_periods)
                .where(lifecycle_periods.c.instrument_id == instrument_id)
                .order_by(lifecycle_periods.c.valid_from)
            ).mappings().all()
        return tuple(self._lifecycle_period(row) for row in rows)

    def register_bundle(
        self,
        instrument: Instrument,
        aliases: Sequence[InstrumentAlias],
        trading_spec_values: Sequence[TradingSpec],
        lifecycle_period_values: Sequence[LifecyclePeriod],
        source_record: SourceRecord,
        event: InstrumentEvent,
    ) -> None:
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(instruments).values(self._instrument_values(instrument)))
                connection.execute(insert(instrument_aliases), [self._alias_values(value) for value in aliases])
                connection.execute(insert(trading_specs), [self._spec_values(value) for value in trading_spec_values])
                connection.execute(
                    insert(lifecycle_periods),
                    [self._lifecycle_values(value) for value in lifecycle_period_values],
                )
                connection.execute(insert(source_records).values(self._source_values(source_record)))
                connection.execute(insert(instrument_events).values(self._event_values(event)))
        except IntegrityError as exc:
            raise RepositoryConflict(f"instrument bundle violates a database constraint: {exc.orig}") from exc

    def change_lifecycle(
        self,
        instrument: Instrument,
        previous_period: LifecyclePeriod,
        next_period: LifecyclePeriod,
        event: InstrumentEvent,
    ) -> None:
        try:
            with self.engine.begin() as connection:
                active = connection.execute(
                    select(lifecycle_periods.c.period_id).where(
                        lifecycle_periods.c.period_id == previous_period.period_id,
                        lifecycle_periods.c.valid_to.is_(None),
                    )
                ).scalar_one_or_none()
                if active is None:
                    raise RepositoryConflict("the active lifecycle period changed concurrently")
                connection.execute(
                    update(lifecycle_periods)
                    .where(lifecycle_periods.c.period_id == previous_period.period_id)
                    .values(valid_to=next_period.validity.valid_from)
                )
                connection.execute(insert(lifecycle_periods).values(self._lifecycle_values(next_period)))
                connection.execute(
                    update(instruments)
                    .where(instruments.c.instrument_id == instrument.instrument_id)
                    .values(
                        lifecycle_status=instrument.lifecycle_status.value,
                        delist_date=instrument.delist_date,
                    )
                )
                connection.execute(insert(instrument_events).values(self._event_values(event)))
        except IntegrityError as exc:
            raise RepositoryConflict(f"lifecycle change violates a database constraint: {exc.orig}") from exc

    def record_revision(
        self,
        instrument: Instrument,
        aliases: Sequence[InstrumentAlias],
        trading_spec_values: Sequence[TradingSpec],
        source_record: SourceRecord,
        event: InstrumentEvent,
    ) -> None:
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(instruments)
                    .where(instruments.c.instrument_id == instrument.instrument_id)
                    .values(name=instrument.name)
                )
                if result.rowcount != 1:
                    raise RepositoryConflict(f"unknown instrument: {instrument.instrument_id}")
                if aliases:
                    connection.execute(insert(instrument_aliases), [self._alias_values(value) for value in aliases])
                if trading_spec_values:
                    connection.execute(
                        insert(trading_specs),
                        [self._spec_values(value) for value in trading_spec_values],
                    )
                connection.execute(insert(source_records).values(self._source_values(source_record)))
                connection.execute(insert(instrument_events).values(self._event_values(event)))
        except IntegrityError as exc:
            raise RepositoryConflict(f"instrument revision violates a database constraint: {exc.orig}") from exc

    def change_alias(
        self,
        previous_alias: InstrumentAlias,
        next_alias: InstrumentAlias,
        event: InstrumentEvent,
    ) -> None:
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(instrument_aliases)
                    .where(
                        instrument_aliases.c.alias_id == previous_alias.alias_id,
                        instrument_aliases.c.valid_to.is_(None),
                    )
                    .values(valid_to=next_alias.validity.valid_from)
                )
                if result.rowcount != 1:
                    raise RepositoryConflict("the active alias changed concurrently")
                connection.execute(insert(instrument_aliases).values(self._alias_values(next_alias)))
                connection.execute(insert(instrument_events).values(self._event_values(event)))
        except IntegrityError as exc:
            raise RepositoryConflict(f"alias change violates a database constraint: {exc.orig}") from exc

    def change_trading_spec(
        self,
        previous_spec: TradingSpec,
        next_spec: TradingSpec,
        event: InstrumentEvent,
    ) -> None:
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(trading_specs)
                    .where(
                        trading_specs.c.spec_id == previous_spec.spec_id,
                        trading_specs.c.valid_to.is_(None),
                    )
                    .values(valid_to=next_spec.validity.valid_from)
                )
                if result.rowcount != 1:
                    raise RepositoryConflict("the active trading spec changed concurrently")
                connection.execute(insert(trading_specs).values(self._spec_values(next_spec)))
                connection.execute(insert(instrument_events).values(self._event_values(event)))
        except IntegrityError as exc:
            raise RepositoryConflict(f"trading spec change violates a database constraint: {exc.orig}") from exc

    @staticmethod
    def _instrument_values(value: Instrument) -> dict[str, Any]:
        return {
            "instrument_id": value.instrument_id,
            "asset_type": value.asset_type.value,
            "exchange": value.exchange.value,
            "board": value.board.value,
            "currency": value.currency,
            "name": value.name,
            "list_date": value.list_date,
            "delist_date": value.delist_date,
            "lifecycle_status": value.lifecycle_status.value,
            "created_at": value.created_at,
        }

    @staticmethod
    def _alias_values(value: InstrumentAlias) -> dict[str, Any]:
        return {
            "alias_id": value.alias_id,
            "instrument_id": value.instrument_id,
            "source": value.source,
            "code": value.code,
            "valid_from": value.validity.valid_from,
            "valid_to": value.validity.valid_to,
        }

    @staticmethod
    def _spec_values(value: TradingSpec) -> dict[str, Any]:
        return {
            "spec_id": value.spec_id,
            "instrument_id": value.instrument_id,
            "valid_from": value.validity.valid_from,
            "valid_to": value.validity.valid_to,
            "lot_size": value.lot_size,
            "tick_size": value.tick_size,
            "min_order_quantity": value.min_order_quantity,
            "max_order_quantity": value.max_order_quantity,
        }

    @staticmethod
    def _lifecycle_values(value: LifecyclePeriod) -> dict[str, Any]:
        return {
            "period_id": value.period_id,
            "instrument_id": value.instrument_id,
            "status": value.status.value,
            "valid_from": value.validity.valid_from,
            "valid_to": value.validity.valid_to,
            "reason": value.reason,
        }

    @staticmethod
    def _source_values(value: SourceRecord) -> dict[str, Any]:
        return {
            "source": value.source,
            "source_record_id": value.source_record_id,
            "revision": value.revision,
            "payload_hash": value.payload_hash,
            "instrument_id": value.instrument_id,
            "batch_id": value.batch_id,
            "raw_payload": dict(value.raw_payload),
            "recorded_at": value.recorded_at,
        }

    @staticmethod
    def _event_values(value: InstrumentEvent) -> dict[str, Any]:
        return {
            "event_id": value.event_id,
            "event_type": value.event_type,
            "instrument_id": value.instrument_id,
            "occurred_at": value.occurred_at,
            "payload": dict(value.payload),
        }

    @staticmethod
    def _instrument(row: RowMapping) -> Instrument:
        return Instrument(
            instrument_id=row["instrument_id"],
            asset_type=AssetType(row["asset_type"]),
            exchange=Exchange(row["exchange"]),
            board=Board(row["board"]),
            currency=row["currency"],
            name=row["name"],
            list_date=row["list_date"],
            delist_date=row["delist_date"],
            lifecycle_status=LifecycleStatus(row["lifecycle_status"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _alias(row: RowMapping) -> InstrumentAlias:
        return InstrumentAlias(
            alias_id=row["alias_id"],
            instrument_id=row["instrument_id"],
            source=row["source"],
            code=row["code"],
            validity=DateRange(row["valid_from"], row["valid_to"]),
        )

    @staticmethod
    def _trading_spec(row: RowMapping) -> TradingSpec:
        return TradingSpec(
            spec_id=row["spec_id"],
            instrument_id=row["instrument_id"],
            validity=DateRange(row["valid_from"], row["valid_to"]),
            lot_size=row["lot_size"],
            tick_size=Decimal(row["tick_size"]),
            min_order_quantity=row["min_order_quantity"],
            max_order_quantity=row["max_order_quantity"],
        )

    @staticmethod
    def _lifecycle_period(row: RowMapping) -> LifecyclePeriod:
        return LifecyclePeriod(
            period_id=row["period_id"],
            instrument_id=row["instrument_id"],
            status=LifecycleStatus(row["status"]),
            validity=DateRange(row["valid_from"], row["valid_to"]),
            reason=row["reason"],
        )

    @staticmethod
    def _source_record(row: RowMapping) -> SourceRecord:
        return SourceRecord(
            source=row["source"],
            source_record_id=row["source_record_id"],
            revision=row["revision"],
            payload_hash=row["payload_hash"],
            instrument_id=row["instrument_id"],
            batch_id=row["batch_id"],
            raw_payload=row["raw_payload"],
            recorded_at=row["recorded_at"],
        )
