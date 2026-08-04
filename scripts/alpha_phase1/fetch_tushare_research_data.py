"""Fetch point-in-time research supplements from Tushare Pro.

Data is written as immutable request shards plus reproducible aggregate Parquet
files.  Re-running skips valid shards, so interrupted jobs resume naturally.
The token is read from ``TUSHARE_TOKEN`` or a local YAML config and is never
written to logs or manifests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import tushare as ts
import yaml


@dataclass(frozen=True, slots=True)
class RequestTask:
    dataset: str
    key: str
    api_name: str
    params: dict[str, str]
    required_columns: tuple[str, ...]
    allow_empty: bool = False


class SlidingWindowRateLimiter:
    def __init__(self, calls_per_minute: int) -> None:
        self._limit = calls_per_minute
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < self._limit:
                    self._calls.append(now)
                    return
                wait_seconds = 60.0 - (now - self._calls[0]) + 0.05
            time.sleep(wait_seconds)


def load_token(config_path: Path | None) -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        return token
    if config_path is None:
        raise RuntimeError("Set TUSHARE_TOKEN or provide --config")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    token = str(config.get("data", {}).get("token", "")).strip()
    if not token:
        raise RuntimeError("Tushare token is missing from the selected config")
    return token


def validate_frame(frame: pd.DataFrame, task: RequestTask) -> None:
    if frame.empty and task.allow_empty:
        return
    missing = set(task.required_columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{task.api_name} missing required columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{task.api_name} returned no rows for {task.params}")


def write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def fetch_one(
    task: RequestTask,
    output_dir: Path,
    token: str,
    limiter: SlidingWindowRateLimiter,
    max_attempts: int,
) -> dict[str, Any]:
    shard = output_dir / "shards" / task.dataset / f"{task.key}.parquet"
    if shard.exists():
        cached = pd.read_parquet(shard)
        validate_frame(cached, task)
        return {"task": asdict(task), "status": "cached", "rows": len(cached), "path": str(shard)}

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            limiter.acquire()
            frame = getattr(ts.pro_api(token), task.api_name)(**task.params)
            validate_frame(frame, task)
            write_parquet_atomic(frame, shard)
            return {
                "task": asdict(task),
                "status": "fetched",
                "attempts": attempt,
                "rows": len(frame),
                "path": str(shard),
            }
        except Exception as exc:  # SDK wraps server and transport errors inconsistently.
            last_error = exc
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
    assert last_error is not None
    return {
        "task": asdict(task),
        "status": "error",
        "attempts": max_attempts,
        "error_type": type(last_error).__name__,
        "message": str(last_error),
    }


def run_tasks(
    tasks: list[RequestTask],
    output_dir: Path,
    token: str,
    calls_per_minute: int,
    workers: int,
    max_attempts: int,
) -> list[dict[str, Any]]:
    limiter = SlidingWindowRateLimiter(calls_per_minute)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_one, task, output_dir, token, limiter, max_attempts): task
            for task in tasks
        }
        for number, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if number % 25 == 0 or result["status"] == "error":
                print(
                    json.dumps(
                        {
                            "event": "fetch_progress",
                            "completed": number,
                            "total": len(tasks),
                            "errors": sum(item["status"] == "error" for item in results),
                        }
                    ),
                    flush=True,
                )
    return results


def combine_shards(output_dir: Path, dataset: str) -> Path:
    paths = sorted((output_dir / "shards" / dataset).glob("*.parquet"))
    if not paths:
        raise ValueError(f"no shards found for {dataset}")
    frames = [pd.read_parquet(path) for path in paths]
    combined = pd.concat(frames, ignore_index=True).drop_duplicates()
    sort_columns = [
        column
        for column in ("trade_date", "cal_date", "ts_code", "con_code", "index_code", "l1_code")
        if column in combined.columns
    ]
    if sort_columns:
        combined = combined.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    destination = output_dir / f"{dataset}.parquet"
    write_parquet_atomic(combined, destination)
    return destination


def file_summary(path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result: dict[str, Any] = {
        "path": str(path),
        "sha256": digest,
        "rows": len(frame),
        "columns": list(frame.columns),
    }
    for date_column in ("trade_date", "cal_date", "list_date", "in_date", "out_date"):
        if date_column in frame.columns:
            values = frame[date_column].dropna().astype(str)
            values = values[values != ""]
            if not values.empty:
                result[f"{date_column}_min"] = values.min()
                result[f"{date_column}_max"] = values.max()
    return result


def make_task(
    dataset: str,
    key: str,
    api_name: str,
    params: dict[str, str],
    required_columns: Iterable[str],
    *,
    allow_empty: bool = False,
) -> RequestTask:
    return RequestTask(dataset, key, api_name, params, tuple(required_columns), allow_empty)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20160101")
    parser.add_argument("--end-date", default="20260727")
    parser.add_argument("--research-start-date", default="20180701")
    parser.add_argument("--calls-per-minute", type=int, default=180)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.calls_per_minute <= 200:
        raise ValueError("calls-per-minute must be between 1 and the 3000-point limit of 200")
    if not 1 <= args.workers <= 8:
        raise ValueError("workers must be between 1 and 8")

    token = load_token(args.config)
    base_columns = ("ts_code", "symbol", "name", "market", "list_date", "delist_date")
    seed_tasks = [
        *[
            make_task(
                "stock_basic",
                status,
                "stock_basic",
                {
                    "exchange": "",
                    "list_status": status,
                    "fields": "ts_code,symbol,name,area,industry,market,list_date,delist_date,list_status",
                },
                (*base_columns, "list_status"),
                allow_empty=status == "P",
            )
            for status in ("L", "D", "P")
        ],
        make_task(
            "trade_cal",
            f"{args.start_date}_{args.end_date}",
            "trade_cal",
            {"exchange": "SSE", "start_date": args.start_date, "end_date": args.end_date},
            ("exchange", "cal_date", "is_open", "pretrade_date"),
        ),
        make_task(
            "index_classify",
            "SW2021_L1",
            "index_classify",
            {"level": "L1", "src": "SW2021"},
            ("index_code", "industry_name", "level", "src"),
        ),
    ]
    seed_results = run_tasks(
        seed_tasks,
        args.output_dir,
        token,
        args.calls_per_minute,
        min(args.workers, len(seed_tasks)),
        args.max_attempts,
    )
    if any(item["status"] == "error" for item in seed_results):
        raise SystemExit(json.dumps(seed_results, ensure_ascii=False, indent=2))

    stock_basic_path = combine_shards(args.output_dir, "stock_basic")
    trade_cal_path = combine_shards(args.output_dir, "trade_cal")
    classify_path = combine_shards(args.output_dir, "index_classify")
    calendar = pd.read_parquet(trade_cal_path)
    open_dates = calendar.loc[calendar["is_open"].astype(str) == "1", "cal_date"].astype(str)
    month_ends = sorted(open_dates.groupby(open_dates.str[:6]).max().tolist())
    industries = pd.read_parquet(classify_path)["index_code"].dropna().astype(str).unique()
    stock_basic = pd.read_parquet(stock_basic_path)

    tasks: list[RequestTask] = []
    daily_fields = (
        "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
        "total_share,float_share,free_share,total_mv,circ_mv"
    )
    for trade_date in month_ends:
        tasks.append(
            make_task(
                "daily_basic_month_end",
                trade_date,
                "daily_basic",
                {"trade_date": trade_date, "fields": daily_fields},
                ("ts_code", "trade_date", "total_mv", "circ_mv"),
            )
        )
        tasks.append(
            make_task(
                "stock_st_month_end",
                trade_date,
                "stock_st",
                {"trade_date": trade_date},
                ("ts_code", "trade_date", "type"),
                allow_empty=True,
            )
        )
    for index_code in ("000300.SH", "000905.SH", "000852.SH"):
        for month_end in month_ends:
            month = month_end[:6]
            tasks.append(
                make_task(
                    f"index_weight_{index_code.replace('.', '_')}",
                    month,
                    "index_weight",
                    {
                        "index_code": index_code,
                        "start_date": f"{month}01",
                        "end_date": month_end,
                    },
                    ("index_code", "con_code", "trade_date", "weight"),
                    allow_empty=True,
                )
            )
    for industry_code in sorted(industries):
        for is_new in ("Y", "N"):
            tasks.append(
                make_task(
                    "index_members_sw2021",
                    f"{industry_code.replace('.', '_')}_{is_new}",
                    "index_member_all",
                    {"l1_code": industry_code, "is_new": is_new},
                    ("l1_code", "ts_code", "in_date", "out_date", "is_new"),
                    allow_empty=is_new == "N",
                )
            )

    delist_dates = stock_basic["delist_date"].fillna("").astype(str)
    delisted = stock_basic.loc[
        (stock_basic["list_status"] == "D") & (delist_dates >= args.research_start_date)
    ]
    for row in delisted.itertuples(index=False):
        start_date = max(args.research_start_date, str(row.list_date))
        end_date = min(args.end_date, str(row.delist_date))
        key = str(row.ts_code).replace(".", "_")
        tasks.append(
            make_task(
                "delisted_daily",
                key,
                "daily",
                {
                    "ts_code": str(row.ts_code),
                    "start_date": start_date,
                    "end_date": end_date,
                    "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
                },
                ("ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"),
                allow_empty=True,
            )
        )
        tasks.append(
            make_task(
                "delisted_adj_factor",
                key,
                "adj_factor",
                {"ts_code": str(row.ts_code), "start_date": start_date, "end_date": end_date},
                ("ts_code", "trade_date", "adj_factor"),
            )
        )

    results = run_tasks(
        tasks,
        args.output_dir,
        token,
        args.calls_per_minute,
        args.workers,
        args.max_attempts,
    )
    errors = [item for item in results if item["status"] == "error"]
    if errors:
        error_path = args.output_dir / "fetch_errors.json"
        error_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"{len(errors)} fetch tasks failed; see {error_path}")

    datasets = [
        "daily_basic_month_end",
        "stock_st_month_end",
        "index_weight_000300_SH",
        "index_weight_000905_SH",
        "index_weight_000852_SH",
        "index_members_sw2021",
        "delisted_daily",
        "delisted_adj_factor",
    ]
    aggregate_paths = [stock_basic_path, trade_cal_path, classify_path]
    aggregate_paths.extend(combine_shards(args.output_dir, dataset) for dataset in datasets)
    manifest = {
        "version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Tushare Pro Python SDK",
        "tushare_version": ts.__version__,
        "window": {"start_date": args.start_date, "end_date": args.end_date},
        "research_start_date": args.research_start_date,
        "documented_account_limit_calls_per_minute": 200,
        "configured_calls_per_minute": args.calls_per_minute,
        "workers": args.workers,
        "request_tasks": len(seed_tasks) + len(tasks),
        "fetched_tasks": sum(item["status"] == "fetched" for item in seed_results + results),
        "cached_tasks": sum(item["status"] == "cached" for item in seed_results + results),
        "files": [file_summary(path) for path in aggregate_paths],
        "documentation": {
            "frequency": "https://tushare.pro/document/1?doc_id=290",
            "daily_basic": "https://tushare.pro/document/2?doc_id=32",
            "index_weight": "https://tushare.pro/document/2?doc_id=96",
            "index_member_all": "https://tushare.pro/document/2?doc_id=335",
            "stock_st": "https://tushare.pro/document/2?doc_id=397",
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
