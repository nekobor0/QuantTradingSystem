from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from quant_trading_system.backtest.account import SimulationAccount
from quant_trading_system.backtest.domain import MarketRule, Side, SimFill
from quant_trading_system.execution_ledger import (
    Account, CashEvent, CashEventType, ExecutionLedgerService, FillInput,
    OrderInput, OrderSide, OrderSource,
)
from quant_trading_system.execution_ledger.in_memory import InMemoryLedgerRepository


def test_backtest_and_operational_ledger_share_fill_accounting() -> None:
    t0 = datetime(2026, 8, 12, 1, 30, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=1)
    instrument, run_id = uuid4(), uuid4()
    rule = MarketRule("SSE", "v1", date(2020, 1, 1), None, 100, Decimal("0.01"), 1)

    simulated = SimulationAccount(run_id, Decimal("100000"))
    simulated.apply_fill(
        SimFill(run_id, uuid4(), instrument, Side.BUY, 100, Decimal("10"), Decimal("1000"),
                Decimal("5"), Decimal("0"), Decimal("1"), Decimal("0"), t0, uuid4()),
        rule,
    )

    repo = InMemoryLedgerRepository()
    service = ExecutionLedgerService(repo)
    account = service.register_account(Account("paper", "CNY", ("SSE",)))
    service.record_cash_event(
        CashEvent(account.account_id, CashEventType.DEPOSIT, "CNY", Decimal("100000"), t0, "fund", "test")
    )
    buy = service.record_order(
        OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.BUY, 100, "CNY", t0, "buy", manual_reason="test")
    )
    service.record_fill(
        buy.order_id,
        FillInput("buy-fill", None, False, t0, 100, Decimal("10"), Decimal("5"), Decimal("0"), Decimal("1"), "CNY", "600000.SH", t1),
        0,
    )
    operational = service.get_account_snapshot(account.account_id, t0)
    assert simulated.cash == operational.cash["CNY"] == Decimal("98994")
    assert simulated.quantities[instrument] == operational.positions[0].quantity == 100
    assert simulated.costs[instrument] == operational.positions[0].cost == Decimal("1006")
    assert operational.positions[0].sellable_quantity == 0

    simulated.settle(t1)
    sell_fill = SimFill(
        run_id, uuid4(), instrument, Side.SELL, 40, Decimal("12"), Decimal("480"),
        Decimal("2"), Decimal("1"), Decimal("1"), Decimal("0"), t1, uuid4(),
    )
    simulated.apply_fill(sell_fill, rule)
    sell = service.record_order(
        OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.SELL, 40, "CNY", t1, "sell", manual_reason="test")
    )
    service.record_fill(
        sell.order_id,
        FillInput("sell-fill", None, False, t1, 40, Decimal("12"), Decimal("2"), Decimal("1"), Decimal("1"), "CNY", "600000.SH", t1),
        0,
    )
    operational = service.get_account_snapshot(account.account_id, t1)
    assert simulated.cash == operational.cash["CNY"] == Decimal("99470")
    assert simulated.quantities[instrument] == operational.positions[0].quantity == 60
    assert simulated.sellable[instrument] == operational.positions[0].sellable_quantity == 60
    assert simulated.costs[instrument] == operational.positions[0].cost == Decimal("603.6")
