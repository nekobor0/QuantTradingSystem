from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.instruments.domain import (
    AssetType,
    Board,
    DateRange,
    Exchange,
    Instrument,
    InstrumentAlias,
    InstrumentEvent,
    LifecycleStatus,
    TradingSpec,
)
from quant_trading_system.instruments.errors import (
    InvalidDateRange,
    InvalidInstrument,
    InvalidTradingSpec,
)


def stock(**overrides) -> Instrument:
    values = dict(
        asset_type=AssetType.A_SHARE,
        exchange=Exchange.SSE,
        board=Board.SH_MAIN,
        currency="cny",
        name=" Example ",
        list_date=date(2020, 1, 2),
        lifecycle_status=LifecycleStatus.LISTED,
    )
    values.update(overrides)
    return Instrument(**values)


def test_date_range_is_half_open() -> None:
    validity = DateRange(date(2020, 1, 1), date(2020, 2, 1))
    assert validity.contains(date(2020, 1, 1))
    assert validity.contains(date(2020, 1, 31))
    assert not validity.contains(date(2020, 2, 1))


def test_adjacent_date_ranges_do_not_overlap() -> None:
    left = DateRange(date(2020, 1, 1), date(2020, 2, 1))
    right = DateRange(date(2020, 2, 1), None)
    assert not left.overlaps(right)
    assert not right.overlaps(left)


def test_open_date_ranges_overlap_later_ranges() -> None:
    assert DateRange(date(2020, 1, 1)).overlaps(DateRange(date(2030, 1, 1)))


def test_invalid_date_range_is_rejected() -> None:
    with pytest.raises(InvalidDateRange) as caught:
        DateRange(date(2020, 1, 1), date(2020, 1, 1))
    assert caught.value.code == "INVALID_DATE_RANGE"


def test_instrument_normalizes_text_fields() -> None:
    instrument = stock()
    assert instrument.currency == "CNY"
    assert instrument.name == "Example"


@pytest.mark.parametrize("currency", ["", "CN", "USDT"])
def test_invalid_currency_is_rejected(currency: str) -> None:
    with pytest.raises(InvalidInstrument):
        stock(currency=currency)


def test_delist_date_cannot_precede_list_date() -> None:
    with pytest.raises(InvalidInstrument):
        stock(
            lifecycle_status=LifecycleStatus.DELISTED,
            delist_date=date(2019, 12, 31),
        )


def test_delist_date_requires_delisted_status() -> None:
    with pytest.raises(InvalidInstrument):
        stock(delist_date=date(2021, 1, 1))


def test_board_must_match_exchange() -> None:
    with pytest.raises(InvalidInstrument):
        stock(board=Board.CHINEXT)


def test_etf_asset_type_requires_etf_board() -> None:
    with pytest.raises(InvalidInstrument):
        stock(asset_type=AssetType.ETF_DOMESTIC)


def test_alias_normalizes_source_and_code() -> None:
    alias = InstrumentAlias(uuid4(), " TuShare ", " sh.600000 ", DateRange(date(2020, 1, 1)))
    assert alias.source == "tushare"
    assert alias.code == "SH.600000"


@pytest.mark.parametrize(
    "values",
    [
        dict(lot_size=0, tick_size=Decimal("0.01"), min_order_quantity=100),
        dict(lot_size=100, tick_size=Decimal("0"), min_order_quantity=100),
        dict(lot_size=100, tick_size=Decimal("0.01"), min_order_quantity=0),
        dict(
            lot_size=100,
            tick_size=Decimal("0.01"),
            min_order_quantity=200,
            max_order_quantity=100,
        ),
    ],
)
def test_invalid_trading_spec_is_rejected(values) -> None:
    with pytest.raises(InvalidTradingSpec):
        TradingSpec(uuid4(), DateRange(date(2020, 1, 1)), **values)


def test_event_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(InvalidInstrument):
        InstrumentEvent("InstrumentRegistered", uuid4(), datetime(2020, 1, 1), {})
