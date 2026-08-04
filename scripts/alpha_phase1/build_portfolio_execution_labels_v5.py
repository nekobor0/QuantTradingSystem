"""Build monthly open-to-open mark returns and rebalance tradability flags."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1.portfolio_execution import (
    sample_monthly_execution,
)
from quant_trading_system.research.alpha_phase1.slow_horizon import horizon_dates

from build_slow_horizon_labels_v4 import _daily_from_raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, default=Path("artifacts/alpha_phase1/factor_panel_style_baseline_v5.parquet"))
    parser.add_argument("--trade-cal", type=Path, default=Path("artifacts/alpha_phase1/tushare/trade_cal.parquet"))
    parser.add_argument("--tushare-dir", type=Path, default=Path("artifacts/alpha_phase1/tushare"))
    parser.add_argument("--tdx-raw", type=Path, default=Path("artifacts/tdx_bridge/raw"))
    parser.add_argument("--tdx-audit", type=Path, default=Path("artifacts/alpha_phase1/tdx_research_raw_audit.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/alpha_phase1/portfolio_execution_labels_v5.parquet"))
    parser.add_argument("--metadata", type=Path, default=Path("artifacts/alpha_phase1/portfolio_execution_labels_v5_metadata.json"))
    args = parser.parse_args()

    keys = pd.read_parquet(args.base_panel, columns=["ts_code", "signal_date"])
    keys["signal_date"] = pd.to_datetime(keys["signal_date"])
    signal_dates = sorted(pd.Timestamp(value) for value in keys["signal_date"].unique())
    calendar = pd.read_parquet(args.trade_cal)
    open_dates = pd.to_datetime(
        calendar.loc[calendar["is_open"].astype(str).eq("1"), "cal_date"].astype(str)
    ).sort_values().tolist()
    entry, exits = horizon_dates(open_dates, signal_dates, horizons=(1,))
    exit_dates = exits[1]

    selected = json.loads(args.tdx_audit.read_text(encoding="utf-8"))["selected"]
    rows = []
    for number, (symbol, details) in enumerate(sorted(selected.items()), start=1):
        labels = sample_monthly_execution(
            _daily_from_raw(args.tdx_raw, symbol, details), signal_dates, entry, exit_dates
        )
        labels.insert(0, "ts_code", symbol)
        rows.append(labels)
        if number % 500 == 0:
            print(json.dumps({"event": "execution_label_progress", "symbols": number}), flush=True)

    daily = pd.read_parquet(args.tushare_dir / "delisted_daily.parquet")
    factors = pd.read_parquet(args.tushare_dir / "delisted_adj_factor.parquet")
    delisted = daily.merge(factors, on=["ts_code", "trade_date"], how="inner", validate="one_to_one")
    for symbol, group in delisted.groupby("ts_code", sort=True):
        source = group.rename(columns={"trade_date": "date", "vol": "volume", "adj_factor": "factor"})
        source["date"] = pd.to_datetime(source["date"].astype(str))
        labels = sample_monthly_execution(source, signal_dates, entry, exit_dates)
        labels.insert(0, "ts_code", str(symbol))
        rows.append(labels)

    generated = pd.concat(rows, ignore_index=True)
    output = keys.merge(generated, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    output.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    payload = {
        "version": 5,
        "rows": int(len(output)),
        "duplicate_keys": int(output.duplicated(["ts_code", "signal_date"]).sum()),
        "signal_months": int(output["signal_date"].nunique()),
        "mark_return_coverage": float(output["mark_return_1m"].notna().mean()),
        "entry_tradable_rate": float(output["entry_tradable"].fillna(False).mean()),
        "exit_tradable_rate": float(output["exit_tradable"].fillna(False).mean()),
        "label": "T month-end signal; next trading-day adjusted open entry; next rebalance next-trading-day adjusted open mark",
        "note": "mark return uses adjusted open when quoted; a missing entry/exit quote for an existing holding uses last adjusted close at or before rebalance, and simulator carries non-delisted unsellable positions",
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
