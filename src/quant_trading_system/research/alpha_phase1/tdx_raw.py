"""Strict extraction of research fields retained in immutable TdxQuant JSON."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


class TdxRawQualityError(ValueError):
    """A raw response cannot safely support phase-one research."""


@dataclass(frozen=True, slots=True)
class RawResearchSeries:
    symbol: str
    dates: tuple[date, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]
    amount_wan: tuple[float, ...]
    forward_factor: tuple[float, ...]
    float_shares: tuple[float | None, ...]

    @property
    def rows(self) -> int:
        return len(self.dates)


REQUIRED_LIST_FIELDS = (
    "Date",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Amount",
    "ForwardFactor",
    "VolInStock",
)


def parse_research_series(payload: Mapping[str, Any]) -> tuple[RawResearchSeries, ...]:
    """Parse all symbols and fail closed on unsafe field or time alignment."""
    result = payload.get("result")
    values = result.get("Value") if isinstance(result, Mapping) else None
    if not isinstance(values, Mapping) or not values:
        raise TdxRawQualityError("TdxQuant response is missing result.Value")
    parsed = tuple(_parse_symbol(str(symbol).upper(), series) for symbol, series in values.items())
    if len({series.symbol for series in parsed}) != len(parsed):
        raise TdxRawQualityError("TdxQuant response contains duplicate symbols")
    return parsed


def _parse_symbol(symbol: str, raw: Any) -> RawResearchSeries:
    if not symbol or not isinstance(raw, Mapping):
        raise TdxRawQualityError("invalid symbol payload")
    if str(raw.get("ErrorId", "0")) != "0":
        raise TdxRawQualityError(f"{symbol}: ErrorId={raw.get('ErrorId')}")
    fields: dict[str, list[Any]] = {}
    for name in REQUIRED_LIST_FIELDS:
        value = raw.get(name)
        if not isinstance(value, list):
            raise TdxRawQualityError(f"{symbol}: missing list field {name}")
        fields[name] = value
    lengths = {name: len(value) for name, value in fields.items()}
    if not lengths["Date"]:
        raise TdxRawQualityError(f"{symbol}: empty daily series")
    if len(set(lengths.values())) != 1:
        raise TdxRawQualityError(f"{symbol}: research fields have different lengths")

    dates = tuple(_date(value, symbol) for value in fields["Date"])
    if any(current <= previous for previous, current in zip(dates, dates[1:])):
        raise TdxRawQualityError(f"{symbol}: dates must be unique and strictly increasing")
    open_ = _numbers(fields["Open"], "Open", symbol, positive=True)
    high = _numbers(fields["High"], "High", symbol, positive=True)
    low = _numbers(fields["Low"], "Low", symbol, positive=True)
    close = _numbers(fields["Close"], "Close", symbol, positive=True)
    volume = _numbers(fields["Volume"], "Volume", symbol, nonnegative=True)
    amount = _numbers(fields["Amount"], "Amount", symbol, nonnegative=True)
    factor = _numbers(fields["ForwardFactor"], "ForwardFactor", symbol, positive=True)
    shares = tuple(_optional_nonnegative(value, "VolInStock", symbol) for value in fields["VolInStock"])
    for index, (o, h, low_value, c) in enumerate(zip(open_, high, low, close)):
        if h < max(o, c, low_value) or low_value > min(o, c, h):
            raise TdxRawQualityError(f"{symbol}: invalid OHLC envelope at row {index}")
    return RawResearchSeries(
        symbol, dates, open_, high, low, close, volume, amount, factor, shares
    )


def _date(value: Any, symbol: str) -> date:
    text = str(value).strip().split(".", 1)[0].replace("-", "")
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise TdxRawQualityError(f"{symbol}: invalid Date={value!r}") from exc


def _numbers(
    values: list[Any], name: str, symbol: str, *, positive: bool = False, nonnegative: bool = False
) -> tuple[float, ...]:
    result: list[float] = []
    for index, value in enumerate(values):
        number = _finite(value, name, symbol, index)
        if positive and number <= 0:
            raise TdxRawQualityError(f"{symbol}: {name} must be positive at row {index}")
        if nonnegative and number < 0:
            raise TdxRawQualityError(f"{symbol}: {name} must be nonnegative at row {index}")
        result.append(number)
    return tuple(result)


def _optional_nonnegative(value: Any, name: str, symbol: str) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    number = _finite(value, name, symbol, None)
    if number < 0:
        raise TdxRawQualityError(f"{symbol}: {name} must be nonnegative")
    return number


def _finite(value: Any, name: str, symbol: str, index: int | None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        where = "" if index is None else f" at row {index}"
        raise TdxRawQualityError(f"{symbol}: invalid {name}{where}") from exc
    if not math.isfinite(number):
        where = "" if index is None else f" at row {index}"
        raise TdxRawQualityError(f"{symbol}: non-finite {name}{where}")
    return number

