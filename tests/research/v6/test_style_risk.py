import numpy as np
import pandas as pd
import pytest

from quant_trading_system.research.v6.style_risk import (
    STYLE_CONTROLS_V6,
    audit_style_risk_panel,
    financial_group_panel,
    portfolio_style_exposure,
    validate_style_risk_panel,
)


def sample_panel() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "ts_code": ["A", "B"],
            "signal_date": pd.to_datetime(["2025-01-31", "2025-01-31"]),
            "l1_code": ["I1", "I2"],
            "financial_sector": ["nonfinancial", "bank"],
            "report_age_days": [20.0, 30.0],
        }
    )
    for number, control in enumerate(STYLE_CONTROLS_V6, start=1):
        frame[control] = [float(number), float(number + 1)]
    return frame


def test_style_risk_schema_requires_all_twelve_controls_and_pit_age():
    frame = sample_panel()
    validate_style_risk_panel(frame)
    with pytest.raises(ValueError, match="missing V6"):
        validate_style_risk_panel(frame.drop(columns=["loss_dummy"]))
    frame.loc[0, "report_age_days"] = 251
    with pytest.raises(ValueError, match="PIT"):
        validate_style_risk_panel(frame)


def test_portfolio_style_exposure_reports_weighted_values_and_coverage():
    frame = sample_panel()
    frame.loc[1, "quality_composite"] = np.nan
    exposure = portfolio_style_exposure(pd.Series({"A": 0.6, "B": 0.4}), frame)
    assert np.isclose(exposure["styles"]["size"], 1.4)
    assert np.isclose(exposure["coverage"]["quality_composite"], 0.6)
    assert exposure["industries"] == {"I1": 0.6, "I2": 0.4}


def test_style_risk_audit_blocks_aggregated_nonbank_financial_group():
    audit = audit_style_risk_panel(sample_panel())
    assert audit["status"] == "DATA_BLOCKED_PARTIAL"
    assert audit["financial_groups_missing"] == ["broker", "insurance"]


def test_financial_group_panel_distinguishes_broker_and_insurance_pit():
    members = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D"],
            "l1_code": ["801780.SI", "801790.SI", "801790.SI", "801180.SI"],
            "l2_code": ["X", "801193.SI", "801194.SI", "Y"],
            "in_date": ["20200101"] * 4,
            "out_date": [None] * 4,
        }
    )
    result = financial_group_panel(members, [pd.Timestamp("2024-01-31")])
    assert result.set_index("ts_code")["financial_sector"].to_dict() == {
        "A": "bank",
        "B": "broker",
        "C": "insurance",
        "D": "nonfinancial",
    }
