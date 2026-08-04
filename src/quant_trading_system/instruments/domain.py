"""Domain model for canonical instruments and time-valid attributes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID, uuid4

from .errors import InvalidDateRange, InvalidInstrument, InvalidTradingSpec


class AssetType(StrEnum):
    A_SHARE = "A_SHARE"
    HK_STOCK_CONNECT_ELIGIBLE_SECURITY = "HK_STOCK_CONNECT_ELIGIBLE_SECURITY"
    ETF_DOMESTIC = "ETF_DOMESTIC"
    ETF_OVERSEAS_LINKED = "ETF_OVERSEAS_LINKED"


class Exchange(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"
    HKEX = "HKEX"


class Board(StrEnum):
    SH_MAIN = "SH_MAIN"
    SZ_MAIN = "SZ_MAIN"
    CHINEXT = "CHINEXT"
    STAR = "STAR"
    BSE = "BSE"
    HK_MAIN = "HK_MAIN"
    ETF = "ETF"


class LifecycleStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    LISTED = "LISTED"
    DELISTED = "DELISTED"


@dataclass(frozen=True, slots=True)
class DateRange:
    valid_from: date
    valid_to: date | None = None

    def __post_init__(self) -> None:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise InvalidDateRange("valid_to must be later than valid_from")

    def contains(self, value: date) -> bool:
        return self.valid_from <= value and (self.valid_to is None or value < self.valid_to)

    def overlaps(self, other: "DateRange") -> bool:
        self_end = self.valid_to or date.max
        other_end = other.valid_to or date.max
        return self.valid_from < other_end and other.valid_from < self_end


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InvalidInstrument(f"{field_name} must not be empty")
    return normalized


def normalize_source(value: str) -> str:
    return _required_text(value, "source").lower()


def normalize_code(value: str) -> str:
    return _required_text(value, "code").upper()


@dataclass(frozen=True, slots=True)
class Instrument:
    asset_type: AssetType
    exchange: Exchange
    board: Board
    currency: str
    name: str
    list_date: date
    delist_date: date | None = None
    lifecycle_status: LifecycleStatus = LifecycleStatus.CANDIDATE
    instrument_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _required_text(self.currency, "currency").upper())
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        if len(self.currency) != 3:
            raise InvalidInstrument("currency must be a three-letter code")
        if self.delist_date is not None and self.delist_date < self.list_date:
            raise InvalidInstrument("delist_date must not precede list_date")
        if self.lifecycle_status is LifecycleStatus.DELISTED and self.delist_date is None:
            raise InvalidInstrument("a delisted instrument requires delist_date")
        if self.delist_date is not None and self.lifecycle_status is not LifecycleStatus.DELISTED:
            raise InvalidInstrument("delist_date is only valid when lifecycle_status is DELISTED")
        allowed_boards = {
            Exchange.SSE: {Board.SH_MAIN, Board.STAR, Board.ETF},
            Exchange.SZSE: {Board.SZ_MAIN, Board.CHINEXT, Board.ETF},
            Exchange.BSE: {Board.BSE},
            Exchange.HKEX: {Board.HK_MAIN},
        }
        if self.board not in allowed_boards[self.exchange]:
            raise InvalidInstrument(f"board {self.board} is not valid for exchange {self.exchange}")
        is_etf = self.asset_type in {AssetType.ETF_DOMESTIC, AssetType.ETF_OVERSEAS_LINKED}
        if is_etf != (self.board is Board.ETF):
            raise InvalidInstrument("ETF asset types must use the ETF board, and vice versa")
        if self.asset_type is AssetType.HK_STOCK_CONNECT_ELIGIBLE_SECURITY and self.exchange is not Exchange.HKEX:
            raise InvalidInstrument("HK stock connect securities must use HKEX")

    def within_listing_dates(self, as_of: date) -> bool:
        return self.list_date <= as_of and (self.delist_date is None or as_of < self.delist_date)


@dataclass(frozen=True, slots=True)
class InstrumentAlias:
    instrument_id: UUID
    source: str
    code: str
    validity: DateRange
    alias_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", normalize_source(self.source))
        object.__setattr__(self, "code", normalize_code(self.code))


@dataclass(frozen=True, slots=True)
class TradingSpec:
    instrument_id: UUID
    validity: DateRange
    lot_size: int
    tick_size: Decimal
    min_order_quantity: int
    max_order_quantity: int | None = None
    spec_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        tick_size = Decimal(str(self.tick_size))
        object.__setattr__(self, "tick_size", tick_size)
        if self.lot_size <= 0:
            raise InvalidTradingSpec("lot_size must be positive")
        if tick_size <= 0:
            raise InvalidTradingSpec("tick_size must be positive")
        if self.min_order_quantity <= 0:
            raise InvalidTradingSpec("min_order_quantity must be positive")
        if self.max_order_quantity is not None and self.max_order_quantity < self.min_order_quantity:
            raise InvalidTradingSpec("max_order_quantity must be at least min_order_quantity")


@dataclass(frozen=True, slots=True)
class LifecyclePeriod:
    instrument_id: UUID
    status: LifecycleStatus
    validity: DateRange
    reason: str
    period_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _required_text(self.reason, "reason"))


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source: str
    source_record_id: str
    revision: str
    payload_hash: str
    instrument_id: UUID
    batch_id: str
    raw_payload: Mapping[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", normalize_source(self.source))
        object.__setattr__(self, "source_record_id", _required_text(self.source_record_id, "source_record_id"))
        object.__setattr__(self, "revision", _required_text(self.revision, "revision"))
        object.__setattr__(self, "payload_hash", _required_text(self.payload_hash, "payload_hash"))
        object.__setattr__(self, "batch_id", _required_text(self.batch_id, "batch_id"))

    @property
    def idempotency_key(self) -> tuple[str, str, str]:
        return self.source, self.source_record_id, self.revision


@dataclass(frozen=True, slots=True)
class InstrumentEvent:
    event_type: str
    instrument_id: UUID
    occurred_at: datetime
    payload: Mapping[str, Any]
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", _required_text(self.event_type, "event_type"))
        if self.occurred_at.tzinfo is None:
            raise InvalidInstrument("occurred_at must be timezone-aware")
