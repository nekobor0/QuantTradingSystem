"""FIFO holding-period audit and tax-aware portfolio selection experiment.

The source return panel is adjusted for distributions, so dividends are never
added to returns a second time. Event-level cash dividends are accrued to FIFO
lots held on each record date, and deferred tax is charged only when those lots
are sold.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import COMMISSION_RATE, MIN_COMMISSION_CNY, dividend_tax_rate_for_dates, stamp_duty_rate
from .p1_validation import _affordable_selection, _arrays, _load, _metrics


@dataclass
class SaleAudit:
    sale_count: int = 0
    sold_weight: float = 0.0
    estimated_dividend: float = 0.0
    estimated_tax: float = 0.0
    by_bucket: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            "within_1_month": {"count": 0, "weight": 0.0, "dividend": 0.0, "tax": 0.0},
            "one_month_to_one_year": {"count": 0, "weight": 0.0, "dividend": 0.0, "tax": 0.0},
            "over_one_year": {"count": 0, "weight": 0.0, "dividend": 0.0, "tax": 0.0},
        }
    )
    protected_retention_count: int = 0
    safety_override_count: int = 0

    def record(self, weight: float, accrued_yield: float, rate: float) -> float:
        bucket = "within_1_month" if rate == 0.20 else "one_month_to_one_year" if rate == 0.10 else "over_one_year"
        dividend = weight * max(0.0, accrued_yield)
        tax = dividend * rate
        self.sale_count += 1
        self.sold_weight += weight
        self.estimated_dividend += dividend
        self.estimated_tax += tax
        row = self.by_bucket[bucket]
        row["count"] += 1
        row["weight"] += weight
        row["dividend"] += dividend
        row["tax"] += tax
        return tax

    def to_dict(self) -> dict:
        result = {
            "sale_count": self.sale_count,
            "sold_weight": self.sold_weight,
            "estimated_dividend_return_sold": self.estimated_dividend,
            "estimated_tax_return": self.estimated_tax,
            "protected_retention_count": self.protected_retention_count,
            "safety_override_count": self.safety_override_count,
            "by_bucket": self.by_bucket,
        }
        under_year = self.by_bucket["within_1_month"]["count"] + self.by_bucket["one_month_to_one_year"]["count"]
        under_year_weight = self.by_bucket["within_1_month"]["weight"] + self.by_bucket["one_month_to_one_year"]["weight"]
        result["under_one_year_sale_share"] = under_year / self.sale_count if self.sale_count else 0.0
        result["under_one_year_sold_weight_share"] = under_year_weight / self.sold_weight if self.sold_weight else 0.0
        return result


@dataclass
class ComponentResult:
    returns: pd.Series
    turnover: float
    order_count: int
    average_holdings: float
    sales: SaleAudit
    blocked_buy_count: int = 0


def _position_schedule(
    raw_position: pd.Series,
    entry_indices: list[int],
    frequency: str,
) -> pd.Series:
    if frequency == "daily":
        return raw_position.copy()
    if frequency != "monthly":
        raise ValueError(f"unsupported position frequency: {frequency}")
    scheduled = pd.Series(np.nan, index=raw_position.index, dtype=float)
    for index in sorted(set(entry_indices)):
        if 0 <= index < len(scheduled):
            scheduled.iloc[index] = float(raw_position.iloc[index])
    return scheduled.ffill().fillna(1.0)




def _ranked(month: pd.DataFrame, factor: str, ascending: bool) -> pd.DataFrame:
    return month[month["eligible"].fillna(False) & month[factor].notna()].sort_values(factor, ascending=ascending)


def _accrue_dividends(
    accrued: dict[str, float],
    holdings: dict[str, float],
    events: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    close_lookup: dict[tuple[str, pd.Timestamp], float],
) -> int:
    window = events[events["record_date"].ge(start) & events["record_date"].lt(end)]
    matched = 0
    for row in window.itertuples(index=False):
        symbol = str(row.ts_code)
        if symbol not in holdings:
            continue
        price = close_lookup.get((symbol, pd.Timestamp(row.record_date)))
        if price is None or price <= 0:
            continue
        accrued[symbol] = accrued.get(symbol, 0.0) + float(row.cash_div_tax) / price
        matched += 1
    return matched

def _tax_aware_component(
    signal: pd.DataFrame,
    factor: str,
    ascending: bool,
    top_n: int,
    capital: float,
    start: pd.Timestamp,
    voltrend: bool,
    protect_young: bool,
    calendar: np.ndarray,
    arrays: dict[str, dict[str, np.ndarray]],
    open_lookup: dict[tuple[str, pd.Timestamp], float],
    close_lookup: dict[tuple[str, pd.Timestamp], float],
    dividend_events: pd.DataFrame,
    position_frequency: str = "daily",
    buy_price_mode: str = "open",
    blocked_buys: set[tuple[str, pd.Timestamp]] | None = None,
) -> ComponentResult:
    if buy_price_mode not in {"open", "open_close_average"}:
        raise ValueError(f"unsupported buy price mode: {buy_price_mode}")
    blocked_buys = blocked_buys or set()
    calendar_index = {pd.Timestamp(value): idx for idx, value in enumerate(calendar)}
    gross = np.zeros(len(calendar), dtype=float)
    holdings_count = np.zeros(len(calendar), dtype=float)
    events: dict[int, tuple[dict[str, float], dict[str, float]]] = {}
    tax_events = np.zeros(len(calendar), dtype=float)
    previous: dict[str, float] = {}
    acquired: dict[str, pd.Timestamp] = {}
    accrued_yield: dict[str, float] = {}
    last_entry: pd.Timestamp | None = None
    audit = SaleAudit()
    blocked_buy_count = 0

    for _, month in signal.groupby("signal_date", sort=True):
        ranked = _ranked(month, factor, ascending)
        if ranked.empty:
            continue
        base = _affordable_selection(month, factor, ascending, top_n, capital, open_lookup)
        if base.empty:
            continue
        entry = pd.Timestamp(base["entry_date"].iloc[0])
        exit_date = pd.Timestamp(base["exit_date"].iloc[0])
        entry_index = calendar_index.get(entry)
        exit_index = calendar_index.get(exit_date)
        if entry_index is None or exit_index is None or exit_index <= entry_index:
            continue

        if last_entry is not None:
            _accrue_dividends(
                accrued_yield, previous, dividend_events, last_entry, entry, close_lookup
            )

        ranked_symbols = [str(value) for value in ranked["ts_code"]]
        eligible_symbols = set(ranked_symbols)
        protected: list[str] = []
        if protect_young:
            for symbol in previous:
                if dividend_tax_rate_for_dates(acquired[symbol].date(), entry.date()) > 0 and symbol in eligible_symbols:
                    protected.append(symbol)
                    audit.protected_retention_count += 1
                elif dividend_tax_rate_for_dates(acquired[symbol].date(), entry.date()) > 0:
                    audit.safety_override_count += 1
        selected_symbols = list(dict.fromkeys(protected + [str(value) for value in base["ts_code"]]))[:top_n]
        if len(selected_symbols) < top_n:
            selected_symbols.extend([symbol for symbol in ranked_symbols if symbol not in selected_symbols][: top_n - len(selected_symbols)])
        if not selected_symbols:
            continue

        weight = 1.0 / len(selected_symbols)
        current = {symbol: weight for symbol in selected_symbols}
        if buy_price_mode == "open_close_average":
            for symbol, target_weight in list(current.items()):
                previous_weight = previous.get(symbol, 0.0)
                if target_weight > previous_weight + 1e-12 and (symbol, entry) in blocked_buys:
                    blocked_buy_count += 1
                    if previous_weight > 0:
                        current[symbol] = min(target_weight, previous_weight)
                    else:
                        current.pop(symbol)
        sells = {symbol: previous[symbol] - current.get(symbol, 0.0) for symbol in previous if previous[symbol] > current.get(symbol, 0.0) + 1e-12}
        buys = {symbol: current[symbol] - previous.get(symbol, 0.0) for symbol in current if current[symbol] > previous.get(symbol, 0.0) + 1e-12}
        events[entry_index] = (buys, sells)
        for symbol, sold_weight in sells.items():
            rate = dividend_tax_rate_for_dates(acquired[symbol].date(), entry.date())
            tax_events[entry_index] += audit.record(sold_weight, accrued_yield.get(symbol, 0.0), rate)
            if symbol not in current:
                acquired.pop(symbol, None)
                accrued_yield.pop(symbol, None)
        for symbol in buys:
            if symbol not in acquired:
                acquired[symbol] = entry
                accrued_yield[symbol] = 0.0

        last_entry = entry
        holdings_count[entry_index:exit_index] = len(current)
        for symbol, current_weight in current.items():
            values = arrays.get(symbol)
            if values is None:
                continue
            retained_weight = min(previous.get(symbol, 0.0), current_weight)
            bought_weight = current_weight - retained_weight
            buy_return_field = "r_ac" if buy_price_mode == "open_close_average" else "r_oc"
            gross[entry_index] += retained_weight * values["r_oc"][entry_index]
            gross[entry_index] += bought_weight * values[buy_return_field][entry_index]
            gross[exit_index] += current_weight * values["r_co"][exit_index]
            gross[entry_index + 1:exit_index] += current_weight * values["r_cc"][entry_index + 1:exit_index]
        previous = current

    gross_series = pd.Series(gross, index=pd.to_datetime(calendar))
    if voltrend:
        realized = gross_series.rolling(60).std(ddof=0) * np.sqrt(252)
        nav = (1.0 + gross_series).cumprod()
        vol_position = (0.20 / realized).clip(upper=1.0).shift(1).fillna(1.0)
        trend_position = (nav.shift(1) >= nav.rolling(250).mean().shift(1)).astype(float).fillna(1.0)
        position = vol_position * trend_position
        position = _position_schedule(position, list(events), position_frequency)
    else:
        position = pd.Series(1.0, index=gross_series.index)

    output = np.zeros(len(calendar), dtype=float)
    nav_cny = capital
    total_turnover = 0.0
    order_count = 0
    previous_position = 0.0
    for idx, timestamp in enumerate(pd.to_datetime(calendar)):
        pos = float(position.iloc[idx])
        cost = 0.0
        buys, sells = events.get(idx, ({}, {}))
        for weights, side in ((buys, "BUY"), (sells, "SELL")):
            for changed_weight in weights.values():
                notional = nav_cny * changed_weight * max(previous_position, pos, 1.0 if idx == 0 else 0.0)
                if notional <= 0:
                    continue
                cost += max(notional * COMMISSION_RATE, MIN_COMMISSION_CNY)
                if side == "SELL":
                    cost += notional * stamp_duty_rate(timestamp.date())
                total_turnover += notional / max(nav_cny, 1.0)
                order_count += 1
        exposure_change = pos - previous_position
        names = int(holdings_count[idx])
        if idx > 0 and abs(exposure_change) >= 0.01 and names > 0:
            per_order = nav_cny * abs(exposure_change) / names
            side = "BUY" if exposure_change > 0 else "SELL"
            cost += names * max(per_order * COMMISSION_RATE, MIN_COMMISSION_CNY)
            if side == "SELL":
                cost += names * per_order * stamp_duty_rate(timestamp.date())
            total_turnover += abs(exposure_change)
            order_count += names
        net_return = float(gross[idx]) * pos - cost / max(nav_cny, 1.0) - float(tax_events[idx])
        output[idx] = net_return
        nav_cny *= 1.0 + net_return
        previous_position = pos
    result = pd.Series(output, index=pd.to_datetime(calendar))
    result = result[result.index >= start]
    average_holdings = float(pd.Series(holdings_count, index=pd.to_datetime(calendar)).loc[result.index].replace(0, np.nan).mean())
    return ComponentResult(result, total_turnover, order_count, average_holdings, audit, blocked_buy_count)


def run(
    data_root: Path,
    dividend_history: Path,
    start: str = "2018-01-01",
    principal: float = 1_000_000.0,
) -> dict:
    start_date = pd.Timestamp(start)
    signal, panel = _load(data_root, start_date)
    for column in ("value_composite", "amihud20", "dividend_yield"):
        signal["r_" + column] = signal.groupby("signal_date")[column].rank(pct=True)
    signal["balanced"] = 0.4 * signal["r_value_composite"] + 0.3 * signal["r_amihud20"] + 0.3 * signal["r_dividend_yield"]
    calendar = np.sort(panel["date"].unique())
    arrays = _arrays(panel, calendar)
    open_lookup = {
        (str(row.ts_code), pd.Timestamp(row.date)): float(row.open)
        for row in panel[["ts_code", "date", "open"]].itertuples(index=False)
        if pd.notna(row.open) and row.open > 0
    }
    close_lookup = {
        (str(row.ts_code), pd.Timestamp(row.date)): float(row.close)
        for row in panel[["ts_code", "date", "close"]].itertuples(index=False)
        if pd.notna(row.close) and row.close > 0
    }
    dividend_events = pd.read_parquet(dividend_history)
    dividend_events["record_date"] = pd.to_datetime(dividend_events["record_date"])
    dividend_events = dividend_events[
        dividend_events["record_date"].ge(start_date)
        & dividend_events["cash_div_tax"].fillna(0).gt(0)
    ].copy()
    scenarios: dict[str, dict] = {}
    component_cache: dict[tuple[int, bool, str], ComponentResult] = {}
    for top_n in (50, 100):
        for protected in (False, True):
            mode = "one_year_protected" if protected else "baseline_fifo"
            component_cache[(top_n, protected, "dividend")] = _tax_aware_component(
                signal[signal["dividend_yield"].ge(0.05)], "dividend_yield", False, top_n,
                principal, start_date, False, protected, calendar, arrays, open_lookup,
                close_lookup, dividend_events,
            )
            component_cache[(top_n, protected, "voltrend")] = _tax_aware_component(
                signal, "balanced", False, top_n, principal, start_date, True, protected,
                calendar, arrays, open_lookup, close_lookup, dividend_events,
            )
            for div_weight in (0.75, 0.25):
                dividend = component_cache[(top_n, protected, "dividend")]
                voltrend = component_cache[(top_n, protected, "voltrend")]
                index = dividend.returns.index.intersection(voltrend.returns.index)
                combined = div_weight * dividend.returns.reindex(index) + (1.0 - div_weight) * voltrend.returns.reindex(index)
                key = f"top{top_n}_div{int(div_weight*100)}_{mode}"
                scenarios[key] = {
                    **_metrics(combined, principal),
                    "mode": mode,
                    "dividend_weight": div_weight,
                    "voltrend_weight": 1.0 - div_weight,
                    "top_n": top_n,
                    "dividend_average_holdings": dividend.average_holdings,
                    "voltrend_average_holdings": voltrend.average_holdings,
                    "dividend_orders": dividend.order_count,
                    "voltrend_orders": voltrend.order_count,
                    "dividend_turnover": dividend.turnover,
                    "voltrend_turnover": voltrend.turnover,
                    "dividend_sale_audit": dividend.sales.to_dict(),
                    "voltrend_sale_audit": voltrend.sales.to_dict(),
                }
    best_key = max(scenarios, key=lambda key: (scenarios[key]["sharpe"], scenarios[key]["annualized_return"]))
    return {
        "method": "event_level_tax_before_cash_with_FIFO_tax_on_sale",
        "tax_amount_posture": "event_based_with_cross_source_coverage_QC",
        "dividend_events": len(dividend_events),
        "start": start,
        "end": panel["date"].max().strftime("%Y-%m-%d"),
        "principal": principal,
        "best_scenario": best_key,
        "scenarios": scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--dividend-history", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", default="2018-01-01")
    args = parser.parse_args()
    result = run(args.data_root, args.dividend_history, args.start)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
