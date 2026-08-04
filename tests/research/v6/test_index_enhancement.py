import numpy as np
import pandas as pd
import pytest

from quant_trading_system.research.v6.index_enhancement import (
    build_shrunken_icir_scores,
    shrunken_icir_weights,
)


def test_shrinkage_is_half_after_sixty_months() -> None:
    history = pd.DataFrame({"a": np.arange(60), "b": np.arange(60)[::-1]})
    weights, shrinkage, _ = shrunken_icir_weights(history, prior_months=60)
    assert shrinkage == pytest.approx(0.5)
    assert weights.sum() == pytest.approx(1.0)
    assert (weights >= 0).all()


def test_no_history_uses_equal_weights() -> None:
    dates = pd.date_range("2020-01-31", periods=2, freq="ME")
    rows = []
    for date in dates:
        for stock, a, b in (("A", 1.0, -1.0), ("B", -1.0, 1.0), ("C", 0.5, 0.2), ("D", 0.1, 0.3)):
            rows.append(
                {
                    "ts_code": stock,
                    "signal_date": date,
                    "exit_date": date + pd.offsets.MonthEnd(1),
                    "mark_return_1m": a / 100,
                    "a": a,
                    "b": b,
                }
            )
    scored, audit = build_shrunken_icir_scores(
        pd.DataFrame(rows),
        component_columns=("a", "b"),
        minimum_history_months=24,
    )
    first = scored[scored["signal_date"].eq(dates[0])]
    assert first["shrunken_icir_v6_score"].tolist() == pytest.approx(
        ((first["a"] + first["b"]) / 2).tolist()
    )
    assert (audit["shrinkage"] == 0).all()


def test_future_exit_is_not_available_to_signal() -> None:
    dates = pd.date_range("2018-01-31", periods=26, freq="ME")
    rows = []
    for date in dates:
        for number in range(8):
            rows.append(
                {
                    "signal_date": date,
                    "exit_date": date + pd.offsets.MonthEnd(1),
                    "mark_return_1m": number / 100,
                    "a": float(number),
                    "b": float(-number),
                }
            )
    _, audit = build_shrunken_icir_scores(
        pd.DataFrame(rows), component_columns=("a", "b"), minimum_history_months=1
    )
    used = audit.dropna(subset=["latest_used_exit_date"])
    assert (used["latest_used_exit_date"] <= used["signal_date"]).all()


def test_invalid_prior_months_fails_closed() -> None:
    history = pd.DataFrame({"a": [0.1, 0.2], "b": [0.2, 0.1]})
    with pytest.raises(ValueError, match="prior_months"):
        shrunken_icir_weights(history, prior_months=0)
