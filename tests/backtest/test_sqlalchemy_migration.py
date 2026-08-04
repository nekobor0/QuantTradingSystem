from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

from quant_trading_system.backtest import *
from quant_trading_system.backtest.sqlalchemy_repository import SqlAlchemyBacktestRepository
from quant_trading_system.backtest.tables import metadata


@pytest.fixture
def sql_repo():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return SqlAlchemyBacktestRepository(engine)


def test_sql_full_result_roundtrip(sql_repo, definition, callbacks, bars, market_rules, cost_rules):
    engine = EventDrivenBacktestEngine(sql_repo)
    result = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    loaded = engine.get_result(result.run.run_id)
    assert loaded.definition == result.definition
    assert loaded.run == result.run
    assert loaded.events == result.events
    assert loaded.orders == result.orders
    assert loaded.fills == result.fills
    assert loaded.ledger == result.ledger
    assert loaded.snapshots == result.snapshots
    assert sorted(loaded.metrics, key=lambda item: item.name) == sorted(result.metrics, key=lambda item: item.name)
    assert sorted(loaded.contributions, key=lambda item: str(item.contribution_id)) == sorted(result.contributions, key=lambda item: str(item.contribution_id))


def test_sql_idempotent_run(sql_repo, definition, callbacks, bars, market_rules, cost_rules):
    engine = EventDrivenBacktestEngine(sql_repo)
    first = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    second = engine.run(definition, callbacks, bars, market_rules, cost_rules)
    assert second.run.run_id == first.run.run_id


def test_sql_failed_run_is_auditable(sql_repo, definition, bars, market_rules, cost_rules):
    engine = EventDrivenBacktestEngine(sql_repo)
    callbacks = {kind: (lambda context, run_id: (_ for _ in ()).throw(RuntimeError("failed"))) for kind in (StrategyKind.ETF_TIMING, StrategyKind.EQUITY_DAILY_SELECTION)}
    with pytest.raises(RuntimeError): engine.run(definition, callbacks, bars, market_rules, cost_rules)
    with sql_repo.engine.connect() as connection:
        row = connection.execute(select(metadata.tables["backtest_runs"])).mappings().one()
    assert row.status == "FAILED" and "RuntimeError" in row.error


REQUIRED = [
    "backtest_definitions", "backtest_runs", "backtest_simulation_events", "backtest_sim_orders", "backtest_sim_fills",
    "backtest_sim_ledger", "backtest_snapshots", "backtest_metrics", "backtest_artifacts", "backtest_sleeve_contributions",
]
SQL = (Path(__file__).parents[2] / "migrations" / "010_backtest.sql").read_text(encoding="utf-8")


@pytest.mark.parametrize("table", REQUIRED)
def test_required_table_in_metadata_and_migration(table):
    assert table in metadata.tables
    assert table in SQL


@pytest.mark.parametrize("fragment", ["UNIQUE(run_id,sequence)", "input_hash TEXT UNIQUE", "TIMESTAMPTZ", "JSONB", "CHECK(execution_delay_bars>=1)", "CHECK(filled_quantity>=0 AND filled_quantity<=quantity)"])
def test_postgresql_integrity_contract(fragment):
    assert fragment in SQL


@pytest.mark.parametrize("table", REQUIRED)
def test_sqlite_tables_are_queryable(sql_repo, table):
    with sql_repo.engine.connect() as connection:
        connection.execute(select(metadata.tables[table]).limit(1)).all()
