"""Point-in-time market-data domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID, uuid4

from .errors import InvalidMarketData


class BarFrequency(StrEnum):
    DAY = "1d"
    MINUTE = "1m"


class PriceMode(StrEnum):
    RAW = "RAW"
    QFQ = "QFQ"
    HFQ = "HFQ"


class VolumeUnit(StrEnum):
    SHARES = "SHARES"
    LOTS = "LOTS"


class BatchStatus(StrEnum):
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"


class QualitySeverity(StrEnum):
    WARNING = "WARNING"
    ERROR = "ERROR"


class CorporateActionType(StrEnum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    SPLIT = "SPLIT"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"


class MarketStatusType(StrEnum):
    NORMAL = "NORMAL"
    SUSPENDED = "SUSPENDED"
    LIMIT_UP = "LIMIT_UP"
    LIMIT_DOWN = "LIMIT_DOWN"


def utc_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidMarketData(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def positive_decimal(value: Decimal | str, name: str) -> Decimal:
    result = Decimal(str(value))
    if result <= 0:
        raise InvalidMarketData(f"{name} must be positive")
    return result


@dataclass(frozen=True, slots=True)
class TradingSession:
    exchange: str
    trading_date: date
    opens_at: datetime
    closes_at: datetime
    is_open: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "opens_at", utc_aware(self.opens_at, "opens_at"))
        object.__setattr__(self, "closes_at", utc_aware(self.closes_at, "closes_at"))
        if self.closes_at <= self.opens_at:
            raise InvalidMarketData("session close must follow open")


@dataclass(frozen=True, slots=True)
class Bar:
    instrument_id: UUID
    frequency: BarFrequency
    trading_date: date
    bar_end_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    turnover: Decimal | None
    batch_id: UUID
    revision: str = "1"
    bar_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bar_end_at", utc_aware(self.bar_end_at, "bar_end_at"))
        object.__setattr__(self, "available_at", utc_aware(self.available_at, "available_at"))
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, positive_decimal(getattr(self, name), name))
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close) or self.high < self.low:
            raise InvalidMarketData("OHLC envelope is invalid")
        for name in ("volume", "turnover"):
            value = getattr(self, name)
            if value is not None:
                value = Decimal(str(value))
                if value < 0:
                    raise InvalidMarketData(f"{name} must not be negative")
                object.__setattr__(self, name, value)
        if self.available_at < self.bar_end_at:
            raise InvalidMarketData("available_at cannot precede bar_end_at")
        if not self.revision.strip():
            raise InvalidMarketData("revision must not be empty")

    def adjusted(self, multiplier: Decimal) -> "Bar":
        multiplier = positive_decimal(multiplier, "adjustment multiplier")
        return replace(
            self,
            open=self.open * multiplier,
            high=self.high * multiplier,
            low=self.low * multiplier,
            close=self.close * multiplier,
            bar_id=uuid4(),
        )


@dataclass(frozen=True, slots=True)
class RawBarInput:
    source_code: str
    frequency: BarFrequency
    trading_date: date
    bar_end_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    turnover: Decimal | None
    volume_unit: VolumeUnit = VolumeUnit.SHARES
    revision: str = "1"


@dataclass(frozen=True, slots=True)
class CorporateAction:
    instrument_id: UUID
    action_type: CorporateActionType
    ex_date: date
    announced_at: datetime
    available_at: datetime
    source: str
    revision: str
    cash_amount: Decimal | None = None
    ratio: Decimal | None = None
    pay_date: date | None = None
    batch_id: UUID | None = None
    action_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "announced_at", utc_aware(self.announced_at, "announced_at"))
        object.__setattr__(self, "available_at", utc_aware(self.available_at, "available_at"))
        if self.available_at < self.announced_at:
            raise InvalidMarketData("action available_at cannot precede announcement")
        if self.cash_amount is not None and Decimal(str(self.cash_amount)) < 0:
            raise InvalidMarketData("cash_amount must not be negative")
        if self.ratio is not None and Decimal(str(self.ratio)) <= 0:
            raise InvalidMarketData("ratio must be positive")


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    instrument_id: UUID
    trading_date: date
    factor: Decimal
    factor_version: str
    definition: str
    available_at: datetime
    batch_id: UUID | None = None
    factor_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "factor", positive_decimal(self.factor, "factor"))
        object.__setattr__(self, "available_at", utc_aware(self.available_at, "available_at"))
        if not self.factor_version.strip() or not self.definition.strip():
            raise InvalidMarketData("factor version and definition are required")


@dataclass(frozen=True, slots=True)
class MarketStatus:
    instrument_id: UUID
    trading_date: date
    status: MarketStatusType
    available_at: datetime
    reason: str = ""
    batch_id: UUID | None = None
    status_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "available_at", utc_aware(self.available_at, "available_at"))


@dataclass(frozen=True, slots=True)
class DataQualityResult:
    rule: str
    severity: QualitySeverity
    message: str
    record_index: int | None = None
    result_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class DatasetBatch:
    source: str
    checksum: str
    raw_uri: str
    received_at: datetime
    status: BatchStatus = BatchStatus.RECEIVED
    record_count: int = 0
    batch_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", self.source.strip().lower())
        object.__setattr__(self, "received_at", utc_aware(self.received_at, "received_at"))
        if not self.source or not self.checksum.strip() or not self.raw_uri.strip():
            raise InvalidMarketData("source, checksum and raw_uri are required")


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    batch_ids: tuple[UUID, ...]
    content_hash: str
    created_at: datetime
    snapshot_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", utc_aware(self.created_at, "created_at"))
        if not self.batch_ids or len(set(self.batch_ids)) != len(self.batch_ids):
            raise InvalidMarketData("snapshot requires unique published batches")


@dataclass(frozen=True, slots=True)
class MarketDataEvent:
    event_type: str
    batch_id: UUID
    occurred_at: datetime
    payload: Mapping[str, str]
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", utc_aware(self.occurred_at, "occurred_at"))
