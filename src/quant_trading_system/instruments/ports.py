"""Persistence port for the instruments application service."""

from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence
from uuid import UUID

from .domain import (
    DateRange,
    Instrument,
    InstrumentAlias,
    InstrumentEvent,
    LifecyclePeriod,
    SourceRecord,
    TradingSpec,
)


class InstrumentRepository(Protocol):
    def get_instrument(self, instrument_id: UUID) -> Instrument | None: ...

    def get_source_record(self, source: str, source_record_id: str, revision: str) -> SourceRecord | None: ...

    def resolve_aliases(self, source: str, code: str, as_of: date) -> Sequence[InstrumentAlias]: ...

    def find_alias_overlaps(self, source: str, code: str, validity: DateRange) -> Sequence[InstrumentAlias]: ...

    def get_trading_specs(self, instrument_id: UUID, as_of: date) -> Sequence[TradingSpec]: ...

    def get_lifecycle_periods(self, instrument_id: UUID) -> Sequence[LifecyclePeriod]: ...

    def register_bundle(
        self,
        instrument: Instrument,
        aliases: Sequence[InstrumentAlias],
        trading_specs: Sequence[TradingSpec],
        lifecycle_periods: Sequence[LifecyclePeriod],
        source_record: SourceRecord,
        event: InstrumentEvent,
    ) -> None: ...

    def change_lifecycle(
        self,
        instrument: Instrument,
        previous_period: LifecyclePeriod,
        next_period: LifecyclePeriod,
        event: InstrumentEvent,
    ) -> None: ...

    def record_revision(
        self,
        instrument: Instrument,
        aliases: Sequence[InstrumentAlias],
        trading_specs: Sequence[TradingSpec],
        source_record: SourceRecord,
        event: InstrumentEvent,
    ) -> None: ...

    def change_alias(
        self,
        previous_alias: InstrumentAlias,
        next_alias: InstrumentAlias,
        event: InstrumentEvent,
    ) -> None: ...

    def change_trading_spec(
        self,
        previous_spec: TradingSpec,
        next_spec: TradingSpec,
        event: InstrumentEvent,
    ) -> None: ...
