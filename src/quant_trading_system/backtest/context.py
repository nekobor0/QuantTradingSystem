from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import UUID

from .domain import SimulationBar, aware
from .errors import LookaheadAccess


@dataclass(frozen=True, slots=True)
class PointInTimeValue:
    key: str
    available_at: datetime
    value: object

    def __post_init__(self):
        object.__setattr__(self, "available_at", aware(self.available_at, "available_at"))


class StrategyContext:
    """Read-only point-in-time view. Future access is an error, never an empty fallback."""

    def __init__(self, decision_at: datetime, bars: Iterable[SimulationBar], values: Iterable[PointInTimeValue] = ()):
        self.decision_at = aware(decision_at, "decision_at")
        self._bars = tuple(bars)
        self._values = tuple(values)

    def history(self, instrument_id: UUID, through: datetime | None = None) -> tuple[SimulationBar, ...]:
        point = self.decision_at if through is None else aware(through, "through")
        if point > self.decision_at:
            raise LookaheadAccess("LOOKAHEAD: requested bar time exceeds decision_at")
        visible = tuple(
            bar for bar in self._bars
            if bar.instrument_id == instrument_id and bar.market_time <= point and bar.available_at <= self.decision_at
        )
        hidden = any(bar.instrument_id == instrument_id and bar.market_time <= point and bar.available_at > self.decision_at for bar in self._bars)
        if hidden:
            raise LookaheadAccess("LOOKAHEAD: requested bar was not available at decision_at")
        return tuple(sorted(visible, key=lambda bar: (bar.market_time, str(bar.bar_id))))

    def latest_bar(self, instrument_id: UUID) -> SimulationBar | None:
        values = self.history(instrument_id)
        return values[-1] if values else None

    def value(self, key: str) -> object:
        candidates = [item for item in self._values if item.key == key]
        if not candidates:
            raise KeyError(key)
        visible = [item for item in candidates if item.available_at <= self.decision_at]
        if not visible:
            raise LookaheadAccess("LOOKAHEAD: value was not available at decision_at")
        return max(visible, key=lambda item: item.available_at).value

