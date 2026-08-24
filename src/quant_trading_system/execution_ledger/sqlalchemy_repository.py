from __future__ import annotations

from datetime import timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from .domain import *
from .errors import RepositoryConflict
from .tables import accounts, cash_events, corporate_cash_actions, events, fills, ledger_entries, orders, position_adjustments, reconciliation_items, reconciliations, snapshots, statement_imports


class SqlAlchemyLedgerRepository:
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _aware(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def save_account(self, value):
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(accounts).values(**self._account_values(value)))
        except IntegrityError as error:
            raise RepositoryConflict(str(error.orig)) from error

    def get_account(self, account_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(accounts).where(accounts.c.account_id == account_id)).mappings().one_or_none()
        return None if row is None else self._account(row)

    def update_account(self, value):
        with self.engine.begin() as connection:
            connection.execute(update(accounts).where(accounts.c.account_id == value.account_id).values(**self._account_values(value)))

    def find_order(self, account_id, key):
        with self.engine.connect() as connection:
            row = connection.execute(select(orders).where(orders.c.account_id == account_id, orders.c.idempotency_key == key)).mappings().one_or_none()
        return None if row is None else self._order(row)

    def get_order(self, order_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(orders).where(orders.c.order_id == order_id)).mappings().one_or_none()
        return None if row is None else self._order(row)

    def save_order(self, value, event):
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(orders).values(**self._order_values(value)))
                connection.execute(insert(events).values(**self._event_values(event)))
        except IntegrityError as error:
            raise RepositoryConflict(str(error.orig)) from error

    def update_order(self, value, event):
        with self.engine.begin() as connection:
            changed = connection.execute(update(orders).where(orders.c.order_id == value.order_id, orders.c.version == value.version - 1).values(**self._order_values(value)))
            if changed.rowcount != 1:
                raise RepositoryConflict("order version conflict")
            connection.execute(insert(events).values(**self._event_values(event)))

    def find_fill(self, broker, account_id, key):
        with self.engine.connect() as connection:
            row = connection.execute(select(fills).where(fills.c.broker == broker, fills.c.account_id == account_id, fills.c.broker_fill_id == key)).mappings().one_or_none()
        return None if row is None else self._fill(row)

    def get_fill(self, fill_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(fills).where(fills.c.fill_id == fill_id)).mappings().one_or_none()
        return None if row is None else self._fill(row)

    def reversal_for(self, fill_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(fills).where(fills.c.reverses_fill_id == fill_id)).mappings().one_or_none()
        return None if row is None else self._fill(row)

    def record_fill(self, fill, entries, order, event):
        try:
            with self.engine.begin() as connection:
                changed = connection.execute(
                    update(orders).where(orders.c.order_id == order.order_id, orders.c.version == order.version - 1).values(**self._order_values(order))
                )
                if changed.rowcount != 1:
                    raise RepositoryConflict("order version conflict")
                connection.execute(insert(fills).values(**self._fill_values(fill)))
                if entries:
                    connection.execute(insert(ledger_entries), [self._entry_values(entry) for entry in entries])
                connection.execute(insert(events).values(**self._event_values(event)))
        except IntegrityError as error:
            raise RepositoryConflict(str(error.orig)) from error

    def entries(self, account_id):
        with self.engine.connect() as connection:
            rows = connection.execute(select(ledger_entries).where(ledger_entries.c.account_id == account_id)).mappings().all()
        return tuple(self._entry(row) for row in rows)

    def find_cash_event(self, account_id, external_ref):
        with self.engine.connect() as connection:
            row = connection.execute(select(cash_events).where(cash_events.c.account_id == account_id, cash_events.c.external_ref == external_ref)).mappings().one_or_none()
        return None if row is None else self._cash_event(row)

    def record_cash(self, event_value, entry, event):
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(cash_events).values(**self._cash_values(event_value)))
                connection.execute(insert(ledger_entries).values(**self._entry_values(entry)))
                connection.execute(insert(events).values(**self._event_values(event)))
        except IntegrityError as error:
            raise RepositoryConflict(str(error.orig)) from error

    def find_position_adjustment(self, account_id, external_ref):
        with self.engine.connect() as connection:
            row = connection.execute(select(position_adjustments).where(position_adjustments.c.account_id == account_id, position_adjustments.c.external_ref == external_ref)).mappings().one_or_none()
        return None if row is None else self._position_adjustment(row)

    def record_position_adjustment(self, value, entries, event):
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(position_adjustments).values(**self._position_adjustment_values(value)))
                connection.execute(insert(ledger_entries), [self._entry_values(entry) for entry in entries])
                connection.execute(insert(events).values(**self._event_values(event)))
        except IntegrityError as error:
            raise RepositoryConflict(str(error.orig)) from error

    def find_corporate_cash_action(self, account_id, external_ref):
        with self.engine.connect() as connection:
            row = connection.execute(select(corporate_cash_actions).where(corporate_cash_actions.c.account_id == account_id, corporate_cash_actions.c.external_ref == external_ref)).mappings().one_or_none()
        return None if row is None else self._corporate_cash_action(row)

    def record_corporate_cash_action(self, value, entries, event):
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(corporate_cash_actions).values(**self._corporate_cash_action_values(value)))
                connection.execute(insert(ledger_entries), [self._entry_values(entry) for entry in entries])
                connection.execute(insert(events).values(**self._event_values(event)))
        except IntegrityError as error:
            raise RepositoryConflict(str(error.orig)) from error

    def save_snapshot(self, value):
        with self.engine.begin() as connection:
            connection.execute(insert(snapshots).values(
                snapshot_id=value.snapshot_id, account_id=value.account_id, as_of=value.as_of,
                cash={key: str(amount) for key, amount in value.cash.items()},
                positions=[{"instrument_id": str(p.instrument_id), "quantity": p.quantity, "sellable_quantity": p.sellable_quantity, "cost": str(p.cost), "lots": [{"lot_id": str(l.lot_id), "buy_date": l.buy_date.isoformat(), "quantity": l.quantity, "sellable_quantity": l.sellable_quantity, "cost": str(l.cost)} for l in p.lots]} for p in value.positions],
                content_hash=value.content_hash, entry_watermark=[str(x) for x in value.entry_watermark], source=value.source,
            ))

    def save_reconciliation(self, value, account, event):
        with self.engine.begin() as connection:
            exists = connection.execute(select(reconciliations.c.reconciliation_id).where(reconciliations.c.reconciliation_id == value.reconciliation_id)).scalar_one_or_none()
            if exists is None:
                connection.execute(insert(reconciliations).values(**self._reconciliation_values(value)))
            else:
                connection.execute(update(reconciliations).where(reconciliations.c.reconciliation_id == value.reconciliation_id).values(**self._reconciliation_values(value)))
                connection.execute(delete(reconciliation_items).where(reconciliation_items.c.reconciliation_id == value.reconciliation_id))
            if value.items:
                connection.execute(insert(reconciliation_items), [self._reconciliation_item_values(value.reconciliation_id, item) for item in value.items])
            connection.execute(update(accounts).where(accounts.c.account_id == account.account_id).values(**self._account_values(account)))
            connection.execute(insert(events).values(**self._event_values(event)))

    def get_reconciliation(self, reconciliation_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(reconciliations).where(reconciliations.c.reconciliation_id == reconciliation_id)).mappings().one_or_none()
            if row is None:
                return None
            item_rows = connection.execute(select(reconciliation_items).where(reconciliation_items.c.reconciliation_id == reconciliation_id)).mappings().all()
        return self._reconciliation(row, item_rows)

    def save_import(self, value):
        with self.engine.begin() as connection:
            row = connection.execute(select(statement_imports.c.import_id).where(statement_imports.c.account_id == value.account_id, statement_imports.c.file_hash == value.file_hash, statement_imports.c.format_version == value.format_version)).scalar_one_or_none()
            if row is None:
                connection.execute(insert(statement_imports).values(**self._import_values(value)))
            else:
                connection.execute(update(statement_imports).where(statement_imports.c.import_id == value.import_id).values(**self._import_values(value)))

    def find_import(self, account_id, file_hash, format_version):
        with self.engine.connect() as connection:
            row = connection.execute(select(statement_imports).where(statement_imports.c.account_id == account_id, statement_imports.c.file_hash == file_hash, statement_imports.c.format_version == format_version)).mappings().one_or_none()
        return None if row is None else self._import(row)

    def get_import(self, import_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(statement_imports).where(statement_imports.c.import_id == import_id)).mappings().one_or_none()
        return None if row is None else self._import(row)

    def latest_event(self):
        with self.engine.connect() as connection:
            row = connection.execute(select(events).order_by(events.c.recorded_at.desc(), events.c.event_id.desc())).mappings().first()
        return None if row is None else LedgerEvent(row.event_type, row.account_id, self._aware(row.occurred_at), self._aware(row.recorded_at), row.payload, row.event_id)

    @staticmethod
    def _account_values(x): return {"account_id": x.account_id, "broker": x.broker, "base_currency": x.base_currency, "market_permissions": list(x.market_permissions), "status": x.status.value, "masked_number": x.masked_number}
    @staticmethod
    def _account(r): return Account(r.broker, r.base_currency, tuple(r.market_permissions), AccountStatus(r.status), r.masked_number, r.account_id)
    @staticmethod
    def _order_values(x): return {"order_id": x.order_id, "account_id": x.account_id, "instrument_id": x.instrument_id, "source": x.source.value, "side": x.side.value, "quantity": x.quantity, "currency": x.currency, "submitted_at": x.submitted_at, "idempotency_key": x.idempotency_key, "recommendation_id": x.recommendation_id, "manual_reason": x.manual_reason, "broker_order_id": x.broker_order_id, "limit_price": x.limit_price, "status": x.status.value, "filled_quantity": x.filled_quantity, "version": x.version}
    @classmethod
    def _order(cls, r): return Order(r.account_id, r.instrument_id, OrderSource(r.source), OrderSide(r.side), r.quantity, r.currency, cls._aware(r.submitted_at), r.idempotency_key, r.recommendation_id, r.manual_reason, r.broker_order_id, None if r.limit_price is None else Decimal(r.limit_price), OrderStatus(r.status), r.filled_quantity, r.version, r.order_id)
    @staticmethod
    def _fill_values(x): return {name: getattr(x, name) for name in ("fill_id", "order_id", "account_id", "instrument_id", "broker", "broker_fill_id", "filled_at", "recorded_at", "quantity", "price", "commission", "tax", "other_fee", "currency", "raw_code", "sellable_on", "payload_hash", "reverses_fill_id")}
    @classmethod
    def _fill(cls, r): return Fill(r.order_id, r.account_id, r.instrument_id, r.broker, r.broker_fill_id, cls._aware(r.filled_at), cls._aware(r.recorded_at), r.quantity, Decimal(r.price), Decimal(r.commission), Decimal(r.tax), Decimal(r.other_fee), r.currency, r.raw_code, cls._aware(r.sellable_on), r.payload_hash, r.reverses_fill_id, r.fill_id)
    @staticmethod
    def _cash_values(x): return {name: (getattr(x, name).value if name == "event_type" else getattr(x, name)) for name in ("event_id", "account_id", "event_type", "currency", "amount", "effective_at", "external_ref", "reason", "counter_currency", "source_rate")}
    @classmethod
    def _cash_event(cls, r): return CashEvent(r.account_id, CashEventType(r.event_type), r.currency, Decimal(r.amount), cls._aware(r.effective_at), r.external_ref, r.reason, r.counter_currency, None if r.source_rate is None else Decimal(r.source_rate), r.event_id)
    @staticmethod
    def _entry_values(x): return {name: (getattr(x, name).value if name == "entry_type" else getattr(x, name)) for name in ("entry_id", "account_id", "entry_type", "currency", "effective_at", "recorded_at", "source_type", "source_id", "instrument_id", "quantity_delta", "cash_delta", "cost_delta", "realized_pnl_delta", "lot_id", "buy_date")}
    @classmethod
    def _entry(cls, r): return LedgerEntry(r.account_id, EntryType(r.entry_type), r.currency, cls._aware(r.effective_at), cls._aware(r.recorded_at), r.source_type, r.source_id, r.instrument_id, r.quantity_delta, Decimal(r.cash_delta), Decimal(r.cost_delta), Decimal(r.realized_pnl_delta), r.lot_id, r.buy_date, r.entry_id)
    @staticmethod
    def _position_adjustment_values(x): return {name: (getattr(x, name).value if name == "action_type" else getattr(x, name)) for name in ("adjustment_id", "account_id", "instrument_id", "lot_id", "buy_date", "action_type", "currency", "quantity_delta", "sellable_quantity_delta", "cost_delta", "effective_at", "available_at", "external_ref", "reason")}
    @classmethod
    def _position_adjustment(cls, r): return PositionAdjustment(r.account_id, r.instrument_id, r.lot_id, r.buy_date, CorporateActionType(r.action_type), r.currency, r.quantity_delta, r.sellable_quantity_delta, Decimal(r.cost_delta), cls._aware(r.effective_at), cls._aware(r.available_at), r.external_ref, r.reason, r.adjustment_id)
    @staticmethod
    def _corporate_cash_action_values(x): return {name: (getattr(x, name).value if name == "action_type" else getattr(x, name)) for name in ("action_id", "account_id", "instrument_id", "lot_id", "buy_date", "action_type", "currency", "gross_cash", "withholding_tax", "effective_at", "available_at", "external_ref", "reason")}
    @classmethod
    def _corporate_cash_action(cls, r): return CorporateCashAction(r.account_id, r.instrument_id, r.lot_id, r.buy_date, CorporateCashActionType(r.action_type), r.currency, Decimal(r.gross_cash), Decimal(r.withholding_tax), cls._aware(r.effective_at), cls._aware(r.available_at), r.external_ref, r.reason, r.action_id)
    @staticmethod
    def _event_values(x): return {"event_id": x.event_id, "event_type": x.event_type, "account_id": x.account_id, "occurred_at": x.occurred_at, "recorded_at": x.recorded_at, "payload": dict(x.payload)}
    @staticmethod
    def _reconciliation_values(x): return {"reconciliation_id": x.reconciliation_id, "account_id": x.account_id, "as_of": x.as_of, "status": x.status.value, "broker_snapshot_hash": x.broker_snapshot_hash, "created_at": x.created_at, "resolved_at": x.resolved_at, "resolution_reason": x.resolution_reason}
    @staticmethod
    def _reconciliation_item_values(reconciliation_id, x): return {"item_id": x.item_id, "reconciliation_id": reconciliation_id, "key": x.key, "system_value": x.system_value, "broker_value": x.broker_value, "difference": x.difference, "material": x.material, "resolved_reason": x.resolved_reason}
    @classmethod
    def _reconciliation(cls, r, rows): return Reconciliation(r.account_id, cls._aware(r.as_of), ReconciliationStatus(r.status), tuple(ReconciliationItem(x.key, Decimal(x.system_value), Decimal(x.broker_value), Decimal(x.difference), x.material, x.resolved_reason, x.item_id) for x in rows), r.broker_snapshot_hash, cls._aware(r.created_at), None if r.resolved_at is None else cls._aware(r.resolved_at), r.resolution_reason, r.reconciliation_id)
    @staticmethod
    def _import_values(x): return {"import_id": x.import_id, "account_id": x.account_id, "file_hash": x.file_hash, "format_version": x.format_version, "preview_hash": x.preview_hash, "confirmed": x.confirmed}
    @staticmethod
    def _import(r): return StatementImport(r.account_id, r.file_hash, r.format_version, r.preview_hash, r.confirmed, r.import_id)
