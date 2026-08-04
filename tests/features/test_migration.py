from pathlib import Path

DDL = Path(__file__).parents[2] / "migrations" / "005_features.sql"


def test_all_owned_tables_present():
    sql=DDL.read_text(encoding="utf-8")
    for table in ("feature_definitions","feature_versions","feature_purpose_bindings","feature_sets","feature_values","feature_events","feature_diagnostics"): assert f"CREATE TABLE {table}" in sql


def test_feature_value_unique_key(): assert "UNIQUE(instrument_id,as_of_date,version_id,data_snapshot_id)" in DDL.read_text(encoding="utf-8")
def test_input_hash_is_unique(): assert "input_hash char(64) UNIQUE NOT NULL" in DDL.read_text(encoding="utf-8")
def test_diagnostic_is_research_only(): assert "CHECK(research_only)" in DDL.read_text(encoding="utf-8")
def test_version_has_dependencies(): assert "dependency_versions jsonb NOT NULL" in DDL.read_text(encoding="utf-8")
def test_null_feature_values_are_allowed():
    part=DDL.read_text(encoding="utf-8").split("CREATE TABLE feature_values",1)[1].split(";",1)[0];assert "value numeric," in part and "value numeric NOT NULL" not in part
