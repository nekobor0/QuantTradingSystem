"""Checkpointed Tushare fetch for Phase 1 money-flow and holder-count data."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import tushare as ts
import yaml


MONEYFLOW_COLUMNS = [
    "ts_code", "trade_date", "buy_sm_vol", "buy_sm_amount", "sell_sm_vol",
    "sell_sm_amount", "buy_md_vol", "buy_md_amount", "sell_md_vol",
    "sell_md_amount", "buy_lg_vol", "buy_lg_amount", "sell_lg_vol",
    "sell_lg_amount", "buy_elg_vol", "buy_elg_amount", "sell_elg_vol",
    "sell_elg_amount", "net_mf_vol", "net_mf_amount",
]
HOLDER_COLUMNS = ["ts_code", "ann_date", "end_date", "holder_num"]


def load_token(config_path: Path) -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        return token
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    token = str(config.get("data", {}).get("token", "")).strip()
    if not token:
        raise RuntimeError("Tushare token is missing")
    return token


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


def request(pro: Any, limiter: IntervalLimiter, api: str, **params: str) -> pd.DataFrame:
    error: Exception | None = None
    for attempt in range(3):
        limiter.wait()
        try:
            return getattr(pro, api)(**params)
        except Exception as exc:  # Tushare raises generic exceptions for server errors.
            error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{api} failed after 3 attempts: {error}") from error


def save_frame(frame: pd.DataFrame, path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for column in columns:
        if column not in frame:
            frame[column] = pd.NA
    frame[columns].to_parquet(path, index=False)


def fetch_moneyflow(
    pro: Any,
    limiter: IntervalLimiter,
    dates: list[str],
    shard_dir: Path,
    workers: int,
) -> None:
    pending = [date for date in dates if not (shard_dir / f"{date}.parquet").exists()]
    print(json.dumps({"event": "moneyflow_start", "total": len(dates), "pending": len(pending)}), flush=True)

    def one(date: str) -> tuple[str, int]:
        frame = pd.DataFrame()
        for attempt in range(3):
            frame = request(pro, limiter, "moneyflow", trade_date=date)
            if not frame.empty:
                break
            if attempt < 2:
                time.sleep(2 ** attempt)
        if frame.empty:
            raise RuntimeError(f"moneyflow returned an unexpected empty frame for open date {date}")
        save_frame(frame, shard_dir / f"{date}.parquet", MONEYFLOW_COLUMNS)
        return date, len(frame)

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(one, date) for date in pending]
        for future in as_completed(futures):
            date, rows = future.result()
            completed += 1
            if completed % 50 == 0 or completed == len(pending):
                print(json.dumps({"event": "moneyflow_progress", "completed": completed, "pending_total": len(pending), "latest": date, "latest_rows": rows}), flush=True)


def fetch_holder_range(
    pro: Any,
    limiter: IntervalLimiter,
    start: pd.Timestamp,
    end: pd.Timestamp,
    shard_dir: Path,
) -> int:
    key = f"{start:%Y%m%d}_{end:%Y%m%d}"
    path = shard_dir / f"{key}.parquet"
    if path.exists():
        return 0
    frame = request(
        pro,
        limiter,
        "stk_holdernumber",
        start_date=f"{start:%Y%m%d}",
        end_date=f"{end:%Y%m%d}",
    )
    if len(frame) >= 3000 and start < end:
        midpoint = start + (end - start) // 2
        calls = fetch_holder_range(pro, limiter, start, midpoint, shard_dir)
        calls += fetch_holder_range(pro, limiter, midpoint + pd.Timedelta(days=1), end, shard_dir)
        return calls + 1
    save_frame(frame, path, HOLDER_COLUMNS)
    return 1


def aggregate(shard_dir: Path, output: Path, keys: list[str]) -> dict[str, Any]:
    files = sorted(shard_dir.glob("*.parquet"))
    frames = [pd.read_parquet(path) for path in files]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    before = len(frame)
    if not frame.empty:
        frame = frame.drop_duplicates(keys).sort_values(keys)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False)
    return {
        "files": len(files),
        "rows": len(frame),
        "duplicates_removed": before - len(frame),
        "symbols": int(frame["ts_code"].nunique()) if "ts_code" in frame else 0,
    }


def quarantine_empty_moneyflow(shard_dir: Path) -> int:
    quarantined = 0
    for path in shard_dir.glob("*.parquet"):
        if pq.ParquetFile(path).metadata.num_rows == 0:
            target = path.with_suffix(f".unexpected_empty_{time.time_ns()}")
            path.rename(target)
            quarantined += 1
    return quarantined


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--start", default="20180501")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--calls-per-minute", type=int, default=180)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    token = load_token(args.config)
    pro = ts.pro_api(token)
    limiter = IntervalLimiter(args.calls_per_minute)
    calendar = pd.read_parquet(args.tushare_dir / "trade_cal.parquet")
    dates = calendar.loc[calendar["is_open"].astype(str) == "1", "cal_date"].astype(str)
    dates = sorted(date for date in dates if args.start <= date <= args.end)
    shards = args.tushare_dir / "shards"
    quarantined = quarantine_empty_moneyflow(shards / "moneyflow")
    if quarantined:
        print(json.dumps({"event": "moneyflow_empty_quarantine", "files": quarantined}), flush=True)
    fetch_moneyflow(pro, limiter, dates, shards / "moneyflow", args.workers)

    months = pd.period_range(args.start[:6], args.end[:6], freq="M")
    holder_calls = 0
    ranges = []
    for month in months:
        start = max(month.start_time, pd.Timestamp(args.start))
        end = min(month.end_time.normalize(), pd.Timestamp(args.end))
        ranges.append((start, end))
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(fetch_holder_range, pro, limiter, start, end, shards / "stk_holdernumber")
            for start, end in ranges
        ]
        for number, future in enumerate(as_completed(futures), start=1):
            holder_calls += future.result()
            if number % 12 == 0 or number == len(futures):
                print(json.dumps({"event": "holder_progress", "months": number, "total_months": len(futures), "new_calls": holder_calls}), flush=True)

    moneyflow = aggregate(shards / "moneyflow", args.tushare_dir / "moneyflow.parquet", ["ts_code", "trade_date"])
    holder = aggregate(shards / "stk_holdernumber", args.tushare_dir / "stk_holdernumber.parquet", ["ts_code", "ann_date", "end_date"])
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": args.start,
        "end": args.end,
        "calls_per_minute": args.calls_per_minute,
        "moneyflow": moneyflow,
        "stk_holdernumber": holder,
    }
    path = args.tushare_dir / "supplemental_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
