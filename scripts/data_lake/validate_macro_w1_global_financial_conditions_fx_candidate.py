"""Validate the frozen zero-row official FX evidence investigation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = ROOT / "artifacts" / "macro_r011" / "state" / "w1_global_financial_conditions_fx_gold_candidate_luna_20260831"
AUDIT_PATH = ROOT / "artifacts" / "macro_r011" / "audits" / "w1_global_financial_conditions_fx_gold_candidate_luna_20260831.json"
RAW_ROOT = ROOT / "artifacts" / "macro_r011" / "raw" / "global_financial_conditions_fx_candidate_luna_20260831"
FROZEN_HASHES = {
    "candidate_audit": "CE3E0745875C1F4A2E9580D12BBE3BA7013917F9ECB0BA75CD70D507D1104BF8",
    "source_map.json": "FE394C1B8A999DABAF54C5A16783DA2AEFF7BCB98E3B305627A8A33518A1C08C",
    "manual_audit.json": "AF6266A823AA22E8A8318E7A995627BDEF40D090CB768D3E60A9F79F5F7E7099",
    "request_evidence_log.json": "DED720E9313D2D0AF5A6EC283D15EEEE054F422BB137715C9AA76CC3D275B3F9",
    "raw_manifest.json": "9C91B6359DF2F79DDA3BBB8652FA1208EC11E14C2F993314ABD4FC6B4AB2FE1A",
}
BLOCKED_SERIES = ["USD.CNY", "USD.CNH"]
DATES = ["2026-08-20", "2026-08-21"]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def validate_global_financial_conditions_fx_candidate(
    state_root: Path = STATE_ROOT,
    audit_path: Path = AUDIT_PATH,
    raw_root: Path = RAW_ROOT,
    frozen_hashes: dict[str, str] = FROZEN_HASHES,
) -> dict[str, Any]:
    paths = {
        "candidate_audit": audit_path,
        "source_map.json": state_root / "source_map.json",
        "manual_audit.json": state_root / "manual_audit.json",
        "request_evidence_log.json": state_root / "request_evidence_log.json",
        "raw_manifest.json": raw_root / "raw_manifest.json",
    }
    checks: dict[str, bool] = {
        "frozen_files_present": all(path.is_file() for path in paths.values()),
        "frozen_hashes_exact": False,
    }
    try:
        checks["frozen_hashes_exact"] = checks["frozen_files_present"] and all(
            _sha256(paths[name]) == digest for name, digest in frozen_hashes.items()
        )
        audit = _load(paths["candidate_audit"])
        source_map = _load(paths["source_map.json"])
        manual = _load(paths["manual_audit.json"])
        request_log = _load(paths["request_evidence_log.json"])
        raw_manifest = _load(paths["raw_manifest.json"])
        profiles = audit.get("series_profiles", {})
        source_series = source_map.get("series", {})
        requests = request_log.get("direct_http_requests", [])
        raw_checks = [
            isinstance(item, dict)
            and item.get("http_status") == 200
            and item.get("transport_status") == "success"
            and item.get("accepted") is False
            and (raw_root / str(item.get("file"))).is_file()
            and _sha256(raw_root / str(item.get("file"))) == item.get("sha256")
            for item in raw_manifest if isinstance(item, dict)
        ] if isinstance(raw_manifest, list) else []
        checks.update(
            {
                "audit_zero_row_block_exact": audit.get("candidate_id") == "R011.W1.GFC.FX.GOLD_CANDIDATE_V1"
                and audit.get("requested_window") == DATES
                and audit.get("candidate_rows") == 0
                and audit.get("candidate_parquet") is None
                and audit.get("status") == "BLOCKED_NO_ACCEPTED_OFFICIAL_ROWS"
                and audit.get("passed_series") == []
                and audit.get("blocked_series") == BLOCKED_SERIES
                and audit.get("pit_counts") == {"PIT-A": 0, "PIT-C": 0}
                and audit.get("accepted_third_party_evidence") == 0,
                "series_profiles_exact": set(profiles) == set(BLOCKED_SERIES)
                and all(profiles.get(series_id, {}).get("expected") == 2 for series_id in BLOCKED_SERIES)
                and all(profiles.get(series_id, {}).get("observed") == 0 for series_id in BLOCKED_SERIES)
                and all(profiles.get(series_id, {}).get("missing") == DATES for series_id in BLOCKED_SERIES),
                "flags_fail_closed": all(
                    audit.get(field) is False
                    for field in ("full_history_allowed", "formal_execution_allowed", "formal_curated_written", "research_ready")
                ) and source_map.get("package_flags") == {
                    "full_history_allowed": False,
                    "formal_execution_allowed": False,
                    "formal_curated_written": False,
                    "research_ready": False,
                },
                "cny_diagnostics_rejected": source_series.get("USD.CNY", {}).get("candidate_rows") == 0
                and source_series.get("USD.CNY", {}).get("target_source_field") == "USD_CNY_1630_SPOT_CLOSE"
                and all(item.get("accepted") is False for item in source_series.get("USD.CNY", {}).get("diagnostic_sources", [])),
                "cnh_entitlement_blocked": source_series.get("USD.CNH", {}).get("candidate_rows") == 0
                and source_series.get("USD.CNH", {}).get("status") == "SOURCE_AND_ENTITLEMENT_BLOCKED"
                and source_series.get("USD.CNH", {}).get("target_source_field") == "UNRESOLVED_OFFICIAL_USD_CNH_SPOT_CLOSE",
                "manual_audit_fail_closed": manual.get("candidate_rows") == 0
                and manual.get("candidate_parquet_generated") is False
                and manual.get("passed_series") == []
                and manual.get("blocked_series") == BLOCKED_SERIES
                and manual.get("accepted_third_party_evidence") == 0
                and manual.get("control_checks", {}).get("cny_1630_close_semantics_proven") is False
                and manual.get("control_checks", {}).get("cnh_official_source_and_entitlement_proven") is False,
                "request_budget_and_rejections_exact": request_log.get("request_budget") == {
                    "maximum": 30,
                    "direct_http_attempts_recorded": 29,
                    "budget_exceeded": False,
                }
                and len(requests) == 29
                and all(item.get("http_status") == 200 and item.get("transport_status") == "success" and item.get("accepted") is False for item in requests)
                and request_log.get("summary", {}).get("accepted_target_rows") == 0
                and request_log.get("summary", {}).get("third_party_rows") == 0,
                "diagnostic_raw_exact": len(raw_checks) == 8 and all(raw_checks),
                "existing_gold_state_unchanged": audit.get("existing_package_state_unchanged") == {
                    "gold_ready_count": 7,
                    "gold_required_count": 9,
                    "missing_series": BLOCKED_SERIES,
                },
            }
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError):
        checks["evidence_parse_and_crosscheck"] = False
    checks = {name: bool(passed) for name, passed in checks.items()}
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "passed": not failures,
        "candidate_rows": 0,
        "gold_ready_count": 7 if not failures else 0,
        "gold_required_count": 9,
        "gold_missing": BLOCKED_SERIES,
        "checks": checks,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    args = parser.parse_args()
    result = validate_global_financial_conditions_fx_candidate(args.state_root, args.audit, args.raw_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
