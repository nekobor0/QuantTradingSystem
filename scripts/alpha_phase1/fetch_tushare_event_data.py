"""Fetch paginated Tushare event datasets as resumable monthly shards."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import tushare as ts

from scripts.alpha_phase1.fetch_tushare_research_data import (
    SlidingWindowRateLimiter,
    load_token,
    write_parquet_atomic,
)


DATASETS = {
    "repurchase": ("repurchase", ["ts_code", "ann_date", "proc"]),
    "stk_holdertrade": ("stk_holdertrade", ["ts_code", "ann_date", "in_de", "change_vol"]),
}


def month_ranges(start: str, end: str) -> list[tuple[str, str, str]]:
    periods = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    result = []
    for period in periods:
        first = max(period.start_time, pd.Timestamp(start)).strftime("%Y%m%d")
        last = min(period.end_time, pd.Timestamp(end)).strftime("%Y%m%d")
        result.append((period.strftime("%Y%m"), first, last))
    return result


def fetch_month(
    dataset: str,
    api_name: str,
    required: list[str],
    key: str,
    start: str,
    end: str,
    output_dir: Path,
    token: str,
    limiter: SlidingWindowRateLimiter,
    attempts: int,
) -> dict[str, object]:
    path = output_dir / "event_shards" / dataset / f"{key}.parquet"
    if path.exists():
        frame = pd.read_parquet(path)
        if not set(required).issubset(frame.columns):
            raise ValueError(f"cached {dataset}/{key} is missing required columns")
        return {"dataset": dataset, "key": key, "status": "cached", "rows": len(frame)}

    pages: list[pd.DataFrame] = []
    if dataset == "share_float":
        days = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
        query_ranges = [(value.strftime("%Y%m%d"), value.strftime("%Y%m%d")) for value in days]
    else:
        query_ranges = [(start, end)]
    for query_start, query_end in query_ranges:
        offset = 0
        while True:
            error: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    limiter.acquire()
                    page = ts.pro_api(token).query(
                        api_name,
                        start_date=query_start,
                        end_date=query_end,
                        limit=6000,
                        offset=offset,
                    )
                    if not set(required).issubset(page.columns):
                        raise ValueError(f"{dataset} missing required columns: {sorted(set(required) - set(page.columns))}")
                    break
                except Exception as exc:
                    error = exc
                    if attempt < attempts:
                        time.sleep(2 ** (attempt - 1))
            else:
                assert error is not None
                raise RuntimeError(
                    f"{dataset}/{key} {query_start}:{query_end} failed at offset={offset} "
                    f"after {attempts} attempts: {error}"
                ) from error
            pages.append(page)
            if len(page) < 6000:
                break
            offset += 6000
    combined = pd.concat(pages, ignore_index=True).drop_duplicates()
    write_parquet_atomic(combined, path)
    return {
        "dataset": dataset,
        "key": key,
        "status": "fetched",
        "rows": len(combined),
        "pages": len(pages),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-date", default="20180701")
    parser.add_argument("--end-date", default="20260630")
    parser.add_argument("--calls-per-minute", type=int, default=180)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.calls_per_minute <= 200:
        raise ValueError("calls-per-minute must be between 1 and 200")

    token = load_token(args.config)
    limiter = SlidingWindowRateLimiter(args.calls_per_minute)
    futures = {}
    ranges = month_ranges(args.start_date, args.end_date)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for dataset, (api_name, required) in DATASETS.items():
            for key, start, end in ranges:
                future = executor.submit(
                        fetch_month,
                        dataset,
                        api_name,
                        required,
                        key,
                        start,
                        end,
                        args.output_dir,
                        token,
                        limiter,
                        args.max_attempts,
                    )
                futures[future] = (dataset, key)
        results = []
        errors = []
        for number, future in enumerate(as_completed(futures), start=1):
            try:
                results.append(future.result())
            except Exception as exc:
                dataset, key = futures[future]
                errors.append({"dataset": dataset, "key": key, "message": str(exc)})
                print({"dataset": dataset, "key": key, "error": str(exc)}, flush=True)
            if number % 25 == 0:
                print({"completed": number, "total": len(futures)}, flush=True)

    if errors:
        error_path = args.output_dir / "event_fetch_errors.json"
        error_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"{len(errors)} event months failed; see {error_path}")

    files = {}
    for dataset in DATASETS:
        paths = sorted((args.output_dir / "event_shards" / dataset).glob("*.parquet"))
        frame = pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True).drop_duplicates()
        destination = args.output_dir / f"{dataset}.parquet"
        write_parquet_atomic(frame, destination)
        files[dataset] = {"path": str(destination), "rows": len(frame), "columns": list(frame.columns)}
    manifest = {
        "version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window": {"start_date": args.start_date, "end_date": args.end_date},
        "pagination": "monthly shards; 6000-row pages followed with offset until a short page",
        "configured_calls_per_minute": args.calls_per_minute,
        "fetched_months": sum(result["status"] == "fetched" for result in results),
        "cached_months": sum(result["status"] == "cached" for result in results),
        "files": files,
    }
    path = args.output_dir / "event_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
