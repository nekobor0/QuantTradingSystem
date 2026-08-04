"""Matched event study for the frozen first-sealed-limit-up hypothesis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.event_evaluation import summarize_matched_events
from quant_trading_system.research.alpha_phase1.short_horizon import HORIZONS
from scripts.alpha_phase1.evaluate_short_horizon_v3 import assign_industry


CORE_HORIZON = 5
COST = 0.0005


def bucket(values: pd.Series, groups: int = 3) -> pd.Series:
    ranks = values.rank(method="first", pct=True)
    return np.minimum((ranks * groups).astype(int), groups - 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", type=int, default=3)
    args = parser.parse_args()

    columns = ["ts_code", "signal_date", "momentum_12_1", *[f"forward_return_{h}" for h in HORIZONS]]
    frame = pd.read_parquet(args.panel, columns=columns)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"])
    basic = pd.read_parquet(
        args.tushare_dir / "daily_basic_full.parquet",
        columns=["ts_code", "trade_date", "circ_mv"],
    )
    basic["signal_date"] = pd.to_datetime(basic.pop("trade_date").astype(str))
    frame = frame.merge(basic, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    frame["l1_code"] = assign_industry(
        frame, pd.read_parquet(args.tushare_dir / "index_members_sw2021.parquet")
    )
    st_manifest = json.loads(
        (args.tushare_dir / "stock_st_full_available_manifest.json").read_text(encoding="utf-8")
    )
    frame = frame.loc[~frame["signal_date"].isin(pd.to_datetime(st_manifest["excluded_source_gap_days"]))].copy()
    events = pd.read_parquet(args.events, columns=["ts_code", "signal_date"])
    events["signal_date"] = pd.to_datetime(events["signal_date"])
    events = events.assign(is_event=True)
    frame = frame.merge(events, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    frame["is_event"] = frame["is_event"].fillna(False).astype(bool)

    event_rows: list[pd.DataFrame] = []
    for date, group in frame.groupby("signal_date", sort=True):
        usable = group.dropna(subset=["circ_mv", "momentum_12_1", "l1_code", f"forward_return_{CORE_HORIZON}"]).copy()
        if len(usable) < 100 or not usable["is_event"].any():
            continue
        usable["size_bucket"] = bucket(np.log(usable["circ_mv"].where(usable["circ_mv"] > 0)))
        usable["momentum_bucket"] = bucket(usable["momentum_12_1"])
        controls = usable.loc[~usable["is_event"]]
        event = usable.loc[usable["is_event"]].copy()
        match_keys = ["l1_code", "size_bucket", "momentum_bucket"]
        for horizon in (1, 2, 3, 5, 10):
            label = f"forward_return_{horizon}"
            means = controls.dropna(subset=[label]).groupby(match_keys)[label].agg(["mean", "count"])
            means = means.rename(columns={"mean": f"match_{horizon}", "count": f"match_count_{horizon}"})
            event = event.merge(means, left_on=match_keys, right_index=True, how="left", validate="many_to_one")
            market = float(usable[label].mean())
            event[f"matched_car_{horizon}"] = (
                event[label] - event[f"match_{horizon}"] - COST
            ).where(event[f"match_count_{horizon}"].ge(5))
            event[f"market_car_{horizon}"] = event[label] - market - COST
        event_rows.append(event)
    matched = pd.concat(event_rows, ignore_index=True) if event_rows else pd.DataFrame()
    horizon_results = {str(h): summarize_matched_events(matched, h) for h in (1, 2, 3, 5, 10)}
    recent_years = [2023, 2024, 2025]
    counts = {
        str(year): int(matched.loc[matched["signal_date"].dt.year.eq(year), f"matched_car_{CORE_HORIZON}"].notna().sum())
        for year in recent_years
    }
    core = horizon_results[str(CORE_HORIZON)]
    checks = {
        "core_5d_matched_car_positive": core["matched_car"]["mean"] is not None and core["matched_car"]["mean"] > 0,
        "core_5d_matched_hac_t_gt_2_5": core["matched_car"]["t_stat_hac"] is not None and core["matched_car"]["t_stat_hac"] > 2.5,
        "each_recent_complete_year_events_gt_50": all(value > 50 for value in counts.values()),
        "event_specific_share_gt_70pct": core["event_specific_share"] is not None and core["event_specific_share"] > 0.70,
        "style_share_lt_30pct": core["style_share"] is not None and core["style_share"] < 0.30,
    }
    payload = {
        "version": args.version,
        "event": "first_sealed_limit_up",
        "entry_price": "T+1 open" if args.version >= 4 else "T+1 close",
        "hypothesis": "A-share price limits delay positive information discovery; first sealed limit-up predicts positive matched T+1-to-T+5 CAR",
        "matching": "same SW L1 industry, same daily circ-mv tercile, same 12-1 momentum tercile; at least five non-event controls",
        "fixed_two_way_cost": COST,
        "core_horizon": CORE_HORIZON,
        "horizons": horizon_results,
        "recent_complete_year_event_counts": counts,
        "gate_checks": {name: bool(value) for name, value in checks.items()},
        "passes_all_gates": bool(all(checks.values())),
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"events": len(matched), "pass": payload["passes_all_gates"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
