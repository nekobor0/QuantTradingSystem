"""Compare monthly versus daily vol/trend overlay update frequencies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DIV_WEIGHT, VOL_WEIGHT
from .p1_validation import _arrays, _load, _metrics
from .tax_lot_validation import _tax_aware_component


DAILY_SHARPE_HURDLE = 0.05
MAX_DRAWDOWN_TOLERANCE = 0.02


def _scenario(
    dividend,
    voltrend,
    principal: float,
    frequency: str,
) -> dict:
    index = dividend.returns.index.intersection(voltrend.returns.index)
    combined = (
        DIV_WEIGHT * dividend.returns.reindex(index)
        + VOL_WEIGHT * voltrend.returns.reindex(index)
    )
    return {
        **_metrics(combined, principal),
        "dividend_constituent_frequency": "monthly",
        "voltrend_constituent_frequency": "monthly",
        "voltrend_position_frequency": frequency,
        "scan_frequency": "daily",
        "execution_price": "next_trading_day_open",
        "dividend_orders": dividend.order_count,
        "voltrend_orders": voltrend.order_count,
        "dividend_turnover": dividend.turnover,
        "voltrend_turnover": voltrend.turnover,
        "dividend_sale_audit": dividend.sales.to_dict(),
        "voltrend_sale_audit": voltrend.sales.to_dict(),
    }


def _select(scenarios: dict[str, dict]) -> tuple[str, str]:
    monthly = scenarios["both_monthly"]
    daily = scenarios["dividend_monthly_voltrend_daily"]
    sharpe_gain = daily["sharpe"] - monthly["sharpe"]
    daily_drawdown_worse_by = abs(daily["max_drawdown"]) - abs(monthly["max_drawdown"])
    if (
        sharpe_gain >= DAILY_SHARPE_HURDLE
        and daily["annualized_return"] > monthly["annualized_return"]
        and daily_drawdown_worse_by <= MAX_DRAWDOWN_TOLERANCE
    ):
        return (
            "dividend_monthly_voltrend_daily",
            "daily overlay clears the pre-registered Sharpe and return hurdles without materially worse drawdown",
        )
    return (
        "both_monthly",
        "daily overlay does not clear all pre-registered hurdles; monthly is preferred for lower operational complexity",
    )


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
    signal["balanced"] = (
        0.4 * signal["r_value_composite"]
        + 0.3 * signal["r_amihud20"]
        + 0.3 * signal["r_dividend_yield"]
    )
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

    common = (calendar, arrays, open_lookup, close_lookup, dividend_events)
    dividend = _tax_aware_component(
        signal[signal["dividend_yield"].ge(0.05)],
        "dividend_yield",
        False,
        50,
        principal * DIV_WEIGHT,
        start_date,
        False,
        False,
        *common,
        position_frequency="monthly",
    )
    scenarios: dict[str, dict] = {}
    for frequency, key in (
        ("monthly", "both_monthly"),
        ("daily", "dividend_monthly_voltrend_daily"),
    ):
        voltrend = _tax_aware_component(
            signal,
            "balanced",
            False,
            50,
            principal * VOL_WEIGHT,
            start_date,
            True,
            False,
            *common,
            position_frequency=frequency,
        )
        scenarios[key] = _scenario(dividend, voltrend, principal, frequency)

    selected, rationale = _select(scenarios)
    return {
        "method": "same_monthly_constituents_compare_voltrend_overlay_frequency",
        "selection_rule": {
            "daily_sharpe_gain_at_least": DAILY_SHARPE_HURDLE,
            "daily_annualized_return_must_be_higher": True,
            "daily_max_drawdown_may_worsen_by_at_most": MAX_DRAWDOWN_TOLERANCE,
        },
        "start": start,
        "end": panel["date"].max().strftime("%Y-%m-%d"),
        "principal": principal,
        "sleeve_capital": {
            "dividend": principal * DIV_WEIGHT,
            "voltrend": principal * VOL_WEIGHT,
        },
        "dividend_events": len(dividend_events),
        "selected_scenario": selected,
        "selection_rationale": rationale,
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
