from copy import deepcopy

import pytest

from quant_trading_system.research.v7.governance import (
    can_run_stage_p,
    validate_combination_inputs,
    validate_registration,
    validate_research_decision,
)


def registration() -> dict[str, object]:
    return {
        "research_id": "C7_CAPACITY_AWARE_QAV",
        "post_v6_hypothesis": True,
        "core_horizon": "6m",
        "primary_benchmark": "ALL_A_EQUAL_WEIGHT",
        "role": "SLEEVE_ALPHA",
        "variant_count": 1,
        "historical_evidence_use": "development_only",
        "live_confirmation": {"unit": "months", "minimum": 12},
        "relaxations": {
            "core_capacity": ["capital_at_most_25pct_conservative_capacity", "adv_cap_2pct"]
        },
    }


def test_valid_registration_passes() -> None:
    validate_registration(registration())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("research_id", ""),
        ("post_v6_hypothesis", False),
        ("core_horizon", ["3m", "6m"]),
        ("primary_benchmark", ""),
        ("role", "MAGIC_ALPHA"),
        ("variant_count", 0),
        ("historical_evidence_use", "independent_confirmation"),
        ("live_confirmation", {"unit": "months", "minimum": 0}),
    ],
)
def test_invalid_registration_fields_fail_closed(field: str, value: object) -> None:
    candidate = registration()
    candidate[field] = value
    with pytest.raises(ValueError):
        validate_registration(candidate)


def test_missing_registration_field_fails_closed() -> None:
    candidate = registration()
    del candidate["primary_benchmark"]
    with pytest.raises(ValueError, match="missing"):
        validate_registration(candidate)


def test_duplicate_research_id_fails_closed() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_registration(
            registration(), existing_research_ids=["C7_CAPACITY_AWARE_QAV"]
        )


def test_forbidden_relaxation_fails_closed() -> None:
    candidate = registration()
    candidate["relaxations"] = {"pit": ["none"]}
    with pytest.raises(ValueError, match="forbidden"):
        validate_registration(candidate)


def test_relaxation_requires_compensation_control() -> None:
    candidate = registration()
    candidate["relaxations"] = {"standalone_ir": []}
    with pytest.raises(ValueError, match="compensation"):
        validate_registration(candidate)


def test_only_signal_valid_can_open_stage_p() -> None:
    assert can_run_stage_p("SIGNAL_VALID")
    for status in ("REJECTED", "DATA_BLOCKED", "RESEARCH_SHADOW", "SHADOW"):
        assert not can_run_stage_p(status)


def test_historical_results_cannot_promote() -> None:
    with pytest.raises(ValueError, match="cannot grant"):
        validate_research_decision(
            "PROMOTE",
            evidence_scope="historical_development",
            live_observations=96,
            required_live_observations=12,
        )


def test_historical_signal_valid_is_allowed() -> None:
    validate_research_decision(
        "SIGNAL_VALID",
        evidence_scope="historical_development",
        live_observations=0,
        required_live_observations=12,
    )


def test_short_live_history_cannot_qualify() -> None:
    with pytest.raises(ValueError, match="shorter"):
        validate_research_decision(
            "SLEEVE_ALPHA",
            evidence_scope="live_append_only",
            live_observations=11,
            required_live_observations=12,
        )


def test_rejected_or_research_shadow_input_cannot_enter_combination() -> None:
    for decision in ("REJECTED", "RESEARCH_SHADOW", "DATA_BLOCKED"):
        with pytest.raises(ValueError, match="ineligible"):
            validate_combination_inputs(["PROMOTE", decision])


def test_qualified_inputs_can_enter_combination() -> None:
    validate_combination_inputs(["SIGNAL_VALID", "RISK_FILTER", "SLEEVE_ALPHA"])
