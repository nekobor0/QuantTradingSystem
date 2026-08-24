"""Shared fill-accounting semantics for research, backtest and operations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class LedgerKernelError(ValueError):
    """Raised when a fill cannot be represented by the shared accounting rules."""


def _decimal(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value))


def calculate_target_quantity(
    *, capital: Decimal, target_weight: Decimal, price: Decimal,
    lot_size: int, fee_bps: Decimal = Decimal(),
) -> int:
    """Round down to lots while reserving the configured buy fee inside capital."""
    capital, target_weight, price, fee_bps = map(_decimal, (capital, target_weight, price, fee_bps))
    if capital <= 0 or not Decimal() < target_weight <= Decimal("1") or price <= 0 or lot_size <= 0 or fee_bps < 0:
        raise LedgerKernelError("invalid target sizing input")
    raw = capital * target_weight / (price * (Decimal("1") + fee_bps / Decimal("10000")))
    return int(raw // lot_size) * lot_size


@dataclass(frozen=True, slots=True)
class FillAccountingDelta:
    gross: Decimal
    fee: Decimal
    cash_delta: Decimal
    quantity_delta: int
    cost_delta: Decimal
    realized_pnl_delta: Decimal


def calculate_fill_accounting(
    *, side: str, quantity: int, price: Decimal,
    commission: Decimal = Decimal(), tax: Decimal = Decimal(),
    other_fee: Decimal = Decimal(), current_quantity: int = 0,
    current_cost: Decimal = Decimal(),
) -> FillAccountingDelta:
    """Return identical accounting deltas for every execution environment."""
    normalized_side = getattr(side, "value", side)
    price = _decimal(price)
    commission, tax, other_fee = map(_decimal, (commission, tax, other_fee))
    current_cost = _decimal(current_cost)
    if normalized_side not in {"BUY", "SELL"}:
        raise LedgerKernelError(f"unknown side: {normalized_side}")
    if quantity <= 0 or price <= 0:
        raise LedgerKernelError("quantity and price must be positive")
    if any(value < 0 for value in (commission, tax, other_fee, current_cost)):
        raise LedgerKernelError("fees and current cost must be nonnegative")
    gross = price * quantity
    fee = commission + tax + other_fee
    if normalized_side == "BUY":
        return FillAccountingDelta(
            gross=gross, fee=fee, cash_delta=-(gross + fee),
            quantity_delta=quantity, cost_delta=gross + fee,
            realized_pnl_delta=Decimal(),
        )
    if current_quantity < quantity or current_quantity <= 0:
        raise LedgerKernelError("sell exceeds current quantity")
    released_cost = current_cost / current_quantity * quantity
    return FillAccountingDelta(
        gross=gross, fee=fee, cash_delta=gross - fee,
        quantity_delta=-quantity, cost_delta=-released_cost,
        realized_pnl_delta=gross - fee - released_cost,
    )
