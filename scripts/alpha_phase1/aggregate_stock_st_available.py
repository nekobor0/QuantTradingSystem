"""Aggregate verified ST shards while explicitly excluding unresolved source-gap dates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20180701")
    parser.add_argument("--end-date", default="20260729")
    args = parser.parse_args()

    calendar = pd.read_parquet(args.tushare_dir / "trade_cal.parquet")
    expected = sorted(
        calendar.loc[
            calendar["is_open"].astype(str).eq("1")
            & calendar["cal_date"].astype(str).between(args.start_date, args.end_date),
            "cal_date",
        ].astype(str)
    )
    shard_dir = args.tushare_dir / "shards" / "stock_st_full"
    paths = {path.stem: path for path in shard_dir.glob("*.parquet")}
    available = [date for date in expected if date in paths]
    excluded = [date for date in expected if date not in paths]
    frames = [pd.read_parquet(paths[date]) for date in available]
    frame = pd.concat(frames, ignore_index=True)
    before = len(frame)
    frame = frame.drop_duplicates(["trade_date", "ts_code"]).sort_values(["trade_date", "ts_code"])
    output = args.tushare_dir / "stock_st_full_available.parquet"
    frame.to_parquet(output, index=False, compression="zstd")
    manifest = {
        "path": str(output),
        "expected_days": len(expected),
        "available_days": len(available),
        "excluded_source_gap_days": excluded,
        "excluded_day_share": len(excluded) / len(expected),
        "rows": len(frame),
        "symbols": int(frame["ts_code"].nunique()),
        "duplicates_removed": before - len(frame),
        "policy": "exclude entire signal date; never treat a failed/empty API response as no ST stocks",
    }
    (args.tushare_dir / "stock_st_full_available_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
