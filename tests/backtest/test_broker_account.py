from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.backtest import *
from quant_trading_system.backtest.account import SimulationAccount
from quant_trading_system.backtest.broker import BrokerSimulator
from quant_trading_system.backtest.errors import MissingRule, SimulationInvariantError

from .conftest import D1, D2, make_bar


def order(instrument_id, *, side=Side.BUY, quantity=1000, submitted_at=D1, eligible=1, order_type=SimOrderType.MARKET, limit=None):
    return SimOrder(uuid4(), instrument_id, "SSE", side, order_type, quantity, submitted_at, eligible, limit)


def rules():
    market = MarketRule("SSE", "v1", date(2020, 1, 1), None, 100, Decimal("0.01"), 1)
    cost = CostRule("SSE", "v1", date(2020, 1, 1), None, Decimal("0.0003"), Decimal("5"), Decimal("0.001"), Decimal("0.0001"), Decimal("0.001"))
    return market, cost


def match(value, bar, *, sequence=2, participation=Decimal("1"), sellable=100000, cash=Decimal("1000000")):
    market, cost = rules()
    return BrokerSimulator().match(value, bar, sequence, market, cost, participation, sellable, cash)


def test_same_bar_never_fills():
    instrument = uuid4()
    value = order(instrument, submitted_at=D1)
    updated, fill, reason = match(value, make_bar(instrument, "SSE", D1))
    assert updated == value and fill is None and reason == "NOT_YET_ELIGIBLE"


def test_next_bar_market_buy_fills_with_one_slippage_and_minimum_commission():
    instrument = uuid4()
    updated, fill, reason = match(order(instrument), make_bar(instrument, "SSE", D2, "10"))
    assert reason is None and fill is not None
    assert fill.price == Decimal("10.01")
    assert fill.slippage_cost == Decimal("10")
    assert fill.commission == Decimal("5")
    assert fill.tax == 0
    assert fill.platform_fee == Decimal("1.001000")
    assert updated.status is SimOrderStatus.FILLED


def test_sell_has_tax_and_downward_slippage():
    instrument = uuid4()
    updated, fill, _ = match(order(instrument, side=Side.SELL), make_bar(instrument, "SSE", D2, "10"))
    assert fill.price == Decimal("9.99")
    assert fill.tax == Decimal("9.99000")
    assert fill.commission == Decimal("5")


@pytest.mark.parametrize("state,side,reason", [(MarketState.SUSPENDED, Side.BUY, "SUSPENDED"), (MarketState.SUSPENDED, Side.SELL, "SUSPENDED"), (MarketState.LIMIT_UP, Side.BUY, "LIMIT_UP"), (MarketState.LIMIT_DOWN, Side.SELL, "LIMIT_DOWN")])
def test_market_state_blocks_matching(state, side, reason):
    instrument = uuid4()
    assert match(order(instrument, side=side), make_bar(instrument, "SSE", D2, state=state))[2] == reason


def test_zero_volume_is_unfilled():
    instrument = uuid4()
    assert match(order(instrument), make_bar(instrument, "SSE", D2, volume=0))[2] == "NO_VOLUME"


@pytest.mark.parametrize("side,limit,expected", [(Side.BUY, "8.9", "LIMIT_NOT_TOUCHED"), (Side.SELL, "11.1", "LIMIT_NOT_TOUCHED")])
def test_limit_not_touched(side, limit, expected):
    instrument = uuid4()
    value = order(instrument, side=side, order_type=SimOrderType.LIMIT, limit=Decimal(limit))
    assert match(value, make_bar(instrument, "SSE", D2, "10"))[2] == expected


@pytest.mark.parametrize("side,limit", [(Side.BUY, "10.5"), (Side.SELL, "9.5")])
def test_limit_touched_fills_no_worse_than_limit(side, limit):
    instrument = uuid4()
    value = order(instrument, side=side, order_type=SimOrderType.LIMIT, limit=Decimal(limit))
    _, fill, _ = match(value, make_bar(instrument, "SSE", D2, "10"))
    assert fill is not None
    assert fill.price <= Decimal(limit) if side is Side.BUY else fill.price >= Decimal(limit)


@pytest.mark.parametrize("volume,participation,expected", [(1000, "0.1", 100), (5500, "0.1", 500), (999, "0.1", 0), (10000, "0.25", 1000)])
def test_capacity_and_lot_rounding(volume, participation, expected):
    instrument = uuid4()
    updated, fill, reason = match(order(instrument, quantity=1000), make_bar(instrument, "SSE", D2, volume=volume), participation=Decimal(participation))
    if expected == 0:
        assert fill is None and reason == "NO_CAPACITY_OR_BALANCE"
    else:
        assert fill.quantity == expected
        assert updated.status is (SimOrderStatus.FILLED if expected == 1000 else SimOrderStatus.PARTIALLY_FILLED)


def test_sell_is_capped_by_sellable_lots():
    instrument = uuid4()
    updated, fill, _ = match(order(instrument, side=Side.SELL, quantity=1000), make_bar(instrument, "SSE", D2), sellable=250)
    assert fill.quantity == 200 and updated.filled_quantity == 200


def test_buy_is_capped_by_cash_and_lots():
    instrument = uuid4()
    _, fill, _ = match(order(instrument, quantity=1000), make_bar(instrument, "SSE", D2, "10"), cash=Decimal("1007"))
    assert fill.quantity == 100


def test_no_cash_means_unfilled():
    instrument = uuid4()
    assert match(order(instrument), make_bar(instrument, "SSE", D2), cash=Decimal("4"))[2] == "NO_CAPACITY_OR_BALANCE"


def test_missing_or_overlapping_rule_rejected():
    broker = BrokerSimulator()
    bar = make_bar(uuid4(), "SSE", D1)
    with pytest.raises(MissingRule): broker.market_rule((), "SSE", bar)
    duplicate = MarketRule("SSE", "v", date(2020, 1, 1), None, 100, Decimal(".01"), 1)
    with pytest.raises(MissingRule): broker.market_rule((duplicate, duplicate), "SSE", bar)


def test_account_buy_fill_and_t1_settlement():
    instrument = uuid4(); run_id = uuid4(); account = SimulationAccount(run_id, Decimal("100000")); market, _ = rules()
    _, fill, _ = match(order(instrument, quantity=100), make_bar(instrument, "SSE", D2, "10"))
    entries = account.apply_fill(fill, market)
    assert account.cash == Decimal("98993.899900")
    assert account.quantities[instrument] == 100 and account.sellable.get(instrument, 0) == 0
    assert len(entries) == 3
    assert account.settle(D2) == ()
    assert account.settle(D2 + timedelta(days=1))[0].kind is LedgerKind.SETTLEMENT
    assert account.sellable[instrument] == 100


def test_account_sell_requires_sellable():
    instrument = uuid4(); account = SimulationAccount(uuid4(), Decimal("100000")); market, _ = rules()
    _, fill, _ = match(order(instrument, side=Side.SELL, quantity=100), make_bar(instrument, "SSE", D2, "10"))
    with pytest.raises(SimulationInvariantError): account.apply_fill(fill, market)


def test_account_cash_action_and_snapshot():
    account = SimulationAccount(uuid4(), Decimal("100"))
    entry = account.apply_cash_action(uuid4(), D1, Decimal("5"))
    snapshot = account.snapshot(D1, {}, {})
    assert entry.kind is LedgerKind.CORPORATE_ACTION
    assert snapshot.cash == snapshot.nav == Decimal("105")


def test_account_snapshot_requires_all_position_prices():
    instrument = uuid4(); account = SimulationAccount(uuid4(), Decimal("100000")); market, _ = rules()
    _, fill, _ = match(order(instrument, quantity=100), make_bar(instrument, "SSE", D2, "10"))
    account.apply_fill(fill, market)
    with pytest.raises(SimulationInvariantError): account.snapshot(D2, {}, {})
