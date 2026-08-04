"""Build material key-holder net-purchase announcement events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.event_evaluation import (
    keep_events_after_cooldown,
    map_to_effective_trading_date,
)


MATERIAL_NET_RATIO = 0.1
COOLDOWN_DAYS = 30


def aggregate_net_purchase(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce")
    frame["change_ratio"] = pd.to_numeric(frame["change_ratio"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "ann_date", "in_de", "change_ratio"])
    frame["signed_ratio"] = np.where(frame["in_de"].eq("IN"), 1.0, -1.0) * frame[
        "change_ratio"
    ].abs()
    return frame.groupby(["ts_code", "ann_date"], as_index=False)["signed_ratio"].sum()


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
        args.tushare_dir / "stk_holdertrade.parquet",
        columns=["ts_code", "ann_date", "in_de", "change_ratio"],
    )
    events = aggregate_net_purchase(raw)
    events = events.loc[events["signed_ratio"].ge(MATERIAL_NET_RATIO)].copy()
    events["signal_date"] = map_to_effective_trading_date(events["ann_date"], calendar)
    events = events.dropna(subset=["signal_date"])
    events = events.loc[keep_events_after_cooldown(events, COOLDOWN_DAYS)]
    events = events.drop_duplicates(["ts_code", "signal_date"]).sort_values(
        ["signal_date", "ts_code"]
    )
    events.to_parquet(args.output, index=False, compression="zstd")

    payload = {
        "version": 3,
        "event": "material_key_holder_net_purchase",
        "rows": len(events),
        "symbols": int(events["ts_code"].nunique()),
        "days": int(events["signal_date"].nunique()),
        "protocol": "same stock-announcement date sums signed actual change ratios (IN positive, DE negative); net purchase >=0.1 percentage point; same-stock 30-calendar-day cooldown; no holder-type weighting",
        "availability": "announcement maps to first trading date on or after ann_date; entry remains next trading-day close",
        "hypothesis": "Material net purchases by key holders reveal informed conviction and predict positive matched T+1-to-T+20 CAR in A shares",
    }
    args.metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
