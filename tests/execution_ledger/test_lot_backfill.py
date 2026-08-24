from datetime import timedelta
from decimal import Decimal

import pytest

from quant_trading_system.execution_ledger import EntryType, OrderSide
from quant_trading_system.execution_ledger.errors import InvalidLedgerInput
from quant_trading_system.execution_ledger.lot_backfill import plan_legacy_lot_entries

from .conftest import T0, fill, manual_order


def _legacy_case(service, funded, instrument_id, repo):
    first = service.record_order(manual_order(funded, instrument_id, quantity=100, key="b1"))
    service.record_fill(first.order_id, fill(fill_id="f1", quantity=100, price="10", commission="0"), 0)
    second_at = T0 + timedelta(days=2)
    second = service.record_order(manual_order(funded, instrument_id, quantity=100, key="b2", at=second_at))
    service.record_fill(second.order_id, fill(fill_id="f2", quantity=100, price="20", commission="0", at=second_at), 0)
    sell_at = T0 + timedelta(days=4)
    sell = service.record_order(manual_order(funded, instrument_id, side=OrderSide.SELL, quantity=120, key="s", at=sell_at))
    service.record_fill(sell.order_id, fill(fill_id="s", quantity=120, price="30", commission="0", at=sell_at, settle_days=0), 0)
    legacy = tuple(entry for entry in repo.entry_values if entry.entry_type not in (EntryType.LOT_POSITION, EntryType.LOT_SETTLEMENT))
    return tuple(repo.orders.values()), tuple(repo.fills.values()), legacy, sell_at


def test_backfill_is_deterministic_and_reconciles_to_legacy_snapshot(service, funded, instrument_id, repo):
    orders, fills, legacy, as_of = _legacy_case(service, funded, instrument_id, repo)
    first = plan_legacy_lot_entries(account_id=funded.account_id, orders=orders, fills=fills, legacy_entries=legacy)
    second = plan_legacy_lot_entries(account_id=funded.account_id, orders=orders, fills=fills, legacy_entries=legacy)
    assert first == second
    assert len({entry.entry_id for entry in first}) == len(first)

    repo.entry_values = list(legacy) + list(first)
    position = service.get_account_snapshot(funded.account_id, as_of, persist=False).positions[0]
    assert position.quantity == position.sellable_quantity == 80
    assert position.cost == Decimal("1200")
    assert len(position.lots) == 1
    assert position.lots[0].buy_date == (T0 + timedelta(days=2)).date()


def test_backfill_rejects_mixed_lot_ledger(service, funded, instrument_id, repo):
    orders, fills, legacy, _ = _legacy_case(service, funded, instrument_id, repo)
    lot_entry = next(entry for entry in repo.entry_values if entry.entry_type is EntryType.LOT_POSITION)
    with pytest.raises(InvalidLedgerInput, match="mixed legacy"):
        plan_legacy_lot_entries(account_id=funded.account_id, orders=orders, fills=fills, legacy_entries=legacy + (lot_entry,))


def test_backfill_rejects_sell_before_settlement(service, funded, instrument_id, repo):
    buy = service.record_order(manual_order(funded, instrument_id, key="b"))
    recorded = service.record_fill(buy.order_id, fill(fill_id="b", settle_days=1), 0)
    sell_order = service.record_order(manual_order(funded, instrument_id, side=OrderSide.SELL, key="s"))
    impossible_fill = type(recorded)(
        sell_order.order_id, funded.account_id, instrument_id, recorded.broker, "impossible", T0,
        recorded.recorded_at, 100, Decimal("10"), Decimal(), Decimal(), Decimal(), "CNY",
        "600000.SH", T0, "hash",
    )
    legacy = tuple(entry for entry in repo.entry_values if entry.entry_type not in (EntryType.LOT_POSITION, EntryType.LOT_SETTLEMENT))
    with pytest.raises(InvalidLedgerInput, match="settled lots"):
        plan_legacy_lot_entries(account_id=funded.account_id, orders=tuple(repo.orders.values()), fills=(recorded, impossible_fill), legacy_entries=legacy)


def test_backfill_orders_same_timestamp_buy_before_sell(service, funded, instrument_id, repo):
    buy = service.record_order(manual_order(funded, instrument_id, key="b"))
    recorded = service.record_fill(buy.order_id, fill(fill_id="b", settle_days=0), 0)
    sell_order = service.record_order(manual_order(funded, instrument_id, side=OrderSide.SELL, key="s"))
    sell_fill = type(recorded)(
        sell_order.order_id, funded.account_id, instrument_id, recorded.broker, "s", T0,
        recorded.recorded_at, 100, Decimal("10"), Decimal(), Decimal(), Decimal(), "CNY",
        "600000.SH", T0, "sell-hash",
    )
    legacy = tuple(entry for entry in repo.entry_values if entry.entry_type not in (EntryType.LOT_POSITION, EntryType.LOT_SETTLEMENT))
    # Add the aggregate sell entries that a pre-lot ledger would contain.
    from dataclasses import replace
    buy_entries = [entry for entry in legacy if entry.source_id == recorded.fill_id]
    for entry in buy_entries:
        if entry.entry_type in (EntryType.POSITION, EntryType.SETTLEMENT):
            legacy += (replace(entry, entry_id=__import__("uuid").uuid4(), source_id=sell_fill.fill_id, quantity_delta=-entry.quantity_delta, cost_delta=-entry.cost_delta),)
    planned = plan_legacy_lot_entries(account_id=funded.account_id, orders=tuple(repo.orders.values()), fills=(sell_fill, recorded), legacy_entries=legacy)
    assert planned
