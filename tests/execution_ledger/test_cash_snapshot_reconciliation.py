from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.execution_ledger import *
from quant_trading_system.execution_ledger.errors import *

from .conftest import T0, fill, manual_order


@pytest.mark.parametrize("event_type,amount", [(CashEventType.DEPOSIT, "10"), (CashEventType.DIVIDEND, "10"), (CashEventType.WITHDRAWAL, "-10"), (CashEventType.TAX, "-10"), (CashEventType.FEE, "-10"), (CashEventType.ADJUSTMENT, "10"), (CashEventType.ADJUSTMENT, "-10")])
def test_cash_event_types_affect_only_original_currency(service, funded, event_type, amount):
    value = CashEvent(funded.account_id, event_type, "CNY", Decimal(amount), T0 + timedelta(hours=1), "ref-" + event_type.value + amount, "reason")
    service.record_cash_event(value)
    expected = Decimal("100000") + Decimal(amount)
    assert service.get_account_snapshot(funded.account_id, T0 + timedelta(hours=2)).cash == {"CNY": expected}


@pytest.mark.parametrize("event_type,amount", [(CashEventType.DEPOSIT, "-1"), (CashEventType.DIVIDEND, "-1"), (CashEventType.WITHDRAWAL, "1"), (CashEventType.TAX, "1"), (CashEventType.FEE, "1")])
def test_cash_event_sign_rules(service, funded, event_type, amount):
    value = CashEvent(funded.account_id, event_type, "CNY", Decimal(amount), T0, "bad-" + event_type.value, "reason")
    with pytest.raises(InvalidLedgerInput):
        service.record_cash_event(value)


def test_cash_event_idempotency(service, funded, repo):
    event = CashEvent(funded.account_id, CashEventType.DIVIDEND, "CNY", Decimal("100"), T0, "div", "dividend")
    assert service.record_cash_event(event) == service.record_cash_event(event)
    assert len(repo.cash_events) == 2


def test_cash_event_reference_conflict(service, funded):
    event = CashEvent(funded.account_id, CashEventType.DIVIDEND, "CNY", Decimal("100"), T0, "div", "dividend")
    service.record_cash_event(event)
    with pytest.raises(FillConflict):
        service.record_cash_event(replace(event, amount=Decimal("101")))


def test_withdrawal_cannot_make_cash_negative(service, funded):
    event = CashEvent(funded.account_id, CashEventType.WITHDRAWAL, "CNY", Decimal("-100001"), T0, "withdraw", "withdrawal")
    with pytest.raises(InsufficientBalance):
        service.record_cash_event(event)


def test_fx_records_paired_original_currency_legs(service, funded):
    debit, credit = service.record_fx(funded.account_id, "CNY", Decimal("700"), "HKD", Decimal("750"), Decimal("750") / Decimal("700"), T0, "fx1", "conversion")
    snapshot = service.get_account_snapshot(funded.account_id, T0)
    assert debit.amount == Decimal("-700") and credit.amount == Decimal("750")
    assert snapshot.cash == {"CNY": Decimal("99300"), "HKD": Decimal("750")}
    assert debit.source_rate == credit.source_rate


@pytest.mark.parametrize("source,target,source_amount,target_amount,rate", [("CNY", "CNY", "1", "1", "1"), ("CNY", "HKD", "0", "1", "1"), ("CNY", "HKD", "1", "0", "1"), ("CNY", "HKD", "1", "1", "0"), ("CNY", "HKD", "2", "3", "1")])
def test_invalid_fx_rejected(service, funded, source, target, source_amount, target_amount, rate):
    with pytest.raises(InvalidLedgerInput):
        service.record_fx(funded.account_id, source, Decimal(source_amount), target, Decimal(target_amount), Decimal(rate), T0, "fx", "reason")


def test_future_entry_does_not_change_old_snapshot_hash(service, funded):
    old = service.get_account_snapshot(funded.account_id, T0)
    service.record_cash_event(CashEvent(funded.account_id, CashEventType.DEPOSIT, "CNY", Decimal("1"), T0 + timedelta(days=10), "future", "future"))
    again = service.get_account_snapshot(funded.account_id, T0)
    assert again.content_hash == old.content_hash
    assert again.entry_watermark == old.entry_watermark


def test_snapshot_hash_changes_when_effective_entry_is_added(service, funded):
    before = service.get_account_snapshot(funded.account_id, T0)
    service.record_cash_event(CashEvent(funded.account_id, CashEventType.DEPOSIT, "CNY", Decimal("1"), T0, "now", "now"))
    after = service.get_account_snapshot(funded.account_id, T0)
    assert after.content_hash != before.content_hash


def test_reversal_preserves_original_and_restores_balance(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id))
    original = service.record_fill(order.order_id, fill(settle_days=0), 0)
    before = service.get_account_snapshot(funded.account_id, T0)
    reversed_fill = service.reverse_fill(original.fill_id, T0 + timedelta(hours=1), 1, "broker correction")
    after = service.get_account_snapshot(funded.account_id, T0 + timedelta(hours=1))
    historical = service.get_account_snapshot(funded.account_id, T0)
    assert before.content_hash == historical.content_hash
    assert after.cash["CNY"] == Decimal("100000") and after.positions == ()
    assert repo.get_fill(original.fill_id) == original
    assert reversed_fill.reverses_fill_id == original.fill_id


def test_reversal_is_idempotent(service, funded, instrument_id, repo):
    order = service.record_order(manual_order(funded, instrument_id))
    original = service.record_fill(order.order_id, fill(settle_days=0), 0)
    first = service.reverse_fill(original.fill_id, T0 + timedelta(hours=1), 1, "reason")
    second = service.reverse_fill(original.fill_id, T0 + timedelta(hours=2), 2, "different retry text")
    assert first == second
    assert len(repo.fills) == 2


def test_reversal_requires_reason(service, funded, instrument_id):
    order = service.record_order(manual_order(funded, instrument_id))
    original = service.record_fill(order.order_id, fill(settle_days=0), 0)
    with pytest.raises(InvalidLedgerInput):
        service.reverse_fill(original.fill_id, T0, 1, "")


def test_reconciliation_match_keeps_account_active(service, funded, repo):
    value = service.reconcile(funded.account_id, {"CNY": Decimal("100000")}, {}, {}, T0, "broker-hash")
    assert value.status is ReconciliationStatus.MATCHED
    assert repo.get_account(funded.account_id).status is AccountStatus.ACTIVE


@pytest.mark.parametrize("kind", ["cash", "position", "sellable"])
def test_material_reconciliation_difference_blocks_signals(service, funded, instrument_id, repo, kind):
    cash = {"CNY": Decimal("100000")}
    positions = {}
    sellable = {}
    if kind == "cash": cash["CNY"] += 1
    if kind == "position": positions[instrument_id] = 1
    if kind == "sellable": sellable[instrument_id] = 1
    value = service.reconcile(funded.account_id, cash, positions, sellable, T0, "hash")
    assert value.status is ReconciliationStatus.DIFFERENCE
    assert any(x.material for x in value.items)
    assert repo.get_account(funded.account_id).status is AccountStatus.BLOCKED_FOR_SIGNAL


def test_reconciliation_tolerance(service, funded):
    value = service.reconcile(funded.account_id, {"CNY": Decimal("100001")}, {}, {}, T0, "hash", cash_tolerance=Decimal("1"))
    assert value.status is ReconciliationStatus.MATCHED


def test_resolve_reconciliation_keeps_evidence_and_unblocks(service, funded, repo):
    value = service.reconcile(funded.account_id, {"CNY": Decimal("99999")}, {}, {}, T0, "hash")
    resolved = service.resolve_reconciliation(value.reconciliation_id, "broker statement verified", T0 + timedelta(hours=1))
    assert resolved.status is ReconciliationStatus.RESOLVED
    assert resolved.resolution_reason == "broker statement verified"
    assert all(item.resolved_reason for item in resolved.items)
    assert repo.get_account(funded.account_id).status is AccountStatus.ACTIVE


def test_resolve_requires_difference_and_reason(service, funded):
    matched = service.reconcile(funded.account_id, {"CNY": Decimal("100000")}, {}, {}, T0, "hash")
    with pytest.raises(ReconciliationConflict):
        service.resolve_reconciliation(matched.reconciliation_id, "reason", T0)
    different = service.reconcile(funded.account_id, {"CNY": Decimal("1")}, {}, {}, T0, "hash2")
    with pytest.raises(ReconciliationConflict):
        service.resolve_reconciliation(different.reconciliation_id, "", T0)


def test_statement_preview_and_confirm_are_idempotent(service, funded):
    first = service.preview_statement(funded.account_id, "file", "v1", "preview")
    assert service.preview_statement(funded.account_id, "file", "v1", "preview") == first
    confirmed = service.confirm_statement(first.import_id)
    assert confirmed.confirmed
    assert service.confirm_statement(first.import_id) == confirmed


def test_statement_preview_conflict(service, funded):
    service.preview_statement(funded.account_id, "file", "v1", "one")
    with pytest.raises(FillConflict):
        service.preview_statement(funded.account_id, "file", "v1", "two")


@pytest.mark.parametrize("file_hash,version,preview", [("", "v1", "p"), ("f", "", "p"), ("f", "v1", ""), (" ", "v1", "p")])
def test_statement_preview_requires_identifiers(service, funded, file_hash, version, preview):
    with pytest.raises(InvalidLedgerInput):
        service.preview_statement(funded.account_id, file_hash, version, preview)
