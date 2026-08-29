"""Validate the package-by-package W1 full-history entry decision."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_execution import validate_audit


EXPECTED_PACKAGES = ["rates_liquidity", "pmi_state", "prices", "money_credit", "growth_output"]
GROWTH_START = "1992-01"
GROWTH_END = "2026-07"
GROWTH_SCOPE = "pit_a_release_plus_pit_c_frozen_manual_official_exports"
GROWTH_SERIES_WINDOWS = {
    "CN.GDP.NOMINAL.YTD": {"start": "1992-Q1", "end": "2026-Q2", "expected_rows": 138},
    "CN.GDP.REAL.YOY": {
        "start": "1993-Q1",
        "end": "2026-Q2",
        "expected_rows": 134,
        "source_scope_exclusions": ["1992-Q1", "1992-Q2", "1992-Q3", "1992-Q4"],
    },
    "CN.INDUSTRIAL.VA.YOY": {
        "start": "1998-07",
        "end": "2026-07",
        "expected_rows": 309,
        "january_rows": 0,
        "february_scope": "independent_through_2012_then_january_february_joint_from_2013",
    },
}
GROWTH_FORMAL_INPUT = {
    "candidate": "shadow/w1_growth_output_manual_exports_full_candidate.parquet",
    "candidate_sha256": "C03769F9C8C4A7E7C0F202AB1D0FA1ACC1AA00F6CF6049D3145F716B23F3C013",
    "manual_audit": "audits/w1_growth_output_manual_exports_full.json",
    "manual_audit_sha256": "A9232C73F2B7262CC03463725F9F7B78D708B2050AF936F6511E7033817E068B",
    "source_map": "state/w1_growth_output_luna_full_candidate/w1_growth_output_full_range_source_map.json",
    "source_map_sha256": "2ECB852AFD20A8510FC392F237B4D0E648D7ABE315B1A64553A426E1C56BC671",
    "formal_curated": "curated/w1_growth_output_official_mixed_pit.parquet",
}
RATES_GOLD_COVERAGE = {
    "ready_count": 9,
    "required_count": 11,
    "missing_series": ["CN.CHINABOND.GOV.YTM.1Y", "CN.CHINABOND.GOV.YTM.10Y"],
}
RATES_FULL_BLOCKERS = [
    "CFETS DR007/R007 historical path remains unverified",
    "ChinaBond 1Y/10Y Gold and full history remain blocked because sufficient authorization evidence has not been obtained",
]
RATES_LEGACY_FULL_BLOCKERS = {
    "seven series lack two-period Gold",
    "CFETS historical path remains unverified",
}


def _blocker(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _period(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        return None
    if not value[:4].isdigit() or not value[5:].isdigit():
        return None
    month = int(value[5:])
    return value if 1 <= month <= 12 else None


def _read_gate_manifest(manifest_path: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    try:
        manifest = _load(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None, [_blocker("MANIFEST_UNREADABLE", str(manifest_path))]
    if not isinstance(manifest, dict):
        return None, [_blocker("MANIFEST_TYPE_INVALID", "manifest must be an object")]
    errors: list[dict[str, str]] = []
    if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 2:
        errors.append(_blocker("MANIFEST_SCHEMA_VERSION_INVALID", "schema_version must be integer 2"))
    if type(manifest.get("gate_version")) is not int or manifest.get("gate_version") != 2:
        errors.append(_blocker("MANIFEST_GATE_VERSION_INVALID", "gate_version must be integer 2"))
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        errors.append(_blocker("PACKAGES_TYPE_INVALID", "packages must be a list"))
    return manifest, errors


def _find_package(manifest: dict[str, Any], package_id: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    packages = manifest.get("packages")
    if not isinstance(packages, list):
        return None, []
    matches = [item for item in packages if isinstance(item, dict) and item.get("package_id") == package_id]
    if not matches:
        return None, [_blocker("PACKAGE_MISSING", f"package {package_id!r} is missing")]
    if len(matches) != 1:
        return None, [_blocker("PACKAGE_DUPLICATE", f"package {package_id!r} must occur exactly once")]
    return matches[0], []


def _package_gate_errors(
    package: dict[str, Any],
    *,
    required_start: str,
    required_end: str,
    required_scope: str,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    allowed = package.get("full_history_allowed")
    if type(allowed) is not bool:
        errors.append(_blocker("FULL_HISTORY_ALLOWED_TYPE_INVALID", "full_history_allowed must be a boolean"))
    blockers = package.get("full_blockers")
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        errors.append(_blocker("FULL_BLOCKERS_TYPE_INVALID", "full_blockers must be a list of strings"))
    window = package.get("full_window")
    if not isinstance(window, dict):
        errors.append(_blocker("FULL_WINDOW_MISSING", "full_window must be an object"))
        return errors
    start = _period(window.get("start"))
    end = _period(window.get("end"))
    if start is None:
        errors.append(_blocker("FULL_WINDOW_START_INVALID", "full_window.start must be YYYY-MM"))
    if end is None:
        errors.append(_blocker("FULL_WINDOW_END_INVALID", "full_window.end must be YYYY-MM"))
    scope = window.get("scope")
    if not isinstance(scope, str) or not scope:
        errors.append(_blocker("FULL_WINDOW_SCOPE_INVALID", "full_window.scope must be a non-empty string"))
    elif scope != required_scope:
        errors.append(_blocker("FULL_SCOPE_MISMATCH", f"scope must be {required_scope!r}"))
    if start is not None and end is not None and (start != required_start or end != required_end or start > end):
        errors.append(_blocker("FULL_WINDOW_OUT_OF_RANGE", f"full_window must be {required_start}..{required_end}"))
    return errors


def check_full_gate_v2(
    manifest_path: Path,
    package_id: str,
    required_start: str,
    required_end: str,
    required_scope: str,
    start: str,
    end: str,
) -> list[dict[str, str]]:
    manifest, errors = _read_gate_manifest(manifest_path)
    if manifest is None:
        return errors
    package, package_errors = _find_package(manifest, package_id)
    errors.extend(package_errors)
    if package is None:
        return errors
    errors.extend(
        _package_gate_errors(
            package,
            required_start=required_start,
            required_end=required_end,
            required_scope=required_scope,
        )
    )
    if errors:
        return errors
    if package["full_history_allowed"] is not True:
        details = package["full_blockers"] or [f"{package_id} full-history gate is closed"]
        return [_blocker("FULL_HISTORY_NOT_ALLOWED", detail) for detail in details]
    if package["full_blockers"]:
        return [_blocker("FULL_BLOCKERS_PRESENT", detail) for detail in package["full_blockers"]]
    requested_start = _period(start)
    requested_end = _period(end)
    if requested_start is None or requested_end is None or requested_start > requested_end:
        return [_blocker("FULL_WINDOW_OUT_OF_RANGE", "requested window must be valid YYYY-MM and ordered")]
    if requested_start < required_start or requested_end > required_end:
        return [_blocker("FULL_WINDOW_OUT_OF_RANGE", f"requested window must be within {required_start}..{required_end}")]
    return []


def _growth_gate_errors(package: dict[str, Any]) -> list[dict[str, str]]:
    errors = _package_gate_errors(
        package,
        required_start=GROWTH_START,
        required_end=GROWTH_END,
        required_scope=GROWTH_SCOPE,
    )
    window = package.get("full_window")
    if isinstance(window, dict) and window.get("series_windows") != GROWTH_SERIES_WINDOWS:
        errors.append(_blocker("FULL_SERIES_WINDOWS_MISMATCH", "growth_output series_windows must match the frozen 581-row calendar"))
    formal_input = package.get("formal_input")
    if not isinstance(formal_input, dict):
        errors.append(_blocker("FORMAL_INPUT_MISSING", "growth_output formal_input must be an object"))
    elif formal_input != GROWTH_FORMAL_INPUT:
        code = "FORMAL_TARGET_MISMATCH" if formal_input.get("formal_curated") != GROWTH_FORMAL_INPUT["formal_curated"] else "FORMAL_INPUT_MISMATCH"
        errors.append(_blocker(code, "growth_output formal evidence paths, hashes, and target must match the frozen contract"))
    return errors


def _rates_blocked_gate_errors(package: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if package.get("gold_state") != "GOLD_BLOCKED_PARTIAL_9_OF_11":
        errors.append(_blocker("RATES_GOLD_STATE_MISMATCH", "rates_liquidity Gold state must remain partial 9 of 11"))
    if package.get("gold_coverage") != RATES_GOLD_COVERAGE:
        errors.append(_blocker("RATES_GOLD_COVERAGE_MISMATCH", "rates_liquidity Gold coverage must match the frozen 9/11 contract"))
    if package.get("full_history_allowed") is not False:
        errors.append(_blocker("RATES_FULL_HISTORY_NOT_BLOCKED", "rates_liquidity full history must remain disallowed"))
    if package.get("full_blockers") != RATES_FULL_BLOCKERS:
        errors.append(_blocker("RATES_FULL_BLOCKERS_MISMATCH", "rates_liquidity must retain the exact CFETS and ChinaBond blockers"))
    if package.get("shadow_allowed") is not False or package.get("shadow_state") != "BLOCKED_GOLD_INCOMPLETE":
        errors.append(_blocker("RATES_SHADOW_STATE_INVALID", "rates_liquidity shadow execution must remain blocked"))
    if package.get("research_ready", False) is not False:
        errors.append(_blocker("RATES_RESEARCH_READY_FORBIDDEN", "rates_liquidity cannot be research ready"))
    if package.get("formal_curated_written") is not False:
        errors.append(_blocker("RATES_FORMAL_WRITE_FORBIDDEN", "rates_liquidity formal curated output must remain unwritten"))
    return errors


def check_growth_full_gate_v2(
    manifest_path: Path,
    start: str = GROWTH_START,
    end: str = GROWTH_END,
) -> list[dict[str, str]]:
    errors = check_full_gate_v2(
        manifest_path,
        "growth_output",
        GROWTH_START,
        GROWTH_END,
        GROWTH_SCOPE,
        start,
        end,
    )
    if errors:
        return errors
    if start != GROWTH_START or end != GROWTH_END:
        return [_blocker("FULL_WINDOW_OUT_OF_RANGE", f"growth_output formal execution requires exact window {GROWTH_START}..{GROWTH_END}")]
    manifest, read_errors = _read_gate_manifest(manifest_path)
    if manifest is None:
        return read_errors
    package, package_errors = _find_package(manifest, "growth_output")
    if package is None:
        return package_errors
    return _growth_gate_errors(package)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_full_entry(manifest_path: Path, audit_root: Path | None = None) -> dict[str, Any]:
    try:
        manifest = _load(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return {
            "passed": False,
            "full_entry_ready": False,
            "all_packages_ready": False,
            "ready_packages": [],
            "blocked_packages": [],
            "invalid_packages": ["<manifest>"],
            "decision": "INVALID_MANIFEST",
            "checks": {"gate_v2_schema": False, "package_state_semantics": False},
            "failures": ["MANIFEST_UNREADABLE"],
            "audits": {},
        }
    if not isinstance(manifest, dict):
        return {
            "passed": False,
            "full_entry_ready": False,
            "all_packages_ready": False,
            "ready_packages": [],
            "blocked_packages": [],
            "invalid_packages": ["<manifest>"],
            "decision": "INVALID_MANIFEST",
            "checks": {"gate_v2_schema": False, "package_state_semantics": False},
            "failures": ["MANIFEST_TYPE_INVALID"],
            "audits": {},
        }
    packages = manifest.get("packages")
    package_by_id = {item.get("package_id"): item for item in packages if isinstance(item, dict)} if isinstance(packages, list) else {}
    ready_packages: list[str] = []
    blocked_packages: list[str] = []
    invalid_packages: list[str] = []
    package_errors: dict[str, list[dict[str, str]]] = {}
    for package_id in EXPECTED_PACKAGES:
        package = package_by_id.get(package_id)
        if not isinstance(package, dict):
            invalid_packages.append(package_id)
            package_errors[package_id] = [_blocker("PACKAGE_MISSING", f"package {package_id!r} is missing or invalid")]
            continue
        allowed = package.get("full_history_allowed")
        blockers = package.get("full_blockers")
        errors: list[dict[str, str]] = []
        if type(allowed) is not bool:
            errors.append(_blocker("FULL_HISTORY_ALLOWED_TYPE_INVALID", "full_history_allowed must be a boolean"))
        if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
            errors.append(_blocker("FULL_BLOCKERS_TYPE_INVALID", "full_blockers must be a list of strings"))
        if package_id == "rates_liquidity":
            errors.extend(_rates_blocked_gate_errors(package))
        if allowed is True:
            if package_id == "pmi_state":
                errors.extend(_package_gate_errors(package, required_start="2009-06", required_end="2026-07", required_scope="official_release_vintage"))
            elif package_id == "prices":
                errors.extend(_package_gate_errors(package, required_start="2021-01", required_end="2026-07", required_scope="pit_a_official_release"))
            elif package_id == "growth_output":
                errors.extend(_growth_gate_errors(package))
            else:
                window = package.get("full_window")
                if not isinstance(window, dict):
                    errors.append(_blocker("FULL_WINDOW_MISSING", "allowed package requires full_window"))
                else:
                    window_start = _period(window.get("start"))
                    window_end = _period(window.get("end"))
                    if window_start is None:
                        errors.append(_blocker("FULL_WINDOW_START_INVALID", "full_window.start must be YYYY-MM"))
                    if window_end is None:
                        errors.append(_blocker("FULL_WINDOW_END_INVALID", "full_window.end must be YYYY-MM"))
                    scope = window.get("scope")
                    if not isinstance(scope, str) or not scope:
                        errors.append(_blocker("FULL_WINDOW_SCOPE_INVALID", "full_window.scope must be a non-empty string"))
                    if window_start is not None and window_end is not None and window_start > window_end:
                        errors.append(_blocker("FULL_WINDOW_OUT_OF_RANGE", "full_window.start must not exceed full_window.end"))
            if isinstance(blockers, list) and blockers:
                errors.append(_blocker("FULL_BLOCKERS_PRESENT", "allowed package must have empty full_blockers"))
        elif allowed is False:
            if isinstance(blockers, list) and not blockers:
                errors.append(_blocker("FULL_BLOCKERS_MISSING", "blocked package must retain explicit full_blockers"))
        else:
            errors.append(_blocker("PACKAGE_STATE_INVALID", "full_history_allowed must be true or false"))
        if errors:
            invalid_packages.append(package_id)
            package_errors[package_id] = errors
        elif allowed is True:
            ready_packages.append(package_id)
        else:
            blocked_packages.append(package_id)
    package_ids = [item.get("package_id") for item in packages] if isinstance(packages, list) else []
    checks = {
        "gate_v2_schema": type(manifest.get("schema_version")) is int and manifest.get("schema_version") == 2 and type(manifest.get("gate_version")) is int and manifest.get("gate_version") == 2,
        "pmi_prices_have_gate_v2_windows": all(isinstance(package_by_id.get(package_id, {}).get("full_window"), dict) for package_id in ("pmi_state", "prices")),
        "five_packages_ordered": package_ids == EXPECTED_PACKAGES,
        "blocked_packages_have_specific_full_blockers": all(
            isinstance(package_by_id.get(package_id), dict)
            and isinstance(package_by_id[package_id].get("full_blockers"), list)
            and bool(package_by_id[package_id]["full_blockers"])
            for package_id in blocked_packages
        ),
        "package_state_semantics": not invalid_packages,
        "ready_packages_have_valid_gate": all(package_id not in invalid_packages for package_id in ready_packages),
        "blocked_packages_have_explicit_blockers": all(package_id not in invalid_packages for package_id in blocked_packages),
        "three_shadow_passed": sum(isinstance(item, dict) and item.get("shadow_state") == "SHADOW_PASSED_SOL_REVIEW" for item in packages) == 3 if isinstance(packages, list) else False,
        "two_gold_blocked": sum(isinstance(item, dict) and item.get("shadow_state") == "BLOCKED_GOLD_INCOMPLETE" for item in packages) == 2 if isinstance(packages, list) else False,
    }
    audits: dict[str, Any] = {}
    execution_pending_packages: list[str] = []
    full_history_complete_packages: list[str] = []
    if audit_root is not None:
        for package in packages if isinstance(packages, list) else []:
            package_id = package["package_id"]
            audit = _load(audit_root / f"w1_{package_id}_full.json")["audit"]
            details = {item["detail"] for item in audit["blockers"] if item["code"] == "FULL_HISTORY_NOT_ALLOWED"}
            blocker_codes = {item["code"] for item in audit["blockers"]}
            package_allowed = package.get("full_history_allowed") is True
            execution_pending = package_allowed and audit["blocked"] and blocker_codes == {"FULL_HISTORY_NOT_ALLOWED"}
            execution_complete = package_allowed and not audit["blocked"]
            if execution_pending:
                execution_pending_packages.append(package_id)
            if execution_complete:
                full_history_complete_packages.append(package_id)
            audits[package_id] = {
                "schema_valid": validate_audit(audit)["passed"],
                "blocked": audit["blocked"],
                "research_ready": audit["research_ready"],
                "execution_pending": execution_pending,
                "execution_complete": execution_complete,
                "specific_blockers_match": (
                    frozenset(details) in {frozenset(package["full_blockers"]), frozenset(RATES_LEGACY_FULL_BLOCKERS)}
                    if not package_allowed and package_id == "rates_liquidity"
                    else details == set(package["full_blockers"])
                    if not package_allowed
                    else execution_pending or execution_complete
                ),
            }
        checks["all_local_full_gate_audits_valid"] = all(
            item["schema_valid"] and (item["blocked"] or not item["research_ready"]) and item["specific_blockers_match"]
            for item in audits.values()
        )
    failures = sorted(name for name, passed in checks.items() if not passed)
    all_packages_ready = ready_packages == EXPECTED_PACKAGES and not invalid_packages
    if invalid_packages:
        decision = "INVALID_PACKAGE_GATE"
    elif ready_packages:
        decision = "ALL_PACKAGES_READY" if all_packages_ready else "MIXED_PACKAGE_READINESS"
    else:
        decision = "BLOCKED_PACKAGE_BY_PACKAGE"
    return {
        "passed": not failures,
        "full_entry_ready": all_packages_ready,
        "all_packages_ready": all_packages_ready,
        "ready_packages": ready_packages,
        "blocked_packages": blocked_packages,
        "invalid_packages": invalid_packages,
        "execution_pending_packages": execution_pending_packages,
        "full_history_complete_packages": full_history_complete_packages,
        "package_errors": package_errors,
        "decision": decision,
        "checks": checks,
        "failures": failures,
        "audits": audits,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "config" / "macro_w1_execution_manifest.json")
    parser.add_argument("--audit-root", type=Path, default=ROOT / "artifacts" / "macro_r011" / "audits")
    args = parser.parse_args()
    result = validate_full_entry(args.manifest, args.audit_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
