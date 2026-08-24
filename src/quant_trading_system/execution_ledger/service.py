from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Mapping
from uuid import UUID, uuid4

from quant_trading_system.portfolio.ledger_kernel import calculate_fill_accounting

from .domain import (
    Account,
    AccountSnapshot,
    AccountStatus,
    CashEvent,
    CashEventType,
    EntryType,
    Fill,
    FillInput,
    LedgerEntry,
    LedgerEvent,
    Order,
    OrderInput,
    OrderSide,
    OrderSource,
    OrderStatus,
    PositionSnapshot,
    PositionLotSnapshot,
    PositionAdjustment,
    CorporateCashAction,
    CorporateCashActionType,
    Reconciliation,
    ReconciliationItem,
    ReconciliationStatus,
    StatementImport,
    aware,
    dec,
)
from .errors import (
    CurrencyMismatch,
    FillConflict,
    InsufficientBalance,
    InvalidLedgerInput,
    LateFillReview,
    NotFound,
    OrderConflict,
    Overfill,
    ReconciliationConflict,
)
from .ports import LedgerRepository


class ExecutionLedgerService:
    """Application service whose only balance source is immutable ledger entries."""

    def __init__(self, repository: LedgerRepository):
        self.repository = repository

    def register_account(self, account: Account) -> Account:
        existing = self.repository.get_account(account.account_id)
        if existing is not None and existing != account:
            raise OrderConflict("account id already has different content")
        if existing is None:
            self.repository.save_account(account)
        return existing or account

    def record_order(self, value: OrderInput) -> Order:
        account = self._account(value.account_id)
        if account.status is AccountStatus.DISABLED:
            raise InvalidLedgerInput("account is disabled")
        if value.source is OrderSource.RECOMMENDATION:
            if value.approved_remaining_quantity is None:
                raise InvalidLedgerInput("approved remaining quantity is required")
            if value.quantity > value.approved_remaining_quantity:
                raise InvalidLedgerInput("order exceeds approved remaining quantity")
        candidate = Order(
            account_id=value.account_id,
            instrument_id=value.instrument_id,
            source=value.source,
            side=value.side,
            quantity=value.quantity,
            currency=value.currency.upper(),
            submitted_at=value.submitted_at,
            idempotency_key=value.idempotency_key,
            recommendation_id=value.recommendation_id,
            manual_reason=value.manual_reason,
            broker_order_id=value.broker_order_id,
            limit_price=value.limit_price,
        )
        existing = self.repository.find_order(value.account_id, value.idempotency_key)
        if existing is not None:
            if self._order_payload(existing) != self._order_payload(candidate):
                raise OrderConflict("idempotency key reused with different order")
            return existing
        self.repository.save_order(
            candidate,
            self._event("OrderRecorded", value.account_id, value.submitted_at, {"order_id": str(candidate.order_id)}),
        )
        return candidate

    def record_fill(self, order_id: UUID, value: FillInput, expected_version: int) -> Fill:
        order = self._order(order_id)
        fill_key = self._fill_key(value)
        payload_hash = self._hash(self._fill_payload(value))
        existing = self.repository.find_fill(self._account(order.account_id).broker, order.account_id, fill_key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise FillConflict("fill key reused with different content")
            return existing
        if order.version != expected_version:
            raise FillConflict("order version conflict")
        if order.status is OrderStatus.CANCELLED:
            raise LateFillReview("LATE_FILL_REVIEW")
        if order.status in (OrderStatus.REJECTED, OrderStatus.FILLED):
            raise FillConflict("order does not accept fills")
        if value.currency.upper() != order.currency:
            raise CurrencyMismatch("CURRENCY_MISMATCH")
        new_filled = order.filled_quantity + value.quantity
        if new_filled > order.quantity:
            raise Overfill("OVERFILL")
        before = self.get_account_snapshot(order.account_id, value.filled_at, persist=False)
        current = next((p for p in before.positions if p.instrument_id == order.instrument_id), None)
        quantity = current.quantity if current else 0
        sellable = current.sellable_quantity if current else 0
        cost = current.cost if current else Decimal()
        gross = dec(value.price) * value.quantity
        fees = dec(value.commission) + dec(value.tax) + dec(value.other_fee)
        if order.side is OrderSide.BUY:
            available_cash = dec(before.cash.get(order.currency, Decimal()))
            if available_cash < gross + fees:
                raise InsufficientBalance("insufficient cash")
        elif quantity < value.quantity or sellable < value.quantity:
            raise InsufficientBalance("insufficient position or settled sellable quantity")
        now = datetime.now(timezone.utc)
        fill = Fill(
            order_id=order.order_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            broker=self._account(order.account_id).broker,
            broker_fill_id=fill_key,
            filled_at=value.filled_at,
            recorded_at=now,
            quantity=value.quantity,
            price=value.price,
            commission=value.commission,
            tax=value.tax,
            other_fee=value.other_fee,
            currency=order.currency,
            raw_code=value.raw_code,
            sellable_on=value.sellable_on,
            payload_hash=payload_hash,
        )
        entries = self._fill_entries(fill, order.side, current)
        status = OrderStatus.FILLED if new_filled == order.quantity else OrderStatus.PARTIALLY_FILLED
        updated = replace(order, filled_quantity=new_filled, status=status, version=order.version + 1)
        self.repository.record_fill(
            fill,
            entries,
            updated,
            self._event("FillRecorded", order.account_id, value.filled_at, {"fill_id": str(fill.fill_id)}),
        )
        return fill

    def transition_order(self, order_id: UUID, status: OrderStatus, expected_version: int, at: datetime) -> Order:
        order = self._order(order_id)
        if order.version != expected_version:
            raise OrderConflict("order version conflict")
        allowed = {
            OrderStatus.SUBMITTED: {OrderStatus.CANCELLED, OrderStatus.REJECTED},
            OrderStatus.PARTIALLY_FILLED: {OrderStatus.CANCELLED},
        }
        if status not in allowed.get(order.status, set()):
            raise OrderConflict("invalid order transition")
        updated = replace(order, status=status, version=order.version + 1)
        self.repository.update_order(updated, self._event("OrderStatusChanged", order.account_id, at, {"status": status.value}))
        return updated

    def record_cash_event(self, value: CashEvent) -> CashEvent:
        self._account(value.account_id)
        existing = self.repository.find_cash_event(value.account_id, value.external_ref)
        if existing is not None:
            if existing != value:
                raise FillConflict("cash event reference reused with different content")
            return existing
        self._validate_cash_sign(value)
        before = self.get_account_snapshot(value.account_id, value.effective_at, persist=False)
        if dec(before.cash.get(value.currency, Decimal())) + value.amount < 0:
            raise InsufficientBalance("cash event would make cash negative")
        entry = LedgerEntry(
            account_id=value.account_id,
            entry_type=EntryType.CASH,
            currency=value.currency,
            effective_at=value.effective_at,
            recorded_at=datetime.now(timezone.utc),
            source_type="CASH_EVENT",
            source_id=value.event_id,
            cash_delta=value.amount,
        )
        self.repository.record_cash(
            value,
            entry,
            self._event("CashEventRecorded", value.account_id, value.effective_at, {"cash_event_id": str(value.event_id)}),
        )
        return value

    def record_fx(
        self,
        account_id: UUID,
        source_currency: str,
        source_amount: Decimal,
        target_currency: str,
        target_amount: Decimal,
        rate: Decimal,
        effective_at: datetime,
        external_ref: str,
        reason: str,
    ) -> tuple[CashEvent, CashEvent]:
        if source_currency == target_currency or source_amount <= 0 or target_amount <= 0 or rate <= 0:
            raise InvalidLedgerInput("invalid FX conversion")
        if abs(dec(target_amount) / dec(source_amount) - dec(rate)) > Decimal("0.00000001"):
            raise InvalidLedgerInput("FX amounts do not match source rate")
        debit = CashEvent(account_id, CashEventType.FX, source_currency, -dec(source_amount), effective_at, external_ref + ":D", reason, target_currency, dec(rate))
        credit = CashEvent(account_id, CashEventType.FX, target_currency, dec(target_amount), effective_at, external_ref + ":C", reason, source_currency, dec(rate))
        return self.record_cash_event(debit), self.record_cash_event(credit)

    def get_account_snapshot(self, account_id: UUID, as_of: datetime, persist: bool = True) -> AccountSnapshot:
        self._account(account_id)
        point = aware(as_of, "as_of")
        included = sorted((e for e in self.repository.entries(account_id) if e.effective_at <= point), key=lambda e: (e.effective_at, str(e.entry_id)))
        cash: dict[str, Decimal] = {}
        position: dict[UUID, int] = {}
        sellable: dict[UUID, int] = {}
        cost: dict[UUID, Decimal] = {}
        lot_position: dict[UUID, int] = {}
        lot_sellable: dict[UUID, int] = {}
        lot_cost: dict[UUID, Decimal] = {}
        lot_meta: dict[UUID, tuple[UUID, date]] = {}
        for entry in included:
            if entry.entry_type is EntryType.CASH:
                cash[entry.currency] = cash.get(entry.currency, Decimal()) + entry.cash_delta
            elif entry.entry_type is EntryType.POSITION and entry.instrument_id is not None:
                position[entry.instrument_id] = position.get(entry.instrument_id, 0) + entry.quantity_delta
                cost[entry.instrument_id] = cost.get(entry.instrument_id, Decimal()) + entry.cost_delta
            elif entry.entry_type is EntryType.SETTLEMENT and entry.instrument_id is not None:
                sellable[entry.instrument_id] = sellable.get(entry.instrument_id, 0) + entry.quantity_delta
            elif entry.entry_type is EntryType.LOT_POSITION and entry.instrument_id is not None and entry.lot_id is not None and entry.buy_date is not None:
                lot_position[entry.lot_id] = lot_position.get(entry.lot_id, 0) + entry.quantity_delta
                lot_cost[entry.lot_id] = lot_cost.get(entry.lot_id, Decimal()) + entry.cost_delta
                lot_meta[entry.lot_id] = (entry.instrument_id, entry.buy_date)
            elif entry.entry_type is EntryType.LOT_SETTLEMENT and entry.lot_id is not None:
                lot_sellable[entry.lot_id] = lot_sellable.get(entry.lot_id, 0) + entry.quantity_delta
        if any(v < 0 for v in cash.values()) or any(v < 0 for v in position.values()) or any(v < 0 for v in sellable.values()):
            raise InsufficientBalance("ledger produces a negative balance")
        ids = tuple(e.entry_id for e in included)
        lots_by_instrument: dict[UUID, list[PositionLotSnapshot]] = {}
        for lot_id, quantity in lot_position.items():
            if quantity == 0:
                continue
            instrument_id, buy_date = lot_meta[lot_id]
            lot = PositionLotSnapshot(lot_id, instrument_id, buy_date, quantity, lot_sellable.get(lot_id, 0), lot_cost.get(lot_id, Decimal()))
            lots_by_instrument.setdefault(instrument_id, []).append(lot)
        if any(v < 0 for v in lot_position.values()) or any(v < 0 for v in lot_sellable.values()) or any(v < 0 for v in lot_cost.values()):
            raise InsufficientBalance("ledger produces a negative lot balance")
        if any(lot_sellable.get(lot_id, 0) > quantity for lot_id, quantity in lot_position.items()):
            raise InsufficientBalance("lot sellable quantity exceeds position quantity")
        positions = tuple(
            PositionSnapshot(i, q, sellable.get(i, 0), cost.get(i, Decimal()), tuple(sorted(lots_by_instrument.get(i, []), key=lambda lot: (lot.buy_date, str(lot.lot_id)))))
            for i, q in sorted(position.items(), key=lambda item: str(item[0]))
            if q != 0
        )
        for value in positions:
            if sum(lot.quantity for lot in value.lots) != value.quantity or sum(lot.sellable_quantity for lot in value.lots) != value.sellable_quantity or sum((lot.cost for lot in value.lots), Decimal()) != value.cost:
                raise InsufficientBalance("position and lot ledger do not reconcile")
        content_hash = self._hash({"entries": [str(i) for i in ids], "as_of": point.isoformat()})
        result = AccountSnapshot(account_id, point, dict(sorted(cash.items())), positions, content_hash, ids)
        if persist:
            self.repository.save_snapshot(result)
        return result

    def record_position_adjustment(self, value: PositionAdjustment) -> PositionAdjustment:
        self._account(value.account_id)
        existing = self.repository.find_position_adjustment(value.account_id, value.external_ref)
        if existing is not None:
            if existing != value:
                raise FillConflict("position adjustment reference reused with different content")
            return existing
        before = self.get_account_snapshot(value.account_id, value.effective_at, persist=False)
        position = next((item for item in before.positions if item.instrument_id == value.instrument_id), None)
        lot = next((item for item in (position.lots if position else ()) if item.lot_id == value.lot_id), None)
        if lot is None or lot.buy_date != value.buy_date:
            raise InvalidLedgerInput("position adjustment requires an existing matching lot")
        adjusted_quantity = lot.quantity + value.quantity_delta
        adjusted_sellable = lot.sellable_quantity + value.sellable_quantity_delta
        adjusted_cost = lot.cost + value.cost_delta
        if adjusted_quantity < 0 or adjusted_sellable < 0 or adjusted_cost < 0:
            raise InsufficientBalance("position adjustment makes lot negative")
        if adjusted_sellable > adjusted_quantity:
            raise InsufficientBalance("position adjustment makes sellable exceed quantity")
        if adjusted_quantity == 0 and (adjusted_sellable != 0 or adjusted_cost != 0):
            raise InsufficientBalance("closed lot must have zero sellable quantity and cost")
        now = datetime.now(timezone.utc)
        def item(entry_type, quantity_delta, cost_delta=Decimal()):
            return LedgerEntry(value.account_id, entry_type, value.currency, value.effective_at, now, "CORPORATE_ACTION", value.adjustment_id, value.instrument_id, quantity_delta, cost_delta=cost_delta, lot_id=value.lot_id, buy_date=value.buy_date)
        entries = (
            item(EntryType.POSITION, value.quantity_delta, value.cost_delta),
            item(EntryType.SETTLEMENT, value.sellable_quantity_delta),
            item(EntryType.LOT_POSITION, value.quantity_delta, value.cost_delta),
            item(EntryType.LOT_SETTLEMENT, value.sellable_quantity_delta),
        )
        self.repository.record_position_adjustment(value, entries, self._event("PositionAdjusted", value.account_id, value.effective_at, {"adjustment_id": str(value.adjustment_id), "action_type": value.action_type.value}))
        self.get_account_snapshot(value.account_id, value.effective_at, persist=False)
        return value

    def record_corporate_cash_action(self, value: CorporateCashAction) -> CorporateCashAction:
        self._account(value.account_id)
        existing = self.repository.find_corporate_cash_action(value.account_id, value.external_ref)
        if existing is not None:
            if existing != value:
                raise FillConflict("corporate cash action reference reused with different content")
            return existing
        before = self.get_account_snapshot(value.account_id, value.effective_at, persist=False)
        position = next((item for item in before.positions if item.instrument_id == value.instrument_id), None)
        lot = next((item for item in (position.lots if position else ()) if item.lot_id == value.lot_id), None)
        if lot is None or lot.buy_date != value.buy_date:
            raise InvalidLedgerInput("corporate cash action requires an existing matching lot")
        now = datetime.now(timezone.utc)
        def entry(entry_type, *, quantity=0, cash=Decimal(), cost=Decimal(), realized=Decimal()):
            return LedgerEntry(value.account_id, entry_type, value.currency, value.effective_at, now, "CORPORATE_CASH_ACTION", value.action_id, value.instrument_id, quantity, cash, cost, realized, value.lot_id, value.buy_date)
        entries = [entry(EntryType.CASH, cash=value.gross_cash)]
        if value.withholding_tax:
            entries.append(entry(EntryType.CASH, cash=-value.withholding_tax))
        if value.action_type is CorporateCashActionType.DELISTING_CASH_DISPOSAL:
            entries.extend((
                entry(EntryType.POSITION, quantity=-lot.quantity, cost=-lot.cost),
                entry(EntryType.SETTLEMENT, quantity=-lot.sellable_quantity),
                entry(EntryType.LOT_POSITION, quantity=-lot.quantity, cost=-lot.cost),
                entry(EntryType.LOT_SETTLEMENT, quantity=-lot.sellable_quantity),
                entry(EntryType.REALIZED_PNL, realized=value.net_cash - lot.cost),
            ))
        self.repository.record_corporate_cash_action(
            value, tuple(entries), self._event("CorporateCashActionRecorded", value.account_id, value.effective_at, {"action_id": str(value.action_id), "action_type": value.action_type.value})
        )
        self.get_account_snapshot(value.account_id, value.effective_at, persist=False)
        return value

    def reverse_fill(self, fill_id: UUID, reversal_at: datetime, expected_version: int, reason: str) -> Fill:
        original = self.repository.get_fill(fill_id)
        if original is None:
            raise NotFound(str(fill_id))
        if not reason.strip():
            raise InvalidLedgerInput("reversal reason is required")
        existing = self.repository.reversal_for(fill_id)
        if existing is not None:
            return existing
        order = self._order(original.order_id)
        if order.version != expected_version:
            raise FillConflict("order version conflict")
        point = aware(reversal_at, "reversal_at")
        reversal = replace(
            original,
            fill_id=uuid4(),
            broker_fill_id="REVERSAL:" + original.broker_fill_id,
            filled_at=point,
            recorded_at=datetime.now(timezone.utc),
            sellable_on=point,
            payload_hash=self._hash({"reverses": str(fill_id), "reason": reason}),
            reverses_fill_id=fill_id,
        )
        originals = [e for e in self.repository.entries(original.account_id) if e.source_id == original.fill_id]
        mirrored = tuple(
            replace(
                e,
                entry_id=uuid4(),
                effective_at=point,
                recorded_at=reversal.recorded_at,
                source_type="FILL_REVERSAL",
                source_id=reversal.fill_id,
                quantity_delta=-e.quantity_delta,
                cash_delta=-e.cash_delta,
                cost_delta=-e.cost_delta,
                realized_pnl_delta=-e.realized_pnl_delta,
            )
            for e in originals
        )
        filled = order.filled_quantity - original.quantity
        status = OrderStatus.SUBMITTED if filled == 0 else OrderStatus.PARTIALLY_FILLED
        updated = replace(order, filled_quantity=filled, status=status, version=order.version + 1)
        self.repository.record_fill(reversal, mirrored, updated, self._event("FillReversed", order.account_id, point, {"fill_id": str(fill_id), "reason": reason}))
        return reversal

    def reconcile(
        self,
        account_id: UUID,
        broker_cash: Mapping[str, Decimal],
        broker_positions: Mapping[UUID, int],
        broker_sellable: Mapping[UUID, int],
        as_of: datetime,
        broker_snapshot_hash: str,
        cash_tolerance: Decimal = Decimal("0"),
        quantity_tolerance: int = 0,
    ) -> Reconciliation:
        snapshot = self.get_account_snapshot(account_id, as_of)
        items: list[ReconciliationItem] = []
        for currency in sorted(set(snapshot.cash) | set(broker_cash)):
            system = dec(snapshot.cash.get(currency, Decimal()))
            broker = dec(broker_cash.get(currency, Decimal()))
            difference = broker - system
            items.append(ReconciliationItem("cash:" + currency, system, broker, difference, abs(difference) > cash_tolerance))
        system_positions = {p.instrument_id: p for p in snapshot.positions}
        for instrument_id in sorted(set(system_positions) | set(broker_positions) | set(broker_sellable), key=str):
            position = system_positions.get(instrument_id)
            system_quantity = Decimal(position.quantity if position else 0)
            system_sellable = Decimal(position.sellable_quantity if position else 0)
            broker_quantity = Decimal(broker_positions.get(instrument_id, 0))
            broker_sellable_quantity = Decimal(broker_sellable.get(instrument_id, 0))
            position_difference = broker_quantity - system_quantity
            sellable_difference = broker_sellable_quantity - system_sellable
            items.append(ReconciliationItem("position:" + str(instrument_id), system_quantity, broker_quantity, position_difference, abs(position_difference) > quantity_tolerance))
            items.append(ReconciliationItem("sellable:" + str(instrument_id), system_sellable, broker_sellable_quantity, sellable_difference, abs(sellable_difference) > quantity_tolerance))
        material = any(item.material for item in items)
        status = ReconciliationStatus.DIFFERENCE if material else ReconciliationStatus.MATCHED
        result = Reconciliation(account_id, as_of, status, tuple(items), broker_snapshot_hash, datetime.now(timezone.utc))
        account = replace(self._account(account_id), status=AccountStatus.BLOCKED_FOR_SIGNAL if material else AccountStatus.ACTIVE)
        self.repository.save_reconciliation(result, account, self._event("AccountReconciled", account_id, as_of, {"status": status.value}))
        return result

    def resolve_reconciliation(self, reconciliation_id: UUID, reason: str, resolved_at: datetime) -> Reconciliation:
        value = self.repository.get_reconciliation(reconciliation_id)
        if value is None:
            raise NotFound(str(reconciliation_id))
        if value.status is not ReconciliationStatus.DIFFERENCE:
            raise ReconciliationConflict("only a difference can be resolved")
        if not reason.strip():
            raise ReconciliationConflict("resolution evidence is required")
        point = aware(resolved_at, "resolved_at")
        items = tuple(replace(item, resolved_reason=reason) for item in value.items)
        updated = replace(value, status=ReconciliationStatus.RESOLVED, items=items, resolved_at=point, resolution_reason=reason)
        account = replace(self._account(value.account_id), status=AccountStatus.ACTIVE)
        self.repository.save_reconciliation(updated, account, self._event("ReconciliationResolved", value.account_id, point, {"reason": reason}))
        return updated

    def preview_statement(self, account_id: UUID, file_hash: str, format_version: str, preview_hash: str) -> StatementImport:
        self._account(account_id)
        if not all(x.strip() for x in (file_hash, format_version, preview_hash)):
            raise InvalidLedgerInput("statement hashes and format are required")
        existing = self.repository.find_import(account_id, file_hash, format_version)
        if existing is not None:
            if existing.preview_hash != preview_hash:
                raise FillConflict("same statement key has different preview")
            return existing
        value = StatementImport(account_id, file_hash, format_version, preview_hash, False)
        self.repository.save_import(value)
        return value

    def confirm_statement(self, import_id: UUID) -> StatementImport:
        value = self.repository.get_import(import_id)
        if value is None:
            raise NotFound(str(import_id))
        if value.confirmed:
            return value
        updated = replace(value, confirmed=True)
        self.repository.save_import(updated)
        return updated

    def _fill_entries(self, fill: Fill, side: OrderSide, current: PositionSnapshot | None) -> tuple[LedgerEntry, ...]:
        current_quantity = current.quantity if current else 0
        current_cost = current.cost if current else Decimal()
        delta = calculate_fill_accounting(
            side=side, quantity=fill.quantity, price=fill.price,
            commission=fill.commission, tax=fill.tax, other_fee=fill.other_fee,
            current_quantity=current_quantity, current_cost=current_cost,
        )
        def entry(
            entry_type: EntryType,
            effective_at: datetime,
            instrument_id: UUID | None = None,
            quantity_delta: int = 0,
            cash_delta: Decimal = Decimal(),
            cost_delta: Decimal = Decimal(),
            realized_pnl_delta: Decimal = Decimal(),
            lot_id: UUID | None = None,
            buy_date=None,
        ) -> LedgerEntry:
            return LedgerEntry(
                account_id=fill.account_id,
                entry_type=entry_type,
                currency=fill.currency,
                effective_at=effective_at,
                recorded_at=fill.recorded_at,
                source_type="FILL",
                source_id=fill.fill_id,
                instrument_id=instrument_id,
                quantity_delta=quantity_delta,
                cash_delta=cash_delta,
                cost_delta=cost_delta,
                realized_pnl_delta=realized_pnl_delta,
                lot_id=lot_id,
                buy_date=buy_date,
            )
        aggregate = (
            entry(EntryType.POSITION, fill.filled_at, fill.instrument_id, delta.quantity_delta, cost_delta=delta.cost_delta),
            entry(EntryType.SETTLEMENT, fill.sellable_on if side is OrderSide.BUY else fill.filled_at, fill.instrument_id, delta.quantity_delta),
            entry(EntryType.CASH, fill.filled_at, cash_delta=delta.cash_delta),
            entry(EntryType.REALIZED_PNL, fill.filled_at, fill.instrument_id, realized_pnl_delta=delta.realized_pnl_delta),
        )
        lots = list(current.lots if current else ())
        if side is OrderSide.BUY:
            final_quantity, final_cost = current_quantity + fill.quantity, current_cost + delta.cost_delta
            average = final_cost / final_quantity
            lot_entries = [entry(EntryType.LOT_POSITION, fill.filled_at, lot.instrument_id, cost_delta=average * lot.quantity - lot.cost, lot_id=lot.lot_id, buy_date=lot.buy_date) for lot in lots]
            lot_entries.extend((
                entry(EntryType.LOT_POSITION, fill.filled_at, fill.instrument_id, fill.quantity, cost_delta=average * fill.quantity, lot_id=fill.fill_id, buy_date=fill.filled_at.date()),
                entry(EntryType.LOT_SETTLEMENT, fill.sellable_on, fill.instrument_id, fill.quantity, lot_id=fill.fill_id, buy_date=fill.filled_at.date()),
            ))
            return aggregate + tuple(lot_entries)
        remaining = fill.quantity
        final_quantity, final_cost = current_quantity - fill.quantity, current_cost + delta.cost_delta
        average = final_cost / final_quantity if final_quantity else Decimal()
        lot_entries = []
        for lot in sorted(lots, key=lambda item: (item.buy_date, str(item.lot_id))):
            consume = min(remaining, lot.sellable_quantity)
            final_lot_quantity = lot.quantity - consume
            target_cost = average * final_lot_quantity
            lot_entries.append(entry(EntryType.LOT_POSITION, fill.filled_at, lot.instrument_id, -consume, cost_delta=target_cost - lot.cost, lot_id=lot.lot_id, buy_date=lot.buy_date))
            if consume:
                lot_entries.append(entry(EntryType.LOT_SETTLEMENT, fill.filled_at, lot.instrument_id, -consume, lot_id=lot.lot_id, buy_date=lot.buy_date))
            remaining -= consume
        if remaining:
            raise InsufficientBalance("FIFO lots do not cover sell quantity")
        return aggregate + tuple(lot_entries)

    @staticmethod
    def _validate_cash_sign(value: CashEvent) -> None:
        positive = (CashEventType.DEPOSIT, CashEventType.DIVIDEND)
        negative = (CashEventType.WITHDRAWAL, CashEventType.TAX, CashEventType.FEE)
        if value.event_type in positive and value.amount <= 0:
            raise InvalidLedgerInput("cash event must be positive")
        if value.event_type in negative and value.amount >= 0:
            raise InvalidLedgerInput("cash event must be negative")
        if value.event_type is CashEventType.FX and (value.counter_currency is None or value.source_rate is None):
            raise InvalidLedgerInput("FX leg needs counter currency and source rate")

    @staticmethod
    def _fill_key(value: FillInput) -> str:
        if value.broker_fill_id and value.broker_fill_id.strip():
            return value.broker_fill_id.strip()
        if value.stable_row_hash and value.stable_row_hash.strip() and value.manually_confirmed:
            return "ROW:" + value.stable_row_hash.strip()
        raise InvalidLedgerInput("fill needs broker id or manually confirmed stable row hash")

    @staticmethod
    def _fill_payload(value: FillInput) -> dict[str, str]:
        return {name: str(getattr(value, name)) for name in ("filled_at", "quantity", "price", "commission", "tax", "other_fee", "currency", "raw_code", "sellable_on")}

    @staticmethod
    def _order_payload(value: Order) -> tuple[object, ...]:
        return (value.account_id, value.instrument_id, value.source, value.side, value.quantity, value.currency, value.submitted_at, value.idempotency_key, value.recommendation_id, value.manual_reason, value.broker_order_id, value.limit_price)

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    @staticmethod
    def _event(event_type: str, account_id: UUID, occurred_at: datetime, payload: Mapping[str, str]) -> LedgerEvent:
        return LedgerEvent(event_type, account_id, occurred_at, datetime.now(timezone.utc), payload)

    def _account(self, account_id: UUID) -> Account:
        value = self.repository.get_account(account_id)
        if value is None:
            raise NotFound(str(account_id))
        return value

    def _order(self, order_id: UUID) -> Order:
        value = self.repository.get_order(order_id)
        if value is None:
            raise NotFound(str(order_id))
        return value
