"""Validate the frozen W1 money-credit full-history candidate contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_lake.validate_macro_w1_full_entry import (
    MONEY_AFRE_FORMAL_INPUT,
    MONEY_AFRE_FORMAL_OUTPUT,
    MONEY_AFRE_FULL_WINDOW,
    MONEY_AFRE_SERIES_GATE,
    MONEY_AFRE_SERIES_ID,
    MONEY_PENDING_FULL_HISTORY_CONTRACT,
    MONEY_RETIRED_SERIES,
)


DEFAULT_PACKAGE = ROOT / "config" / "macro_w1_packages" / "money_credit.json"
DEFAULT_MANIFEST = ROOT / "config" / "macro_w1_execution_manifest.json"
MONEY_AFRE_PACKAGE_GATE = {
    "series_id": MONEY_AFRE_SERIES_ID,
    **{
        key: value
        for key, value in MONEY_AFRE_SERIES_GATE.items()
        if key not in {"full_window", "formal_input", "formal_output"}
    },
    "window": MONEY_AFRE_FULL_WINDOW,
    "formal_input": MONEY_AFRE_FORMAL_INPUT,
    "formal_output": MONEY_AFRE_FORMAL_OUTPUT,
}


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _months(start: str, end: str) -> int:
    start_parts = start.split("-")
    end_parts = end.split("-")
    if len(start_parts) != 2 or len(end_parts) != 2:
        raise ValueError("month must use YYYY-MM")
    start_year, start_month = map(int, start_parts)
    end_year, end_month = map(int, end_parts)
    if not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
        raise ValueError("month must be between 01 and 12")
    return (end_year - start_year) * 12 + end_month - start_month + 1


def _window_row_math(windows: Any) -> tuple[bool, int | None]:
    if not isinstance(windows, dict):
        return False, None
    try:
        valid = all(
            isinstance(window, dict)
            and isinstance(window.get("start"), str)
            and isinstance(window.get("end"), str)
            and window.get("calendar_rows") == _months(window["start"], window["end"])
            for window in windows.values()
        )
    except (KeyError, TypeError, ValueError):
        return False, None
    if not valid:
        return False, None
    return True, sum(window["calendar_rows"] for window in windows.values())


def validate_money_credit_full_contract(package_path: Path, manifest_path: Path) -> dict[str, Any]:
    package = _load(package_path)
    manifest = _load(manifest_path)
    if package is None or manifest is None:
        return {"passed": False, "checks": {"documents_readable": False}, "failures": ["DOCUMENT_UNREADABLE"]}

    packages = manifest.get("packages")
    money_entries = [
        item for item in packages if isinstance(item, dict) and item.get("package_id") == "money_credit"
    ] if isinstance(packages, list) else []
    manifest_money = money_entries[0] if len(money_entries) == 1 else None
    package_contract = package.get("pending_full_history_contract")
    manifest_contract = manifest_money.get("pending_full_history_contract") if isinstance(manifest_money, dict) else None
    windows = package_contract.get("series_windows") if isinstance(package_contract, dict) else None
    row_math, total = _window_row_math(windows)
    rules = package_contract.get("candidate_rules") if isinstance(package_contract, dict) else None

    checks = {
        "documents_readable": True,
        "package_identity": package.get("package_id") == "money_credit",
        "one_manifest_package": manifest_money is not None,
        "package_contract_exact": package_contract == MONEY_PENDING_FULL_HISTORY_CONTRACT,
        "manifest_contract_exact": manifest_contract == MONEY_PENDING_FULL_HISTORY_CONTRACT,
        "contracts_match": package_contract == manifest_contract,
        "five_series_exact": isinstance(windows, dict)
        and list(windows) == MONEY_PENDING_FULL_HISTORY_CONTRACT["series_order"],
        "calendar_row_math": row_math and total == 1165,
        "pboc_only": isinstance(package_contract, dict)
        and package_contract.get("source_whitelist") == ["PBOC_STATS"],
        "candidate_only_states": isinstance(package_contract, dict)
        and package_contract.get("candidate_only") is True
        and all(package_contract.get(key) is False for key in ("full_history_allowed", "formal_execution_allowed", "formal_curated_written", "research_ready")),
        "no_derived_fill": isinstance(rules, dict)
        and all(rules.get(key) is False for key in ("cumulative_differencing_allowed", "balance_differencing_allowed", "interpolation_allowed", "zero_fill_allowed", "forward_fill_allowed")),
        "partial_evidence_fail_closed": isinstance(rules, dict)
        and rules.get("incomplete_series_evidence_rows_allowed") is True
        and rules.get("complete_series_gate_requires_full_window") is True
        and rules.get("partial_evidence_status") == "PARTIAL_EVIDENCE_NOT_FULL_HISTORY"
        and rules.get("partial_evidence_cannot_promote_gate") is True
        and "blocked_series_emit_no_rows" not in rules,
        "methodology_versions_required": isinstance(rules, dict)
        and rules.get("methodology_version_required") is True
        and package_contract.get("required_methodology_breaks") == MONEY_PENDING_FULL_HISTORY_CONTRACT["required_methodology_breaks"],
        "package_formal_not_built": package.get("formal_state_scope") == "package_level"
        and package.get("formal_execution_state") == "NOT_BUILT"
        and package.get("formal_curated_written") is False,
        "afre_series_formal_complete": package.get("afre_full_history_gate") == MONEY_AFRE_PACKAGE_GATE,
        "retired_tombstones_preserved": package.get("canonical_scope_policy", {}).get("retired_not_required") == MONEY_RETIRED_SERIES,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "series_windows": windows if isinstance(windows, dict) else {},
        "calendar_rows_total": total,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    result = validate_money_credit_full_contract(args.package, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
