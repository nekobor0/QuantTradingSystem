from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from quant_trading_system.instruments import (
    AliasInput,
    AssetType,
    Board,
    Exchange,
    LifecycleStatus,
    RegisterInstrumentCommand,
    TradingSpecInput,
)
from quant_trading_system.instruments.in_memory import InMemoryInstrumentRepository
from quant_trading_system.instruments.sqlalchemy_repository import SqlAlchemyInstrumentRepository
from quant_trading_system.instruments.tables import metadata


@pytest.fixture(params=["memory", "sqlalchemy"])
def repository(request):
    if request.param == "memory":
        yield InMemoryInstrumentRepository()
        return
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    try:
        yield SqlAlchemyInstrumentRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def listed_command():
    def build(**overrides):
        values = {
            "source": "tushare",
            "source_record_id": "600000.SH",
            "revision": "1",
            "batch_id": "batch-20200102",
            "asset_type": AssetType.A_SHARE,
            "exchange": Exchange.SSE,
            "board": Board.SH_MAIN,
            "currency": "CNY",
            "name": "浦发银行",
            "list_date": date(2020, 1, 2),
            "aliases": (
                AliasInput("tushare", "600000.SH", date(2020, 1, 2)),
                AliasInput("tushare", "sh.600000", date(2020, 1, 2)),
                AliasInput("tushare", "600000", date(2020, 1, 2)),
            ),
            "trading_specs": (
                TradingSpecInput(date(2020, 1, 2), 100, Decimal("0.01"), 100, 1_000_000),
            ),
            "initial_status": LifecycleStatus.LISTED,
        }
        values.update(overrides)
        return RegisterInstrumentCommand(**values)

    return build
