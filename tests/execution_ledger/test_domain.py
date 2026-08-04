from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.execution_ledger import *
from quant_trading_system.execution_ledger.errors import InvalidLedgerInput

from .conftest import T0, fill, manual_order


@pytest.mark.parametrize("broker,currency", [("b", "CNY"), ("ib", "HKD"), ("x", "USD"), ("券商", "CNY")])
def test_valid_account(broker, currency):
    assert Account(broker, currency, ()).base_currency == currency


@pytest.mark.parametrize("broker,currency", [("", "CNY"), (" ", "CNY"), ("b", "CN"), ("b", "CNYY"), ("b", "")])
def test_invalid_account(broker, currency):
    with pytest.raises(InvalidLedgerInput):
        Account(broker, currency, ())


@pytest.mark.parametrize("quantity", [1, 10, 100, 101, 1000, 10000])
def test_valid_manual_order_quantities(quantity):
    value = Order(uuid4(), uuid4(), OrderSource.MANUAL, OrderSide.BUY, quantity, "CNY", T0, "k", manual_reason="reason")
    assert value.quantity == quantity


@pytest.mark.parametrize("quantity", [0, -1, -100])
def test_order_rejects_non_positive_quantity(quantity):
    with pytest.raises(InvalidLedgerInput):
        Order(uuid4(), uuid4(), OrderSource.MANUAL, OrderSide.BUY, quantity, "CNY", T0, "k", manual_reason="reason")


def test_order_requires_aware_time():
    with pytest.raises(InvalidLedgerInput):
        Order(uuid4(), uuid4(), OrderSource.MANUAL, OrderSide.BUY, 1, "CNY", datetime(2025, 1, 1), "k", manual_reason="reason")


def test_manual_order_requires_reason():
    with pytest.raises(InvalidLedgerInput):
        Order(uuid4(), uuid4(), OrderSource.MANUAL, OrderSide.BUY, 1, "CNY", T0, "k")


def test_recommendation_order_requires_reference():
    with pytest.raises(InvalidLedgerInput):
        Order(uuid4(), uuid4(), OrderSource.RECOMMENDATION, OrderSide.BUY, 1, "CNY", T0, "k")


@pytest.mark.parametrize("price", ["0", "-1", "-0.01"])
def test_order_rejects_non_positive_limit(price):
    with pytest.raises(InvalidLedgerInput):
        Order(uuid4(), uuid4(), OrderSource.MANUAL, OrderSide.BUY, 1, "CNY", T0, "k", manual_reason="r", limit_price=Decimal(price))


@pytest.mark.parametrize("field,value", [("quantity", 0), ("quantity", -1), ("price", Decimal("0")), ("commission", Decimal("-1")), ("tax", Decimal("-1")), ("other_fee", Decimal("-1"))])
def test_fill_domain_rejects_invalid_numeric(field, value):
    data = dict(order_id=uuid4(), account_id=uuid4(), instrument_id=uuid4(), broker="b", broker_fill_id="f", filled_at=T0, recorded_at=T0, quantity=1, price=Decimal("1"), commission=Decimal(), tax=Decimal(), other_fee=Decimal(), currency="CNY", raw_code="x", sellable_on=T0, payload_hash="h")
    data[field] = value
    with pytest.raises(InvalidLedgerInput):
        Fill(**data)


@pytest.mark.parametrize("event_type,amount", [(CashEventType.DEPOSIT, "1"), (CashEventType.WITHDRAWAL, "-1"), (CashEventType.DIVIDEND, "2"), (CashEventType.TAX, "-2"), (CashEventType.FEE, "-3"), (CashEventType.ADJUSTMENT, "4")])
def test_cash_event_domain_accepts_nonzero(event_type, amount):
    value = CashEvent(uuid4(), event_type, "CNY", Decimal(amount), T0, "r", "reason")
    assert value.amount == Decimal(amount)


@pytest.mark.parametrize("currency", ["", "C", "CN", "CNYY"])
def test_cash_event_rejects_bad_currency(currency):
    with pytest.raises(InvalidLedgerInput):
        CashEvent(uuid4(), CashEventType.DEPOSIT, currency, Decimal("1"), T0, "r", "reason")


def test_fill_fee_sums_components():
    value = Fill(uuid4(), uuid4(), uuid4(), "b", "f", T0, T0, 1, Decimal("1"), Decimal("1"), Decimal("2"), Decimal("3"), "CNY", "x", T0, "h")
    assert value.fee == Decimal("6")


def test_account_snapshot_source_is_ledger():
    value = AccountSnapshot(uuid4(), T0, {}, (), "h", ())
    assert value.source == "execution_ledger"
