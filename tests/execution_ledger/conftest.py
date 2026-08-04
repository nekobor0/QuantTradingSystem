from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.execution_ledger import Account, CashEvent, CashEventType, ExecutionLedgerService, FillInput, OrderInput, OrderSide, OrderSource
from quant_trading_system.execution_ledger.in_memory import InMemoryLedgerRepository

UTC = timezone.utc
T0 = datetime(2025, 1, 2, 8, tzinfo=UTC)


@pytest.fixture
def repo():
    return InMemoryLedgerRepository()


@pytest.fixture
def service(repo):
    return ExecutionLedgerService(repo)


@pytest.fixture
def account(service):
    value = Account("demo-broker", "CNY", ("SSE", "SZSE"), masked_number="***8899")
    service.register_account(value)
    return value


@pytest.fixture
def funded(service, account):
    service.record_cash_event(CashEvent(account.account_id, CashEventType.DEPOSIT, "CNY", Decimal("100000"), T0, "initial", "initial funding"))
    return account


@pytest.fixture
def instrument_id():
    return uuid4()


def manual_order(account, instrument_id, *, side=OrderSide.BUY, quantity=100, key="order-1", currency="CNY", at=T0):
    return OrderInput(account.account_id, instrument_id, OrderSource.MANUAL, side, quantity, currency, at, key, manual_reason="entered at broker")


def recommendation_order(account, instrument_id, *, quantity=100, approved=100, key="rec-1"):
    return OrderInput(account.account_id, instrument_id, OrderSource.RECOMMENDATION, OrderSide.BUY, quantity, "CNY", T0, key, recommendation_id=uuid4(), approved_remaining_quantity=approved)


def fill(*, fill_id="fill-1", quantity=100, price="10", commission="5", tax="0", other_fee="0", currency="CNY", at=T0, settle_days=1, row_hash=None, confirmed=False):
    return FillInput(fill_id, row_hash, confirmed, at, quantity, Decimal(price), Decimal(commission), Decimal(tax), Decimal(other_fee), currency, "600000.SH", at + timedelta(days=settle_days))
