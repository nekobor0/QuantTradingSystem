from pathlib import Path

DDL = Path(__file__).parents[2] / "migrations" / "003_fundamentals.sql"


def test_migration_defines_all_owned_tables():
    sql = DDL.read_text(encoding="utf-8")
    for table in ("metric_definitions", "fundamental_source_mappings", "filings", "fundamental_facts", "share_capital_changes", "fundamental_quality_results", "fundamental_revision_events"):
        assert f"CREATE TABLE {table}" in sql


def test_migration_enforces_filing_idempotency():
    assert "UNIQUE(source,source_filing_id,revision)" in DDL.read_text(encoding="utf-8")


def test_migration_enforces_fact_revision_identity():
    assert "UNIQUE(instrument_id,metric_id,period_end,period_type,source,revision)" in DDL.read_text(encoding="utf-8")


def test_migration_enforces_availability_order():
    assert DDL.read_text(encoding="utf-8").count("CHECK(available_at>=announced_at)") >= 2


def test_migration_preserves_nullable_fact_value():
    fragment = DDL.read_text(encoding="utf-8").split("CREATE TABLE fundamental_facts", 1)[1].split(";", 1)[0]
    assert "value numeric," in fragment and "value numeric NOT NULL" not in fragment
