from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from quant_trading_system.instruments import (
    AliasInput,
    AssetType,
    Board,
    Exchange,
    InstrumentService,
    LifecycleStatus,
    RegisterInstrumentCommand,
    TradingSpecInput,
)
from quant_trading_system.instruments.in_memory import InMemoryInstrumentRepository
from quant_trading_system.market_data import BatchStatus, VolumeUnit
from quant_trading_system.market_data.errors import QualityGateRejected
from quant_trading_system.market_data.in_memory import InMemoryMarketDataRepository
from quant_trading_system.market_data.raw_store import RawFileStore
from quant_trading_system.market_data.service import MarketDataService
from quant_trading_system.tdx_bridge import TdxIngestionBridge, TdxProtocolError

RECEIVED = datetime(2024, 2, 1, 8, tzinfo=timezone.utc)


def envelope(*, high: str = "6.74", empty: bool = False) -> dict:
    values = {
        "Amount": ["14606.63", "19980.50"],
        "Close": ["6.64", "6.70"],
        "Date": ["20240102", "20240103"],
        "ErrorId": "0",
        "ForwardFactor": ["0.938507", "0.938507"],
        "High": [high, "6.75"],
        "Low": ["6.56", "6.60"],
        "Open": ["6.63", "6.64"],
        "Volume": ["22066700.00", "30000000.00"],
    }
    if empty:
        values = {key: ([] if isinstance(value, list) else value) for key, value in values.items()}
    return {"id": 1, "result": {"ErrorId": "0", "Value": {"600000.SH": values}}}


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[tuple[str, ...], str, str]] = []

    def get_daily_bars(self, symbols, *, start_time, end_time):
        self.calls.append((tuple(symbols), start_time, end_time))
        return self.payload


@pytest.fixture
def setup_bridge(tmp_path):
    instruments = InstrumentService(InMemoryInstrumentRepository())
    instruments.register(RegisterInstrumentCommand(
        source="tdx",
        source_record_id="600000.SH",
        revision="1",
        batch_id="tdx-reference-test",
        asset_type=AssetType.A_SHARE,
        exchange=Exchange.SSE,
        board=Board.SH_MAIN,
        currency="CNY",
        name="浦发银行",
        list_date=date(1999, 11, 10),
        aliases=(AliasInput("tdx", "600000.SH", date(1999, 11, 10)),),
        trading_specs=(TradingSpecInput(date(1999, 11, 10), 100, Decimal("0.01"), 100),),
        initial_status=LifecycleStatus.LISTED,
    ))
    repository = InMemoryMarketDataRepository()

    def build(payload: dict):
        client = FakeClient(payload)
        bridge = TdxIngestionBridge(
            client,
            RawFileStore(tmp_path / "raw"),
            MarketDataService(repository, instruments),
        )
        return bridge, client, repository

    return build


def test_backfill_normalizes_units_timezone_and_publishes(setup_bridge) -> None:
    bridge, client, repository = setup_bridge(envelope())
    batch = bridge.backfill(
        ["600000.sh"], start=date(2024, 1, 1), end=date(2024, 1, 31), received_at=RECEIVED
    )

    assert batch.status is BatchStatus.PUBLISHED
    assert batch.record_count == 2
    assert client.calls == [(('600000.SH',), "20240101", "20240131")]
    first = repository.bars[0]
    assert first.trading_date == date(2024, 1, 2)
    assert first.bar_end_at == datetime(2024, 1, 2, 7, tzinfo=timezone.utc)
    assert first.volume == Decimal("22066700.00")
    assert first.turnover == Decimal("146066300.00")
    assert first.revision.startswith("tdx-")
    assert batch.raw_uri.startswith("file:")


def test_identical_backfill_is_idempotent(setup_bridge) -> None:
    bridge, _client, repository = setup_bridge(envelope())
    first = bridge.backfill(
        ["600000.SH"], start=date(2024, 1, 1), end=date(2024, 1, 31), received_at=RECEIVED
    )
    second = bridge.backfill(
        ["600000.SH"], start=date(2024, 1, 1), end=date(2024, 1, 31), received_at=RECEIVED
    )

    assert second.batch_id == first.batch_id
    assert len(repository.batches) == 1
    assert len(repository.bars) == 2


def test_empty_symbol_response_is_not_published(setup_bridge, tmp_path) -> None:
    bridge, _client, repository = setup_bridge(envelope(empty=True))
    with pytest.raises(TdxProtocolError, match="no daily bars"):
        bridge.backfill(
            ["600000.SH"], start=date(2024, 1, 1), end=date(2024, 1, 31), received_at=RECEIVED
        )

    assert not repository.batches
    assert not repository.bars
    assert len(list((tmp_path / "raw").glob("*.json"))) == 1


def test_invalid_ohlc_is_rejected_by_existing_quality_gate(setup_bridge) -> None:
    bridge, _client, repository = setup_bridge(envelope(high="6.60"))
    with pytest.raises(QualityGateRejected):
        bridge.backfill(
            ["600000.SH"], start=date(2024, 1, 1), end=date(2024, 1, 31), received_at=RECEIVED
        )
    with pytest.raises(QualityGateRejected, match="has status REJECTED"):
        bridge.backfill(
            ["600000.SH"], start=date(2024, 1, 1), end=date(2024, 1, 31), received_at=RECEIVED
        )

    batch = next(iter(repository.batches.values()))
    assert batch.status is BatchStatus.REJECTED
    assert repository.quality_results(batch.batch_id)
    assert not repository.bars


def test_incremental_requests_only_the_explicit_date(setup_bridge) -> None:
    payload = envelope()
    values = payload["result"]["Value"]["600000.SH"]
    for field, series in values.items():
        if isinstance(series, list):
            values[field] = series[1:]
    bridge, client, _repository = setup_bridge(payload)
    batch = bridge.incremental(
        ["600000.SH"], trading_date=date(2024, 1, 3), received_at=RECEIVED,
        volume_unit=VolumeUnit.SHARES,
    )
    assert batch.record_count == 1
    assert client.calls == [(('600000.SH',), "20240103", "20240103")]


def test_mismatched_field_lengths_fail_before_publication(setup_bridge) -> None:
    payload = envelope()
    payload["result"]["Value"]["600000.SH"]["Close"].pop()
    bridge, _client, repository = setup_bridge(payload)
    with pytest.raises(TdxProtocolError, match="different lengths"):
        bridge.backfill(
            ["600000.SH"], start=date(2024, 1, 1), end=date(2024, 1, 31), received_at=RECEIVED
        )
    assert not repository.batches
