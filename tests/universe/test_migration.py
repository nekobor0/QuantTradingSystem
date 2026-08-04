from pathlib import Path

DDL = Path(__file__).parents[2] / "migrations" / "004_universe.sql"


def test_all_owned_tables_present():
    sql = DDL.read_text(encoding="utf-8")
    for table in ("universe_definitions", "universe_batches", "universe_memberships", "classification_memberships", "universe_snapshots", "universe_quality_results", "universe_events"):
        assert f"CREATE TABLE {table}" in sql


def test_half_open_overlap_constraint(): assert "daterange(valid_from,valid_to,'[)')" in DDL.read_text(encoding="utf-8")
def test_batch_idempotency_constraint(): assert "UNIQUE(universe_id,source_batch_id)" in DDL.read_text(encoding="utf-8")
def test_availability_checks(): assert DDL.read_text(encoding="utf-8").count("CHECK(available_at>=announced_at)") >= 2
