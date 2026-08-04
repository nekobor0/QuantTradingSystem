from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.backtest import *
from quant_trading_system.backtest.context import PointInTimeValue, StrategyContext
from quant_trading_system.backtest.errors import InvalidBacktest, LookaheadAccess
from quant_trading_system.strategies import StrategyKind

from .conftest import D1, D2, D3, make_bar


@pytest.mark.parametrize("budget", ["0", "0.1", "0.5", "1"])
def test_strategy_spec_accepts_budget_range(budget):
    assert StrategySpec(StrategyKind.ETF_TIMING, uuid4(), "hash", Decimal(budget), "daily").sleeve_budget == Decimal(budget)


@pytest.mark.parametrize("budget", ["-0.1", "1.1", "2"])
def test_strategy_spec_rejects_budget_outside_range(budget):
    with pytest.raises(InvalidBacktest):
        StrategySpec(StrategyKind.ETF_TIMING, uuid4(), "hash", Decimal(budget), "daily")


@pytest.mark.parametrize("lot,tick,settlement", [(1, "0.001", 0), (100, "0.01", 1), (200, "0.1", 2), (10, "1", 0)])
def test_market_rule_valid(lot, tick, settlement):
    rule = MarketRule("M", "v", date(2020, 1, 1), None, lot, Decimal(tick), settlement)
    assert rule.lot_size == lot


@pytest.mark.parametrize("lot,tick,settlement", [(0, "0.01", 1), (-1, "0.01", 1), (100, "0", 1), (100, "-1", 1), (100, "0.01", -1)])
def test_market_rule_invalid(lot, tick, settlement):
    with pytest.raises(InvalidBacktest):
        MarketRule("M", "v", date(2020, 1, 1), None, lot, Decimal(tick), settlement)


def test_market_rule_interval_and_applies():
    rule = MarketRule("M", "v", date(2025, 1, 1), date(2025, 1, 31), 1, Decimal(".01"), 0)
    assert rule.applies("M", date(2025, 1, 1)) and rule.applies("M", date(2025, 1, 31))
    assert not rule.applies("M", date(2025, 2, 1)) and not rule.applies("X", date(2025, 1, 1))


@pytest.mark.parametrize("field", ["commission_rate", "minimum_commission", "sell_tax_rate", "platform_fee_rate", "slippage_rate"])
def test_cost_rule_rejects_negative_component(field):
    values = dict(commission_rate=Decimal(), minimum_commission=Decimal(), sell_tax_rate=Decimal(), platform_fee_rate=Decimal(), slippage_rate=Decimal())
    values[field] = Decimal("-0.1")
    with pytest.raises(InvalidBacktest):
        CostRule("M", "v", date(2020, 1, 1), None, **values)


def test_definition_requires_both_strategies(definition):
    with pytest.raises(InvalidBacktest):
        replace(definition, strategies=(definition.strategies[0],))


def test_definition_rejects_duplicate_strategy_kind(definition):
    with pytest.raises(InvalidBacktest):
        replace(definition, strategies=(definition.strategies[0], replace(definition.strategies[1], kind=StrategyKind.ETF_TIMING)))


@pytest.mark.parametrize("field,value", [("initial_cash", Decimal("0")), ("base_currency", "CN"), ("max_participation", Decimal("0")), ("max_participation", Decimal("1.1")), ("execution_delay_bars", 0)])
def test_definition_rejects_invalid_core_fields(definition, field, value):
    with pytest.raises(InvalidBacktest):
        replace(definition, **{field: value})


@pytest.mark.parametrize("status", [BacktestRunStatus.VALIDATING, BacktestRunStatus.CANCELLED])
def test_created_run_valid_transitions(status):
    run = BacktestRun(uuid4(), "h", None, BacktestRunStatus.CREATED)
    assert run.transition(status, D1).status is status


@pytest.mark.parametrize("status", [BacktestRunStatus.CREATED, BacktestRunStatus.RUNNING, BacktestRunStatus.COMPLETED, BacktestRunStatus.FAILED])
def test_created_run_invalid_transitions(status):
    run = BacktestRun(uuid4(), "h", None, BacktestRunStatus.CREATED)
    with pytest.raises(InvalidBacktest):
        run.transition(status, D1)


def test_simulation_event_requires_positive_sequence():
    with pytest.raises(InvalidBacktest):
        SimulationEvent(uuid4(), 0, D1, D1, EventPriority.MARKET_BAR, "Bar", "1", {})


@pytest.mark.parametrize("state", list(MarketState))
def test_bar_accepts_every_market_state(state):
    assert make_bar(uuid4(), "M", D1, state=state).state is state


def test_bar_rejects_availability_before_market_time():
    with pytest.raises(InvalidBacktest):
        make_bar(uuid4(), "M", D1, available_at=D1 - timedelta(seconds=1))


@pytest.mark.parametrize("train_end,test_start", [(date(2025, 1, 5), date(2025, 1, 6)), (date(2025, 1, 1), date(2025, 1, 2))])
def test_walk_forward_accepts_disjoint_windows(train_end, test_start):
    WalkForwardWindow(date(2024, 1, 1), train_end, test_start, date(2025, 12, 31))


@pytest.mark.parametrize("train_end,test_start", [(date(2025, 1, 5), date(2025, 1, 5)), (date(2025, 1, 6), date(2025, 1, 5))])
def test_walk_forward_rejects_overlap(train_end, test_start):
    with pytest.raises(InvalidBacktest):
        WalkForwardWindow(date(2024, 1, 1), train_end, test_start, date(2025, 12, 31))


def test_context_returns_only_visible_history(etf_id):
    bars = (make_bar(etf_id, "ETF", D1), make_bar(etf_id, "ETF", D2), make_bar(etf_id, "ETF", D3))
    context = StrategyContext(D2, bars)
    assert [item.market_time for item in context.history(etf_id)] == [D1, D2]
    assert context.latest_bar(etf_id).market_time == D2


def test_context_rejects_explicit_future_through(etf_id):
    context = StrategyContext(D1, (make_bar(etf_id, "ETF", D1),))
    with pytest.raises(LookaheadAccess):
        context.history(etf_id, D2)


def test_context_rejects_bar_not_yet_available(etf_id):
    delayed = make_bar(etf_id, "ETF", D1, available_at=D2)
    with pytest.raises(LookaheadAccess):
        StrategyContext(D1, (delayed,)).history(etf_id)


def test_context_point_in_time_value():
    context = StrategyContext(D2, (), (PointInTimeValue("x", D1, 1), PointInTimeValue("x", D3, 2)))
    assert context.value("x") == 1


def test_context_rejects_future_only_value():
    context = StrategyContext(D1, (), (PointInTimeValue("x", D2, 1),))
    with pytest.raises(LookaheadAccess):
        context.value("x")


def test_context_unknown_value_is_key_error():
    with pytest.raises(KeyError):
        StrategyContext(D1, ()).value("missing")
