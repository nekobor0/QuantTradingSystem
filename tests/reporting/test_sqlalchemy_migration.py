from pathlib import Path
import pytest
from sqlalchemy import create_engine,select
from quant_trading_system.reporting import *
from quant_trading_system.reporting.sqlalchemy_repository import SqlAlchemyReportingRepository
from quant_trading_system.reporting.tables import metadata
from .conftest import make_command

@pytest.fixture
def sql_repo():
 engine=create_engine("sqlite+pysqlite:///:memory:");metadata.create_all(engine);return SqlAlchemyReportingRepository(engine)

def test_sql_full_report_roundtrip(sql_repo,definition):
 service=ReportingService(sql_repo);result=service.build_report(make_command(definition));loaded=service.get_report(result.run.run_id)
 assert loaded.run==result.run and loaded.inputs==result.inputs
 assert set(loaded.metrics)==set(result.metrics);assert set(loaded.attributions)==set(result.attributions);assert set(loaded.strategy_summaries)==set(result.strategy_summaries);assert set(loaded.artifacts)==set(result.artifacts);assert set(loaded.quality)==set(result.quality)

def test_sql_idempotent_build(sql_repo,definition):
 service=ReportingService(sql_repo);command=make_command(definition);first=service.build_report(command);second=service.build_report(command);assert first.run.run_id==second.run.run_id

def test_sql_explain_metric(sql_repo,definition):
 service=ReportingService(sql_repo);result=service.build_report(make_command(definition));assert service.explain_metric(result.run.run_id,"fees").input_snapshots

REQUIRED=("report_definitions","report_runs","report_input_bindings","report_metrics","report_sleeve_attributions","report_strategy_summaries","report_artifacts","report_quality_results","report_events")
SQL=(Path(__file__).parents[2]/"migrations"/"012_reporting.sql").read_text(encoding="utf-8")
@pytest.mark.parametrize("table",REQUIRED)
def test_required_tables_in_metadata_and_migration(table):assert table in metadata.tables and table in SQL
@pytest.mark.parametrize("fragment",("input_hash TEXT UNIQUE","UNIQUE(run_id,name)","UNIQUE(run_id,format)","TIMESTAMPTZ","JSONB","publishable BOOLEAN NOT NULL"))
def test_postgresql_contract(fragment):assert fragment in SQL
@pytest.mark.parametrize("table",REQUIRED)
def test_sqlite_tables_queryable(sql_repo,table):
 with sql_repo.engine.connect() as c:c.execute(select(metadata.tables[table]).limit(1)).all()
