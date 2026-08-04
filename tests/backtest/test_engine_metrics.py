from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.backtest import *
from quant_trading_system.backtest.context import PointInTimeValue
from quant_trading_system.backtest.errors import InvalidBacktest, LookaheadAccess, RunConflict, RunNotFound
from quant_trading_system.backtest.metrics import calculate_metrics
from quant_trading_system.strategies import CandidateAction, StrategyKind

from .conftest import D1, D2, D3, make_bar


def test_dual_strategy_event_driven_golden_path(engine, definition, callbacks, bars, market_rules, cost_rules, etf_id, stock_id):
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    assert result.run.status is BacktestRunStatus.COMPLETED
    assert result.run.result_hash
    assert len({item.strategy_run_id for item in result.contributions}) == 2
    assert {item.kind for item in result.contributions} == {StrategyKind.ETF_TIMING, StrategyKind.EQUITY_DAILY_SELECTION}
    assert all(fill.filled_at > next(order.submitted_at for order in result.orders if order.order_id == fill.order_id) for fill in result.fills)
    assert any(fill.instrument_id == etf_id for fill in result.fills)
    assert any(fill.instrument_id == stock_id for fill in result.fills)
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))


def test_same_inputs_are_idempotent(engine, repo, definition, callbacks, bars, market_rules, cost_rules):
    first = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    second = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    assert second is first
    assert len(repo.results) == 1


def test_result_query(engine, definition, callbacks, bars, market_rules, cost_rules):
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    assert engine.get_result(result.run.run_id) == result
    with pytest.raises(RunNotFound): engine.get_result(uuid4())


def test_input_hash_changes_with_random_seed(engine, definition, callbacks, bars, market_rules, cost_rules):
    first = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    second = engine.run(replace(definition, definition_id=uuid4(), random_seed=8), callbacks, bars, market_rules, cost_rules)
    assert first.run.input_hash != second.run.input_hash


def test_future_append_outside_frozen_window_is_rejected(engine, definition, callbacks, bars, market_rules, cost_rules, etf_id):
    future = make_bar(etf_id, "ETF", D3 + timedelta(days=1))
    with pytest.raises(InvalidBacktest):
        engine.run(definition, callbacks, bars + (future,), market_rules, cost_rules)


def test_future_data_access_fails_run_and_preserves_error(engine, repo, definition, bars, market_rules, cost_rules):
    def future_callback(context, run_id):
        context.history(bars[0].instrument_id, D3)
        return ()
    callbacks = {StrategyKind.ETF_TIMING: future_callback, StrategyKind.EQUITY_DAILY_SELECTION: lambda context, run_id: ()}
    with pytest.raises(LookaheadAccess):
        engine.run(definition, callbacks, bars, market_rules, cost_rules)
    failed = next(iter(repo.runs.values()))
    assert failed.status is BacktestRunStatus.FAILED and "LOOKAHEAD" in failed.error


def test_failed_same_input_does_not_silently_retry(engine, definition, bars, market_rules, cost_rules):
    callbacks = {StrategyKind.ETF_TIMING: lambda context, run_id: (_ for _ in ()).throw(RuntimeError("boom")), StrategyKind.EQUITY_DAILY_SELECTION: lambda context, run_id: ()}
    with pytest.raises(RuntimeError): engine.run(definition, callbacks, bars, market_rules, cost_rules)
    with pytest.raises(RunConflict): engine.run(definition, callbacks, bars, market_rules, cost_rules)


@pytest.mark.parametrize("missing", [StrategyKind.ETF_TIMING, StrategyKind.EQUITY_DAILY_SELECTION])
def test_requires_both_callbacks(engine, definition, callbacks, bars, market_rules, cost_rules, missing):
    callbacks = dict(callbacks); callbacks.pop(missing)
    with pytest.raises(InvalidBacktest): engine.run(definition, callbacks, bars, market_rules, cost_rules)


def test_callback_provenance_kind_is_checked(engine, definition, callbacks, bars, market_rules, cost_rules, etf_id):
    def wrong(context, run_id):
        return (StrategyTarget(StrategyKind.EQUITY_DAILY_SELECTION, run_id, etf_id, CandidateAction.SELECT, Decimal("1"), context.decision_at, definition.data_snapshot_id, ()),)
    callbacks = dict(callbacks); callbacks[StrategyKind.ETF_TIMING] = wrong
    with pytest.raises(InvalidBacktest): engine.run(definition, callbacks, bars, market_rules, cost_rules)


def test_missing_market_rule_fails_before_simulation(engine, definition, callbacks, bars, market_rules, cost_rules):
    with pytest.raises(Exception): engine.run(definition, callbacks, bars, market_rules[:1], cost_rules)


def test_duplicate_bar_id_is_rejected(engine, definition, callbacks, bars, market_rules, cost_rules):
    duplicate = replace(bars[1], instrument_id=uuid4())
    with pytest.raises(InvalidBacktest): engine.run(definition, callbacks, bars + (duplicate,), market_rules, cost_rules)


def test_corporate_cash_action_precedes_bar_and_credits_position(engine, definition, callbacks, bars, market_rules, cost_rules, etf_id):
    action = CorporateCashAction(etf_id, Decimal("0.1"), D3, D2)
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules, corporate_actions=(action,))
    same_time = [event for event in result.events if event.market_time == D3]
    priorities = [event.priority for event in same_time]
    assert priorities == sorted(priorities)
    assert any(entry.kind is LedgerKind.CORPORATE_ACTION for entry in result.ledger)


def test_order_events_are_net_portfolio_orders(engine, definition, callbacks, bars, market_rules, cost_rules):
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    event_types = [event.event_type for event in result.events]
    assert event_types.index("StrategyTargetProduced") < event_types.index("SleevesNetted") < event_types.index("SimOrderSubmitted")


def test_each_fill_has_account_event(engine, definition, callbacks, bars, market_rules, cost_rules):
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    assert sum(event.event_type == "SimFillRecorded" for event in result.events) == len(result.fills)
    assert sum(event.event_type == "SimAccountUpdated" for event in result.events) == len(result.fills)


def test_snapshots_have_nonnegative_balances_and_source_hash(engine, definition, callbacks, bars, market_rules, cost_rules):
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    assert all(snapshot.cash >= 0 and snapshot.nav >= 0 and len(snapshot.content_hash) == 64 for snapshot in result.snapshots)
    assert all(position.quantity >= 0 and position.sellable_quantity >= 0 for snapshot in result.snapshots for position in snapshot.positions)


def test_expected_metric_set(engine, definition, callbacks, bars, market_rules, cost_rules):
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    assert {item.name for item in result.metrics} == {"total_return", "annual_return", "volatility", "sharpe", "sortino", "max_drawdown", "calmar", "turnover", "win_rate", "profit_loss_ratio", "cost"}


@pytest.mark.parametrize("cost_multiplier,delay,capacity", [("1", 0, "1"), ("2", 0, "0.5"), ("1", 1, "2"), ("1.5", 2, "0.1")])
def test_sensitivity_definition(engine, definition, cost_multiplier, delay, capacity):
    derived = engine.sensitivity(definition, cost_multiplier=Decimal(cost_multiplier), extra_delay_bars=delay, participation_multiplier=Decimal(capacity))
    assert derived.definition_id != definition.definition_id
    assert derived.execution_delay_bars == definition.execution_delay_bars + delay
    assert derived.max_participation == min(Decimal("1"), definition.max_participation * Decimal(capacity))


@pytest.mark.parametrize("cost_multiplier,delay", [("0", 0), ("-1", 0), ("1", -1)])
def test_invalid_sensitivity(engine, definition, cost_multiplier, delay):
    with pytest.raises(InvalidBacktest): engine.sensitivity(definition, cost_multiplier=Decimal(cost_multiplier), extra_delay_bars=delay)


def test_invalid_capacity_sensitivity(engine, definition):
    with pytest.raises(InvalidBacktest): engine.sensitivity(definition, participation_multiplier=Decimal("0"))


def test_cost_rule_scaling(engine, cost_rules):
    scaled = engine.scale_cost_rules(cost_rules, Decimal("2"))
    assert scaled[0].commission_rate == cost_rules[0].commission_rate * 2
    assert scaled[0].minimum_commission == cost_rules[0].minimum_commission * 2
    assert scaled[0].cost_rule_id != cost_rules[0].cost_rule_id


@pytest.mark.parametrize("multiplier", ["0", "-1"])
def test_cost_rule_scaling_rejects_nonpositive(engine, cost_rules, multiplier):
        with pytest.raises(InvalidBacktest): engine.scale_cost_rules(cost_rules, Decimal(multiplier))


def test_delisted_bar_requires_explicit_policy(engine, definition, callbacks, bars, market_rules, cost_rules):
    delisted = replace(bars[0], state=MarketState.DELISTED)
    with pytest.raises(InvalidBacktest):
        engine.run(definition, callbacks, (delisted,) + bars[1:], market_rules, cost_rules)


def test_metrics_empty_series():
    metrics = calculate_metrics(uuid4(), (), (), Decimal("100"))
    assert len(metrics) == 11 and all(item.value == 0 for item in metrics)


def test_metrics_positive_path():
    run_id = uuid4()
    snapshots = tuple(BacktestSnapshot(run_id, at, Decimal(), (), Decimal(nav), {}, str(nav)) for at, nav in ((D1, "100"), (D2, "110"), (D3, "105")))
    metrics = {item.name: item.value for item in calculate_metrics(run_id, snapshots, (), Decimal("100"))}
    assert metrics["total_return"] == Decimal("0.05")
    assert metrics["max_drawdown"] < 0
    assert metrics["volatility"] > 0


def test_metrics_win_rate_and_profit_loss_use_realized_round_trips():
    run_id = uuid4(); instrument = uuid4(); order_id = uuid4(); bar_id = uuid4()
    def trade(side, quantity, price, at):
        gross = Decimal(price) * quantity
        return SimFill(run_id, order_id, instrument, side, quantity, Decimal(price), gross, Decimal("1"), Decimal(), Decimal(), Decimal(), at, bar_id)
    fills = (
        trade(Side.BUY, 200, "10", D1),
        trade(Side.SELL, 100, "12", D2),
        trade(Side.SELL, 100, "8", D3),
    )
    values = {item.name: item.value for item in calculate_metrics(run_id, (), fills, Decimal("100"))}
    assert values["win_rate"] == Decimal("0.5000000000")
    assert values["profit_loss_ratio"] > 0


def test_independent_engines_have_same_result_hash(definition, callbacks, bars, market_rules, cost_rules):
    from quant_trading_system.backtest.in_memory import InMemoryBacktestRepository
    first = EventDrivenBacktestEngine(InMemoryBacktestRepository()).run(definition, callbacks, bars, market_rules, cost_rules)
    second = EventDrivenBacktestEngine(InMemoryBacktestRepository()).run(definition, callbacks, bars, market_rules, cost_rules)
    assert first.run.result_hash == second.run.result_hash
