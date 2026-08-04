"""Build first-sealed-limit-up events from official daily price limits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1 import parse_research_series
from quant_trading_system.research.alpha_phase1.event_evaluation import identify_first_sealed_limit_up


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tdx-raw", type=Path, required=True)
    parser.add_argument("--tdx-audit", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--start", default="2018-07-01")
    parser.add_argument("--end", default="2026-06-30")
    args = parser.parse_args()

    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    limits = pd.read_parquet(
        args.tushare_dir / "stk_limit_full.parquet",
        columns=["ts_code", "trade_date", "up_limit"],
    )
    limits["signal_date"] = pd.to_datetime(limits.pop("trade_date").astype(str))
    limit_groups = {str(code): group.drop(columns="ts_code") for code, group in limits.groupby("ts_code", sort=False)}
    selected = json.loads(args.tdx_audit.read_text(encoding="utf-8"))["selected"]
    rows: list[pd.DataFrame] = []
    for number, (symbol, details) in enumerate(sorted(selected.items()), start=1):
        if symbol not in limit_groups:
            continue
        payload = json.loads((args.tdx_raw / details["file"]).read_text(encoding="utf-8"))
        series = next(item for item in parse_research_series(payload) if item.symbol == symbol)
        price = pd.DataFrame(
            {
                "signal_date": pd.to_datetime(series.dates),
                "close": series.close,
                "volume": series.volume,
            }
        ).sort_values("signal_date")
        price["trading_age"] = range(len(price))
        merged = price.merge(limit_groups[symbol], on="signal_date", how="inner", validate="one_to_one")
        merged["event"] = identify_first_sealed_limit_up(merged)
        event = merged.loc[
            merged["event"] & merged["trading_age"].ge(10)
            & merged["signal_date"].between(start, end),
            ["signal_date", "close", "up_limit", "trading_age"],
        ].copy()
        if len(event):
            event.insert(0, "ts_code", symbol)
            rows.append(event)
        if number % 1000 == 0:
            print(json.dumps({"event": "limit_event_progress", "symbols": number}), flush=True)
    events = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    events = events.drop_duplicates(["ts_code", "signal_date"]).sort_values(["signal_date", "ts_code"])
    events.to_parquet(args.output, index=False, compression="zstd")
    metadata = {
        "version": 3,
        "event": "first_sealed_limit_up",
        "rows": len(events),
        "symbols": int(events["ts_code"].nunique()) if len(events) else 0,
        "days": int(events["signal_date"].nunique()) if len(events) else 0,
        "protocol": "close equals official up_limit within 0.001; prior trading day not sealed; positive volume; at least 10 observed trading sessions",
        "hypothesis": "A-share price limits delay positive information discovery; first sealed limit-up predicts positive matched T+1-to-T+5 CAR",
    }
    args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
