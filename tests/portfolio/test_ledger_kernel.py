from decimal import Decimal

import pytest

from quant_trading_system.portfolio.ledger_kernel import (
    LedgerKernelError, calculate_fill_accounting, calculate_target_quantity,
)


def test_shared_buy_and_sell_accounting_conserves_cost_and_realized_pnl() -> None:
    buy = calculate_fill_accounting(
        side="BUY", quantity=100, price=Decimal("10"),
        commission=Decimal("5"), tax=Decimal("0"), other_fee=Decimal("1"),
    )
    assert buy.cash_delta == Decimal("-1006")
    assert buy.cost_delta == Decimal("1006")
    sell = calculate_fill_accounting(
        side="SELL", quantity=40, price=Decimal("12"),
        commission=Decimal("2"), tax=Decimal("1"), other_fee=Decimal("1"),
        current_quantity=100, current_cost=buy.cost_delta,
    )
    assert sell.cash_delta == Decimal("476")
    assert sell.cost_delta == Decimal("-402.4")
    assert sell.realized_pnl_delta == Decimal("73.6")
    assert buy.cost_delta + sell.cost_delta == Decimal("603.6")


def test_shared_kernel_rejects_oversell_and_negative_fees() -> None:
    with pytest.raises(LedgerKernelError, match="exceeds"):
        calculate_fill_accounting(
            side="SELL", quantity=101, price=Decimal("10"),
            current_quantity=100, current_cost=Decimal("1000"),
        )
    with pytest.raises(LedgerKernelError, match="nonnegative"):
        calculate_fill_accounting(
            side="BUY", quantity=1, price=Decimal("10"), commission=Decimal("-1"),
        )


def test_target_quantity_reserves_fee_and_rounds_down_to_lot() -> None:
    quantity = calculate_target_quantity(
        capital=Decimal("1000000"), target_weight=Decimal("0.01"),
        price=Decimal("10"), lot_size=100, fee_bps=Decimal("10"),
    )
    assert quantity == 900
    assert Decimal(quantity) * Decimal("10") * Decimal("1.001") <= Decimal("10000")
