"""Fail-closed governance rules frozen by GOAL_V7."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ALLOWED_ROLES = frozenset(
    {
        "CORE_ALPHA",
        "SLEEVE_ALPHA",
        "ENSEMBLE_FEATURE",
        "RISK_FILTER",
        "BENCHMARK_SPECIFIC",
        "STYLE_BASELINE",
        "REJECTED",
    }
)

ALLOWED_RELAXATIONS = frozenset(
    {
        "core_capacity",
        "standalone_ir",
        "cross_benchmark_consistency",
        "concentration",
        "drawdown",
        "weak_positive_ic",
    }
)

FORBIDDEN_RELAXATIONS = frozenset(
    {
        "direction",
        "pit",
        "execution",
        "core_horizon",
        "live_validation",
        "multiple_testing",
        "posthoc_selection",
    }
)

HISTORICAL_ONLY_DECISIONS = frozenset(
    {"SIGNAL_VALID", "RESEARCH_SHADOW", "REJECTED", "DATA_BLOCKED"}
)

COMBINATION_ELIGIBLE_DECISIONS = frozenset(
    {
        "SIGNAL_VALID",
        "SLEEVE_ALPHA",
        "SHADOW",
        "PROMOTE",
        "CORE_ALPHA",
        "RISK_FILTER",
        "BENCHMARK_SPECIFIC",
    }
)

_REQUIRED_REGISTRATION_FIELDS = frozenset(
    {
        "research_id",
        "post_v6_hypothesis",
        "core_horizon",
        "primary_benchmark",
        "role",
        "variant_count",
        "historical_evidence_use",
        "live_confirmation",
        "relaxations",
    }
)


def _single_nonempty_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be one non-empty string")


def validate_registration(
    registration: Mapping[str, Any],
    *,
    existing_research_ids: Sequence[str] = (),
) -> None:
    missing = _REQUIRED_REGISTRATION_FIELDS.difference(registration)
    if missing:
        raise ValueError(f"missing V7 registration fields: {sorted(missing)}")
    _single_nonempty_text(registration["research_id"], "research_id")
    if registration["research_id"] in existing_research_ids:
        raise ValueError(f"duplicate V7 research_id: {registration['research_id']}")
    if registration["post_v6_hypothesis"] is not True:
        raise ValueError("post_v6_hypothesis must be true")
    _single_nonempty_text(registration["core_horizon"], "core_horizon")
    _single_nonempty_text(registration["primary_benchmark"], "primary_benchmark")
    if registration["role"] not in ALLOWED_ROLES:
        raise ValueError(f"unknown V7 role: {registration['role']}")
    if not isinstance(registration["variant_count"], int) or isinstance(
        registration["variant_count"], bool
    ) or registration["variant_count"] < 1:
        raise ValueError("variant_count must be a positive integer")
    if registration["historical_evidence_use"] != "development_only":
        raise ValueError("V7 history must be marked development_only")

    live = registration["live_confirmation"]
    if not isinstance(live, Mapping):
        raise ValueError("live_confirmation must be a mapping")
    if live.get("unit") not in {"months", "rebalances", "events"}:
        raise ValueError("live_confirmation unit must be months, rebalances, or events")
    minimum = live.get("minimum")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ValueError("live_confirmation minimum must be a positive integer")

    relaxations = registration["relaxations"]
    if not isinstance(relaxations, Mapping):
        raise ValueError("relaxations must map each relaxation to compensation controls")
    forbidden = FORBIDDEN_RELAXATIONS.intersection(relaxations)
    if forbidden:
        raise ValueError(f"forbidden V7 relaxations: {sorted(forbidden)}")
    unknown = set(relaxations).difference(ALLOWED_RELAXATIONS)
    if unknown:
        raise ValueError(f"unknown V7 relaxations: {sorted(unknown)}")
    for name, controls in relaxations.items():
        if not isinstance(controls, Sequence) or isinstance(controls, (str, bytes)):
            raise ValueError(f"relaxation {name} must have a control list")
        if not controls or any(not isinstance(item, str) or not item.strip() for item in controls):
            raise ValueError(f"relaxation {name} requires non-empty compensation controls")


def can_run_stage_p(signal_status: str) -> bool:
    return signal_status == "SIGNAL_VALID"


def validate_research_decision(
    decision: str,
    *,
    evidence_scope: str,
    live_observations: int,
    required_live_observations: int,
) -> None:
    if evidence_scope == "historical_development":
        if decision not in HISTORICAL_ONLY_DECISIONS:
            raise ValueError("historical development evidence cannot grant a product qualification")
        return
    if evidence_scope != "live_append_only":
        raise ValueError(f"unknown evidence scope: {evidence_scope}")
    if live_observations < required_live_observations and decision in {
        "CORE_ALPHA",
        "SLEEVE_ALPHA",
        "ENSEMBLE_FEATURE",
        "RISK_FILTER",
        "BENCHMARK_SPECIFIC",
        "STYLE_BASELINE",
        "SHADOW",
        "PROMOTE",
    }:
        raise ValueError("live confirmation is shorter than the preregistered minimum")


def validate_combination_inputs(decisions: Sequence[str]) -> None:
    if not decisions:
        raise ValueError("combination requires at least one qualified input")
    ineligible = [item for item in decisions if item not in COMBINATION_ELIGIBLE_DECISIONS]
    if ineligible:
        raise ValueError(f"ineligible combination inputs: {ineligible}")
