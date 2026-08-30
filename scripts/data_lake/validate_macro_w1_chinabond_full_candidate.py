"""Validate the frozen ChinaBond 1Y/10Y full-history evidence candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import (  # noqa: E402
    CANONICAL_V2_COLUMNS,
    validate_canonical_v2,
)


CANDIDATE_ROOT = (
    ROOT
    / "artifacts"
    / "macro_r011"
    / "state"
    / "w1_rates_liquidity_evidence_luna_20260830"
    / "chinabond_ytm_full_candidate"
)
FROZEN_HASHES = {
    "expected.json": "494F1CFF7D2CCF4A23DD27D7CCADA852C89D3B1C98CD80DC061D6C71536EE8C5",
    "source_map.json": "34CAE8DDECA6B0B0A343A0E4BB5907CA7D94E7F55AC2F730830D95349D1B4EA3",
    "manual_audit.json": "138BFEBDACE5492A4FEB355899C8D31A2CA13760A14C9A7B1A09EA6F180EB1A5",
    "candidate_audit.json": "54739F29FAD0013926141C17770CCED71BE9E4609EEEB6F6B930843670C24A7D",
    "chinabond_ytm_full_candidate.parquet": "CD75349939256CA0A90DCC071B9B982F94D046291D27E19DFA487C188D9F5197",
}
SERIES = {"CN.CHINABOND.GOV.YTM.1Y", "CN.CHINABOND.GOV.YTM.10Y"}
BLOCKED_SERIES = {"CN.REPO.DR007", "CN.REPO.R007"}
EXPECTED_COUNTS = {series_id: 6159 for series_id in SERIES}
EXPECTED_COVERAGE = {
    "files": 25,
    "years": [2002, 2026],
    "physical_rows": 114014,
    "distinct_date_tenor_keys": 113963,
    "cross_file_duplicate_rows": 51,
    "selected_rows": 12318,
    "series_counts": EXPECTED_COUNTS,
    "date_sets_equal": True,
    "earliest": "2002-01-04",
    "latest": "2026-08-28",
}
EXPECTED_CONTROLS = {
    ("CN.CHINABOND.GOV.YTM.1Y", "2026-08-24"): 1.2020,
    ("CN.CHINABOND.GOV.YTM.10Y", "2026-08-24"): 1.6794,
    ("CN.CHINABOND.GOV.YTM.1Y", "2026-08-25"): 1.2030,
    ("CN.CHINABOND.GOV.YTM.10Y", "2026-08-25"): 1.6815,
}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def validate_chinabond_full_candidate(
    candidate_root: Path = CANDIDATE_ROOT,
    *,
    repo_root: Path = ROOT,
    frozen_hashes: dict[str, str] = FROZEN_HASHES,
) -> dict[str, Any]:
    paths = {name: candidate_root / name for name in FROZEN_HASHES}
    checks: dict[str, bool] = {
        "frozen_files_present": all(path.is_file() for path in paths.values()),
        "frozen_hashes_exact": False,
    }
    try:
        checks["frozen_hashes_exact"] = checks["frozen_files_present"] and all(
            _sha256(paths[name]) == digest for name, digest in frozen_hashes.items()
        )
        expected = _load(paths["expected.json"])
        source_map = _load(paths["source_map.json"])
        manual = _load(paths["manual_audit.json"])
        audit = _load(paths["candidate_audit.json"])
        frame = pd.read_parquet(paths["chinabond_ytm_full_candidate.parquet"])
        expected_rows = expected.get("rows")
        expected_frame = pd.DataFrame(expected_rows) if isinstance(expected_rows, list) else pd.DataFrame()

        counts = frame.get("series_id", pd.Series(dtype="object")).value_counts().to_dict()
        one_year_dates = set(frame.loc[frame.get("series_id") == "CN.CHINABOND.GOV.YTM.1Y", "reference_period"])
        ten_year_dates = set(frame.loc[frame.get("series_id") == "CN.CHINABOND.GOV.YTM.10Y", "reference_period"])
        values = pd.to_numeric(frame.get("value", pd.Series(dtype="float64")), errors="coerce")
        release = pd.to_datetime(frame.get("release_at", pd.Series(dtype="object")))
        available = pd.to_datetime(frame.get("available_at", pd.Series(dtype="object")))
        tradable = pd.to_datetime(frame.get("tradable_at", pd.Series(dtype="object")))
        reference_dates = pd.to_datetime(frame.get("reference_period", pd.Series(dtype="object"))).dt.date
        observed_dates = sorted(set(reference_dates))
        next_observed = {observed_dates[index]: observed_dates[index + 1] for index in range(len(observed_dates) - 1)}
        next_day_exact = all(
            available_date == next_observed.get(reference_date, pd.Timestamp("2026-08-31").date())
            for reference_date, available_date in zip(reference_dates, available.dt.date, strict=True)
        )
        controls = {
            (row.series_id, str(row.reference_period)): float(row.value)
            for row in frame.itertuples()
            if str(row.reference_period) in {"2026-08-24", "2026-08-25"}
        }
        canonical = validate_canonical_v2(frame) if list(frame.columns) == CANONICAL_V2_COLUMNS else {"passed": False}

        closure = source_map.get("raw_closure")
        closure = closure if isinstance(closure, list) else []
        closure_by_year = {
            int(item["file_year"]): item
            for item in closure
            if isinstance(item, dict) and type(item.get("file_year")) is int
        }
        raw_files_match = len(closure_by_year) == 25
        if raw_files_match:
            for year, item in closure_by_year.items():
                raw_path = repo_root / item.get("raw_path", "")
                raw_files_match = (
                    raw_files_match
                    and year in range(2002, 2027)
                    and raw_path.is_file()
                    and raw_path.stat().st_size == item.get("bytes")
                    and _sha256(raw_path) == item.get("sha256")
                )
        row_hash_by_year = {year: item.get("sha256") for year, item in closure_by_year.items()}
        row_hashes_match = all(
            row.raw_sha256 == row_hash_by_year.get(pd.Timestamp(row.reference_period).year)
            for row in frame.itertuples()
        )

        sort_keys = ["series_id", "reference_period"]
        parquet_sorted = frame.sort_values(sort_keys).reset_index(drop=True)
        expected_sorted = expected_frame.sort_values(sort_keys).reset_index(drop=True) if set(sort_keys) <= set(expected_frame) else expected_frame
        checks.update(
            {
                "candidate_identity_exact": expected.get("package_id") == "rates_liquidity"
                and expected.get("candidate_id") == "R011.W1.RATES_LIQUIDITY.CHINABOND_YTM.FULL_CANDIDATE_V1"
                and expected.get("status") == "FULL_HISTORY_CANDIDATE_AWAITING_SOL_REVIEW",
                "authorization_scope_exact": expected.get("provenance") == "user_provided_manual_official_export"
                and expected.get("authorization_scope") == {
                    "internal_research_only": True,
                    "redistribution": False,
                    "commercial_entitlement_inference": False,
                },
                "coverage_exact": expected.get("coverage") == EXPECTED_COVERAGE,
                "requested_window_exact": expected.get("requested_window") == {
                    "start": "2002-01-04",
                    "end": "2026-08-28",
                    "source_years": [2002, 2026],
                },
                "expected_profile_exact": expected.get("profile") == {
                    "unit": "percent_per_annum",
                    "measure_basis": "daily_close",
                    "null_value_count": 0,
                    "interpolation": False,
                    "zero_fill": False,
                    "forward_fill": False,
                    "pit_grade": "C",
                    "release_rule": "same-date end 23:59:59+08:00",
                    "availability_rule": "next China trading day 09:30+08:00",
                    "final_date_next_trading_day": "2026-08-31",
                }
                and {
                    (series_id, period): float(value)
                    for period, values_by_series in expected.get("control_values", {}).items()
                    for series_id, value in values_by_series.items()
                }
                == EXPECTED_CONTROLS,
                "candidate_rows_exact": len(frame) == 12318 and counts == EXPECTED_COUNTS,
                "canonical_columns_exact": list(frame.columns) == CANONICAL_V2_COLUMNS,
                "canonical_v2": bool(canonical.get("passed")),
                "parquet_matches_expected": list(frame.columns) == list(expected_frame.columns)
                and parquet_sorted.astype(str).equals(expected_sorted.astype(str)),
                "series_and_date_sets_exact": set(counts) == SERIES and one_year_dates == ten_year_dates,
                "window_exact": min(one_year_dates | ten_year_dates) == "2002-01-04"
                and max(one_year_dates | ten_year_dates) == "2026-08-28",
                "unique_primary_keys": not frame.duplicated(["series_id", "reference_period", "vintage_id"]).any(),
                "values_finite": len(values) == 12318 and all(math.isfinite(float(value)) for value in values),
                "unit_and_measure_exact": set(frame.get("unit", [])) == {"percent_per_annum"}
                and set(frame.get("measure_basis", [])) == {"daily_close"},
                "pit_c_exact": set(frame.get("pit_grade", [])) == {"C"}
                and set(frame.get("release_at", pd.Series(dtype="object")).astype(str).str[11:19]) == {"23:59:59"}
                and set(frame.get("available_at", pd.Series(dtype="object")).astype(str).str[11:19]) == {"09:30:00"},
                "timestamps_ordered": bool(((release <= available) & (available == tradable)).all()),
                "next_trading_day_rule_exact": bool((release.dt.date == reference_dates).all()) and next_day_exact,
                "control_values_exact": controls == EXPECTED_CONTROLS,
                "raw_closure_exact": set(closure_by_year) == set(range(2002, 2027)) and raw_files_match,
                "row_raw_hashes_match": row_hashes_match and frame.get("raw_sha256", pd.Series(dtype="object")).nunique() == 25,
                "manual_audit_exact": manual.get("candidate_rows") == 12318
                and manual.get("coverage") == EXPECTED_COVERAGE
                and set(manual.get("candidate_qualified_series", [])) == SERIES
                and manual.get("passed_series") == []
                and set(manual.get("blocked_series", [])) == BLOCKED_SERIES
                and manual.get("failures") == [],
                "candidate_audit_exact": audit.get("candidate_validation_passed") is True
                and audit.get("candidate_rows") == 12318
                and set(audit.get("candidate_qualified_series", [])) == SERIES
                and audit.get("passed_series") == []
                and set(audit.get("blocked_series", [])) == BLOCKED_SERIES
                and audit.get("pit_grade") == "C"
                and audit.get("failures") == [],
                "no_premature_state": expected.get("full_history_allowed") is False
                and expected.get("formal_curated_written") is False
                and expected.get("research_ready") is False
                and expected.get("gold_gate_promotion") is False,
            }
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        checks["candidate_parse_and_crosscheck"] = False
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "passed": not failures,
        "candidate_rows": 12318 if not failures else 0,
        "candidate_qualified_series": sorted(SERIES) if not failures else [],
        "pit_grade": "C" if not failures else None,
        "checks": checks,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, default=CANDIDATE_ROOT)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = validate_chinabond_full_candidate(args.candidate_root, repo_root=args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
