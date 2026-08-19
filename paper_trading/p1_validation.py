"""P1 executable-cost validation for the 75/25 and 25/75 portfolios.

The historical total-return series uses adjusted prices. Dividend tax is therefore
applied as an explicit sensitivity drag and cash dividends are not added again.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import COMMISSION_RATE, MIN_COMMISSION_CNY, stamp_duty_rate


@dataclass
class ComponentResult:
    returns: pd.Series
    turnover: float
    order_count: int
    average_holdings: float


def _metrics(returns: pd.Series, principal: float) -> dict[str, float]:
    returns = returns.fillna(0.0)
    wealth = (1.0 + returns).cumprod()
    years = len(returns) / 252.0
    annualized = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0
    volatility = float(returns.std(ddof=0) * np.sqrt(252))
    sharpe = float(returns.mean() / returns.std(ddof=0) * np.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0
    drawdown = wealth / wealth.cummax() - 1.0
    return {
        "annualized_return": annualized,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "ending_capital": float(principal * wealth.iloc[-1]),
    }


def _load(root: Path, start: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    signal = pd.read_parquet(root / "epoch2_signal_frame_v9.parquet")
    signal["signal_date"] = pd.to_datetime(signal["signal_date"])
    signal["entry_date"] = pd.to_datetime(signal["entry_date"])
    signal["exit_date"] = pd.to_datetime(signal["exit_date"])
    signal = signal[signal["exit_date"].ge(start - pd.Timedelta(days=40))].copy()
    panel = pd.read_parquet(
        root / "daily_panel_v8.parquet",
        columns=["ts_code", "date", "open", "close", "factor"],
    )
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["date"].ge(start - pd.Timedelta(days=370))].copy()
    panel = panel.sort_values(["ts_code", "date"])
    panel["adj_open"] = panel["open"] * panel["factor"]
    panel["adj_close"] = panel["close"] * panel["factor"]
    panel["prev_adj_close"] = panel.groupby("ts_code")["adj_close"].shift(1)
    panel["r_cc"] = panel["adj_close"] / panel["prev_adj_close"] - 1.0
    panel["r_oc"] = panel["adj_close"] / panel["adj_open"] - 1.0
    panel["r_co"] = panel["adj_open"] / panel["prev_adj_close"] - 1.0
    return signal, panel


def _arrays(panel: pd.DataFrame, calendar: np.ndarray) -> dict[str, dict[str, np.ndarray]]:
    output: dict[str, dict[str, np.ndarray]] = {}
    for symbol, group in panel.groupby("ts_code", sort=False):
        positions = np.searchsorted(calendar, group["date"].to_numpy())
        values: dict[str, np.ndarray] = {}
        for field in ("r_cc", "r_oc", "r_co"):
            arr = np.zeros(len(calendar), dtype=np.float32)
            arr[positions] = group[field].fillna(0.0).to_numpy(dtype=np.float32)
            values[field] = arr
        output[str(symbol)] = values
    return output


def _affordable_selection(month: pd.DataFrame, factor: str, ascending: bool, top_n: int, capital: float, open_lookup: dict[tuple[str, pd.Timestamp], float]) -> pd.DataFrame:
    ranked = month[month["eligible"].fillna(False) & month[factor].notna()].sort_values(factor, ascending=ascending)
    if ranked.empty:
        return ranked
    count = min(top_n, len(ranked))
    selected = ranked.head(count)
    for _ in range(4):
        per_name = capital / max(1, count)
        affordable = ranked[
            ranked.apply(
                lambda row: open_lookup.get((str(row["ts_code"]), pd.Timestamp(row["entry_date"])), np.inf) * 100.0 + MIN_COMMISSION_CNY <= per_name,
                axis=1,
            )
        ]
        selected = affordable.head(top_n)
        new_count = len(selected)
        if new_count == count:
            break
        count = new_count
    return selected


def _component(
    signal: pd.DataFrame, factor: str, ascending: bool, top_n: int, capital: float,
    start: pd.Timestamp, dividend_tax: float, voltrend: bool,
    calendar: np.ndarray, arrays: dict[str, dict[str, np.ndarray]],
    open_lookup: dict[tuple[str, pd.Timestamp], float],
) -> ComponentResult:
    calendar_index = {pd.Timestamp(value): idx for idx, value in enumerate(calendar)}
    gross = np.zeros(len(calendar), dtype=float)
    holdings_count = np.zeros(len(calendar), dtype=float)
    events: dict[int, tuple[dict[str, float], dict[str, float]]] = {}
    dividend_drag = np.zeros(len(calendar), dtype=float)
    previous: dict[str, float] = {}
    for _, month in signal.groupby("signal_date", sort=True):
        selected = _affordable_selection(month, factor, ascending, top_n, capital, open_lookup)
        if selected.empty:
            continue
        entry = pd.Timestamp(selected["entry_date"].iloc[0])
        exit_date = pd.Timestamp(selected["exit_date"].iloc[0])
        entry_index = calendar_index.get(entry)
        exit_index = calendar_index.get(exit_date)
        if entry_index is None or exit_index is None or exit_index <= entry_index:
            continue
        weight = 1.0 / len(selected)
        current = {str(symbol): weight for symbol in selected["ts_code"]}
        sells = {symbol: previous[symbol] - current.get(symbol, 0.0) for symbol in previous if previous[symbol] > current.get(symbol, 0.0)}
        buys = {symbol: current[symbol] - previous.get(symbol, 0.0) for symbol in current if current[symbol] > previous.get(symbol, 0.0)}
        events[entry_index] = (buys, sells)
        mean_yield = float(selected["dividend_yield"].fillna(0.0).mean())
        daily_tax_drag = max(0.0, mean_yield) * dividend_tax / 252.0
        dividend_drag[entry_index:exit_index] = daily_tax_drag
        holdings_count[entry_index:exit_index] = len(selected)
        for symbol in current:
            values = arrays.get(symbol)
            if values is None:
                continue
            gross[entry_index] += weight * values["r_oc"][entry_index]
            gross[exit_index] += weight * values["r_co"][exit_index]
            gross[entry_index + 1:exit_index] += weight * values["r_cc"][entry_index + 1:exit_index]
        previous = current

    gross_series = pd.Series(gross, index=pd.to_datetime(calendar))
    if voltrend:
        realized = gross_series.rolling(60).std(ddof=0) * np.sqrt(252)
        nav = (1.0 + gross_series).cumprod()
        vol_position = (0.20 / realized).clip(upper=1.0).shift(1).fillna(1.0)
        trend_position = (nav.shift(1) >= nav.rolling(250).mean().shift(1)).astype(float).fillna(1.0)
        position = vol_position * trend_position
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
            for weight in weights.values():
                notional = nav_cny * weight * max(previous_position, pos, 1.0 if idx == 0 else 0.0)
                if notional <= 0:
                    continue
                fee = max(notional * COMMISSION_RATE, MIN_COMMISSION_CNY)
                stamp = notional * stamp_duty_rate(timestamp.date()) if side == "SELL" else 0.0
                cost += fee + stamp
                total_turnover += notional / max(nav_cny, 1.0)
                order_count += 1
        exposure_change = pos - previous_position
        names = int(holdings_count[idx])
        if idx > 0 and abs(exposure_change) >= 0.01 and names > 0:
            per_order = nav_cny * abs(exposure_change) / names
            side = "BUY" if exposure_change > 0 else "SELL"
            per_fee = max(per_order * COMMISSION_RATE, MIN_COMMISSION_CNY)
            per_stamp = per_order * stamp_duty_rate(timestamp.date()) if side == "SELL" else 0.0
            cost += names * (per_fee + per_stamp)
            total_turnover += abs(exposure_change)
            order_count += names
        net_return = float(gross[idx]) * pos - cost / max(nav_cny, 1.0) - float(dividend_drag[idx])
        output[idx] = net_return
        nav_cny *= 1.0 + net_return
        previous_position = pos
    result = pd.Series(output, index=pd.to_datetime(calendar))
    result = result[result.index >= start]
    average_holdings = float(pd.Series(holdings_count, index=pd.to_datetime(calendar)).loc[result.index].replace(0, np.nan).mean())
    return ComponentResult(result, total_turnover, order_count, average_holdings)


def run(data_root: Path, start: str = "2018-01-01", principal: float = 1_000_000.0) -> dict:
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
    scenarios: dict[str, dict] = {}
    for top_n in (50, 100):
        for tax in (0.0, 0.10, 0.20):
            dividend = _component(signal[signal["dividend_yield"].ge(0.05)], "dividend_yield", False, top_n, principal * 0.75, start_date, tax, False, calendar, arrays, open_lookup)
            voltrend = _component(signal, "balanced", False, top_n, principal * 0.25, start_date, tax, True, calendar, arrays, open_lookup)
            index = dividend.returns.index.intersection(voltrend.returns.index)
            for div_weight in (0.75, 0.25):
                combined = div_weight * dividend.returns.reindex(index) + (1.0 - div_weight) * voltrend.returns.reindex(index)
                key = f"top{top_n}_div{int(div_weight*100)}_tax{int(tax*100)}"
                scenarios[key] = {
                    **_metrics(combined, principal),
                    "dividend_weight": div_weight,
                    "voltrend_weight": 1.0 - div_weight,
                    "top_n": top_n,
                    "dividend_tax_sensitivity": tax,
                    "dividend_average_holdings": dividend.average_holdings,
                    "voltrend_average_holdings": voltrend.average_holdings,
                    "dividend_orders": dividend.order_count,
                    "voltrend_orders": voltrend.order_count,
                    "dividend_turnover": dividend.turnover,
                    "voltrend_turnover": voltrend.turnover,
                }
    return {"start": start, "end": panel["date"].max().strftime("%Y-%m-%d"), "principal": principal, "scenarios": scenarios}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", default="2018-01-01")
    args = parser.parse_args()
    result = run(args.data_root, args.start)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

