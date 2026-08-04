"""Audit completeness, truncation risk, versions and field coverage of PIT financial data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-basic", type=Path, required=True)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    expected = set(
        pd.read_parquet(args.stock_basic, columns=["ts_code"])["ts_code"]
        .dropna().astype(str).str.replace(".", "_", regex=False)
    )
    shards = sorted(args.shard_dir.glob("*.parquet"))
    actual = {path.stem for path in shards}
    row_counts = {path.stem: pq.ParquetFile(path).metadata.num_rows for path in shards}
    frame = pd.read_parquet(args.aggregate)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    dates = {
        column: {
            "min": str(frame[column].dropna().astype(str).min()),
            "max": str(frame[column].dropna().astype(str).max()),
        }
        for column in ("ann_date", "end_date")
    }
    payload = {
        "expected_shards": len(expected),
        "actual_shards": len(actual),
        "missing_shards": sorted(expected - actual),
        "unexpected_shards": sorted(actual - expected),
        "temporary_files": sorted(path.name for path in args.shard_dir.glob("*.tmp")),
        "empty_shards": sum(rows == 0 for rows in row_counts.values()),
        "shards_at_100_row_limit": sorted(key for key, rows in row_counts.items() if rows >= 100),
        "maximum_rows_per_shard": max(row_counts.values(), default=0),
        "aggregate_rows": int(len(frame)),
        "aggregate_exact_duplicates": int(frame.duplicated().sum()),
        "duplicate_version_keys": int(frame.duplicated(["ts_code", "end_date", "ann_date"]).sum()),
        "symbols": int(frame["ts_code"].nunique()),
        "dates": dates,
        "field_coverage": {
            column: float(frame[column].notna().mean())
            for column in frame.columns
            if column not in {"ts_code", "ann_date", "end_date", "update_flag"}
        },
        "manifest_status_counts": manifest.get("status_counts"),
        "manifest_errors": manifest.get("errors"),
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["missing_shards"] or payload["temporary_files"] or payload["manifest_errors"]:
        raise SystemExit("financial audit failed completeness checks")
    if payload["shards_at_100_row_limit"]:
        raise SystemExit("financial audit found possible 100-row truncation")


if __name__ == "__main__":
    main()
