"""Production wiring for the TdxQuant bridge."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect

from quant_trading_system.instruments.sqlalchemy_repository import SqlAlchemyInstrumentRepository
from quant_trading_system.market_data.raw_store import RawFileStore
from quant_trading_system.market_data.service import MarketDataService
from quant_trading_system.market_data.sqlalchemy_repository import SqlAlchemyMarketDataRepository

from .bridge import TdxIngestionBridge
from .client import TdxHttpClient
from .errors import TdxConfigurationError
from .resolver import CachedInstrumentService

REQUIRED_TABLES = {
    "instruments",
    "instrument_aliases",
    "instrument_lifecycle_periods",
    "dataset_batches",
    "market_bars",
    "data_quality_results",
    "market_data_events",
}


def build_bridge(
    database_url: str,
    raw_root: Path,
    *,
    endpoint: str = "http://127.0.0.1:17709/",
    timeout_seconds: float = 120.0,
) -> tuple[TdxIngestionBridge, Engine]:
    engine = open_data_layer(database_url)
    instruments = CachedInstrumentService(SqlAlchemyInstrumentRepository(engine))
    market_data = MarketDataService(SqlAlchemyMarketDataRepository(engine), instruments)
    bridge = TdxIngestionBridge(
        TdxHttpClient(endpoint, timeout_seconds=timeout_seconds),
        RawFileStore(raw_root.resolve()),
        market_data,
    )
    return bridge, engine


def open_data_layer(database_url: str) -> Engine:
    """Open an already-migrated database without creating or altering schema."""
    if not database_url.strip():
        raise TdxConfigurationError("database URL is required")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        present = set(inspect(engine).get_table_names())
    except Exception:
        engine.dispose()
        raise
    missing = sorted(REQUIRED_TABLES - present)
    if missing:
        engine.dispose()
        raise TdxConfigurationError(
            "database is missing required tables: " + ", ".join(missing)
        )
    return engine
