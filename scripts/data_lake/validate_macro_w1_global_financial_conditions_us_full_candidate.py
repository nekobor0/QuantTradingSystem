"""Validate the frozen U.S. GFC full-history evidence candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "artifacts" / "macro_r011" / "shadow" / "w1_global_financial_conditions_us_full_candidate.parquet"
AUDIT = ROOT / "artifacts" / "macro_r011" / "audits" / "w1_global_financial_conditions_us_full_candidate.json"
STATE = ROOT / "artifacts" / "macro_r011" / "state" / "w1_global_financial_conditions_us_full_candidate_luna_20260831"
RAW_MANIFEST = ROOT / "artifacts" / "macro_r011" / "raw" / "global_financial_conditions_us_full_candidate_luna_20260831" / "raw_manifest.json"
HASHES = {
    "candidate_parquet": "FDC500EFAB0DCAD9C5F077FC9FA29DFD97DA1802D13F7C57B64C0EE232F57FEA",
    "candidate_audit": "4B0E424E2204ABF7745E3A75BBACE2DC5DD02B4CB8A363FF36936F668E6B6751",
    "expected.json": "168C0C22704CBC51E79001150EA64908A24B1C3F9330C08187DC09F4E4386DB5",
    "source_map.json": "18412E3D492CF8597AF820B2075C78BEDEC55878C0AACDEBCD560B6093B413E9",
    "manual_audit.json": "7B38EE270B7EB08D6AC9630402F42F7155958FFAAE891EC322531B4922E08A9B",
    "request_evidence_log.json": "1D4B9C232BC175CF795367BF21AF13BC7B47C77C36EBF7A08E5AF596373E0A61",
    "raw_manifest.json": "14B40F83AD4460262C056A4FC0D39B8DF877FFC0D1B39972ED969640720FC695",
}
SERIES = ["US.EFFR", "US.SOFR", "US.TREASURY.3M", "US.TREASURY.2Y", "US.TREASURY.10Y", "US.TIPS.REAL.10Y", "US.BROAD_DOLLAR"]
COUNTS = {"US.BROAD_DOLLAR":5174,"US.EFFR":6573,"US.SOFR":2100,"US.TIPS.REAL.10Y":5919,"US.TREASURY.10Y":9171,"US.TREASURY.2Y":9171,"US.TREASURY.3M":9168}
FIXED = ["US.TREASURY.3M", "US.TREASURY.2Y", "US.TREASURY.10Y", "US.TIPS.REAL.10Y"]
LAGGED = ["US.EFFR", "US.SOFR", "US.BROAD_DOLLAR"]
OMISSIONS = ["2008-12-10", "2008-12-18", "2008-12-24"]
EFFR_EXCEPTION = {"reference_period":"2003-07-20","value":1.02,"raw_sha256":"0C7B8054A99F66A763059577264B48FAE827F5F44F140E4A0EE3F021BB4AC47A"}
ND_COUNTS = {"official_holiday_or_market_closure":186,"official_non_observation":25,"methodology_or_source_break":0,"unexplained_missing":0}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def validate_global_financial_conditions_us_full_candidate(
    candidate: Path = CANDIDATE,
    audit_path: Path = AUDIT,
    state_root: Path = STATE,
    raw_manifest_path: Path = RAW_MANIFEST,
    hashes: dict[str, str] = HASHES,
) -> dict[str, Any]:
    paths = {
        "candidate_parquet": candidate,
        "candidate_audit": audit_path,
        "expected.json": state_root / "expected.json",
        "source_map.json": state_root / "source_map.json",
        "manual_audit.json": state_root / "manual_audit.json",
        "request_evidence_log.json": state_root / "request_evidence_log.json",
        "raw_manifest.json": raw_manifest_path,
    }
    checks: dict[str, bool] = {"files_present": all(path.is_file() for path in paths.values())}
    try:
        checks["frozen_hashes_exact"] = checks["files_present"] and all(_sha(paths[name]) == digest for name, digest in hashes.items())
        frame = pd.read_parquet(candidate)
        audit = _load(audit_path)
        manifest = _load(raw_manifest_path)
        keys = list(zip(frame["series_id"], frame["reference_period"], frame["vintage_id"], strict=False))
        checks.update({
            "candidate_profile_exact": len(frame) == 47276 and frame.groupby("series_id").size().to_dict() == COUNTS and set(frame["series_id"]) == set(SERIES),
            "canonical_v2_and_unique": set(frame["schema_version"].astype(str)) == {"2"} and len(keys) == len(set(keys)),
            "pit_c_only_and_time_ordered": frame["release_at"].isna().all() and frame["available_at"].notna().all() and (frame["available_at"] <= frame["tradable_at"]).all(),
            "row_raw_sha_closure": set(frame["raw_sha256"]).issubset({item["sha256"] for item in manifest.values()}),
            "audit_profile_exact": audit.get("candidate_rows") == 47276 and audit.get("series_counts") == COUNTS and audit.get("raw_file_sha_closure") == "64/64" and audit.get("raw_sha_closure") == "47276/47276" and audit.get("pit_counts") == {"PIT-A":0,"PIT-C":47276},
            "release_aware_as_of_complete": audit.get("fixed_contract_complete_series") == FIXED and audit.get("as_of_complete_series") == SERIES and audit.get("publication_lag_pending_series") == LAGGED and all(not periods for periods in audit.get("unexplained_missing_by_series", {}).values()),
            "treasury_3m_structural_omissions_exact": [item.get("reference_period") for item in audit["series_profiles"]["US.TREASURY.3M"]["structural_omissions"]] == OMISSIONS and audit.get("structural_omission_series") == ["US.TREASURY.3M"],
            "effr_official_sunday_exception_retained": any(item.get("reference_period") == EFFR_EXCEPTION["reference_period"] and item.get("value") == EFFR_EXCEPTION["value"] and item.get("raw_sha256") == EFFR_EXCEPTION["raw_sha256"] for item in audit.get("official_calendar_exceptions", {}).get("US.EFFR", [])) and ((frame["series_id"] == "US.EFFR") & (frame["reference_period"] == "2003-07-20") & (frame["value"] == 1.02)).sum() == 1,
            "broad_dollar_nd_classification_exact": audit["series_profiles"]["US.BROAD_DOLLAR"]["h10_nd_classification"]["counts"] == ND_COUNTS,
            "no_fx_rows": not set(frame["series_id"]) & {"USD.CNY", "USD.CNH"},
            "candidate_flags_fail_closed": all(audit.get(field) is False for field in ("full_history_allowed", "formal_execution_allowed", "formal_curated_written", "research_ready")),
        })
        raw_checks = []
        for item in manifest.values():
            raw_path = ROOT / "artifacts" / "macro_r011" / item["raw_path"]
            raw_checks.append(item.get("http_status") == 200 and raw_path.is_file() and _sha(raw_path) == item.get("sha256"))
        checks["raw_files_exact"] = len(raw_checks) == 64 and all(raw_checks)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
        checks["parse_and_crosscheck"] = False
    checks = {name: bool(passed) for name, passed in checks.items()}
    failures = sorted(name for name, passed in checks.items() if not bool(passed))
    return {"passed": not failures, "candidate_rows": 47276 if not failures else 0, "series_full_gates": SERIES if not failures else [], "pit_counts": {"PIT-A":0,"PIT-C":47276} if not failures else {}, "checks": checks, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--state-root", type=Path, default=STATE)
    parser.add_argument("--raw-manifest", type=Path, default=RAW_MANIFEST)
    args = parser.parse_args()
    result = validate_global_financial_conditions_us_full_candidate(args.candidate, args.audit, args.state_root, args.raw_manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
