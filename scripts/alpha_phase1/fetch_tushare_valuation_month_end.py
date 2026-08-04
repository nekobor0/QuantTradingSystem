"""Fetch checkpointed month-end valuation fields from Tushare daily_basic."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import tushare as ts

from fetch_tushare_supplemental_data import IntervalLimiter, load_token, request, save_frame


COLUMNS = [
    "ts_code", "trade_date", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
    "dv_ratio", "dv_ttm", "total_mv",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--start", default="20160701")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--calls-per-minute", type=int, default=120)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    pro = ts.pro_api(load_token(args.config))
    limiter = IntervalLimiter(args.calls_per_minute)
    calendar = pd.read_parquet(args.tushare_dir / "trade_cal.parquet")
    opens = calendar.loc[calendar["is_open"].astype(str) == "1", "cal_date"].astype(str)
    dates = pd.Series(sorted(date for date in opens if args.start <= date <= args.end))
    dates = dates.groupby(pd.to_datetime(dates).dt.to_period("M")).max().tolist()
    shard_dir = args.tushare_dir / "shards" / "daily_valuation_month_end"
    pending = [date for date in dates if not (shard_dir / f"{date}.parquet").exists()]

    def one(date: str) -> tuple[str, int]:
        frame = request(
            pro,
            limiter,
            "daily_basic",
            trade_date=date,
            fields=",".join(COLUMNS),
        )
        if frame.empty:
            raise RuntimeError(f"daily_basic valuation unexpectedly empty for {date}")
        save_frame(frame, shard_dir / f"{date}.parquet", COLUMNS)
        return date, len(frame)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(one, date) for date in pending]
        for number, future in enumerate(as_completed(futures), start=1):
            date, rows = future.result()
            if number % 20 == 0 or number == len(futures):
                print(json.dumps({"event": "valuation_progress", "completed": number, "pending": len(pending), "latest": date, "rows": rows}), flush=True)
    frames = [pd.read_parquet(path) for path in sorted(shard_dir.glob("*.parquet"))]
    frame = pd.concat(frames, ignore_index=True).drop_duplicates(["ts_code", "trade_date"])
    output = args.tushare_dir / "daily_valuation_month_end.parquet"
    frame.sort_values(["trade_date", "ts_code"]).to_parquet(output, index=False)
    print(json.dumps({"files": len(frames), "rows": len(frame), "symbols": int(frame.ts_code.nunique())}), flush=True)


if __name__ == "__main__":
    main()
