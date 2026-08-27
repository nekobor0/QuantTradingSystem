from __future__ import annotations

import pandas as pd
import pytest

from quant_trading_system.research.macro_data.contracts import (
    CANONICAL_V1_COLUMNS,
    CANONICAL_V2_COLUMNS,
    upgrade_canonical_v1_to_v2,
    validate_canonical_v2,
)


def _v1() -> pd.DataFrame:
    return pd.DataFrame([{
        "series_id": "CN.TEST",
        "reference_period": "2026-07",
        "value": 1.0,
        "unit": "percent_yoy",
        "seasonal_adjustment": "not_applicable",
        "source_id": "official",
        "source_record_id": "record-1",
        "release_at": "2026-08-01T09:30:00+08:00",
        "available_at": "2026-08-01T09:30:00+08:00",
        "tradable_at": "2026-08-01T09:30:00+08:00",
        "availability_evidence": "official_page_timestamp",
        "retrieved_at": "2026-08-02T09:30:00+08:00",
        "vintage_id": "v1",
        "raw_sha256": "a" * 64,
        "parser_version": "test",
    }], columns=CANONICAL_V1_COLUMNS)


def test_v1_upgrade_is_non_mutating_and_v2_exact() -> None:
    source = _v1()
    upgraded = upgrade_canonical_v1_to_v2(source, metadata={
        "measure_basis": "ytd_cumulative",
        "methodology_version": "nbs-2026",
        "pit_grade": "A",
    })
    assert list(source.columns) == CANONICAL_V1_COLUMNS
    assert list(upgraded.columns) == CANONICAL_V2_COLUMNS
    assert upgraded.loc[0, "measure_basis"] == "ytd_cumulative"
    assert validate_canonical_v2(upgraded)["passed"] is True


def test_v2_supports_joint_january_february_period() -> None:
    upgraded = upgrade_canonical_v1_to_v2(_v1(), metadata={
        "reference_period_start": "2026-01",
        "reference_period_end": "2026-02",
        "period_span": "2026-01/02",
    })
    assert validate_canonical_v2(upgraded)["passed"] is True


def test_v2_rejects_unapproved_metadata_and_bad_pit_grade() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        upgrade_canonical_v1_to_v2(_v1(), metadata={"invented": "x"})
    upgraded = upgrade_canonical_v1_to_v2(_v1())
    upgraded.loc[0, "pit_grade"] = "PERFECT"
    assert validate_canonical_v2(upgraded)["failures"] == ["pit_grade_allowed"]
