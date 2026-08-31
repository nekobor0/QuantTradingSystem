"""Validate the frozen ignored-local U.S. GFC Gold candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_ROOT = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_global_financial_conditions_us_candidate_v1"
AUDIT_PATH = ROOT / "artifacts" / "macro_r011" / "audits" / "w1_global_financial_conditions_us_gold_candidate_v1.json"
FROZEN_HASHES = {
    "candidate_canonical_v2.parquet": "7738CDF057CE7E6F7E1653CA805A0CC6EDD3B54A8EEFED9EBD4D2F3237BCBBD0",
    "expected.json": "1458D90A0CBA56C773C057991F903C34432AFEFC94D0444B5254EA3644109351",
    "source_map.json": "A5BA0561322E21A603322343E1C449AE664E4F2A229C62DF27A65D5D9634E0FC",
    "manual_audit.json": "32A9AE58857AC1FBDE471D05948E48860CB6F41D3CF2BCD7A37AA9572238B61F",
    "raw_manifest.json": "293A68F380CD036F2A7CAF6B76C702C80A9C107FD4651AADCE9F6C7F29407231",
    "candidate_audit": "E5F0CF2AB6192C4CE8330DBC28FB8D7DA6AA342864DE76CB4D7452BDFCB234C0",
}
READY_SERIES = [
    "US.EFFR",
    "US.SOFR",
    "US.TREASURY.3M",
    "US.TREASURY.2Y",
    "US.TREASURY.10Y",
    "US.TIPS.REAL.10Y",
    "US.BROAD_DOLLAR",
]
MISSING_SERIES = ["USD.CNY", "USD.CNH"]
DATES = ["2026-08-20", "2026-08-21"]
VALUES = {
    ("US.EFFR", "2026-08-20"): 3.63,
    ("US.EFFR", "2026-08-21"): 3.63,
    ("US.SOFR", "2026-08-20"): 3.63,
    ("US.SOFR", "2026-08-21"): 3.65,
    ("US.TREASURY.3M", "2026-08-20"): 3.87,
    ("US.TREASURY.3M", "2026-08-21"): 3.88,
    ("US.TREASURY.2Y", "2026-08-20"): 4.19,
    ("US.TREASURY.2Y", "2026-08-21"): 4.24,
    ("US.TREASURY.10Y", "2026-08-20"): 4.69,
    ("US.TREASURY.10Y", "2026-08-21"): 4.74,
    ("US.TIPS.REAL.10Y", "2026-08-20"): 2.35,
    ("US.TIPS.REAL.10Y", "2026-08-21"): 2.40,
    ("US.BROAD_DOLLAR", "2026-08-20"): 118.2548,
    ("US.BROAD_DOLLAR", "2026-08-21"): 118.0628,
}
FIELDS = {
    "US.EFFR": "percentRate",
    "US.SOFR": "percentRate",
    "US.TREASURY.3M": "BC_3MONTH",
    "US.TREASURY.2Y": "BC_2YEAR",
    "US.TREASURY.10Y": "BC_10YEAR",
    "US.TIPS.REAL.10Y": "TC_10YEAR",
    "US.BROAD_DOLLAR": "H10/H10/JRXWTFB_N.B",
}
UNITS = {
    **{series_id: "percent_per_annum" for series_id in READY_SERIES},
    "US.TIPS.REAL.10Y": "percent_per_annum_real",
    "US.BROAD_DOLLAR": "index_2006_100",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def validate_global_financial_conditions_us_candidate(
    candidate_root: Path = CANDIDATE_ROOT,
    audit_path: Path = AUDIT_PATH,
    frozen_hashes: dict[str, str] = FROZEN_HASHES,
) -> dict[str, Any]:
    paths = {
        "candidate_canonical_v2.parquet": candidate_root / "candidate_canonical_v2.parquet",
        "expected.json": candidate_root / "expected.json",
        "source_map.json": candidate_root / "source_map.json",
        "manual_audit.json": candidate_root / "manual_audit.json",
        "raw_manifest.json": candidate_root / "raw_manifest.json",
        "candidate_audit": audit_path,
    }
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
        raw_manifest = _load(paths["raw_manifest.json"])
        audit = _load(paths["candidate_audit"])
        frame = pd.read_parquet(paths["candidate_canonical_v2.parquet"])
        rows = expected.get("rows") if isinstance(expected.get("rows"), list) else []
        expected_by_key = {
            (row.get("series_id"), row.get("reference_period")): row
            for row in rows if isinstance(row, dict)
        }
        frame_keys = list(zip(frame.get("series_id", []), frame.get("reference_period", []), strict=False))
        primary_keys = list(zip(frame.get("series_id", []), frame.get("reference_period", []), frame.get("vintage_id", []), strict=False))
        checks.update(
            {
                "candidate_identity_exact": expected.get("package_id") == "global_financial_conditions"
                and expected.get("candidate_id") == "R011.W1.GFC.US.GOLD_CANDIDATE_V1",
                "fourteen_rows_seven_by_two": len(frame) == 14
                and set(frame.get("series_id", [])) == set(READY_SERIES)
                and all(int((frame["series_id"] == series_id).sum()) == 2 for series_id in READY_SERIES),
                "reference_dates_exact": set(frame.get("reference_period", [])) == set(DATES),
                "unique_primary_keys": len(primary_keys) == len(set(primary_keys)),
                "expected_and_parquet_keys_exact": set(frame_keys) == set(expected_by_key) == set(VALUES),
                "values_fields_units_exact": all(
                    key in expected_by_key
                    and math.isclose(float(row.value), VALUES[key], rel_tol=0.0, abs_tol=1e-10)
                    and math.isclose(float(expected_by_key[key]["value"]), VALUES[key], rel_tol=0.0, abs_tol=1e-10)
                    and row.source_field == FIELDS[row.series_id]
                    and expected_by_key[key].get("source_field") == FIELDS[row.series_id]
                    and row.unit == UNITS[row.series_id]
                    and expected_by_key[key].get("unit") == UNITS[row.series_id]
                    for row, key in zip(frame.itertuples(index=False), frame_keys, strict=False)
                ),
                "pit_c_timestamps_exact": frame["release_at"].isna().all()
                and frame["available_at"].notna().all()
                and (frame["available_at"] == frame["tradable_at"]).all()
                and (frame["available_at"] == frame["retrieved_at"]).all()
                and frame["availability_evidence"].str.endswith("PIT-C").all(),
                "revision_indicator_preserved": all(
                    row.revision_indicator == ""
                    for row in frame[frame["series_id"].isin({"US.EFFR", "US.SOFR"})].itertuples(index=False)
                ),
                "fx_series_have_no_rows": not set(frame.get("series_id", [])) & set(MISSING_SERIES)
                and expected.get("blocked_series") == MISSING_SERIES,
                "expected_flags_fail_closed": expected.get("status") == "GOLD_CANDIDATE_AWAITING_SOL_REVIEW"
                and expected.get("passed_series") == sorted(READY_SERIES)
                and all(expected.get(field) is False for field in ("full_history_allowed", "formal_execution_allowed", "formal_curated_written", "research_ready")),
                "audit_flags_fail_closed": audit.get("status") == "GOLD_CANDIDATE_AWAITING_SOL_REVIEW"
                and audit.get("passed_series") == sorted(READY_SERIES)
                and audit.get("blocked_series") == MISSING_SERIES
                and audit.get("pit_counts") == {"PIT-A": 0, "PIT-C": 14}
                and audit.get("raw_sha_closure") == "14/14"
                and all(audit.get(field) is False for field in ("full_history_allowed", "formal_execution_allowed", "formal_curated_written", "research_ready")),
                "manual_audit_exact": manual.get("candidate_rows") == 14
                and manual.get("duplicate_primary_keys") == 0
                and manual.get("raw_sha_closure") == "14/14"
                and manual.get("pit_counts") == {"PIT-A": 0, "PIT-C": 14}
                and manual.get("control_values_verified") is True,
                "source_map_official_only": source_map.get("package") == "global_financial_conditions"
                and source_map.get("crosscheck") == {"accepted_third_party_evidence": 0, "openbb_or_fred_used": False}
                and set(source_map.get("series", {})) == set(READY_SERIES),
                "broad_dollar_metadata_anomaly_frozen": all(
                    row.source_field == "H10/H10/JRXWTFB_N.B"
                    and row.source_unit == "Index:_1997_Jan_100"
                    and row.unit == "index_2006_100"
                    for row in frame[frame["series_id"] == "US.BROAD_DOLLAR"].itertuples(index=False)
                )
                and "no numerical rescaling applied" in manual.get("source_unit_notes", {}).get("US.BROAD_DOLLAR", ""),
            }
        )
        raw_sha_by_url = {
            item.get("official_url"): item.get("sha256")
            for item in raw_manifest.values() if isinstance(item, dict)
        }
        checks["row_raw_sha_closure"] = all(
            raw_sha_by_url.get(row.source_url) == row.raw_sha256 for row in frame.itertuples(index=False)
        )
        raw_checks: list[bool] = []
        for item in raw_manifest.values():
            raw_path = ROOT / "artifacts" / "macro_r011" / item["raw_path"]
            raw_checks.append(
                item.get("http_status") == 200
                and item.get("transport_status") == "success"
                and raw_path.is_file()
                and _sha256(raw_path) == item.get("sha256")
            )
        checks["raw_files_exact"] = len(raw_checks) == 5 and all(raw_checks)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError):
        checks["candidate_parse_and_crosscheck"] = False
    checks = {name: bool(passed) for name, passed in checks.items()}
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "passed": not failures,
        "gold_ready_count": 7 if not failures else 0,
        "gold_required_count": 9,
        "gold_missing": MISSING_SERIES if not failures else READY_SERIES + MISSING_SERIES,
        "pit_counts": {"PIT-A": 0, "PIT-C": 14} if not failures else {},
        "checks": checks,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, default=CANDIDATE_ROOT)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()
    result = validate_global_financial_conditions_us_candidate(args.candidate_root, args.audit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
