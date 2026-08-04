"""Measure whether cached TDX raw files recover Tushare-delisted A shares."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trading_system.research.alpha_phase1 import TdxRawQualityError, parse_research_series


def audit(raw_dir: Path, stock_basic_path: Path) -> dict[str, Any]:
    stock = pd.read_parquet(stock_basic_path)
    delisted = stock.loc[stock["list_status"] == "D", ["ts_code", "list_date", "delist_date"]]
    targets = set(delisted["ts_code"].astype(str))
    recovered: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, str]] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = payload.get("result", {}).get("Value", {})
            if not isinstance(values, dict) or not (set(values) & targets):
                continue
            for series in parse_research_series(payload):
                if series.symbol not in targets:
                    continue
                candidate = {
                    "file": path.name,
                    "rows": series.rows,
                    "first_date": series.dates[0].isoformat(),
                    "last_date": series.dates[-1].isoformat(),
                    "factor_last": series.forward_factor[-1],
                }
                current = recovered.get(series.symbol)
                if current is None or (candidate["rows"], candidate["last_date"]) > (
                    current["rows"],
                    current["last_date"],
                ):
                    recovered[series.symbol] = candidate
        except (OSError, json.JSONDecodeError, TdxRawQualityError) as exc:
            rejected.append({"file": path.name, "error": str(exc)})

    metadata = delisted.set_index("ts_code").to_dict(orient="index")
    covered_since_research_start = sum(
        str(metadata[symbol]["delist_date"]) >= "20180701" for symbol in recovered
    )
    eligible_since_research_start = sum(
        str(row.delist_date) >= "20180701" for row in delisted.itertuples()
    )
    return {
        "version": 1,
        "delisted_symbols": len(targets),
        "recovered_symbols": len(recovered),
        "coverage": len(recovered) / len(targets) if targets else None,
        "delisted_on_or_after_20180701": eligible_since_research_start,
        "recovered_delisted_on_or_after_20180701": covered_since_research_start,
        "research_window_coverage": (
            covered_since_research_start / eligible_since_research_start
            if eligible_since_research_start
            else None
        ),
        "missing_symbols": sorted(targets - recovered.keys()),
        "rejected_target_files": rejected,
        "recovered": recovered,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--stock-basic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.raw_dir, args.stock_basic)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"recovered", "missing_symbols"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
