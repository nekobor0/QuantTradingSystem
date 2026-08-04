"""Build resumable-independent slow labels from local adjusted A-share daily data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1 import parse_research_series
from quant_trading_system.research.alpha_phase1.slow_horizon import horizon_dates, sample_slow_labels


def _daily_from_raw(raw_dir: Path, symbol: str, details: dict[str, object]) -> pd.DataFrame:
    payload = json.loads((raw_dir / str(details["file"])).read_text(encoding="utf-8"))
    series = next(item for item in parse_research_series(payload) if item.symbol == symbol)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(series.dates), "open": series.open, "high": series.high,
            "low": series.low, "close": series.close, "volume": series.volume,
            "factor": series.forward_factor,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--trade-cal", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--tdx-raw", type=Path, required=True)
    parser.add_argument("--tdx-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    keys = pd.read_parquet(args.base_panel, columns=["ts_code", "signal_date"])
    keys["signal_date"] = pd.to_datetime(keys["signal_date"])
    signal_dates = sorted(pd.Timestamp(value) for value in keys["signal_date"].unique())
    calendar = pd.read_parquet(args.trade_cal)
    open_dates = pd.to_datetime(
        calendar.loc[calendar["is_open"].astype(str).eq("1"), "cal_date"].astype(str)
    ).sort_values().tolist()
    entry, exits = horizon_dates(open_dates, signal_dates)

    audit = json.loads(args.tdx_audit.read_text(encoding="utf-8"))
    rows = []
    for number, (symbol, details) in enumerate(sorted(audit["selected"].items()), start=1):
        labels = sample_slow_labels(_daily_from_raw(args.tdx_raw, symbol, details), signal_dates, entry, exits)
        labels.insert(0, "ts_code", symbol)
        rows.append(labels)
        if number % 500 == 0:
            print(json.dumps({"event": "slow_label_progress", "symbols": number}), flush=True)

    daily = pd.read_parquet(args.tushare_dir / "delisted_daily.parquet")
    factors = pd.read_parquet(args.tushare_dir / "delisted_adj_factor.parquet")
    delisted = daily.merge(factors, on=["ts_code", "trade_date"], how="inner", validate="one_to_one")
    for symbol, group in delisted.groupby("ts_code", sort=True):
        source = group.rename(columns={"trade_date": "date", "vol": "volume", "adj_factor": "factor"})
        source["date"] = pd.to_datetime(source["date"].astype(str))
        labels = sample_slow_labels(source, signal_dates, entry, exits)
        labels.insert(0, "ts_code", str(symbol))
        rows.append(labels)

    generated = pd.concat(rows, ignore_index=True)
    output = keys.merge(generated, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    output.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(args.output)
    payload = {
        "version": 4,
        "rows": int(len(output)),
        "duplicate_keys": int(output.duplicated(["ts_code", "signal_date"]).sum()),
        "signal_months": int(output["signal_date"].nunique()),
        "label": "T month-end signal; T+1 adjusted open entry; future rebalance T+1 adjusted close exit",
        "coverage": {column: float(output[column].notna().mean()) for column in output if column.startswith("forward_return_")},
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
