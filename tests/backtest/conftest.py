from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.backtest import *
from quant_trading_system.backtest.in_memory import InMemoryBacktestRepository
from quant_trading_system.strategies import CandidateAction, StrategyKind

UTC = timezone.utc
D1 = datetime(2025, 1, 2, 7, tzinfo=UTC)
D2 = datetime(2025, 1, 3, 7, tzinfo=UTC)
D3 = datetime(2025, 1, 6, 7, tzinfo=UTC)


@pytest.fixture
def etf_id(): return uuid4()


@pytest.fixture
def stock_id(): return uuid4()


@pytest.fixture
def definition():
    return BacktestDefinition(
        "dual-strategy",
        (
            StrategySpec(StrategyKind.ETF_TIMING, uuid4(), "etf-params", Decimal("0.4"), "daily-gate-weekly-target"),
            StrategySpec(StrategyKind.EQUITY_DAILY_SELECTION, uuid4(), "stock-params", Decimal("0.5"), "daily"),
        ),
        D1, D3, Decimal("100000"), "CNY", uuid4(), uuid4(), "git:abc", 7, Decimal("0.1"), 1,
    )


@pytest.fixture
def market_rules():
    return (
        MarketRule("ETF", "v1", date(2020, 1, 1), None, 100, Decimal("0.001"), 0),
        MarketRule("SSE", "v1", date(2020, 1, 1), None, 100, Decimal("0.01"), 1),
    )


@pytest.fixture
def cost_rules():
    return (
        CostRule("ETF", "v1", date(2020, 1, 1), None, Decimal("0.0003"), Decimal("5"), Decimal("0"), Decimal("0"), Decimal("0.001")),
        CostRule("SSE", "v1", date(2020, 1, 1), None, Decimal("0.0003"), Decimal("5"), Decimal("0.001"), Decimal("0.0001"), Decimal("0.001")),
    )


def make_bar(instrument_id, market, at, price="10", volume=100000, state=MarketState.NORMAL, available_at=None):
    price = Decimal(price)
    return SimulationBar(instrument_id, market, at, available_at or at, price, price + 1, price - 1, price, volume, state)


@pytest.fixture
def bars(etf_id, stock_id):
    return tuple(
        make_bar(instrument, market, at, price)
        for at, etf_price, stock_price in ((D1, "10", "20"), (D2, "11", "21"), (D3, "12", "19"))
        for instrument, market, price in ((etf_id, "ETF", etf_price), (stock_id, "SSE", stock_price))
    )


@pytest.fixture
def callbacks(etf_id, stock_id, definition):
    snapshot_id = definition.data_snapshot_id
    def etf(context, run_id):
        if context.decision_at == D1:
            return (StrategyTarget(StrategyKind.ETF_TIMING, run_id, etf_id, CandidateAction.SELECT, Decimal("1"), D1, snapshot_id, ("WEEKLY_TARGET",)),)
        if context.decision_at == D3:
            return (StrategyTarget(StrategyKind.ETF_TIMING, run_id, etf_id, CandidateAction.EXIT, Decimal("0"), D3, snapshot_id, ("DAILY_EXIT",)),)
        return ()
    def stock(context, run_id):
        action = CandidateAction.SELECT if context.decision_at == D1 else CandidateAction.KEEP if context.decision_at == D2 else CandidateAction.EXIT
        weight = Decimal("1") if action is not CandidateAction.EXIT else Decimal()
        return (StrategyTarget(StrategyKind.EQUITY_DAILY_SELECTION, run_id, stock_id, action, weight, context.decision_at, snapshot_id, (action.value,)),)
    return {StrategyKind.ETF_TIMING: etf, StrategyKind.EQUITY_DAILY_SELECTION: stock}


@pytest.fixture
def repo(): return InMemoryBacktestRepository()


@pytest.fixture
def engine(repo): return EventDrivenBacktestEngine(repo)

