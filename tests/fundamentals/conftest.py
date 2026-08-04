from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from quant_trading_system.fundamentals import FundamentalService, MetricDefinition, SourceMapping, ValueKind
from quant_trading_system.fundamentals.in_memory import InMemoryFundamentalRepository
from quant_trading_system.fundamentals.sqlalchemy_repository import SqlAlchemyFundamentalRepository
from quant_trading_system.fundamentals.tables import metadata
from quant_trading_system.instruments import AliasInput, AssetType, Board, Exchange, InstrumentService, RegisterInstrumentCommand, TradingSpecInput
from quant_trading_system.instruments.in_memory import InMemoryInstrumentRepository


@pytest.fixture(params=["memory", "sqlalchemy"])
def repository(request):
    if request.param == "memory":
        yield InMemoryFundamentalRepository()
        return
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    try:
        yield SqlAlchemyFundamentalRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def fundamentals_setup(repository):
    instruments = InstrumentService(InMemoryInstrumentRepository())
    instrument = instruments.register(RegisterInstrumentCommand(
        source="tushare", source_record_id="600000.SH", revision="1", batch_id="reference-1",
        asset_type=AssetType.A_SHARE, exchange=Exchange.SSE, board=Board.SH_MAIN,
        currency="CNY", name="浦发银行", list_date=date(2020, 1, 2),
        aliases=(AliasInput("tushare", "600000.SH", date(2020, 1, 2)),),
        trading_specs=(TradingSpecInput(date(2020, 1, 2), 100, Decimal("0.01"), 100),),
    ))
    service = FundamentalService(repository, instruments)
    metric = MetricDefinition("revenue", "CNY", ValueKind.AMOUNT, True)
    service.define_metric(metric, (SourceMapping("tushare", "revenue", metric.metric_id, "万元", Decimal("10000")),))
    return service, instrument, metric, repository
