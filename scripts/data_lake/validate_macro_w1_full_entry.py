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
        if allowed is True:
            if package_id == "pmi_state":
                errors.extend(_package_gate_errors(package, required_start="2009-06", required_end="2026-07", required_scope="official_release_vintage"))
            elif package_id == "prices":
                errors.extend(_package_gate_errors(package, required_start="2021-01", required_end="2026-07", required_scope="pit_a_official_release"))
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
    if audit_root is not None:
        for package in packages if isinstance(packages, list) else []:
            package_id = package["package_id"]
            audit = _load(audit_root / f"w1_{package_id}_full.json")["audit"]
            details = {item["detail"] for item in audit["blockers"] if item["code"] == "FULL_HISTORY_NOT_ALLOWED"}
            package_allowed = package.get("full_history_allowed") is True
            audits[package_id] = {
                "schema_valid": validate_audit(audit)["passed"],
                "blocked": audit["blocked"],
                "research_ready": audit["research_ready"],
                "specific_blockers_match": (details == set(package["full_blockers"])) if not package_allowed else not audit["blocked"],
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
