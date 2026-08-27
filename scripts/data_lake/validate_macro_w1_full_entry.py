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


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_full_entry(manifest_path: Path, audit_root: Path | None = None) -> dict[str, Any]:
    packages = _load(manifest_path)["packages"]
    checks = {
        "five_packages_ordered": [item["package_id"] for item in packages]
        == ["rates_liquidity", "pmi_state", "prices", "money_credit", "growth_output"],
        "all_have_specific_full_blockers": all(len(item.get("full_blockers", [])) >= 2 for item in packages),
        "no_package_full_allowed": all(item["full_history_allowed"] is False for item in packages),
        "three_shadow_passed": sum(item["shadow_state"] == "SHADOW_PASSED_SOL_REVIEW" for item in packages) == 3,
        "two_gold_blocked": sum(item["shadow_state"] == "BLOCKED_GOLD_INCOMPLETE" for item in packages) == 2,
    }
    audits: dict[str, Any] = {}
    if audit_root is not None:
        for package in packages:
            package_id = package["package_id"]
            audit = _load(audit_root / f"w1_{package_id}_full.json")["audit"]
            details = {item["detail"] for item in audit["blockers"] if item["code"] == "FULL_HISTORY_NOT_ALLOWED"}
            audits[package_id] = {
                "schema_valid": validate_audit(audit)["passed"],
                "blocked": audit["blocked"],
                "research_ready": audit["research_ready"],
                "specific_blockers_match": details == set(package["full_blockers"]),
            }
        checks["all_local_full_gate_audits_valid"] = all(
            item["schema_valid"] and item["blocked"] and not item["research_ready"] and item["specific_blockers_match"]
            for item in audits.values()
        )
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "passed": not failures,
        "full_entry_ready": False,
        "decision": "BLOCKED_PACKAGE_BY_PACKAGE",
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
