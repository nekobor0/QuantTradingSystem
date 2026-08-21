"""Compare next-open fills with sell-open / buy-open-close-average fills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .p1_validation import _arrays, _load, _metrics
from .tax_lot_validation import _tax_aware_component


STRATEGIES = {
    "A": {"dividend_weight": 0.25, "voltrend_weight": 0.75},
    "B": {"dividend_weight": 0.75, "voltrend_weight": 0.25},
}


def _sealed_limit_up_buys(
    panel: pd.DataFrame,
    limit_path: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[set[tuple[str, pd.Timestamp]], dict]:
    limits = pd.read_parquet(
        limit_path,
        columns=["ts_code", "trade_date", "up_limit"],
        filters=[
            ("trade_date", ">=", start.strftime("%Y%m%d")),
            ("trade_date", "<=", end.strftime("%Y%m%d")),
        ],
    )
    limits["date"] = pd.to_datetime(limits["trade_date"].astype(str))
    daily = panel.loc[
        panel["date"].between(start, end), ["ts_code", "date", "close"]
    ]
    merged = daily.merge(
        limits[["ts_code", "date", "up_limit"]],
        on=["ts_code", "date"],
        how="left",
        validate="one_to_one",
    )
    matched = merged["up_limit"].notna()
    sealed = matched & merged["close"].sub(merged["up_limit"]).abs().le(0.001)
    blocked = {
        (str(row.ts_code), pd.Timestamp(row.date))
        for row in merged.loc[sealed, ["ts_code", "date"]].itertuples(index=False)
    }
    return blocked, {
        "official_limit_rows": int(len(limits)),
        "panel_rows": int(len(merged)),
        "matched_rows": int(matched.sum()),
        "match_rate": float(matched.mean()) if len(merged) else 0.0,
        "sealed_limit_up_rows": int(sealed.sum()),
        "duplicate_limit_keys": int(limits.duplicated(["ts_code", "date"]).sum()),
    }


def _components(
    signal: pd.DataFrame,
    calendar: np.ndarray,
    arrays: dict[str, dict[str, np.ndarray]],
    open_lookup: dict[tuple[str, pd.Timestamp], float],
    close_lookup: dict[tuple[str, pd.Timestamp], float],
    dividend_events: pd.DataFrame,
    start: pd.Timestamp,
    principal: float,
    buy_price_mode: str,
    blocked_buys: set[tuple[str, pd.Timestamp]],
) -> dict:
    output: dict[str, dict] = {}
    for key, weights in STRATEGIES.items():
        dividend = _tax_aware_component(
            signal[signal["dividend_yield"].ge(0.05)],
            "dividend_yield",
            False,
            50,
            principal * weights["dividend_weight"],
            start,
            False,
            False,
            calendar,
            arrays,
            open_lookup,
            close_lookup,
            dividend_events,
            position_frequency="daily",
            buy_price_mode=buy_price_mode,
            blocked_buys=blocked_buys,
        )
        voltrend = _tax_aware_component(
            signal,
            "balanced",
            False,
            50,
            principal * weights["voltrend_weight"],
            start,
            True,
            False,
            calendar,
            arrays,
            open_lookup,
            close_lookup,
            dividend_events,
            position_frequency="daily",
            buy_price_mode=buy_price_mode,
            blocked_buys=blocked_buys,
        )
        index = dividend.returns.index.intersection(voltrend.returns.index)
        combined = (
            weights["dividend_weight"] * dividend.returns.reindex(index)
            + weights["voltrend_weight"] * voltrend.returns.reindex(index)
        )
        output[key] = {
            **weights,
            **_metrics(combined, principal),
            "dividend_orders": dividend.order_count,
            "voltrend_orders": voltrend.order_count,
            "dividend_turnover": dividend.turnover,
            "voltrend_turnover": voltrend.turnover,
            "dividend_limit_up_buys_skipped": dividend.blocked_buy_count,
            "voltrend_limit_up_buys_skipped": voltrend.blocked_buy_count,
        }
    return output


def run(
    data_root: Path,
    dividend_history: Path,
    limit_path: Path,
    start: str = "2018-07-02",
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
    end_date = pd.Timestamp(panel["date"].max())
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
        dividend_events["record_date"].between(start_date, end_date)
        & dividend_events["cash_div_tax"].fillna(0).gt(0)
    ].copy()
    blocked_buys, limit_quality = _sealed_limit_up_buys(
        panel, limit_path, start_date, end_date
    )
    baseline = _components(
        signal,
        calendar,
        arrays,
        open_lookup,
        close_lookup,
        dividend_events,
        start_date,
        principal,
        "open",
        set(),
    )
    average_only = _components(
        signal,
        calendar,
        arrays,
        open_lookup,
        close_lookup,
        dividend_events,
        start_date,
        principal,
        "open_close_average",
        set(),
    )
    realistic = _components(
        signal,
        calendar,
        arrays,
        open_lookup,
        close_lookup,
        dividend_events,
        start_date,
        principal,
        "open_close_average",
        blocked_buys,
    )
    deltas = {
        key: {
            metric: realistic[key][metric] - baseline[key][metric]
            for metric in (
                "annualized_return",
                "annualized_volatility",
                "sharpe",
                "max_drawdown",
                "ending_capital",
            )
        }
        for key in STRATEGIES
    }
    return {
        "method": "same_T_signal_sell_next_open_buy_next_open_close_average",
        "start": start_date.strftime("%Y-%m-%d"),
        "end": end_date.strftime("%Y-%m-%d"),
        "principal_per_strategy": principal,
        "limit_up_definition": "official up_limit and close equal within 0.001",
        "limit_data_quality": limit_quality,
        "dividend_events": len(dividend_events),
        "policies": {
            "baseline_next_open": baseline,
            "sell_open_buy_average_without_limit_filter": average_only,
            "realistic_sell_open_buy_average_exclude_limit_up": realistic,
        },
        "realistic_minus_baseline": deltas,
        "average_minus_baseline": {
            key: {
                metric: average_only[key][metric] - baseline[key][metric]
                for metric in deltas[key]
            }
            for key in STRATEGIES
        },
        "limit_filter_minus_average": {
            key: {
                metric: realistic[key][metric] - average_only[key][metric]
                for metric in deltas[key]
            }
            for key in STRATEGIES
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--dividend-history", type=Path, required=True)
    parser.add_argument("--limit-path", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", default="2018-07-02")
    args = parser.parse_args()
    result = run(args.data_root, args.dividend_history, args.limit_path, args.start)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
