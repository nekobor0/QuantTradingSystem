from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Mapping
from uuid import UUID, uuid4

from quant_trading_system.strategies import CandidateAction, StrategyKind

from .errors import InvalidBacktest


def aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidBacktest(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def dec(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value))


class BacktestRunStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EventPriority(IntEnum):
    CORPORATE_ACTION_SETTLEMENT = 10
    MARKET_BAR = 20
    STRATEGY_DECISION = 30
    PORTFOLIO_NETTING = 40
    ORDER = 50
    FILL = 60
    ACCOUNT = 70
    VALUATION = 80


class MarketState(StrEnum):
    NORMAL = "NORMAL"
    SUSPENDED = "SUSPENDED"
    LIMIT_UP = "LIMIT_UP"
    LIMIT_DOWN = "LIMIT_DOWN"
    DELISTED = "DELISTED"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class SimOrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class SimOrderStatus(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class LedgerKind(StrEnum):
    CASH = "CASH"
    POSITION = "POSITION"
    SETTLEMENT = "SETTLEMENT"
    FEE = "FEE"
    CORPORATE_ACTION = "CORPORATE_ACTION"


@dataclass(frozen=True, slots=True)
class StrategySpec:
    kind: StrategyKind
    version_id: UUID
    parameters_hash: str
    sleeve_budget: Decimal
    decision_frequency: str

    def __post_init__(self):
        object.__setattr__(self, "sleeve_budget", dec(self.sleeve_budget))
        if not self.parameters_hash.strip() or not self.decision_frequency.strip() or not 0 <= self.sleeve_budget <= 1:
            raise InvalidBacktest("invalid strategy spec")


@dataclass(frozen=True, slots=True)
class MarketRule:
    market: str
    version: str
    effective_from: date
    effective_to: date | None
    lot_size: int
    tick_size: Decimal
    settlement_days: int
    price_limit_ratio: Decimal | None = None
    rule_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        object.__setattr__(self, "tick_size", dec(self.tick_size))
        if self.price_limit_ratio is not None:
            object.__setattr__(self, "price_limit_ratio", dec(self.price_limit_ratio))
        if not self.market.strip() or not self.version.strip() or self.lot_size <= 0 or self.tick_size <= 0 or self.settlement_days < 0:
            raise InvalidBacktest("invalid market rule")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise InvalidBacktest("invalid market rule interval")

    def applies(self, market: str, on_date: date) -> bool:
        return self.market == market and self.effective_from <= on_date and (self.effective_to is None or on_date <= self.effective_to)


@dataclass(frozen=True, slots=True)
class CostRule:
    market: str
    version: str
    effective_from: date
    effective_to: date | None
    commission_rate: Decimal
    minimum_commission: Decimal
    sell_tax_rate: Decimal
    platform_fee_rate: Decimal
    slippage_rate: Decimal
    cost_rule_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        for name in ("commission_rate", "minimum_commission", "sell_tax_rate", "platform_fee_rate", "slippage_rate"):
            object.__setattr__(self, name, dec(getattr(self, name)))
        if not self.market.strip() or not self.version.strip() or any(getattr(self, name) < 0 for name in ("commission_rate", "minimum_commission", "sell_tax_rate", "platform_fee_rate", "slippage_rate")):
            raise InvalidBacktest("invalid cost rule")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise InvalidBacktest("invalid cost rule interval")

    def applies(self, market: str, on_date: date) -> bool:
        return self.market == market and self.effective_from <= on_date and (self.effective_to is None or on_date <= self.effective_to)


@dataclass(frozen=True, slots=True)
class BacktestDefinition:
    name: str
    strategies: tuple[StrategySpec, ...]
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal
    base_currency: str
    data_snapshot_id: UUID
    universe_snapshot_id: UUID
    code_version: str
    random_seed: int
    max_participation: Decimal
    execution_delay_bars: int
    benchmark_id: UUID | None = None
    delisting_policy: str = "FAIL"
    definition_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        object.__setattr__(self, "start_at", aware(self.start_at, "start_at"))
        object.__setattr__(self, "end_at", aware(self.end_at, "end_at"))
        object.__setattr__(self, "initial_cash", dec(self.initial_cash))
        object.__setattr__(self, "max_participation", dec(self.max_participation))
        kinds = {item.kind for item in self.strategies}
        if kinds != {StrategyKind.ETF_TIMING, StrategyKind.EQUITY_DAILY_SELECTION} or len(self.strategies) != 2:
            raise InvalidBacktest("exactly both first-batch strategies are required")
        if sum((item.sleeve_budget for item in self.strategies), Decimal()) > 1:
            raise InvalidBacktest("sleeve budgets exceed one")
        if self.end_at < self.start_at or self.initial_cash <= 0 or len(self.base_currency) != 3:
            raise InvalidBacktest("invalid backtest window or capital")
        if not self.name.strip() or not self.code_version.strip() or not 0 < self.max_participation <= 1 or self.execution_delay_bars < 1:
            raise InvalidBacktest("invalid definition")


@dataclass(frozen=True, slots=True)
class BacktestRun:
    definition_id: UUID
    input_hash: str
    result_hash: str | None
    status: BacktestRunStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_sequence: int = 0
    error: str | None = None
    run_id: UUID = field(default_factory=uuid4)

    def transition(self, status: BacktestRunStatus, at: datetime, error: str | None = None) -> "BacktestRun":
        allowed = {
            BacktestRunStatus.CREATED: {BacktestRunStatus.VALIDATING, BacktestRunStatus.CANCELLED},
            BacktestRunStatus.VALIDATING: {BacktestRunStatus.RUNNING, BacktestRunStatus.FAILED, BacktestRunStatus.CANCELLED},
            BacktestRunStatus.RUNNING: {BacktestRunStatus.COMPLETED, BacktestRunStatus.FAILED, BacktestRunStatus.CANCELLED},
        }
        if status not in allowed.get(self.status, set()):
            raise InvalidBacktest(f"invalid run transition {self.status}->{status}")
        point = aware(at, "transition_at")
        return replace(self, status=status, started_at=point if status is BacktestRunStatus.RUNNING else self.started_at, completed_at=point if status in (BacktestRunStatus.COMPLETED, BacktestRunStatus.FAILED, BacktestRunStatus.CANCELLED) else None, error=error)


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    run_id: UUID
    sequence: int
    market_time: datetime
    received_at: datetime
    priority: EventPriority
    event_type: str
    payload_version: str
    payload: Mapping[str, str]
    causation_id: UUID | None = None
    correlation_id: UUID | None = None
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        object.__setattr__(self, "market_time", aware(self.market_time, "market_time"))
        object.__setattr__(self, "received_at", aware(self.received_at, "received_at"))
        if self.sequence <= 0 or not self.event_type.strip() or not self.payload_version.strip():
            raise InvalidBacktest("invalid simulation event")


@dataclass(frozen=True, slots=True)
class SimulationBar:
    instrument_id: UUID
    market: str
    market_time: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    state: MarketState = MarketState.NORMAL
    bar_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        object.__setattr__(self, "market_time", aware(self.market_time, "market_time"))
        object.__setattr__(self, "available_at", aware(self.available_at, "available_at"))
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, dec(getattr(self, name)))
        if self.available_at < self.market_time or min(self.open, self.high, self.low, self.close) <= 0 or self.high < max(self.open, self.close) or self.low > min(self.open, self.close) or self.volume < 0:
            raise InvalidBacktest("invalid simulation bar")


@dataclass(frozen=True, slots=True)
class CorporateCashAction:
    instrument_id: UUID
    amount_per_share: Decimal
    effective_at: datetime
    available_at: datetime
    action_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        object.__setattr__(self, "amount_per_share", dec(self.amount_per_share))
        object.__setattr__(self, "effective_at", aware(self.effective_at, "effective_at"))
        object.__setattr__(self, "available_at", aware(self.available_at, "available_at"))
        if self.amount_per_share < 0 or self.available_at > self.effective_at:
            raise InvalidBacktest("invalid corporate cash action")


@dataclass(frozen=True, slots=True)
class StrategyTarget:
    kind: StrategyKind
    strategy_run_id: UUID
    instrument_id: UUID
    action: CandidateAction
    target_weight: Decimal
    decision_at: datetime
    input_snapshot_id: UUID
    reason_codes: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "decision_at", aware(self.decision_at, "decision_at"))
        object.__setattr__(self, "target_weight", dec(self.target_weight))
        if not 0 <= self.target_weight <= 1:
            raise InvalidBacktest("target weight out of range")


@dataclass(frozen=True, slots=True)
class SleeveContribution:
    run_id: UUID
    strategy_run_id: UUID
    kind: StrategyKind
    instrument_id: UUID
    raw_weight: Decimal
    final_weight: Decimal
    contribution_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class SimOrder:
    run_id: UUID
    instrument_id: UUID
    market: str
    side: Side
    order_type: SimOrderType
    quantity: int
    submitted_at: datetime
    eligible_after_bar_sequence: int
    limit_price: Decimal | None = None
    filled_quantity: int = 0
    status: SimOrderStatus = SimOrderStatus.OPEN
    reason: str | None = None
    order_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        object.__setattr__(self, "submitted_at", aware(self.submitted_at, "submitted_at"))
        if self.limit_price is not None:
            object.__setattr__(self, "limit_price", dec(self.limit_price))
        if self.quantity <= 0 or self.filled_quantity < 0 or self.filled_quantity > self.quantity or self.eligible_after_bar_sequence < 1:
            raise InvalidBacktest("invalid simulated order")

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_quantity


@dataclass(frozen=True, slots=True)
class SimFill:
    run_id: UUID
    order_id: UUID
    instrument_id: UUID
    side: Side
    quantity: int
    price: Decimal
    gross: Decimal
    commission: Decimal
    tax: Decimal
    platform_fee: Decimal
    slippage_cost: Decimal
    filled_at: datetime
    bar_id: UUID
    fill_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class SimLedgerEntry:
    run_id: UUID
    kind: LedgerKind
    effective_at: datetime
    source_id: UUID
    cash_delta: Decimal = Decimal()
    instrument_id: UUID | None = None
    quantity_delta: int = 0
    fee_delta: Decimal = Decimal()
    entry_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class BacktestPosition:
    instrument_id: UUID
    quantity: int
    sellable_quantity: int
    market_price: Decimal
    market_value: Decimal


@dataclass(frozen=True, slots=True)
class BacktestSnapshot:
    run_id: UUID
    as_of: datetime
    cash: Decimal
    positions: tuple[BacktestPosition, ...]
    nav: Decimal
    sleeve_exposure: Mapping[str, Decimal]
    content_hash: str
    snapshot_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class BacktestMetric:
    run_id: UUID
    name: str
    value: Decimal | None
    unit: str
    scope: str = "PORTFOLIO"
    metric_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class BacktestArtifact:
    run_id: UUID
    artifact_type: str
    content_hash: str
    reference: str
    artifact_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    definition: BacktestDefinition
    run: BacktestRun
    events: tuple[SimulationEvent, ...]
    orders: tuple[SimOrder, ...]
    fills: tuple[SimFill, ...]
    ledger: tuple[SimLedgerEntry, ...]
    snapshots: tuple[BacktestSnapshot, ...]
    metrics: tuple[BacktestMetric, ...]
    contributions: tuple[SleeveContribution, ...]
    artifacts: tuple[BacktestArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __post_init__(self):
        if not (self.train_start <= self.train_end < self.test_start <= self.test_end):
            raise InvalidBacktest("walk-forward train/test windows must be ordered and disjoint")
