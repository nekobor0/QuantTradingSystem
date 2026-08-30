"""Validate the frozen 294-row AFRE full-range candidate fail closed."""

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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.contracts import (  # noqa: E402
    CANONICAL_V2_COLUMNS,
    validate_canonical_v2,
)
from scripts.data_lake.validate_macro_w1_full_entry import (  # noqa: E402
    MONEY_AFRE_END,
    MONEY_AFRE_FORMAL_INPUT,
    MONEY_AFRE_SERIES_ID,
    MONEY_AFRE_START,
)


STRUCTURAL_OMISSION = "2025-12"
EXPECTED_ROWS = 294
EXPECTED_PIT = {"A": 7, "C": 287}
EXPECTED_REGIMES = {
    "afre_historical_direct_monthly_2002_2012": 132,
    "afre_direct_monthly_old_structure_2013_2018_06": 66,
    "afre_methodology_adjusted_2018_07_2019_11": 17,
    "afre_government_bonds_regime_2019_12_onward": 79,
}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _months(start: str, end: str) -> list[str]:
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def validate_candidate(candidate_path: Path, audit_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    checks["candidate_sha256_exact"] = _sha256(candidate_path) == MONEY_AFRE_FORMAL_INPUT["candidate_sha256"]
    checks["candidate_audit_sha256_exact"] = _sha256(audit_path) == MONEY_AFRE_FORMAL_INPUT["candidate_audit_sha256"]
    try:
        frame = pd.read_parquet(candidate_path)
        audit = _load(audit_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"passed": False, "checks": checks, "failures": ["candidate_or_audit_unreadable"], "rows": 0}

    expected_periods = [item for item in _months(MONEY_AFRE_START, MONEY_AFRE_END) if item != STRUCTURAL_OMISSION]
    periods = frame.get("reference_period", pd.Series(dtype="object")).astype(str).tolist()
    checks["canonical_columns_exact"] = list(frame.columns) == CANONICAL_V2_COLUMNS
    canonical = validate_canonical_v2(frame) if checks["canonical_columns_exact"] else {"passed": False}
    checks["canonical_v2"] = bool(canonical.get("passed"))
    checks["row_count_294"] = len(frame) == EXPECTED_ROWS
    checks["single_series_exact"] = set(frame.get("series_id", [])) == {MONEY_AFRE_SERIES_ID}
    checks["period_calendar_exact"] = periods == expected_periods
    checks["structural_omission_absent"] = STRUCTURAL_OMISSION not in periods
    checks["unique_primary_keys"] = not frame.duplicated(["series_id", "reference_period", "vintage_id"]).any() if set(("series_id", "reference_period", "vintage_id")) <= set(frame) else False
    values = pd.to_numeric(frame.get("value", pd.Series(dtype="float64")), errors="coerce")
    checks["values_finite"] = len(values) == EXPECTED_ROWS and all(math.isfinite(float(value)) for value in values)
    checks["units_exact"] = set(frame.get("unit", [])) == {"100m_cny"}
    checks["measure_basis_exact"] = set(frame.get("measure_basis", [])) == {"flow"}
    checks["methodology_version_exact"] = set(frame.get("methodology_version", [])) == {"r011.afre.direct_monthly.v2"}
    checks["source_exact"] = set(frame.get("source_id", [])) == {"PBOC_STATS"}
    checks["pit_profile_exact"] = frame.get("pit_grade", pd.Series(dtype="object")).value_counts().to_dict() == EXPECTED_PIT
    checks["regime_profile_exact"] = frame.get("regime_id", pd.Series(dtype="object")).value_counts().to_dict() == EXPECTED_REGIMES
    checks["timestamps_ordered"] = all(
        pd.isna(release) or pd.isna(available) or pd.Timestamp(release) <= pd.Timestamp(available) <= pd.Timestamp(tradable)
        for release, available, tradable in zip(frame.get("release_at", []), frame.get("available_at", []), frame.get("tradable_at", []), strict=True)
    )

    coverage = audit.get("coverage_summary", {})
    checks["audit_identity_exact"] = (
        audit.get("status") == "PARTIAL_EVIDENCE_NOT_FULL_HISTORY"
        and audit.get("series_id") == MONEY_AFRE_SERIES_ID
        and audit.get("candidate_sha256") == MONEY_AFRE_FORMAL_INPUT["candidate_sha256"]
        and audit.get("candidate_rows") == EXPECTED_ROWS
    )
    checks["audit_coverage_exact"] = (
        coverage.get("candidate_rows") == EXPECTED_ROWS
        and coverage.get("full_history_rows_required") == 295
        and coverage.get("missing_periods") == [STRUCTURAL_OMISSION]
        and coverage.get("unexplained_missing_periods") == []
        and coverage.get("explained_not_raw_closed_periods") == [STRUCTURAL_OMISSION]
    )
    checks["audit_states_false"] = all(audit.get(key) is False for key in ("formal_curated_written", "full_history_allowed", "research_ready"))
    checks["no_differencing"] = audit.get("quality_checks", {}).get("cumulative_or_balance_differencing") == "not_used"

    raw_entries = audit.get("raw_closure", {}).get("files", [])
    raw_by_sha: dict[str, Path] = {}
    if isinstance(raw_entries, list):
        for item in raw_entries:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
                continue
            raw_by_sha[item["sha256"]] = root / item["path"]
    row_hashes = set(frame.get("raw_sha256", []))
    checks["row_raw_hashes_declared"] = bool(row_hashes) and row_hashes <= set(raw_by_sha)
    checks["raw_files_hash_match"] = checks["row_raw_hashes_declared"] and all(_sha256(raw_by_sha[digest]) == digest for digest in row_hashes)

    failures.extend(name for name, passed in checks.items() if not passed)
    return {
        "passed": not failures,
        "checks": checks,
        "failures": sorted(failures),
        "rows": len(frame),
        "calendar_rows": 295,
        "structural_omissions": [STRUCTURAL_OMISSION],
        "pit_a_rows": int((frame.get("pit_grade") == "A").sum()),
        "pit_c_rows": int((frame.get("pit_grade") == "C").sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=ROOT / "artifacts" / "macro_r011" / MONEY_AFRE_FORMAL_INPUT["candidate"])
    parser.add_argument("--audit", type=Path, default=ROOT / "artifacts" / "macro_r011" / MONEY_AFRE_FORMAL_INPUT["candidate_audit"])
    args = parser.parse_args()
    result = validate_candidate(args.candidate, args.audit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
