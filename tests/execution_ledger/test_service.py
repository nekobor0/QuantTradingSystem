from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.execution_ledger import *
from quant_trading_system.execution_ledger.errors import *

from .conftest import T0, fill, manual_order, recommendation_order


def test_register_account_is_idempotent(service, account, repo):
    assert service.register_account(account) == account
    assert len(repo.accounts) == 1


def test_register_account_conflicting_id(service, account):
    with pytest.raises(OrderConflict):
        service.register_account(replace(account, broker="other"))


def test_order_is_idempotent_and_creates_no_entry(service, funded, instrument_id, repo):
    command = manual_order(funded, instrument_id)
    first = service.record_order(command)
    assert service.record_order(command) == first
    assert len(repo.orders) == 1
    assert len(repo.entry_values) == 1  # initial funding only


def test_order_key_conflict(service, funded, instrument_id):
    service.record_order(manual_order(funded, instrument_id))
    with pytest.raises(OrderConflict):
        service.record_order(manual_order(funded, instrument_id, quantity=200))


def test_recommendation_order_enforces_approved_remaining(service, funded, instrument_id):
    with pytest.raises(InvalidLedgerInput):
        service.record_order(recommendation_order(funded, instrument_id, quantity=101, approved=100))


def test_recommendation_order_needs_approval_quantity(service, funded, instrument_id):
    command = recommendation_order(funded, instrument_id)
    with pytest.raises(InvalidLedgerInput):
        service.record_order(replace(command, approved_remaining_quantity=None))


def test_disabled_account_rejects_order(service, account, instrument_id, repo):
    repo.update_account(replace(account, status=AccountStatus.DISABLED))
    with pytest.raises(InvalidLedgerInput):
        service.record_order(manual_order(account, instrument_id))


def test_buy_fill_updates_order_cash_position_and_delays_sellable(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id))
    recorded = service.record_fill(order.order_id, fill(), 0)
    assert service.record_fill(order.order_id, fill(), 1) == recorded
    at_fill = service.get_account_snapshot(funded.account_id, T0)
    assert at_fill.cash["CNY"] == Decimal("98995")
    assert at_fill.positions[0].quantity == 100
    assert at_fill.positions[0].sellable_quantity == 0
    assert at_fill.positions[0].cost == Decimal("1005")
    assert at_fill.positions[0].lots[0].lot_id == recorded.fill_id
    assert at_fill.positions[0].lots[0].buy_date == T0.date()
    assert at_fill.positions[0].lots[0].sellable_quantity == 0
    settled = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=1))
    assert settled.positions[0].sellable_quantity == 100
    assert repo.get_order(order.order_id).status is OrderStatus.FILLED
    assert len([e for e in repo.entry_values if e.source_id == recorded.fill_id]) == 6


def test_fifo_lots_preserve_buy_date_and_reconcile_to_position(service, funded, instrument_id):
    first = service.record_order(manual_order(funded, instrument_id, quantity=100, key="b1"))
    f1 = service.record_fill(first.order_id, fill(fill_id="f1", quantity=100, price="10", commission="0"), 0)
    second_at = T0 + timedelta(days=2)
    second = service.record_order(manual_order(funded, instrument_id, quantity=100, key="b2", at=second_at))
    f2 = service.record_fill(second.order_id, fill(fill_id="f2", quantity=100, price="20", commission="0", at=second_at), 0)
    sell_at = T0 + timedelta(days=4)
    sell = service.record_order(manual_order(funded, instrument_id, side=OrderSide.SELL, quantity=120, key="s", at=sell_at))
    service.record_fill(sell.order_id, fill(fill_id="s1", quantity=120, price="30", commission="0", at=sell_at, settle_days=0), 0)

    position = service.get_account_snapshot(funded.account_id, sell_at).positions[0]
    assert len(position.lots) == 1
    assert position.lots[0].lot_id == f2.fill_id
    assert position.lots[0].buy_date == second_at.date()
    assert position.lots[0].quantity == position.lots[0].sellable_quantity == 80
    assert sum(lot.quantity for lot in position.lots) == position.quantity
    assert sum((lot.cost for lot in position.lots), Decimal()) == position.cost


def test_share_action_requires_existing_lot_and_is_idempotent(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id, key="buy"))
    recorded = service.record_fill(order.order_id, fill(fill_id="buy", settle_days=0), 0)
    action = PositionAdjustment(
        funded.account_id, instrument_id, recorded.fill_id, T0.date(), CorporateActionType.SPLIT,
        "CNY", 100, 100, Decimal("0"), T0 + timedelta(days=2), T0 + timedelta(days=1),
        "action-1", "two-for-one split",
    )
    assert service.record_position_adjustment(action) == action
    assert service.record_position_adjustment(action) == action
    position = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=2)).positions[0]
    assert position.quantity == position.sellable_quantity == 200
    assert position.cost == position.lots[0].cost == Decimal("1005")
    with pytest.raises(InvalidLedgerInput, match="existing matching lot"):
        service.record_position_adjustment(replace(action, adjustment_id=uuid4(), external_ref="bad", lot_id=uuid4()))


def test_share_action_fails_closed_when_not_available_by_effective_time(funded, instrument_id):
    with pytest.raises(InvalidLedgerInput, match="unavailable"):
        PositionAdjustment(
            funded.account_id, instrument_id, uuid4(), T0.date(), CorporateActionType.SPLIT,
            "CNY", 100, 100, Decimal("0"), T0, T0 + timedelta(days=1), "future", "future fact",
        )


def test_share_action_rejects_sellable_above_quantity_before_write(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id, key="buy"))
    recorded = service.record_fill(order.order_id, fill(fill_id="buy", settle_days=0), 0)
    action = PositionAdjustment(
        funded.account_id, instrument_id, recorded.fill_id, T0.date(), CorporateActionType.CANCELLATION,
        "CNY", -50, 0, Decimal("0"), T0 + timedelta(days=1), T0, "bad-action", "bad instruction",
    )
    before = len(repo.entry_values)
    with pytest.raises(InsufficientBalance, match="sellable exceed"):
        service.record_position_adjustment(action)
    assert len(repo.entry_values) == before
    assert repo.find_position_adjustment(funded.account_id, "bad-action") is None


def test_full_cancellation_requires_explicit_cost_release(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id, key="buy"))
    recorded = service.record_fill(order.order_id, fill(fill_id="buy", settle_days=0), 0)
    incomplete = PositionAdjustment(
        funded.account_id, instrument_id, recorded.fill_id, T0.date(), CorporateActionType.CANCELLATION,
        "CNY", -100, -100, Decimal("0"), T0 + timedelta(days=1), T0, "cancel-bad", "missing cost instruction",
    )
    with pytest.raises(InsufficientBalance, match="closed lot"):
        service.record_position_adjustment(incomplete)
    complete = replace(incomplete, adjustment_id=uuid4(), external_ref="cancel-good", cost_delta=Decimal("-1005"))
    service.record_position_adjustment(complete)
    assert service.get_account_snapshot(funded.account_id, T0 + timedelta(days=1)).positions == ()


def test_cash_dividend_is_net_atomic_idempotent_and_keeps_lot(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id, key="div-buy"))
    recorded = service.record_fill(order.order_id, fill(fill_id="div-buy", settle_days=0), 0)
    action = CorporateCashAction(
        funded.account_id, instrument_id, recorded.fill_id, T0.date(), CorporateCashActionType.CASH_DIVIDEND,
        "CNY", Decimal("100"), Decimal("10"), T0 + timedelta(days=2), T0 + timedelta(days=1),
        "dividend-1", "tax-withheld cash dividend",
    )
    before = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=2))
    assert service.record_corporate_cash_action(action) == action
    assert service.record_corporate_cash_action(action) == action
    after = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=2))
    assert after.cash["CNY"] - before.cash["CNY"] == Decimal("90")
    assert after.positions == before.positions
    action_entries = [entry for entry in repo.entry_values if entry.source_id == action.action_id]
    assert [entry.cash_delta for entry in action_entries] == [Decimal("100"), Decimal("-10")]
    assert len(repo.corporate_cash_actions) == 1


def test_delisting_cash_disposal_closes_lot_and_records_realized_pnl(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id, key="delist-buy"))
    recorded = service.record_fill(order.order_id, fill(fill_id="delist-buy", settle_days=0), 0)
    action = CorporateCashAction(
        funded.account_id, instrument_id, recorded.fill_id, T0.date(), CorporateCashActionType.DELISTING_CASH_DISPOSAL,
        "CNY", Decimal("800"), Decimal("0"), T0 + timedelta(days=2), T0 + timedelta(days=1),
        "delist-1", "cash disposal on delisting",
    )
    before_cash = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=2)).cash["CNY"]
    service.record_corporate_cash_action(action)
    after = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=2))
    assert after.cash["CNY"] - before_cash == Decimal("800")
    assert after.positions == ()
    assert sum(entry.realized_pnl_delta for entry in repo.entry_values if entry.source_id == action.action_id) == Decimal("-205")


def test_corporate_cash_action_fails_before_write_for_missing_lot_or_future_fact(service, funded, instrument_id, repo):
    with pytest.raises(InvalidLedgerInput, match="unavailable"):
        CorporateCashAction(
            funded.account_id, instrument_id, uuid4(), T0.date(), CorporateCashActionType.CASH_DIVIDEND,
            "CNY", Decimal("10"), Decimal("0"), T0, T0 + timedelta(days=1), "future-div", "future fact",
        )
    action = CorporateCashAction(
        funded.account_id, instrument_id, uuid4(), T0.date(), CorporateCashActionType.CASH_DIVIDEND,
        "CNY", Decimal("10"), Decimal("0"), T0, T0, "missing-lot", "missing lot",
    )
    before = len(repo.entry_values)
    with pytest.raises(InvalidLedgerInput, match="existing matching lot"):
        service.record_corporate_cash_action(action)
    assert len(repo.entry_values) == before and not repo.corporate_cash_actions


def test_two_partial_fills_progress_status_and_average_cost(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id, quantity=200))
    service.record_fill(order.order_id, fill(fill_id="f1", quantity=100, price="10", commission="5"), 0)
    assert repo.get_order(order.order_id).status is OrderStatus.PARTIALLY_FILLED
    service.record_fill(order.order_id, fill(fill_id="f2", quantity=100, price="20", commission="5", at=T0 + timedelta(minutes=1)), 1)
    current = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=2))
    assert current.positions[0].cost == Decimal("3010")
    assert current.positions[0].quantity == current.positions[0].sellable_quantity == 200
    assert repo.get_order(order.order_id).status is OrderStatus.FILLED


def test_duplicate_fill_different_payload_conflicts(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id, quantity=200))
    service.record_fill(order.order_id, fill(quantity=100), 0)
    with pytest.raises(FillConflict):
        service.record_fill(order.order_id, fill(quantity=101), 1)


def test_overfill_has_no_side_effect(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id, quantity=100))
    before = len(repo.entry_values)
    with pytest.raises(Overfill):
        service.record_fill(order.order_id, fill(quantity=101), 0)
    assert len(repo.entry_values) == before
    assert repo.get_order(order.order_id).version == 0


def test_currency_mismatch_has_no_side_effect(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id))
    with pytest.raises(CurrencyMismatch):
        service.record_fill(order.order_id, fill(currency="HKD"), 0)
    assert len(repo.entry_values) == 1


def test_wrong_order_version_rejected(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id))
    with pytest.raises(FillConflict):
        service.record_fill(order.order_id, fill(), 99)


def test_fallback_fill_id_requires_manual_confirmation(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id))
    with pytest.raises(InvalidLedgerInput):
        service.record_fill(order.order_id, fill(fill_id=None, row_hash="row", confirmed=False), 0)
    recorded = service.record_fill(order.order_id, fill(fill_id=None, row_hash="row", confirmed=True), 0)
    assert recorded.broker_fill_id == "ROW:row"


def test_insufficient_cash_rejects_buy(service, account, instrument_id):
    order = service.record_order(manual_order(account, instrument_id))
    with pytest.raises(InsufficientBalance):
        service.record_fill(order.order_id, fill(), 0)


def test_sell_uses_settled_quantity_and_moving_average_cost(service, funded, instrument_id, repo):
    buy = service.record_order(manual_order(funded, instrument_id, quantity=200, key="buy"))
    service.record_fill(buy.order_id, fill(fill_id="buy-fill", quantity=200, price="10", commission="10"), 0)
    sell = service.record_order(manual_order(funded, instrument_id, side=OrderSide.SELL, quantity=100, key="sell", at=T0 + timedelta(days=2)))
    service.record_fill(sell.order_id, fill(fill_id="sell-fill", quantity=100, price="12", commission="5", tax="1", at=T0 + timedelta(days=2), settle_days=0), 0)
    snapshot = service.get_account_snapshot(funded.account_id, T0 + timedelta(days=2))
    assert snapshot.positions[0].quantity == snapshot.positions[0].sellable_quantity == 100
    assert snapshot.positions[0].cost == Decimal("1005")
    assert snapshot.cash["CNY"] == Decimal("99184")
    realized = sum(e.realized_pnl_delta for e in repo.entry_values)
    assert realized == Decimal("189")


def test_sell_before_settlement_rejected(service, funded, instrument_id):
    buy = service.record_order(manual_order(funded, instrument_id, key="buy"))
    service.record_fill(buy.order_id, fill(fill_id="buy-fill"), 0)
    sell = service.record_order(manual_order(funded, instrument_id, side=OrderSide.SELL, key="sell"))
    with pytest.raises(InsufficientBalance):
        service.record_fill(sell.order_id, fill(fill_id="sell-fill", settle_days=0), 0)


def test_cancelled_order_routes_late_fill_to_review(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id))
    cancelled = service.transition_order(order.order_id, OrderStatus.CANCELLED, 0, T0)
    assert cancelled.status is OrderStatus.CANCELLED
    with pytest.raises(LateFillReview):
        service.record_fill(order.order_id, fill(), 1)


@pytest.mark.parametrize("target", [OrderStatus.CANCELLED, OrderStatus.REJECTED])
def test_submitted_order_terminal_transitions(service, funded, instrument_id, target):
    order = service.record_order(manual_order(funded, instrument_id))
    assert service.transition_order(order.order_id, target, 0, T0).status is target


@pytest.mark.parametrize("target", [OrderStatus.DRAFT, OrderStatus.SUBMITTED, OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED])
def test_invalid_order_transition_rejected(service, funded, instrument_id, target):
    order = service.record_order(manual_order(funded, instrument_id))
    with pytest.raises(OrderConflict):
        service.transition_order(order.order_id, target, 0, T0)


def test_order_transition_version_conflict(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id))
    with pytest.raises(OrderConflict):
        service.transition_order(order.order_id, OrderStatus.CANCELLED, 2, T0)
