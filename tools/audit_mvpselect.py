"""Read-only structural and quality audit for the legacy MvpSelect data assets."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds
import pyarrow.parquet as pq


def parquet_inventory(data_root: Path) -> dict[str, Any]:
    files = list(data_root.rglob("*"))
    regular_files = [path for path in files if path.is_file()]
    parquet_files = [path for path in regular_files if path.suffix.lower() == ".parquet"]
    schema_counts: Counter[tuple[str, ...]] = Counter()
    unreadable: list[dict[str, str]] = []
    rows = 0

    for path in parquet_files:
        try:
            metadata = pq.ParquetFile(path).metadata
            rows += metadata.num_rows
            schema_counts[tuple(metadata.schema.names)] += 1
        except Exception as exc:  # audit must continue and report corrupt assets
            unreadable.append({"path": str(path), "error": str(exc)})

    extension_counts = Counter(path.suffix.lower() or "<none>" for path in regular_files)
    return {
        "file_count": len(regular_files),
        "bytes": sum(path.stat().st_size for path in regular_files),
        "extension_counts": dict(extension_counts.most_common()),
        "parquet_file_count": len(parquet_files),
        "parquet_metadata_rows": rows,
        "distinct_parquet_schemas": len(schema_counts),
        "unreadable_parquet": unreadable,
    }


def scan_daily(daily_root: Path) -> dict[str, Any]:
    paths = sorted(daily_root.glob("*.parquet"))
    required_common = {"date", "open", "high", "low", "close", "volume", "amount", "adj_factor"}
    schema_groups: dict[tuple[str, ...], list[Path]] = defaultdict(list)
    for path in paths:
        schema_groups[tuple(pq.ParquetFile(path).schema_arrow.names)].append(path)

    rows = 0
    symbols: set[str] = set()
    min_date: str | None = None
    max_date: str | None = None
    nulls = Counter()
    invalid_ohlc = 0
    negative_volume = 0
    nonpositive_adjustment = 0
    shard_rows: list[int] = []

    schema_summary = []
    for schema, group_paths in schema_groups.items():
        actual = set(schema)
        identifier = "symbol" if "symbol" in actual else "code" if "code" in actual else None
        missing = sorted(required_common - actual)
        group_rows = sum(pq.ParquetFile(path).metadata.num_rows for path in group_paths)
        schema_summary.append({
            "files": len(group_paths),
            "rows": group_rows,
            "identifier": identifier,
            "columns": list(schema),
            "missing_required": missing,
        })
        if identifier is None or missing:
            continue
        dataset = ds.dataset(group_paths, format="parquet")
        columns = ["date", identifier, "open", "high", "low", "close", "volume", "amount", "adj_factor"]
        for batch in dataset.scanner(columns=columns, batch_size=131_072).to_batches():
            table = batch.to_pandas().rename(columns={identifier: "instrument_id"})
            rows += len(table)
            symbols.update(table["instrument_id"].dropna().astype(str).unique())
            dates = table["date"].dropna().astype(str)
            if not dates.empty:
                batch_min, batch_max = dates.min(), dates.max()
                min_date = batch_min if min_date is None else min(min_date, batch_min)
                max_date = batch_max if max_date is None else max(max_date, batch_max)
            normalized_columns = ["date", "instrument_id", "open", "high", "low", "close", "volume", "amount", "adj_factor"]
            nulls.update({column: int(table[column].isna().sum()) for column in normalized_columns})
            price = table[["open", "high", "low", "close"]]
            valid_price = price.notna().all(axis=1)
            invalid_ohlc += int(
                (
                    valid_price
                    & (
                        (table["high"] < table[["open", "close", "low"]].max(axis=1))
                        | (table["low"] > table[["open", "close", "high"]].min(axis=1))
                        | (table["low"] <= 0)
                    )
                ).sum()
            )
            negative_volume += int((table["volume"] < 0).sum())
            nonpositive_adjustment += int((table["adj_factor"] <= 0).sum())

    for path in paths:
        shard_rows.append(pq.ParquetFile(path).metadata.num_rows)

    return {
        "files": len(paths),
        "rows": rows,
        "symbols": len(symbols),
        "min_date": min_date,
        "max_date": max_date,
        "schema_groups": sorted(schema_summary, key=lambda item: item["rows"], reverse=True),
        "null_counts": dict(nulls),
        "invalid_ohlc_rows": invalid_ohlc,
        "negative_volume_rows": negative_volume,
        "nonpositive_adjustment_rows": nonpositive_adjustment,
        "smallest_shard_rows": min(shard_rows, default=0),
        "largest_shard_rows": max(shard_rows, default=0),
        "limitations": [
            "This scan does not prove trading-calendar completeness per instrument.",
            "Duplicate (code, date) keys and point-in-time constituent validity require a database-stage audit.",
        ],
    }


def scan_small_table(path: Path, key: list[str]) -> dict[str, Any]:
    table = pq.read_table(path).to_pandas()
    result: dict[str, Any] = {
        "path": str(path),
        "rows": len(table),
        "columns": list(table.columns),
        "null_counts": {column: int(table[column].isna().sum()) for column in table.columns},
        "duplicate_key_rows": int(table.duplicated(key, keep=False).sum()),
    }
    for column in ("date", "trade_date", "ipo_date", "out_date"):
        if column in table.columns:
            values = table[column].dropna().astype(str)
            result[f"{column}_min"] = values.min() if not values.empty else None
            result[f"{column}_max"] = values.max() if not values.empty else None
    for column in ("symbol", "ts_code", "code"):
        if column in table.columns:
            result[f"unique_{column}"] = int(table[column].nunique(dropna=True))
    return result


def merged_inventory(merged_root: Path) -> dict[str, Any]:
    unified = sorted(merged_root.glob("*_unified.parquet"))
    validations = sorted(merged_root.glob("*_validation.json"))
    schemas: Counter[tuple[str, ...]] = Counter()
    rows = 0
    for path in unified:
        parquet = pq.ParquetFile(path)
        rows += parquet.metadata.num_rows
        schemas[tuple(parquet.schema_arrow.names)] += 1
    return {
        "unified_files": len(unified),
        "validation_files": len(validations),
        "rows": rows,
        "distinct_schemas": len(schemas),
        "column_counts": sorted({len(schema) for schema in schemas}),
    }


def build_report(mvp_root: Path) -> dict[str, Any]:
    data_root = mvp_root / "data"
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": str(mvp_root.resolve()),
        "inventory": parquet_inventory(data_root),
        "stock_basic": scan_small_table(data_root / "stock_basic.parquet", ["symbol"]),
        "archive_daily_raw": scan_small_table(data_root / "archive" / "daily_raw.parquet", ["ts_code", "trade_date"]),
        "archive_adj_factor": scan_small_table(data_root / "archive" / "adj_factor.parquet", ["symbol", "date"]),
        "expanded_daily": scan_daily(data_root / "expanded" / "daily"),
        "expanded_merged": merged_inventory(data_root / "expanded" / "merged"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mvp-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.mvp_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
