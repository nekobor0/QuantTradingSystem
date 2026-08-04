"""Fail-closed V6 factor and strategy grading gates."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class ResearchGrade(StrEnum):
    STANDALONE = "A_STANDALONE"
    ENSEMBLE_FEATURE = "B_ENSEMBLE_FEATURE"
    RISK_FILTER = "C_RISK_FILTER"
    NONE = "NONE"


GRADE_GATES = {
    ResearchGrade.STANDALONE: (
        "fixed_validation_significant",
        "net_economic_value",
        "out_of_sample_stable",
        "cross_domain_explainable",
        "capacity_pass",
        "mechanism_clear",
        "not_concentrated",
    ),
    ResearchGrade.ENSEMBLE_FEATURE: (
        "partial_or_conditional_signal_stable",
        "low_existing_exposure_correlation",
        "low_existing_return_correlation",
        "incremental_ir_positive",
        "no_material_turnover_tail_or_concentration_harm",
        "not_duplicate_variant",
    ),
    ResearchGrade.RISK_FILTER: ("independent_exclusion_improvement",),
}


def classify_research(
    evidence: Mapping[ResearchGrade | str, Mapping[str, bool]],
) -> dict[str, object]:
    """Return the highest fully evidenced grade; missing evidence always fails."""

    normalized = {ResearchGrade(key): value for key, value in evidence.items()}
    gate_results: dict[str, dict[str, object]] = {}
    for grade, required in GRADE_GATES.items():
        supplied = normalized.get(grade, {})
        invalid = [key for key, value in supplied.items() if not isinstance(value, bool)]
        if invalid:
            raise TypeError(f"classification evidence must be boolean: {invalid}")
        missing = [key for key in required if key not in supplied]
        failed = [key for key in required if supplied.get(key) is not True]
        gate_results[grade.value] = {
            "passed": not missing and not failed,
            "missing": missing,
            "failed": failed,
        }

    selected = ResearchGrade.NONE
    for grade in (
        ResearchGrade.STANDALONE,
        ResearchGrade.ENSEMBLE_FEATURE,
        ResearchGrade.RISK_FILTER,
    ):
        if gate_results[grade.value]["passed"]:
            selected = grade
            break
    return {"grade": selected.value, "gates": gate_results}
