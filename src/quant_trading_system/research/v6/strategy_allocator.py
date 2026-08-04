"""Fail-closed Lane G strategy input qualification."""

from __future__ import annotations

from collections.abc import Iterable


REQUIRED_ROLES = ("index_enhancement", "defensive", "independent_alpha")
ELIGIBLE_DECISIONS = {
    "PROMOTE",
    "PROMOTE_TO_LIVE_SHADOW",
    "SHADOW",
    "SHADOW_BASELINE",
}


def audit_allocator_inputs(inputs: Iterable[dict[str, object]]) -> dict[str, object]:
    records = list(inputs)
    required = {"research_id", "lane", "role", "decision", "monthly_path", "holdings_path"}
    invalid: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    for record in records:
        missing = sorted(required.difference(record))
        if missing:
            invalid.append({"research_id": record.get("research_id"), "missing_fields": missing})
            continue
        if record["decision"] in ELIGIBLE_DECISIONS:
            eligible.append(record)
    roles = {str(record["role"]) for record in eligible}
    missing_roles = [role for role in REQUIRED_ROLES if role not in roles]
    return {
        "status": "PASS" if not invalid and not missing_roles else "DATA_BLOCKED",
        "input_count": len(records),
        "eligible_count": len(eligible),
        "eligible_inputs": eligible,
        "rejected_or_blocked_inputs": [
            record for record in records if record.get("decision") not in ELIGIBLE_DECISIONS
        ],
        "invalid_inputs": invalid,
        "required_roles": list(REQUIRED_ROLES),
        "available_roles": sorted(roles),
        "missing_roles": missing_roles,
    }
