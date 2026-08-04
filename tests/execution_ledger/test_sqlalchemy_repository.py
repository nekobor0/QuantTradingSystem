from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select

from quant_trading_system.execution_ledger import *
from quant_trading_system.execution_ledger.sqlalchemy_repository import SqlAlchemyLedgerRepository
from quant_trading_system.execution_ledger.tables import accounts, fills, ledger_entries, metadata, orders

from .conftest import T0, fill, manual_order


@pytest.fixture
def sql_repo():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return SqlAlchemyLedgerRepository(engine)


@pytest.fixture
def sql_service(sql_repo):
    return ExecutionLedgerService(sql_repo)


def sql_funded(sql_service):
    account = Account("sql-broker", "CNY", ("SSE",))
    sql_service.register_account(account)
    sql_service.record_cash_event(CashEvent(account.account_id, CashEventType.DEPOSIT, "CNY", Decimal("100000"), T0, "initial", "funding"))
    return account


def test_sql_account_roundtrip(sql_service, sql_repo):
    account = Account("b", "CNY", ("SSE",), masked_number="***1")
    sql_service.register_account(account)
    assert sql_repo.get_account(account.account_id) == account


def test_sql_order_roundtrip_and_no_balance_change(sql_service, sql_repo):
    account = sql_funded(sql_service)
    before = sql_service.get_account_snapshot(account.account_id, T0)
    order = sql_service.record_order(manual_order(account, __import__("uuid").uuid4()))
    assert sql_repo.get_order(order.order_id) == order
    assert sql_service.get_account_snapshot(account.account_id, T0).cash == before.cash


def test_sql_fill_and_entries_are_atomic_roundtrip(sql_service, sql_repo):
    account = sql_funded(sql_service)
    instrument = __import__("uuid").uuid4()
    order = sql_service.record_order(manual_order(account, instrument))
    recorded = sql_service.record_fill(order.order_id, fill(settle_days=0), 0)
    assert sql_repo.get_fill(recorded.fill_id) == recorded
    assert len(sql_repo.entries(account.account_id)) == 5
    assert sql_service.get_account_snapshot(account.account_id, T0).positions[0].quantity == 100


def test_sql_duplicate_fill_is_idempotent(sql_service, sql_repo):
    account = sql_funded(sql_service)
    order = sql_service.record_order(manual_order(account, __import__("uuid").uuid4()))
    first = sql_service.record_fill(order.order_id, fill(), 0)
    assert sql_service.record_fill(order.order_id, fill(), 1) == first
    assert len(sql_repo.entries(account.account_id)) == 5


def test_sql_reversal_roundtrip(sql_service, sql_repo):
    account = sql_funded(sql_service)
    order = sql_service.record_order(manual_order(account, __import__("uuid").uuid4()))
    original = sql_service.record_fill(order.order_id, fill(settle_days=0), 0)
    reversal = sql_service.reverse_fill(original.fill_id, T0 + timedelta(hours=1), 1, "correction")
    assert sql_repo.reversal_for(original.fill_id) == reversal
    assert sql_service.get_account_snapshot(account.account_id, T0 + timedelta(hours=1)).positions == ()


def test_sql_reconciliation_and_resolution_roundtrip(sql_service, sql_repo):
    account = sql_funded(sql_service)
    value = sql_service.reconcile(account.account_id, {"CNY": Decimal("99999")}, {}, {}, T0, "broker")
    stored = sql_repo.get_reconciliation(value.reconciliation_id)
    assert stored == value
    resolved = sql_service.resolve_reconciliation(value.reconciliation_id, "verified", T0 + timedelta(hours=1))
    assert sql_repo.get_reconciliation(value.reconciliation_id) == resolved
    assert sql_repo.get_account(account.account_id).status is AccountStatus.ACTIVE


def test_sql_statement_import_roundtrip(sql_service, sql_repo):
    account = sql_funded(sql_service)
    preview = sql_service.preview_statement(account.account_id, "file", "v1", "preview")
    assert sql_repo.find_import(account.account_id, "file", "v1") == preview
    assert sql_service.confirm_statement(preview.import_id).confirmed
    assert sql_repo.get_import(preview.import_id).confirmed


def test_sql_latest_event(sql_service, sql_repo):
    account = sql_funded(sql_service)
    assert sql_repo.latest_event().account_id == account.account_id


@pytest.mark.parametrize("table", [accounts, orders, fills, ledger_entries])
def test_sql_owned_tables_exist(sql_repo, table):
    with sql_repo.engine.connect() as connection:
        connection.execute(select(table).limit(1)).all()
