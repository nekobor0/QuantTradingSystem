from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from quant_trading_system.instruments import AliasInput, AssetType, Board, Exchange, InstrumentService, RegisterInstrumentCommand, TradingSpecInput
from quant_trading_system.instruments.in_memory import InMemoryInstrumentRepository
from quant_trading_system.universe import StrategyUniverseKind, UniverseDefinition, UniverseService
from quant_trading_system.universe.in_memory import InMemoryUniverseRepository
from quant_trading_system.universe.sqlalchemy_repository import SqlAlchemyUniverseRepository
from quant_trading_system.universe.tables import metadata


def register(service, *, code, asset, exchange, board):
    return service.register(RegisterInstrumentCommand(
        source="tushare", source_record_id=code, revision="1", batch_id="ref",
        asset_type=asset, exchange=exchange, board=board,
        currency="HKD" if exchange is Exchange.HKEX else "CNY", name=code,
        list_date=date(2020, 1, 2), aliases=(AliasInput("tushare", code, date(2020, 1, 2)),),
        trading_specs=(TradingSpecInput(date(2020, 1, 2), 100, Decimal("0.01"), 100),),
    ))


@pytest.fixture(params=["memory", "sqlalchemy"])
def repository(request):
    if request.param == "memory":
        yield InMemoryUniverseRepository()
        return
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    try:
        yield SqlAlchemyUniverseRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def universe_setup(repository):
    instruments = InstrumentService(InMemoryInstrumentRepository())
    etf = register(instruments, code="510300.SH", asset=AssetType.ETF_DOMESTIC, exchange=Exchange.SSE, board=Board.ETF)
    stock = register(instruments, code="600000.SH", asset=AssetType.A_SHARE, exchange=Exchange.SSE, board=Board.SH_MAIN)
    hk = register(instruments, code="00005.HK", asset=AssetType.HK_STOCK_CONNECT_ELIGIBLE_SECURITY, exchange=Exchange.HKEX, board=Board.HK_MAIN)
    service = UniverseService(repository, instruments)
    etf_pool = UniverseDefinition("ETF timing", StrategyUniverseKind.ETF_TIMING_POOL, "tushare", "1", "listed ETFs", Decimal("1"), 10)
    equity_pool = UniverseDefinition("Equity daily", StrategyUniverseKind.EQUITY_DAILY_POOL, "tushare", "1", "listed stocks", Decimal("1"), 10)
    service.create_definition(etf_pool)
    service.create_definition(equity_pool)
    return service, repository, etf_pool, equity_pool, etf, stock, hk
