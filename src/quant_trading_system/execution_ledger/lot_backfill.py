"""Deterministic, read-only planning for legacy lot-ledger compensation entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import NAMESPACE_URL, UUID, uuid5

from quant_trading_system.portfolio.ledger_kernel import calculate_fill_accounting

from .domain import EntryType, Fill, LedgerEntry, Order, OrderSide
from .errors import InvalidLedgerInput


@dataclass(slots=True)
class _Lot:
    lot_id: UUID
    instrument_id: UUID
    buy_date: date
    quantity: int
    sellable_on: datetime
    cost: Decimal


_COST_QUANTUM = Decimal("0.0000000001")


def _stored_cost(value: Decimal) -> Decimal:
    """Match the repository's persisted Numeric scale deterministically."""
    return value.quantize(_COST_QUANTUM, rounding=ROUND_HALF_EVEN)


def _allocate_cost(total: Decimal, quantities: list[int]) -> list[Decimal]:
    """Allocate stored cost; the final positive lot absorbs the exact remainder."""
    if not quantities or sum(quantities) <= 0:
        return [Decimal() for _ in quantities]
    total = _stored_cost(total)
    positive = [index for index, quantity in enumerate(quantities) if quantity > 0]
    average = total / sum(quantities)
    result = [Decimal() for _ in quantities]
    allocated = Decimal()
    for index in positive[:-1]:
        result[index] = _stored_cost(average * quantities[index])
        allocated += result[index]
    result[positive[-1]] = total - allocated
    return result


def _entry_id(fill_id: UUID, lot_id: UUID, kind: str, sequence: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"quant-ledger-lot-backfill:{fill_id}:{lot_id}:{kind}:{sequence}")


def plan_legacy_lot_entries(
    *, account_id: UUID, orders: tuple[Order, ...], fills: tuple[Fill, ...],
    legacy_entries: tuple[LedgerEntry, ...],
) -> tuple[LedgerEntry, ...]:
    """Plan append-only LOT entries; never writes or mutates legacy records."""
    relevant = tuple(entry for entry in legacy_entries if entry.account_id == account_id)
    if any(entry.entry_type in (EntryType.LOT_POSITION, EntryType.LOT_SETTLEMENT) for entry in relevant):
        raise InvalidLedgerInput("mixed legacy and lot-aware entries require manual adjudication")
    if any(entry.source_type == "CORPORATE_ACTION" for entry in relevant):
        raise InvalidLedgerInput("legacy corporate actions require primary-instruction adjudication")
    account_fills = tuple(fill for fill in fills if fill.account_id == account_id)
    if any(fill.reverses_fill_id is not None for fill in account_fills):
        raise InvalidLedgerInput("legacy fill reversals require manual adjudication")
    order_by_id = {order.order_id: order for order in orders if order.account_id == account_id}
    if len(order_by_id) != len(tuple(order for order in orders if order.account_id == account_id)):
        raise InvalidLedgerInput("duplicate order id")
    if any(fill.order_id not in order_by_id for fill in account_fills):
        raise InvalidLedgerInput("fill has no account order")

    lots: dict[UUID, list[_Lot]] = {}
    planned: list[LedgerEntry] = []
    for fill in sorted(account_fills, key=lambda item: (item.filled_at, 0 if order_by_id[item.order_id].side is OrderSide.BUY else 1, str(item.fill_id))):
        order = order_by_id[fill.order_id]
        instrument_lots = lots.setdefault(fill.instrument_id, [])
        quantity = sum(lot.quantity for lot in instrument_lots)
        cost = sum((lot.cost for lot in instrument_lots), Decimal())
        delta = calculate_fill_accounting(
            side=order.side, quantity=fill.quantity, price=fill.price,
            commission=fill.commission, tax=fill.tax, other_fee=fill.other_fee,
            current_quantity=quantity, current_cost=cost,
        )

        def add(kind: EntryType, lot: _Lot, quantity_delta: int, cost_delta=Decimal(), effective_at=None) -> None:
            sequence = len(planned)
            planned.append(LedgerEntry(
                account_id, kind, fill.currency, effective_at or fill.filled_at, fill.recorded_at,
                "LOT_BACKFILL", fill.fill_id, fill.instrument_id, quantity_delta,
                cost_delta=cost_delta, lot_id=lot.lot_id, buy_date=lot.buy_date,
                entry_id=_entry_id(fill.fill_id, lot.lot_id, kind.value, sequence),
            ))

        if order.side is OrderSide.BUY:
            final_cost = _stored_cost(cost + delta.cost_delta)
            new_lot = _Lot(fill.fill_id, fill.instrument_id, fill.filled_at.date(), fill.quantity, fill.sellable_on, Decimal())
            all_lots = instrument_lots + [new_lot]
            targets = _allocate_cost(final_cost, [lot.quantity for lot in all_lots])
            for lot, target in zip(instrument_lots, targets[:-1]):
                adjustment = target - lot.cost
                if adjustment:
                    add(EntryType.LOT_POSITION, lot, 0, adjustment)
                    lot.cost = target
            new_lot.cost = targets[-1]
            instrument_lots.append(new_lot)
            add(EntryType.LOT_POSITION, new_lot, fill.quantity, new_lot.cost)
            add(EntryType.LOT_SETTLEMENT, new_lot, fill.quantity, effective_at=fill.sellable_on)
            continue

        remaining = fill.quantity
        ordered_lots = sorted(instrument_lots, key=lambda item: (item.buy_date, str(item.lot_id)))
        consumed: dict[UUID, int] = {}
        for lot in ordered_lots:
            available = lot.quantity if lot.sellable_on <= fill.filled_at else 0
            consume = min(remaining, available)
            consumed[lot.lot_id] = consume
            remaining -= consume
        if remaining:
            raise InvalidLedgerInput("legacy sell exceeds FIFO settled lots")
        post_quantities = [lot.quantity - consumed[lot.lot_id] for lot in ordered_lots]
        targets = _allocate_cost(cost + delta.cost_delta, post_quantities)
        for lot, target_cost in zip(ordered_lots, targets):
            consume = consumed[lot.lot_id]
            add(EntryType.LOT_POSITION, lot, -consume, target_cost - lot.cost)
            if consume:
                add(EntryType.LOT_SETTLEMENT, lot, -consume)
            lot.quantity -= consume
            lot.cost = target_cost
        lots[fill.instrument_id] = [lot for lot in instrument_lots if lot.quantity]

    legacy_quantity: dict[UUID, int] = {}
    legacy_sellable: dict[UUID, int] = {}
    legacy_cost: dict[UUID, Decimal] = {}
    for entry in relevant:
        if entry.instrument_id is None:
            continue
        if entry.entry_type is EntryType.POSITION:
            legacy_quantity[entry.instrument_id] = legacy_quantity.get(entry.instrument_id, 0) + entry.quantity_delta
            legacy_cost[entry.instrument_id] = legacy_cost.get(entry.instrument_id, Decimal()) + entry.cost_delta
        elif entry.entry_type is EntryType.SETTLEMENT:
            legacy_sellable[entry.instrument_id] = legacy_sellable.get(entry.instrument_id, 0) + entry.quantity_delta
    as_of = max((entry.effective_at for entry in relevant), default=None)
    for instrument_id in set(legacy_quantity) | set(lots):
        open_lots = lots.get(instrument_id, [])
        got = (
            sum(lot.quantity for lot in open_lots),
            sum(lot.quantity for lot in open_lots if as_of is not None and lot.sellable_on <= as_of),
            sum((lot.cost for lot in open_lots), Decimal()),
        )
        expected = (legacy_quantity.get(instrument_id, 0), legacy_sellable.get(instrument_id, 0), legacy_cost.get(instrument_id, Decimal()))
        if got != expected:
            raise InvalidLedgerInput(f"planned lots do not reconcile for {instrument_id}: {got} != {expected}")
    return tuple(planned)
