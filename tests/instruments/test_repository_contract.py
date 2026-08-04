from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.instruments import (
    AssetType,
    Board,
    Exchange,
    Instrument,
    InstrumentService,
    LifecycleStatus,
)
from quant_trading_system.instruments.domain import (
    DateRange,
    InstrumentAlias,
    InstrumentEvent,
    LifecyclePeriod,
    SourceRecord,
    TradingSpec,
)
from quant_trading_system.instruments.errors import InstrumentError


def test_register_bundle_is_atomic_when_late_source_constraint_fails(repository, listed_command) -> None:
    service = InstrumentService(repository)
    service.register(listed_command())

    new_id = uuid4()
    instrument = Instrument(
        instrument_id=new_id,
        asset_type=AssetType.A_SHARE,
        exchange=Exchange.SSE,
        board=Board.SH_MAIN,
        currency="CNY",
        name="Atomicity Probe",
        list_date=date(2020, 1, 2),
        lifecycle_status=LifecycleStatus.LISTED,
    )
    alias = InstrumentAlias(new_id, "tushare", "999999.SH", DateRange(date(2020, 1, 2)))
    spec = TradingSpec(new_id, DateRange(date(2020, 1, 2)), 100, Decimal("0.01"), 100)
    period = LifecyclePeriod(
        new_id,
        LifecycleStatus.LISTED,
        DateRange(date(2020, 1, 2)),
        "atomicity test",
    )
    duplicate_source = SourceRecord(
        source="tushare",
        source_record_id="600000.SH",
        revision="1",
        payload_hash="different",
        instrument_id=new_id,
        batch_id="atomicity-test",
    )
    event = InstrumentEvent(
        "InstrumentRegistered",
        new_id,
        datetime.now(timezone.utc),
        {"test": "atomicity"},
    )

    with pytest.raises(InstrumentError):
        repository.register_bundle(instrument, (alias,), (spec,), (period,), duplicate_source, event)

    assert repository.get_instrument(new_id) is None
    assert not repository.resolve_aliases("tushare", "999999.SH", date(2020, 1, 2))
