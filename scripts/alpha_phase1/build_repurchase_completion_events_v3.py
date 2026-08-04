"""Build material completed-repurchase announcement events without fuzzy plan identifiers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1.event_evaluation import (
    keep_events_after_cooldown,
    map_to_effective_trading_date,
)


MATERIAL_INTENSITY = 0.001
COOLDOWN_DAYS = 30


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()

    calendar = pd.DatetimeIndex(
        pd.read_parquet(args.panel, columns=["signal_date"])["signal_date"].drop_duplicates()
    ).sort_values()
    raw = pd.read_parquet(
        args.tushare_dir / "repurchase.parquet",
        columns=["ts_code", "ann_date", "proc", "amount"],
    )
    raw["ann_date"] = pd.to_datetime(raw["ann_date"], errors="coerce")
    raw["amount"] = pd.to_numeric(raw["amount"], errors="coerce")
    completed = raw.loc[
        raw["proc"].eq("完成") & raw["amount"].gt(0) & raw["ann_date"].notna()
    ].copy()
    completed = completed.groupby(["ts_code", "ann_date"], as_index=False)["amount"].max()
    completed["signal_date"] = map_to_effective_trading_date(completed["ann_date"], calendar)
    completed = completed.dropna(subset=["signal_date"])

    basic = pd.read_parquet(
        args.tushare_dir / "daily_basic_full.parquet",
        columns=["ts_code", "trade_date", "circ_mv"],
    )
    basic["signal_date"] = pd.to_datetime(basic.pop("trade_date").astype(str))
    events = completed.merge(
        basic, on=["ts_code", "signal_date"], how="left", validate="many_to_one"
    )
    events["execution_intensity"] = events["amount"] / (
        events["circ_mv"].where(events["circ_mv"] > 0) * 10000.0
    )
    events = events.loc[events["execution_intensity"].ge(MATERIAL_INTENSITY)].copy()
    events = events.loc[keep_events_after_cooldown(events, COOLDOWN_DAYS)]
    events = events.drop_duplicates(["ts_code", "signal_date"]).sort_values(
        ["signal_date", "ts_code"]
    )
    events.to_parquet(args.output, index=False, compression="zstd")

    payload = {
        "version": 3,
        "event": "material_repurchase_completion",
        "rows": len(events),
        "symbols": int(events["ts_code"].nunique()),
        "days": int(events["signal_date"].nunique()),
        "protocol": "proc=完成; positive final amount; same stock-announcement date uses max cumulative amount; amount/circ_mv >=0.1%; same-stock 30-calendar-day cooldown",
        "availability": "announcement maps to first trading date on or after ann_date; entry remains next trading-day close",
        "hypothesis": "Material completed repurchases are credible management cash-allocation signals and predict positive matched T+1-to-T+20 CAR in A shares",
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
