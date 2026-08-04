import pytest

from quant_trading_system.research.v6.classification import (
    GRADE_GATES,
    ResearchGrade,
    classify_research,
)


def passing(grade: ResearchGrade) -> dict[str, bool]:
    return {key: True for key in GRADE_GATES[grade]}


def test_classification_selects_highest_fully_evidenced_grade() -> None:
    result = classify_research(
        {
            ResearchGrade.STANDALONE: passing(ResearchGrade.STANDALONE),
            ResearchGrade.ENSEMBLE_FEATURE: passing(
                ResearchGrade.ENSEMBLE_FEATURE
            ),
        }
    )
    assert result["grade"] == ResearchGrade.STANDALONE.value


def test_classification_is_fail_closed_for_missing_or_failed_evidence() -> None:
    evidence = passing(ResearchGrade.ENSEMBLE_FEATURE)
    evidence.pop("incremental_ir_positive")
    result = classify_research({ResearchGrade.ENSEMBLE_FEATURE: evidence})
    assert result["grade"] == ResearchGrade.NONE.value
    assert result["gates"][ResearchGrade.ENSEMBLE_FEATURE.value]["missing"] == [
        "incremental_ir_positive"
    ]


def test_classification_rejects_non_boolean_evidence() -> None:
    evidence = passing(ResearchGrade.RISK_FILTER)
    evidence["independent_exclusion_improvement"] = 1
    with pytest.raises(TypeError, match="must be boolean"):
        classify_research({ResearchGrade.RISK_FILTER: evidence})
