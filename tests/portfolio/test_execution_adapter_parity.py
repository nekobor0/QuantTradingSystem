"""PL10 contract: backtest and operations are thin adapters over one kernel."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from quant_trading_system.backtest.account import SimulationAccount
from quant_trading_system.backtest.domain import MarketRule, Side, SimFill
from quant_trading_system.execution_ledger import (
    Account, CashEvent, CashEventType, ExecutionLedgerService, FillInput,
    OrderInput, OrderSide, OrderSource,
)
from quant_trading_system.execution_ledger.in_memory import InMemoryLedgerRepository
from quant_trading_system.portfolio import ledger_kernel


UTC = timezone.utc
T0 = datetime(2026, 8, 3, 1, 30, tzinfo=UTC)


def _sim_fill(run_id, order_id, instrument, side, quantity, price, commission, tax, at):
    return SimFill(
        run_id, order_id, instrument, side, quantity, Decimal(price),
        Decimal(price) * quantity, Decimal(commission), Decimal(tax), Decimal(),
        Decimal(), at, uuid4(),
    )


def test_backtest_and_operational_adapters_produce_identical_economic_state(monkeypatch):
    calls = []
    original = ledger_kernel.calculate_fill_accounting

    def traced(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr("quant_trading_system.backtest.account.calculate_fill_accounting", traced)
    monkeypatch.setattr("quant_trading_system.execution_ledger.service.calculate_fill_accounting", traced)

    instrument = uuid4(); run_id = uuid4()
    rule = MarketRule("SSE", "v1", date(2020, 1, 1), None, 100, Decimal("0.01"), 1)
    simulation = SimulationAccount(run_id, Decimal("100000"))
    repository = InMemoryLedgerRepository()
    operations = ExecutionLedgerService(repository)
    account = operations.register_account(Account("PARITY", "CNY", ("SSE",)))
    operations.record_cash_event(CashEvent(account.account_id, CashEventType.DEPOSIT, "CNY", Decimal("100000"), T0 - timedelta(days=1), "fund", "parity"))

    buy_at = T0
    simulation.apply_fill(_sim_fill(run_id, uuid4(), instrument, Side.BUY, 200, "10", "10", "0", buy_at), rule)
    buy = operations.record_order(OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.BUY, 200, "CNY", buy_at, "buy", manual_reason="parity"))
    operations.record_fill(buy.order_id, FillInput("buy", None, False, buy_at, 200, Decimal("10"), Decimal("10"), Decimal(), Decimal(), "CNY", "600000.SH", buy_at + timedelta(days=1)), 0)

    sell_at = T0 + timedelta(days=2)
    simulation.settle(sell_at)
    simulation.apply_fill(_sim_fill(run_id, uuid4(), instrument, Side.SELL, 100, "12", "5", "1", sell_at), rule)
    sell = operations.record_order(OrderInput(account.account_id, instrument, OrderSource.MANUAL, OrderSide.SELL, 100, "CNY", sell_at, "sell", manual_reason="parity"))
    operations.record_fill(sell.order_id, FillInput("sell", None, False, sell_at, 100, Decimal("12"), Decimal("5"), Decimal("1"), Decimal(), "CNY", "600000.SH", sell_at), 0)

    snapshot = operations.get_account_snapshot(account.account_id, sell_at, persist=False)
    position = snapshot.positions[0]
    realized = sum(entry.realized_pnl_delta for entry in repository.entry_values)
    expected_realized = Decimal("189")
    assert simulation.cash == snapshot.cash["CNY"] == Decimal("99184")
    assert simulation.quantities[instrument] == position.quantity == 100
    assert simulation.sellable[instrument] == position.sellable_quantity == 100
    assert simulation.costs[instrument] == position.cost == Decimal("1005")
    assert realized == expected_realized
    assert len(calls) == 4
    assert calls[0] == calls[1] and calls[2] == calls[3]


def test_both_adapters_import_the_only_shared_fill_kernel_directly():
    root = Path(__file__).resolve().parents[2]
    expected = "from quant_trading_system.portfolio.ledger_kernel import calculate_fill_accounting"
    for relative in (
        "src/quant_trading_system/backtest/account.py",
        "src/quant_trading_system/execution_ledger/service.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert text.count(expected) == 1
        assert "def calculate_fill_accounting" not in text
