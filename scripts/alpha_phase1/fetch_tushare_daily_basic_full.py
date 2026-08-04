"""Fetch resumable full daily-basic data needed by the V3 short-horizon evaluator."""

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
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    calendar = pd.read_parquet(args.tushare_dir / "trade_cal.parquet")
    dates = calendar.loc[
        calendar["is_open"].astype(str).eq("1")
        & calendar["cal_date"].astype(str).between(args.start_date, args.end_date),
        "cal_date",
    ].astype(str)
    required = (
        "ts_code", "trade_date", "close", "turnover_rate_f", "volume_ratio",
        "float_share", "free_share", "total_mv", "circ_mv",
    )
    tasks = [
        make_task(
            "daily_basic_full",
            date,
            "daily_basic",
            {"trade_date": date, "fields": ",".join(required)},
            required,
        )
        for date in dates
    ]
    results = run_tasks(
        tasks,
        args.tushare_dir,
        load_token(args.config),
        args.calls_per_minute,
        args.workers,
        args.max_attempts,
    )
    errors = [result for result in results if result["status"] == "error"]
    if errors:
        path = args.tushare_dir / "daily_basic_full_errors.json"
        path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"{len(errors)} daily-basic days failed; see {path}")
    output = combine_shards(args.tushare_dir, "daily_basic_full")
    frame = pd.read_parquet(output, columns=["ts_code", "trade_date"])
    summary = {
        "path": str(output),
        "rows": len(frame),
        "days": int(frame["trade_date"].nunique()),
        "symbols": int(frame["ts_code"].nunique()),
        "duplicates": int(frame.duplicated(["trade_date", "ts_code"]).sum()),
        "fetched_days": sum(result["status"] == "fetched" for result in results),
        "cached_days": sum(result["status"] == "cached" for result in results),
    }
    (args.tushare_dir / "daily_basic_full_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
