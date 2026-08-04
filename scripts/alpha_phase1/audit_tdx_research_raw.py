"""Stream an audit of cached TdxQuant research fields without changing source data."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from quant_trading_system.research.alpha_phase1 import TdxRawQualityError, parse_research_series

MIN_UNIVERSE_COVERAGE = 0.95


@dataclass(frozen=True, slots=True)
class SeriesAudit:
    file: str
    rows: int
    first_date: str
    last_date: str
    factor_min: float
    factor_max: float
    factor_last: float
    factor_levels: int
    missing_float_shares: int
    zero_float_shares: int


def load_a_share_symbols(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "symbol" not in reader.fieldnames or "asset_type" not in reader.fieldnames:
            raise ValueError("universe CSV must contain symbol and asset_type")
        return {
            str(row["symbol"]).strip().upper()
            for row in reader
            if str(row.get("asset_type", "")).strip().upper() == "A_SHARE"
        }


def audit(raw_dir: Path, universe_file: Path) -> dict[str, Any]:
    files = sorted(raw_dir.glob("*.json"))
    universe = load_a_share_symbols(universe_file)
    best: dict[str, SeriesAudit] = {}
    occurrences: dict[str, int] = {}
    rejected: list[dict[str, str]] = []
    parsed_rows = 0
    parsed_series = 0
    for number, path in enumerate(files, start=1):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            series_values = parse_research_series(payload)
        except (OSError, json.JSONDecodeError, TdxRawQualityError) as exc:
            rejected.append({"file": path.name, "error": str(exc)})
            continue
        for series in series_values:
            parsed_series += 1
            parsed_rows += series.rows
            occurrences[series.symbol] = occurrences.get(series.symbol, 0) + 1
            shares = series.float_shares
            candidate = SeriesAudit(
                file=path.name,
                rows=series.rows,
                first_date=series.dates[0].isoformat(),
                last_date=series.dates[-1].isoformat(),
                factor_min=min(series.forward_factor),
                factor_max=max(series.forward_factor),
                factor_last=series.forward_factor[-1],
                factor_levels=len(set(series.forward_factor)),
                missing_float_shares=sum(value is None for value in shares),
                zero_float_shares=sum(value == 0 for value in shares if value is not None),
            )
            current = best.get(series.symbol)
            if current is None or (candidate.rows, candidate.last_date, candidate.file) > (
                current.rows,
                current.last_date,
                current.file,
            ):
                best[series.symbol] = candidate
        if number % 500 == 0:
            print(json.dumps({"event": "audit_progress", "files": number, "total": len(files)}), flush=True)

    selected = {symbol: value for symbol, value in best.items() if symbol in universe}
    selected_rows = sum(value.rows for value in selected.values())
    missing_share_rows = sum(value.missing_float_shares for value in selected.values())
    zero_share_rows = sum(value.zero_float_shares for value in selected.values())
    factor_latest_not_one = sum(
        not (0.999999 <= value.factor_last <= 1.000001) for value in selected.values()
    )
    report: dict[str, Any] = {
        "version": 1,
        "raw_dir": str(raw_dir.resolve()),
        "universe_file": str(universe_file.resolve()),
        "files": len(files),
        "parsed_series_occurrences": parsed_series,
        "parsed_rows_including_repeated_files": parsed_rows,
        "rejected_files": len(rejected),
        "rejections": rejected,
        "unique_symbols_in_raw": len(best),
        "repeated_symbol_payloads": sum(count > 1 for count in occurrences.values()),
        "a_share_universe_symbols": len(universe),
        "selected_a_share_symbols": len(selected),
        "a_share_universe_coverage": len(selected) / len(universe) if universe else 0.0,
        "missing_a_share_symbols": sorted(universe - selected.keys()),
        "selected_rows": selected_rows,
        "factor_coverage": 1.0 if selected_rows else 0.0,
        "float_share_nonmissing_ratio": (
            (selected_rows - missing_share_rows) / selected_rows if selected_rows else 0.0
        ),
        "float_share_positive_ratio": (
            (selected_rows - missing_share_rows - zero_share_rows) / selected_rows
            if selected_rows else 0.0
        ),
        "selected_symbols_factor_last_not_one": factor_latest_not_one,
        "selected": {symbol: asdict(value) for symbol, value in sorted(selected.items())},
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--universe-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.raw_dir, args.universe_file)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {key: value for key, value in report.items() if key not in {"selected", "rejections"}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if report["a_share_universe_coverage"] <= MIN_UNIVERSE_COVERAGE:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
