from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from quant_trading_system.instruments.tables import metadata


MIGRATION = Path(__file__).parents[2] / "migrations" / "001_instruments.sql"


def test_migration_declares_btree_gist() -> None:
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in MIGRATION.read_text(encoding="utf-8")


def test_migration_has_three_range_exclusion_constraints() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql.count("EXCLUDE USING gist") == 3
    assert sql.count("'[)'") == 3


def test_migration_has_source_record_idempotency_key() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "UNIQUE (source, source_record_id, revision)" in sql


def test_migration_is_transactional() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").strip()
    assert sql.startswith("BEGIN;")
    assert sql.endswith("COMMIT;")


def test_sqlalchemy_metadata_creates_all_module_tables_in_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    assert set(inspect(engine).get_table_names()) == {
        "instrument_aliases",
        "instrument_events",
        "instrument_lifecycle_periods",
        "instrument_source_records",
        "instruments",
        "trading_specs",
    }
    engine.dispose()
