from datetime import date

from quant_trading_system.research.macro_data.w1_execution import build_audit, expected_periods, validate_audit


def test_expected_periods_handle_month_quarter_and_joint_january_february():
    assert expected_periods(date(2026, 1, 1), date(2026, 3, 31), "monthly") == ["2026-01", "2026-02", "2026-03"]
    assert expected_periods(date(2026, 1, 1), date(2026, 7, 1), "quarterly") == ["2026-Q1", "2026-Q2", "2026-Q3"]
    assert expected_periods(date(2026, 1, 1), date(2026, 3, 31), "monthly_with_jan_feb_joint") == ["2026-01_02", "2026-03"]


def test_audit_blocker_semantics_are_machine_checked():
    audit = build_audit(
        package_id="prices", run_mode="shadow", start="2026-06", end="2026-07",
        expected=["2026-06", "2026-07"], observed=["2026-06"], sources=[],
        blockers=[{"code": "MISSING_PERIOD", "detail": "2026-07"}], unexplained_missing=["2026-07"],
    )
    assert validate_audit(audit)["passed"]
    audit["blocked"] = False
    assert not validate_audit(audit)["passed"]
