from pathlib import Path
from datetime import date,timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine,select

from quant_trading_system.risk import *
from quant_trading_system.risk.sqlalchemy_repository import SqlAlchemyRiskRepository
from quant_trading_system.risk.tables import metadata
from .conftest import NOW,SCOPES,make_input

@pytest.fixture
def sql_repo():
 engine=create_engine("sqlite+pysqlite:///:memory:");metadata.create_all(engine);return SqlAlchemyRiskRepository(engine)

@pytest.fixture
def sql_setup(sql_repo):
 service=RiskService(sql_repo);account_id=uuid4();versions=[]
 for code,scope,metric,operator,threshold,severity,allowed in (("ETF",RiskScope.ETF_TIMING,"liquidity",ComparisonOperator.GE,"100",RiskSeverity.WARNING,False),("STOCK",RiskScope.EQUITY_DAILY_SELECTION,"max_weight",ComparisonOperator.LE,"0.8",RiskSeverity.HARD_BLOCK,False),("ALL",RiskScope.COMBINED_ACCOUNT,"market_weight",ComparisonOperator.LE,"0.8",RiskSeverity.APPROVAL_REQUIRED,True)):
  rule=RiskRule(code,code,"owner","description");version=RiskRuleVersion(rule.rule_id,"v1",RiskStage.PRE_TRADE,scope,metric,operator,Decimal(threshold),severity,date(2020,1,1),None,"owner",allowed);service.register_rule(rule,version);versions.append(version)
 policy=RiskPolicyVersion("p","v1",account_id,"CN",tuple(x.version_id for x in versions),SCOPES,date(2020,1,1),None,"owner",3600);service.register_policy(policy)
 return service,sql_repo,account_id,policy,versions

def test_sql_rule_policy_roundtrip(sql_setup):
 service,repo,account_id,policy,versions=sql_setup
 assert repo.get_policy(policy.policy_version_id)==policy
 assert tuple(repo.get_rule_version(x.version_id) for x in versions)==tuple(versions)

def test_sql_run_result_alert_roundtrip(sql_setup):
 service,repo,account_id,policy,versions=sql_setup
 value=make_input(account_id,stock_weight=Decimal("1"));output=service.run_pre_trade_checks(value,policy.policy_version_id)
 loaded=repo.get_run_result(output.run.run_id)
 assert loaded.run==output.run
 assert set(loaded.results)==set(output.results)
 assert repo.alerts_for_account(account_id)
 assert service.get_sleeve_risk(value.object_id)[0].run==output.run

def test_sql_exception_and_effective_decision(sql_setup):
 service,repo,account_id,policy,versions=sql_setup
 output=service.run_pre_trade_checks(make_input(account_id,market_weight=Decimal("1")),policy.policy_version_id)
 result=next(x for x in output.results if x.metric=="market_weight")
 exception=service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(days=1))
 assert repo.get_exception(exception.exception_id)==exception
 assert service.effective_decision(output.run.run_id,NOW+timedelta(hours=1)) is RiskDecision.PASS

def test_sql_alert_update_roundtrip(sql_setup):
 service,repo,account_id,policy,versions=sql_setup
 output=service.run_pre_trade_checks(make_input(account_id,stock_weight=Decimal("1")),policy.policy_version_id)
 alert=repo.alerts_for_account(account_id)[0]
 updated=service.acknowledge_alert(alert.alert_id,"operator",NOW,0)
 assert repo.get_alert(alert.alert_id)==updated

REQUIRED=("risk_rules","risk_rule_versions","risk_policy_versions","risk_policy_rule_bindings","risk_check_runs","risk_check_results","risk_exceptions","risk_alerts","risk_events")
SQL=(Path(__file__).parents[2]/"migrations"/"011_risk.sql").read_text(encoding="utf-8")

@pytest.mark.parametrize("table",REQUIRED)
def test_required_tables_in_metadata_and_migration(table):assert table in metadata.tables and table in SQL

@pytest.mark.parametrize("fragment",("UNIQUE(rule_id,version)","input_hash TEXT UNIQUE","dedupe_key TEXT UNIQUE","CHECK(expires_at>approved_at)","TIMESTAMPTZ","JSONB"))
def test_postgresql_constraints(fragment):assert fragment in SQL

@pytest.mark.parametrize("table",REQUIRED)
def test_sqlite_tables_queryable(sql_repo,table):
 with sql_repo.engine.connect() as c:c.execute(select(metadata.tables[table]).limit(1)).all()
