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
class PaperState:
    version: int = 2
    start_date: str = ""
    dividend_book: Book = field(default_factory=lambda: Book("dividend", 750_000.0))
    voltrend_book: Book = field(default_factory=lambda: Book("voltrend", 250_000.0))
    run_history: list[dict[str, Any]] = field(default_factory=list)
    reconciliations: list[dict[str, Any]] = field(default_factory=list)
    legacy_import: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

