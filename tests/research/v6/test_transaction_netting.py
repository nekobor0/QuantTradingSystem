import numpy as np
import pandas as pd
import pytest

from quant_trading_system.research.v6.transaction_netting import net_strategy_trades


def test_opposing_strategy_orders_are_netted_before_execution():
    result = net_strategy_trades(
        {
            "enhancement": pd.Series({"A": 0.3, "B": 0.2}),
            "defensive": pd.Series({"A": 0.1, "B": 0.4}),
        },
        {
            "enhancement": pd.Series({"A": 0.4, "B": 0.1}),
            "defensive": pd.Series({"A": 0.0, "B": 0.5}),
        },
    )
    detail = result["detail"]
    assert np.isclose(detail["intended_trade_weight"].abs().sum(), 0.0)
    assert np.isclose(result["summary"]["gross_strategy_trade_weight"], 0.4)
    assert np.isclose(result["summary"]["netting_saved_weight"], 0.4)


def test_untradable_netted_order_is_reported_not_assumed_filled():
    result = net_strategy_trades(
        {"one": pd.Series({"A": 0.5, "B": 0.5})},
        {"one": pd.Series({"A": 0.4, "B": 0.6})},
        tradable=pd.Series({"A": False, "B": True}),
    )
    assert result["detail"].at["A", "executed_trade_weight"] == 0.0
    assert np.isclose(result["detail"].at["A", "unfilled_trade_weight"], -0.1)
    assert result["summary"]["unfilled_gross_trade_weight"] == pytest.approx(0.1)


def test_strategy_set_mismatch_fails_closed():
    with pytest.raises(ValueError, match="sets differ"):
        net_strategy_trades(
            {"one": pd.Series({"A": 1.0})},
            {"two": pd.Series({"A": 1.0})},
        )


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_non_finite_weight_fails_closed(value):
    with pytest.raises(ValueError, match="non-finite"):
        net_strategy_trades(
            {"one": pd.Series({"A": value})},
            {"one": pd.Series({"A": 1.0})},
        )
