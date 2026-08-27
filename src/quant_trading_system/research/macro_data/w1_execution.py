"""State, expected-period, and audit contracts for W1 package execution."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Iterable


AUDIT_REQUIRED = {
    "schema_version", "package_id", "run_mode", "requested_window",
    "expected_periods", "observed_periods", "sources", "raw_hashes_valid",
    "duplicate_primary_keys", "value_domain_failures", "unexplained_missing",
    "structural_omissions", "blocked", "blockers", "research_ready",
}


def _months(start: date, end: date) -> list[str]:
    if end < start:
        raise ValueError("end must not precede start")
    year, month = start.year, start.month
    result: list[str] = []
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def expected_periods(start: date, end: date, frequency: str) -> list[str]:
    months = _months(start, end)
    if frequency == "monthly":
        return months
    if frequency == "quarterly":
        return list(dict.fromkeys(f"{item[:4]}-Q{(int(item[5:]) - 1) // 3 + 1}" for item in months))
    if frequency == "monthly_with_jan_feb_joint":
        result: list[str] = []
        for item in months:
            month = int(item[5:])
            period = f"{item[:4]}-01_02" if month in {1, 2} else item
            if period not in result:
                result.append(period)
        return result
    if frequency == "calendar_daily":
        span = (end - start).days
        return [(start.fromordinal(start.toordinal() + offset)).isoformat() for offset in range(span + 1)]
    raise ValueError(f"frequency needs an explicit calendar implementation: {frequency}")


def validate_audit(audit: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "required_fields_exact": set(audit) == AUDIT_REQUIRED,
        "schema_version_1": audit.get("schema_version") == 1,
        "known_run_mode": audit.get("run_mode") in {"gold", "shadow", "full"},
        "expected_unique": len(audit.get("expected_periods", [])) == len(set(audit.get("expected_periods", []))),
        "observed_unique": len(audit.get("observed_periods", [])) == len(set(audit.get("observed_periods", []))),
        "blocking_semantics": bool(audit.get("blocked")) == bool(audit.get("blockers")),
        "research_ready_never_true_while_blocked": not (audit.get("blocked") and audit.get("research_ready")),
        "counts_nonnegative": all(
            isinstance(audit.get(key), int) and audit[key] >= 0
            for key in ("duplicate_primary_keys", "value_domain_failures")
        ),
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {"passed": not failures, "checks": checks, "failures": failures}


def build_audit(
    *,
    package_id: str,
    run_mode: str,
    start: str,
    end: str,
    expected: Iterable[str],
    observed: Iterable[str],
    sources: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    unexplained_missing: Iterable[str] = (),
    structural_omissions: Iterable[dict[str, Any]] = (),
    raw_hashes_valid: bool = True,
    duplicate_primary_keys: int = 0,
    value_domain_failures: int = 0,
) -> dict[str, Any]:
    blocker_list = list(blockers)
    return {
        "schema_version": 1,
        "package_id": package_id,
        "run_mode": run_mode,
        "requested_window": {"start": start, "end": end},
        "expected_periods": list(expected),
        "observed_periods": list(observed),
        "sources": sources,
        "raw_hashes_valid": raw_hashes_valid,
        "duplicate_primary_keys": duplicate_primary_keys,
        "value_domain_failures": value_domain_failures,
        "unexplained_missing": list(unexplained_missing),
        "structural_omissions": list(structural_omissions),
        "blocked": bool(blocker_list),
        "blockers": blocker_list,
        "research_ready": False,
    }
