"""Resumable, bounded-concurrency Tushare dividend history backfill."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import tushare as ts

from .data_update import load_token
from .dividend_backfill import strategy_universe

FIELDS = "ts_code,end_date,ann_date,div_proc,cash_div,cash_div_tax,record_date,ex_date,pay_date,imp_ann_date"


def _fetch_one(symbol: str, cache_dir: Path, retries: int = 5) -> tuple[str, str | None]:
    path = cache_dir / f"{symbol.replace('.', '_')}.parquet"
    if path.exists():
        return symbol, None
    error: Exception | None = None
    for attempt in range(retries):
        try:
            frame = ts.pro_api(load_token()).dividend(ts_code=symbol, fields=FIELDS)
            cache_dir.mkdir(parents=True, exist_ok=True)
            if frame is None:
                frame = pd.DataFrame(columns=FIELDS.split(","))
            frame.to_parquet(path, index=False)
            return symbol, None
        except Exception as exc:
            error = exc
            time.sleep(1.5 * (attempt + 1))
    return symbol, f"{type(error).__name__}: {error}"


def _normalize(frames: list[pd.DataFrame], start: str, end: str) -> pd.DataFrame:
    history = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if history.empty:
        return history
    for column in ("record_date", "ex_date", "pay_date", "ann_date", "imp_ann_date"):
        history[column] = pd.to_datetime(history[column], errors="coerce")
    history["cash_div_tax"] = pd.to_numeric(history["cash_div_tax"], errors="coerce")
    history = history[
        history["div_proc"].eq("实施")
        & history["record_date"].between(pd.Timestamp(start), pd.Timestamp(end))
        & history["cash_div_tax"].fillna(0).gt(0)
    ].copy()
    history["source"] = "tushare_dividend"
    history = history.drop_duplicates(["ts_code", "record_date", "cash_div_tax"], keep="last")
    return history.sort_values(["record_date", "ts_code"]).reset_index(drop=True)


def run(
    signal_path: Path,
    output: Path,
    start: str = "2017-01-01",
    end: str = "2026-07-29",
    workers: int = 4,
) -> dict:
    universe = sorted(strategy_universe(signal_path))
    cache_dir = output.parent / "tushare_dividend_cache"
    errors: list[dict[str, str]] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, symbol, cache_dir): symbol for symbol in universe}
        for future in as_completed(futures):
            symbol, error = future.result()
            completed += 1
            if error:
                errors.append({"ts_code": symbol, "error": error})
            if completed % 100 == 0:
                print(json.dumps({"completed": completed, "total": len(universe), "errors": len(errors)}), flush=True)
    frames = [pd.read_parquet(path) for path in sorted(cache_dir.glob("*.parquet"))]
    history = _normalize(frames, start, end)
    if history.empty:
        raise RuntimeError("Tushare dividend history is empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    history.to_parquet(tmp, index=False)
    tmp.replace(output)
    manifest = {
        "source": "Tushare dividend",
        "strategy_universe_size": len(universe),
        "symbol_files": len(frames),
        "events": len(history),
        "symbols_with_events": int(history["ts_code"].nunique()),
        "min_record_date": history["record_date"].min().strftime("%Y-%m-%d"),
        "max_record_date": history["record_date"].max().strftime("%Y-%m-%d"),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "workers": workers,
        "errors": errors,
    }
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="2017-01-01")
    parser.add_argument("--end", default="2026-07-29")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    print(json.dumps(run(args.signal_path, args.output, args.start, args.end, args.workers), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
