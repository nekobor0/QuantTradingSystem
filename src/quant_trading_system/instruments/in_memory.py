"""Thread-safe in-memory adapter used by unit tests and local research."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from threading import RLock
from typing import Sequence
from uuid import UUID

from .domain import (
    DateRange,
    Instrument,
    InstrumentAlias,
    InstrumentEvent,
    LifecyclePeriod,
    SourceRecord,
    TradingSpec,
    normalize_code,
    normalize_source,
)
from .errors import RepositoryConflict, SourceRecordConflict, ValidityOverlap


class InMemoryInstrumentRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self.instruments: dict[UUID, Instrument] = {}
        self.aliases: dict[UUID, InstrumentAlias] = {}
        self.trading_specs: dict[UUID, TradingSpec] = {}
        self.lifecycle_periods: dict[UUID, LifecyclePeriod] = {}
        self.source_records: dict[tuple[str, str, str], SourceRecord] = {}
        self.events: dict[UUID, InstrumentEvent] = {}

    def get_instrument(self, instrument_id: UUID) -> Instrument | None:
        with self._lock:
            return self.instruments.get(instrument_id)

    def get_source_record(self, source: str, source_record_id: str, revision: str) -> SourceRecord | None:
        key = normalize_source(source), source_record_id.strip(), revision.strip()
        with self._lock:
            return self.source_records.get(key)

    def resolve_aliases(self, source: str, code: str, as_of: date) -> Sequence[InstrumentAlias]:
        normalized_source = normalize_source(source)
        normalized_code = normalize_code(code)
        with self._lock:
            return tuple(
                alias
                for alias in self.aliases.values()
                if alias.source == normalized_source
                and alias.code == normalized_code
                and alias.validity.contains(as_of)
            )

    def find_alias_overlaps(self, source: str, code: str, validity: DateRange) -> Sequence[InstrumentAlias]:
        normalized_source = normalize_source(source)
        normalized_code = normalize_code(code)
        with self._lock:
            return tuple(
                alias
                for alias in self.aliases.values()
                if alias.source == normalized_source
                and alias.code == normalized_code
                and alias.validity.overlaps(validity)
            )

    def get_trading_specs(self, instrument_id: UUID, as_of: date) -> Sequence[TradingSpec]:
        with self._lock:
            return tuple(
                spec
                for spec in self.trading_specs.values()
                if spec.instrument_id == instrument_id and spec.validity.contains(as_of)
            )

    def get_lifecycle_periods(self, instrument_id: UUID) -> Sequence[LifecyclePeriod]:
        with self._lock:
            periods = [period for period in self.lifecycle_periods.values() if period.instrument_id == instrument_id]
            return tuple(sorted(periods, key=lambda period: period.validity.valid_from))

    def register_bundle(
        self,
        instrument: Instrument,
        aliases: Sequence[InstrumentAlias],
        trading_specs: Sequence[TradingSpec],
        lifecycle_periods: Sequence[LifecyclePeriod],
        source_record: SourceRecord,
        event: InstrumentEvent,
    ) -> None:
        with self._lock:
            if instrument.instrument_id in self.instruments:
                raise RepositoryConflict(f"instrument already exists: {instrument.instrument_id}")
            if source_record.idempotency_key in self.source_records:
                raise SourceRecordConflict(f"source record already exists: {source_record.idempotency_key}")
            self._assert_no_alias_overlaps(aliases)
            self._assert_no_spec_overlaps(trading_specs)
            self._assert_no_lifecycle_overlaps(lifecycle_periods)

            self.instruments[instrument.instrument_id] = instrument
            self.aliases.update({alias.alias_id: alias for alias in aliases})
            self.trading_specs.update({spec.spec_id: spec for spec in trading_specs})
            self.lifecycle_periods.update({period.period_id: period for period in lifecycle_periods})
            self.source_records[source_record.idempotency_key] = source_record
            self.events[event.event_id] = event

    def change_lifecycle(
        self,
        instrument: Instrument,
        previous_period: LifecyclePeriod,
        next_period: LifecyclePeriod,
        event: InstrumentEvent,
    ) -> None:
        with self._lock:
            existing = self.lifecycle_periods.get(previous_period.period_id)
            if existing is None or existing.validity.valid_to is not None:
                raise RepositoryConflict("the active lifecycle period changed concurrently")
            if next_period.validity.valid_from <= existing.validity.valid_from:
                raise ValidityOverlap("next lifecycle period must start after the active period")
            closed = LifecyclePeriod(
                instrument_id=existing.instrument_id,
                status=existing.status,
                validity=DateRange(existing.validity.valid_from, next_period.validity.valid_from),
                reason=existing.reason,
                period_id=existing.period_id,
            )
            other_periods = [
                period
                for period in self.lifecycle_periods.values()
                if period.instrument_id == instrument.instrument_id and period.period_id != existing.period_id
            ]
            if any(period.validity.overlaps(next_period.validity) for period in other_periods):
                raise ValidityOverlap("lifecycle periods overlap")
            self.lifecycle_periods[closed.period_id] = closed
            self.lifecycle_periods[next_period.period_id] = next_period
            self.instruments[instrument.instrument_id] = instrument
            self.events[event.event_id] = event

    def record_revision(
        self,
        instrument: Instrument,
        aliases: Sequence[InstrumentAlias],
        trading_specs: Sequence[TradingSpec],
        source_record: SourceRecord,
        event: InstrumentEvent,
    ) -> None:
        with self._lock:
            if instrument.instrument_id not in self.instruments:
                raise RepositoryConflict(f"unknown instrument: {instrument.instrument_id}")
            if source_record.idempotency_key in self.source_records:
                raise SourceRecordConflict(f"source record already exists: {source_record.idempotency_key}")
            self._assert_no_alias_overlaps(aliases)
            self._assert_no_spec_overlaps(trading_specs)
            self.instruments[instrument.instrument_id] = instrument
            self.aliases.update({alias.alias_id: alias for alias in aliases})
            self.trading_specs.update({spec.spec_id: spec for spec in trading_specs})
            self.source_records[source_record.idempotency_key] = source_record
            self.events[event.event_id] = event

    def change_alias(
        self,
        previous_alias: InstrumentAlias,
        next_alias: InstrumentAlias,
        event: InstrumentEvent,
    ) -> None:
        with self._lock:
            existing = self.aliases.get(previous_alias.alias_id)
            if existing is None or existing.validity.valid_to is not None:
                raise RepositoryConflict("the active alias changed concurrently")
            if next_alias.validity.valid_from <= existing.validity.valid_from:
                raise ValidityOverlap("next alias must start after the active alias")
            closed = InstrumentAlias(
                instrument_id=existing.instrument_id,
                source=existing.source,
                code=existing.code,
                validity=DateRange(existing.validity.valid_from, next_alias.validity.valid_from),
                alias_id=existing.alias_id,
            )
            other_aliases = [alias for alias in self.aliases.values() if alias.alias_id != existing.alias_id]
            for alias in other_aliases:
                if (
                    alias.source == next_alias.source
                    and alias.code == next_alias.code
                    and alias.validity.overlaps(next_alias.validity)
                ):
                    raise ValidityOverlap(f"alias validity overlaps for {next_alias.source}:{next_alias.code}")
            self.aliases[closed.alias_id] = closed
            self.aliases[next_alias.alias_id] = next_alias
            self.events[event.event_id] = event

    def change_trading_spec(
        self,
        previous_spec: TradingSpec,
        next_spec: TradingSpec,
        event: InstrumentEvent,
    ) -> None:
        with self._lock:
            existing = self.trading_specs.get(previous_spec.spec_id)
            if existing is None or existing.validity.valid_to is not None:
                raise RepositoryConflict("the active trading spec changed concurrently")
            if next_spec.validity.valid_from <= existing.validity.valid_from:
                raise ValidityOverlap("next trading spec must start after the active specification")
            closed = TradingSpec(
                instrument_id=existing.instrument_id,
                validity=DateRange(existing.validity.valid_from, next_spec.validity.valid_from),
                lot_size=existing.lot_size,
                tick_size=existing.tick_size,
                min_order_quantity=existing.min_order_quantity,
                max_order_quantity=existing.max_order_quantity,
                spec_id=existing.spec_id,
            )
            other_specs = [spec for spec in self.trading_specs.values() if spec.spec_id != existing.spec_id]
            if any(
                spec.instrument_id == next_spec.instrument_id
                and spec.validity.overlaps(next_spec.validity)
                for spec in other_specs
            ):
                raise ValidityOverlap(f"trading spec validity overlaps for {next_spec.instrument_id}")
            self.trading_specs[closed.spec_id] = closed
            self.trading_specs[next_spec.spec_id] = next_spec
            self.events[event.event_id] = event

    def content_hash(self) -> str:
        with self._lock:
            payload = {
                "instruments": sorted(str(value.instrument_id) for value in self.instruments.values()),
                "aliases": sorted((value.source, value.code, str(value.instrument_id)) for value in self.aliases.values()),
                "specs": sorted(str(value.spec_id) for value in self.trading_specs.values()),
                "periods": sorted(str(value.period_id) for value in self.lifecycle_periods.values()),
                "source_records": sorted(self.source_records),
                "events": sorted(str(value.event_id) for value in self.events.values()),
            }
            return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _assert_no_alias_overlaps(self, aliases: Sequence[InstrumentAlias]) -> None:
        combined = [*self.aliases.values(), *aliases]
        for index, left in enumerate(combined):
            for right in combined[index + 1 :]:
                if left.source == right.source and left.code == right.code and left.validity.overlaps(right.validity):
                    raise ValidityOverlap(f"alias validity overlaps for {left.source}:{left.code}")

    def _assert_no_spec_overlaps(self, specs: Sequence[TradingSpec]) -> None:
        combined = [*self.trading_specs.values(), *specs]
        for index, left in enumerate(combined):
            for right in combined[index + 1 :]:
                if left.instrument_id == right.instrument_id and left.validity.overlaps(right.validity):
                    raise ValidityOverlap(f"trading spec validity overlaps for {left.instrument_id}")

    def _assert_no_lifecycle_overlaps(self, periods: Sequence[LifecyclePeriod]) -> None:
        combined = [*self.lifecycle_periods.values(), *periods]
        for index, left in enumerate(combined):
            for right in combined[index + 1 :]:
                if left.instrument_id == right.instrument_id and left.validity.overlaps(right.validity):
                    raise ValidityOverlap(f"lifecycle validity overlaps for {left.instrument_id}")
