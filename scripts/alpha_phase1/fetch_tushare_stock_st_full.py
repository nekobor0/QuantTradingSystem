"""Fetch resumable daily historical ST flags for the V3 research universe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from scripts.alpha_phase1.fetch_tushare_research_data import (
    combine_shards,
    load_token,
    make_task,
    run_tasks,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20180701")
    parser.add_argument("--end-date", default="20260729")
    parser.add_argument("--calls-per-minute", type=int, default=180)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    calendar = pd.read_parquet(args.tushare_dir / "trade_cal.parquet")
    dates = calendar.loc[
        calendar["is_open"].astype(str).eq("1")
        & calendar["cal_date"].astype(str).between(args.start_date, args.end_date),
        "cal_date",
    ].astype(str)
    required = ("ts_code", "name", "trade_date", "type", "type_name")
    tasks = [
        make_task("stock_st_full", date, "stock_st", {"trade_date": date}, required)
        for date in dates
    ]
    results = run_tasks(tasks, args.tushare_dir, load_token(args.config), args.calls_per_minute, args.workers, 3)
    errors = [result for result in results if result["status"] == "error"]
    if errors:
        path = args.tushare_dir / "stock_st_full_errors.json"
        path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"{len(errors)} stock-ST days failed; see {path}")
    output = combine_shards(args.tushare_dir, "stock_st_full")
    frame = pd.read_parquet(output)
    summary = {
        "path": str(output), "rows": len(frame),
        "days": int(frame["trade_date"].nunique()),
        "symbols": int(frame["ts_code"].nunique()),
        "duplicates": int(frame.duplicated(["trade_date", "ts_code"]).sum()),
        "fetched_days": sum(result["status"] == "fetched" for result in results),
        "cached_days": sum(result["status"] == "cached" for result in results),
    }
    (args.tushare_dir / "stock_st_full_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
