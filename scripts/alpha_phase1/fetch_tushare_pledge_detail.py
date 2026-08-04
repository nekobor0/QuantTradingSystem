"""Checkpointed per-stock Tushare pledge-detail fetch for PIT research."""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts

from scripts.alpha_phase1.fetch_tushare_supplemental_data import load_token


COLUMNS = [
    "ts_code", "ann_date", "holder_name", "pledge_amount", "start_date",
    "end_date", "is_release", "release_date", "pledgor", "holding_amount",
    "pledged_amount", "p_total_ratio", "h_total_ratio", "is_buyback",
]


class IntervalLimiter:
    def __init__(self, calls_per_minute: int) -> None:
        self.interval = 60.0 / calls_per_minute
        self.lock = threading.Lock()
        self.next_call = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_call - now)
            self.next_call = max(now, self.next_call) + self.interval
        if delay:
            time.sleep(delay)


def fetch_one(pro: Any, limiter: IntervalLimiter, ts_code: str, path: Path) -> int:
    error: Exception | None = None
    for attempt in range(3):
        limiter.wait()
        try:
            frame = pro.pledge_detail(ts_code=ts_code)
            for column in COLUMNS:
                if column not in frame:
                    frame[column] = pd.NA
            frame[COLUMNS].to_parquet(path, index=False)
            return len(frame)
        except Exception as exc:
            error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"pledge_detail failed for {ts_code}: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--stock-basic", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--calls-per-minute", type=int, default=180)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    codes = sorted(pd.read_parquet(args.stock_basic, columns=["ts_code"])["ts_code"].dropna().unique())
    shard_dir = args.tushare_dir / "shards" / "pledge_detail"
    shard_dir.mkdir(parents=True, exist_ok=True)
    pending = [code for code in codes if not (shard_dir / f"{code}.parquet").exists()]
    pro = ts.pro_api(load_token(args.config))
    limiter = IntervalLimiter(args.calls_per_minute)
    print(json.dumps({"event": "start", "stocks": len(codes), "pending": len(pending)}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(fetch_one, pro, limiter, code, shard_dir / f"{code}.parquet"): code
            for code in pending
        }
        for number, future in enumerate(as_completed(futures), start=1):
            rows = future.result()
            if number % 100 == 0 or number == len(futures):
                print(json.dumps({"event": "progress", "completed": number, "pending_total": len(pending), "latest": futures[future], "latest_rows": rows}), flush=True)

    frames = [pd.read_parquet(path) for path in sorted(shard_dir.glob("*.parquet"))]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    before = len(frame)
    keys = ["ts_code", "ann_date", "holder_name", "start_date", "pledge_amount", "is_release", "release_date"]
    frame = frame.drop_duplicates(keys).sort_values(keys, na_position="last")
    output = args.tushare_dir / "pledge_detail.parquet"
    frame.to_parquet(output, index=False, compression="zstd")
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stocks": len(codes),
        "shards": len(frames),
        "rows": len(frame),
        "duplicates_removed": before - len(frame),
        "symbols_with_rows": int(frame["ts_code"].nunique()),
        "missing_ann_date": int(frame["ann_date"].isna().sum()),
    }
    (args.tushare_dir / "pledge_detail_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
