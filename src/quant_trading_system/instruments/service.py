"""Application service for canonical instrument registration and queries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

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
)
from .errors import (
    AliasAmbiguous,
    InstrumentNotFound,
    InvalidInstrument,
    InvalidLifecycleTransition,
    SourceRecordConflict,
    TradingSpecNotFound,
    ValidityOverlap,
)
from .ports import InstrumentRepository


@dataclass(frozen=True, slots=True)
class AliasInput:
    source: str
    code: str
    valid_from: date
    valid_to: date | None = None


@dataclass(frozen=True, slots=True)
class TradingSpecInput:
    valid_from: date
    lot_size: int
    tick_size: Decimal
    min_order_quantity: int
    max_order_quantity: int | None = None
    valid_to: date | None = None


@dataclass(frozen=True, slots=True)
class RegisterInstrumentCommand:
    source: str
    source_record_id: str
    revision: str
    batch_id: str
    asset_type: AssetType
    exchange: Exchange
    board: Board
    currency: str
    name: str
    list_date: date
    aliases: tuple[AliasInput, ...]
    trading_specs: tuple[TradingSpecInput, ...]
    initial_status: LifecycleStatus = LifecycleStatus.LISTED
    delist_date: date | None = None
    status_effective_from: date | None = None
    raw_payload: Mapping[str, Any] | None = None
    instrument_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ChangeLifecycleCommand:
    instrument_id: UUID
    next_status: LifecycleStatus
    effective_from: date
    reason: str


@dataclass(frozen=True, slots=True)
class ChangeAliasCommand:
    instrument_id: UUID
    source: str
    old_code: str
    new_code: str
    effective_from: date
    reason: str


@dataclass(frozen=True, slots=True)
class ChangeTradingSpecCommand:
    instrument_id: UUID
    effective_from: date
    lot_size: int
    tick_size: Decimal
    min_order_quantity: int
    max_order_quantity: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedInstrument:
    instrument: Instrument
    tradable: bool


class InstrumentService:
    _TRANSITIONS = {
        LifecycleStatus.CANDIDATE: LifecycleStatus.LISTED,
        LifecycleStatus.LISTED: LifecycleStatus.DELISTED,
    }

    def __init__(self, repository: InstrumentRepository) -> None:
        self.repository = repository

    def register(self, command: RegisterInstrumentCommand) -> Instrument:
        payload_hash = self._command_hash(command)
        existing_record = self.repository.get_source_record(
            command.source, command.source_record_id, command.revision
        )
        if existing_record is not None:
            if existing_record.payload_hash != payload_hash:
                raise SourceRecordConflict("the idempotency key already exists with different content")
            instrument = self.repository.get_instrument(existing_record.instrument_id)
            if instrument is None:
                raise InstrumentNotFound("source record points to a missing instrument")
            return instrument

        if command.instrument_id is not None:
            existing_instrument = self.repository.get_instrument(command.instrument_id)
            if existing_instrument is not None:
                return self._record_revision(existing_instrument, command, payload_hash)

        instrument = Instrument(
            instrument_id=command.instrument_id or uuid4(),
            asset_type=command.asset_type,
            exchange=command.exchange,
            board=command.board,
            currency=command.currency,
            name=command.name,
            list_date=command.list_date,
            delist_date=command.delist_date,
            lifecycle_status=command.initial_status,
        )
        aliases = tuple(
            InstrumentAlias(
                instrument_id=instrument.instrument_id,
                source=value.source,
                code=value.code,
                validity=DateRange(value.valid_from, value.valid_to),
            )
            for value in command.aliases
        )
        if not aliases:
            raise InvalidInstrument("at least one explicit alias is required")
        self._assert_new_aliases_do_not_overlap(aliases)

        specs = tuple(
            TradingSpec(
                instrument_id=instrument.instrument_id,
                validity=DateRange(value.valid_from, value.valid_to),
                lot_size=value.lot_size,
                tick_size=value.tick_size,
                min_order_quantity=value.min_order_quantity,
                max_order_quantity=value.max_order_quantity,
            )
            for value in command.trading_specs
        )
        if not specs:
            raise InvalidInstrument("at least one trading spec is required")
        self._assert_ranges_do_not_overlap([spec.validity for spec in specs], "trading specs")

        lifecycle_periods = self._initial_lifecycle_periods(instrument, command.status_effective_from)
        source_record = SourceRecord(
            source=command.source,
            source_record_id=command.source_record_id,
            revision=command.revision,
            payload_hash=payload_hash,
            instrument_id=instrument.instrument_id,
            batch_id=command.batch_id,
            raw_payload=command.raw_payload or {},
        )
        event = InstrumentEvent(
            event_type="InstrumentRegistered",
            instrument_id=instrument.instrument_id,
            occurred_at=datetime.now(timezone.utc),
            payload={"source": source_record.source, "batch_id": source_record.batch_id},
        )
        self.repository.register_bundle(
            instrument, aliases, specs, lifecycle_periods, source_record, event
        )
        return instrument

    def resolve(self, source: str, code: str, as_of: date) -> ResolvedInstrument:
        aliases = self.repository.resolve_aliases(source, code, as_of)
        if not aliases:
            raise InstrumentNotFound(f"no instrument for {source}:{code} at {as_of}")
        instrument_ids = {alias.instrument_id for alias in aliases}
        if len(instrument_ids) != 1 or len(aliases) != 1:
            raise AliasAmbiguous(f"multiple instruments for {source}:{code} at {as_of}")
        instrument = self.repository.get_instrument(next(iter(instrument_ids)))
        if instrument is None:
            raise InstrumentNotFound("alias points to a missing instrument")
        return ResolvedInstrument(instrument, self.is_tradable(instrument.instrument_id, as_of))

    def get_trading_spec(self, instrument_id: UUID, as_of: date) -> TradingSpec:
        if self.repository.get_instrument(instrument_id) is None:
            raise InstrumentNotFound(f"unknown instrument: {instrument_id}")
        specs = self.repository.get_trading_specs(instrument_id, as_of)
        if not specs:
            raise TradingSpecNotFound(f"no trading spec for {instrument_id} at {as_of}")
        if len(specs) > 1:
            raise ValidityOverlap(f"multiple trading specs for {instrument_id} at {as_of}")
        return specs[0]

    def is_tradable(self, instrument_id: UUID, as_of: date) -> bool:
        instrument = self.repository.get_instrument(instrument_id)
        if instrument is None:
            raise InstrumentNotFound(f"unknown instrument: {instrument_id}")
        if not instrument.within_listing_dates(as_of):
            return False
        active = [period for period in self.repository.get_lifecycle_periods(instrument_id) if period.validity.contains(as_of)]
        if len(active) > 1:
            raise ValidityOverlap(f"multiple lifecycle periods for {instrument_id} at {as_of}")
        return bool(active and active[0].status is LifecycleStatus.LISTED)

    def change_lifecycle(self, command: ChangeLifecycleCommand) -> Instrument:
        instrument = self.repository.get_instrument(command.instrument_id)
        if instrument is None:
            raise InstrumentNotFound(f"unknown instrument: {command.instrument_id}")
        expected = self._TRANSITIONS.get(instrument.lifecycle_status)
        if expected is not command.next_status:
            raise InvalidLifecycleTransition(
                f"cannot transition {instrument.lifecycle_status} to {command.next_status}"
            )
        periods = self.repository.get_lifecycle_periods(command.instrument_id)
        active = [period for period in periods if period.validity.valid_to is None]
        if len(active) != 1:
            raise ValidityOverlap("instrument must have exactly one open lifecycle period")
        previous = active[0]
        if command.effective_from <= previous.validity.valid_from:
            raise InvalidLifecycleTransition("transition date must follow the active period start")
        if command.next_status is LifecycleStatus.LISTED and command.effective_from != instrument.list_date:
            raise InvalidLifecycleTransition("LISTED must become effective on list_date")
        next_instrument = replace(
            instrument,
            lifecycle_status=command.next_status,
            delist_date=(command.effective_from if command.next_status is LifecycleStatus.DELISTED else instrument.delist_date),
        )
        next_period = LifecyclePeriod(
            instrument_id=instrument.instrument_id,
            status=command.next_status,
            validity=DateRange(command.effective_from, None),
            reason=command.reason,
        )
        event = InstrumentEvent(
            event_type="InstrumentStatusChanged",
            instrument_id=instrument.instrument_id,
            occurred_at=datetime.now(timezone.utc),
            payload={
                "from": previous.status.value,
                "to": command.next_status.value,
                "effective_from": command.effective_from.isoformat(),
                "reason": command.reason,
            },
        )
        self.repository.change_lifecycle(next_instrument, previous, next_period, event)
        return next_instrument

    def change_alias(self, command: ChangeAliasCommand) -> InstrumentAlias:
        instrument = self.repository.get_instrument(command.instrument_id)
        if instrument is None:
            raise InstrumentNotFound(f"unknown instrument: {command.instrument_id}")
        if normalize_code(command.old_code) == normalize_code(command.new_code):
            raise InvalidInstrument("new alias code must differ from old alias code")
        active = self.repository.resolve_aliases(command.source, command.old_code, command.effective_from)
        if len(active) != 1 or active[0].instrument_id != instrument.instrument_id:
            if not active:
                raise InstrumentNotFound("old alias is not active for this instrument")
            raise AliasAmbiguous("old alias does not resolve uniquely to this instrument")
        previous = active[0]
        if command.effective_from <= previous.validity.valid_from:
            raise InvalidInstrument("alias change must follow the old alias start")
        next_alias = InstrumentAlias(
            instrument_id=instrument.instrument_id,
            source=command.source,
            code=command.new_code,
            validity=DateRange(command.effective_from, None),
        )
        conflicts = self.repository.find_alias_overlaps(
            next_alias.source, next_alias.code, next_alias.validity
        )
        if conflicts:
            raise ValidityOverlap(f"new alias already has an overlapping mapping: {next_alias.code}")
        event = InstrumentEvent(
            event_type="InstrumentAliasChanged",
            instrument_id=instrument.instrument_id,
            occurred_at=datetime.now(timezone.utc),
            payload={
                "source": next_alias.source,
                "old_code": previous.code,
                "new_code": next_alias.code,
                "effective_from": command.effective_from.isoformat(),
                "reason": command.reason,
            },
        )
        self.repository.change_alias(previous, next_alias, event)
        return next_alias

    def change_trading_spec(self, command: ChangeTradingSpecCommand) -> TradingSpec:
        instrument = self.repository.get_instrument(command.instrument_id)
        if instrument is None:
            raise InstrumentNotFound(f"unknown instrument: {command.instrument_id}")
        active = self.repository.get_trading_specs(command.instrument_id, command.effective_from)
        if len(active) != 1:
            if not active:
                raise TradingSpecNotFound("no active trading spec to replace")
            raise ValidityOverlap("multiple active trading specs cannot be replaced safely")
        previous = active[0]
        if command.effective_from <= previous.validity.valid_from:
            raise InvalidInstrument("trading spec change must follow the old spec start")
        next_spec = TradingSpec(
            instrument_id=instrument.instrument_id,
            validity=DateRange(command.effective_from, None),
            lot_size=command.lot_size,
            tick_size=command.tick_size,
            min_order_quantity=command.min_order_quantity,
            max_order_quantity=command.max_order_quantity,
        )
        event = InstrumentEvent(
            event_type="TradingSpecChanged",
            instrument_id=instrument.instrument_id,
            occurred_at=datetime.now(timezone.utc),
            payload={
                "effective_from": command.effective_from.isoformat(),
                "lot_size": command.lot_size,
                "tick_size": str(command.tick_size),
                "reason": command.reason,
            },
        )
        self.repository.change_trading_spec(previous, next_spec, event)
        return next_spec

    def _record_revision(
        self,
        instrument: Instrument,
        command: RegisterInstrumentCommand,
        payload_hash: str,
    ) -> Instrument:
        immutable_actual = (
            instrument.asset_type,
            instrument.exchange,
            instrument.board,
            instrument.currency,
            instrument.list_date,
            instrument.delist_date,
            instrument.lifecycle_status,
        )
        immutable_requested = (
            command.asset_type,
            command.exchange,
            command.board,
            command.currency.strip().upper(),
            command.list_date,
            command.delist_date,
            command.initial_status,
        )
        if immutable_actual != immutable_requested:
            raise SourceRecordConflict("a source revision cannot change canonical identity or lifecycle")

        new_aliases: list[InstrumentAlias] = []
        for alias_input in command.aliases:
            candidate_alias = InstrumentAlias(
                instrument_id=instrument.instrument_id,
                source=alias_input.source,
                code=alias_input.code,
                validity=DateRange(alias_input.valid_from, alias_input.valid_to),
            )
            overlaps = self.repository.find_alias_overlaps(
                candidate_alias.source, candidate_alias.code, candidate_alias.validity
            )
            exact_existing = any(
                alias.instrument_id == instrument.instrument_id
                and alias.validity == candidate_alias.validity
                for alias in overlaps
            )
            if not exact_existing:
                if overlaps:
                    raise ValidityOverlap(
                        f"revised alias overlaps an existing mapping: {candidate_alias.code}"
                    )
                new_aliases.append(candidate_alias)

        new_specs: list[TradingSpec] = []
        for spec_input in command.trading_specs:
            candidate_spec = TradingSpec(
                instrument_id=instrument.instrument_id,
                validity=DateRange(spec_input.valid_from, spec_input.valid_to),
                lot_size=spec_input.lot_size,
                tick_size=spec_input.tick_size,
                min_order_quantity=spec_input.min_order_quantity,
                max_order_quantity=spec_input.max_order_quantity,
            )
            existing = self.repository.get_trading_specs(
                instrument.instrument_id, candidate_spec.validity.valid_from
            )
            exact_existing = any(
                spec.validity == candidate_spec.validity
                and spec.lot_size == candidate_spec.lot_size
                and spec.tick_size == candidate_spec.tick_size
                and spec.min_order_quantity == candidate_spec.min_order_quantity
                and spec.max_order_quantity == candidate_spec.max_order_quantity
                for spec in existing
            )
            if not exact_existing:
                if existing:
                    raise ValidityOverlap("revised trading spec overlaps an existing specification")
                new_specs.append(candidate_spec)

        revised = replace(instrument, name=command.name.strip())
        source_record = SourceRecord(
            source=command.source,
            source_record_id=command.source_record_id,
            revision=command.revision,
            payload_hash=payload_hash,
            instrument_id=instrument.instrument_id,
            batch_id=command.batch_id,
            raw_payload=command.raw_payload or {},
        )
        event = InstrumentEvent(
            event_type="InstrumentReferenceDataRevised",
            instrument_id=instrument.instrument_id,
            occurred_at=datetime.now(timezone.utc),
            payload={"source": source_record.source, "revision": source_record.revision},
        )
        self.repository.record_revision(revised, new_aliases, new_specs, source_record, event)
        return revised

    def _initial_lifecycle_periods(
        self, instrument: Instrument, status_effective_from: date | None
    ) -> tuple[LifecyclePeriod, ...]:
        if instrument.lifecycle_status is LifecycleStatus.CANDIDATE:
            start = status_effective_from or date.today()
            if start >= instrument.list_date:
                raise InvalidLifecycleTransition("candidate status must start before list_date")
            return (
                LifecyclePeriod(
                    instrument.instrument_id,
                    LifecycleStatus.CANDIDATE,
                    DateRange(start, None),
                    "initial registration",
                ),
            )
        if instrument.lifecycle_status is LifecycleStatus.LISTED:
            if status_effective_from not in (None, instrument.list_date):
                raise InvalidLifecycleTransition("listed status must start on list_date")
            return (
                LifecyclePeriod(
                    instrument.instrument_id,
                    LifecycleStatus.LISTED,
                    DateRange(instrument.list_date, None),
                    "initial registration",
                ),
            )
        if instrument.delist_date is None:
            raise InvalidLifecycleTransition("historical delisted registration requires delist_date")
        if status_effective_from not in (None, instrument.delist_date):
            raise InvalidLifecycleTransition("delisted status must start on delist_date")
        return (
            LifecyclePeriod(
                instrument.instrument_id,
                LifecycleStatus.LISTED,
                DateRange(instrument.list_date, instrument.delist_date),
                "historical listing",
            ),
            LifecyclePeriod(
                instrument.instrument_id,
                LifecycleStatus.DELISTED,
                DateRange(instrument.delist_date, None),
                "historical delisting",
            ),
        )

    def _assert_new_aliases_do_not_overlap(self, aliases: Sequence[InstrumentAlias]) -> None:
        for index, left in enumerate(aliases):
            for right in aliases[index + 1 :]:
                if left.source == right.source and left.code == right.code and left.validity.overlaps(right.validity):
                    raise ValidityOverlap(f"new aliases overlap for {left.source}:{left.code}")
            if self.repository.find_alias_overlaps(left.source, left.code, left.validity):
                raise ValidityOverlap(f"alias already valid for {left.source}:{left.code}")

    @staticmethod
    def _assert_ranges_do_not_overlap(ranges: Sequence[DateRange], label: str) -> None:
        for index, left in enumerate(ranges):
            for right in ranges[index + 1 :]:
                if left.overlaps(right):
                    raise ValidityOverlap(f"{label} contain overlapping ranges")

    @staticmethod
    def _command_hash(command: RegisterInstrumentCommand) -> str:
        payload = asdict(command)
        payload.pop("instrument_id", None)
        payload["raw_payload"] = command.raw_payload or {}
        encoded = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
