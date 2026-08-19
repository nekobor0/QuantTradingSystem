"""Serializable paper-account domain objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class Lot:
    lot_id: str
    shares: int
    acquired_date: str
    unit_cost: float
    taxable_dividend_per_share: float = 0.0

    @classmethod
    def new(cls, shares: int, acquired_date: str, unit_cost: float) -> "Lot":
        return cls(uuid4().hex, shares, acquired_date, unit_cost)


@dataclass
class Fill:
    fill_id: str
    plan_id: str
    date: str
    symbol: str
    side: str
    shares: int
    price: float
    commission: float
    stamp_duty: float
    dividend_tax: float
    status: str = "FILLED"
    note: str = ""


@dataclass
class CashEvent:
    event_id: str
    date: str
    symbol: str
    kind: str
    gross: float
    tax: float
    net: float
    note: str = ""


@dataclass
class DividendEntitlement:
    entitlement_id: str
    symbol: str
    record_date: str
    pay_date: str
    shares: int
    cash_div_per_share: float
    credited: bool = False


@dataclass
class PendingPlan:
    plan_id: str
    book: str
    signal_date: str
    execute_date: str
    target_weights: dict[str, float] = field(default_factory=dict)
    cash_buys: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    status: str = "PENDING"
    warnings: list[str] = field(default_factory=list)


@dataclass
class Book:
    name: str
    cash: float
    lots: dict[str, list[Lot]] = field(default_factory=dict)
    model_weights: dict[str, float] = field(default_factory=dict)
    pending_plan: PendingPlan | None = None
    fills: list[Fill] = field(default_factory=list)
    cash_events: list[CashEvent] = field(default_factory=list)
    entitlements: list[DividendEntitlement] = field(default_factory=list)
    nav_history: list[dict[str, Any]] = field(default_factory=list)
    last_prices: dict[str, float] = field(default_factory=dict)
    risk_position: float = 1.0

    def shares(self, symbol: str) -> int:
        return sum(lot.shares for lot in self.lots.get(symbol, []))

    @property
    def holdings(self) -> dict[str, int]:
        return {symbol: self.shares(symbol) for symbol in self.lots if self.shares(symbol) > 0}


@dataclass
class StrategyAccount:
    key: str
    name: str
    dividend_weight: float
    voltrend_weight: float
    dividend_book: Book
    voltrend_book: Book

    @classmethod
    def new(
        cls,
        key: str,
        name: str,
        dividend_weight: float,
        voltrend_weight: float,
        principal: float = 1_000_000.0,
    ) -> "StrategyAccount":
        return cls(
            key=key,
            name=name,
            dividend_weight=dividend_weight,
            voltrend_weight=voltrend_weight,
            dividend_book=Book(f"{key}_dividend", principal * dividend_weight),
            voltrend_book=Book(f"{key}_voltrend", principal * voltrend_weight),
        )

    @property
    def books(self) -> tuple[Book, Book]:
        return self.dividend_book, self.voltrend_book


def default_strategies() -> dict[str, StrategyAccount]:
    return {
        "A": StrategyAccount.new("A", "A策略：25%红利 + 75%波动", 0.25, 0.75),
        "B": StrategyAccount.new("B", "B策略：75%红利 + 25%波动", 0.75, 0.25),
    }


@dataclass
class PaperState:
    version: int = 3
    start_date: str = ""
    strategies: dict[str, StrategyAccount] = field(default_factory=default_strategies)
    run_history: list[dict[str, Any]] = field(default_factory=list)
    reconciliations: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    last_data_update: dict[str, Any] | None = None
    last_scan: dict[str, Any] | None = None
    legacy_import: bool = False

    @property
    def dividend_book(self) -> Book:
        """Compatibility alias for strategy A."""
        return self.strategies["A"].dividend_book

    @property
    def voltrend_book(self) -> Book:
        """Compatibility alias for strategy A."""
        return self.strategies["A"].voltrend_book

    @property
    def books(self) -> list[Book]:
        return [book for strategy in self.strategies.values() for book in strategy.books]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
