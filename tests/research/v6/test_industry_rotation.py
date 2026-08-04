import pandas as pd
import pytest

from quant_trading_system.research.v6.industry_rotation import build_industry_momentum_scores


def industry_history() -> pd.DataFrame:
    rows = []
    for number, date in enumerate(pd.date_range("2023-01-31", periods=14, freq="ME")):
        for industry, value in (("A", 0.02), ("B", 0.01), ("C", -0.01)):
            rows.append(
                {
                    "signal_date": date,
                    "exit_date": date + pd.offsets.MonthEnd(1),
                    "l1_code": industry,
                    "industry_return": value + number / 10_000,
                }
            )
    return pd.DataFrame(rows)


def test_scores_use_only_returns_ended_by_signal_date() -> None:
    scores, audit = build_industry_momentum_scores(industry_history(), history_months=3)
    assert not scores.empty
    assert (audit["latest_used_exit_date"] <= audit["signal_date"]).all()


def test_relative_scores_remove_common_industry_level() -> None:
    scores, _ = build_industry_momentum_scores(industry_history(), history_months=3)
    means = scores.groupby("signal_date")["relative_momentum"].mean()
    assert means.abs().max() < 1e-12


def test_invalid_history_fails_closed() -> None:
    with pytest.raises(ValueError, match="history_months"):
        build_industry_momentum_scores(industry_history(), history_months=0)
