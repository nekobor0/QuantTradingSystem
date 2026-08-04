"""Read-through instrument cache for large historical TdxQuant batches."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from quant_trading_system.instruments import (
    Instrument,
    InstrumentAlias,
    InstrumentService,
    LifecyclePeriod,
    ResolvedInstrument,
)
from quant_trading_system.instruments.domain import DateRange
from quant_trading_system.instruments.errors import AliasAmbiguous, InstrumentNotFound, ValidityOverlap
from quant_trading_system.instruments.sqlalchemy_repository import SqlAlchemyInstrumentRepository


class CachedInstrumentService(InstrumentService):
    """Preserve InstrumentService semantics without querying once per historical bar."""

    def __init__(self, repository: SqlAlchemyInstrumentRepository) -> None:
        super().__init__(repository)
        self.repository = repository
        self._aliases: dict[tuple[str, str], tuple[InstrumentAlias, ...]] = {}
        self._instruments: dict[UUID, Instrument] = {}
        self._lifecycles: dict[UUID, tuple[LifecyclePeriod, ...]] = {}

    def resolve(self, source: str, code: str, as_of: date) -> ResolvedInstrument:
        key = (source.strip().lower(), code.strip().upper())
        aliases = self._aliases.get(key)
        if aliases is None:
            aliases = tuple(
                self.repository.find_alias_overlaps(
                    key[0], key[1], DateRange(date.min, None)
                )
            )
            self._aliases[key] = aliases
        active = [value for value in aliases if value.validity.contains(as_of)]
        if not active:
            raise InstrumentNotFound(f"no instrument for {key[0]}:{key[1]} at {as_of}")
        instrument_ids = {value.instrument_id for value in active}
        if len(active) != 1 or len(instrument_ids) != 1:
            raise AliasAmbiguous(f"multiple instruments for {key[0]}:{key[1]} at {as_of}")
        instrument_id = next(iter(instrument_ids))
        instrument = self._instruments.get(instrument_id)
        if instrument is None:
            instrument = self.repository.get_instrument(instrument_id)
            if instrument is None:
                raise InstrumentNotFound("alias points to a missing instrument")
            self._instruments[instrument_id] = instrument
        periods = self._lifecycles.get(instrument_id)
        if periods is None:
            periods = tuple(self.repository.get_lifecycle_periods(instrument_id))
            self._lifecycles[instrument_id] = periods
        current = [value for value in periods if value.validity.contains(as_of)]
        if len(current) > 1:
            raise ValidityOverlap(f"multiple lifecycle periods for {instrument_id} at {as_of}")
        tradable = bool(
            instrument.within_listing_dates(as_of)
            and current
            and current[0].status.value == "LISTED"
        )
        return ResolvedInstrument(instrument, tradable)
