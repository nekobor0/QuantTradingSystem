from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.risk import *
from quant_trading_system.risk.errors import InvalidRiskInput

from .conftest import NOW, SCOPES, make_input


@pytest.mark.parametrize("code", ["CASH", "MAX_WEIGHT", "LIQUIDITY", "ST", "TASK_HEALTH"])
def test_rule_accepts_metadata(code):
    assert RiskRule(code, code, "owner", "description").code == code


@pytest.mark.parametrize("field", ["code", "name", "owner", "description"])
def test_rule_rejects_missing_metadata(field):
    values={"code":"c","name":"n","owner":"o","description":"d"};values[field]=""
    with pytest.raises(InvalidRiskInput):RiskRule(**values)


@pytest.mark.parametrize("operator", list(ComparisonOperator))
def test_rule_version_accepts_all_operators(operator):
    value=RiskRuleVersion(uuid4(),"v1",RiskStage.PRE_TRADE,RiskScope.COMBINED_ACCOUNT,"x",operator,1,RiskSeverity.WARNING,date(2020,1,1),None,"owner")
    assert value.operator is operator


@pytest.mark.parametrize("severity", list(RiskSeverity))
def test_rule_version_accepts_all_severities(severity):
    assert RiskRuleVersion(uuid4(),"v",RiskStage.POST_TRADE,RiskScope.ETF_TIMING,"x",ComparisonOperator.EQ,1,severity,date(2020,1,1),None,"o").severity is severity


def test_rule_version_effective_interval():
    value=RiskRuleVersion(uuid4(),"v",RiskStage.PRE_TRADE,RiskScope.ETF_TIMING,"x",ComparisonOperator.EQ,1,RiskSeverity.WARNING,date(2025,1,1),date(2025,1,31),"o")
    assert value.active_on(date(2025,1,1)) and value.active_on(date(2025,1,31)) and not value.active_on(date(2025,2,1))


def test_rule_version_rejects_inverted_interval():
    with pytest.raises(InvalidRiskInput):RiskRuleVersion(uuid4(),"v",RiskStage.PRE_TRADE,RiskScope.ETF_TIMING,"x",ComparisonOperator.EQ,1,RiskSeverity.WARNING,date(2025,2,1),date(2025,1,1),"o")


def test_policy_requires_all_three_scopes(account_id):
    with pytest.raises(InvalidRiskInput):RiskPolicyVersion("p","v",account_id,"CN",(uuid4(),),(RiskScope.COMBINED_ACCOUNT,),date(2020,1,1),None,"o",60)


def test_policy_rejects_duplicate_rule_versions(account_id):
    rule_id=uuid4()
    with pytest.raises(InvalidRiskInput):RiskPolicyVersion("p","v",account_id,"CN",(rule_id,rule_id),SCOPES,date(2020,1,1),None,"o",60)


@pytest.mark.parametrize("stage", list(RiskStage))
def test_input_accepts_all_stages(account_id, stage):
    assert make_input(account_id,stage=stage).stage is stage


def test_post_trade_requires_execution_ledger(account_id):
    with pytest.raises(InvalidRiskInput):make_input(account_id,stage=RiskStage.POST_TRADE,account_source="backtest")


def test_input_requires_all_scopes(account_id):
    value=make_input(account_id)
    with pytest.raises(InvalidRiskInput):replace(value,scoped_values={RiskScope.COMBINED_ACCOUNT:{}})


def test_input_requires_content_hashes(account_id):
    with pytest.raises(InvalidRiskInput):make_input(account_id,hashes={})


@pytest.mark.parametrize("status", list(AlertStatus))
def test_alert_status_values(status):
    assert status.value


@pytest.mark.parametrize("status", list(ExceptionStatus))
def test_exception_status_values(status):
    assert status.value


def test_exception_requires_two_people():
    with pytest.raises(InvalidRiskInput):RiskException(uuid4(),uuid4(),RiskScope.COMBINED_ACCOUNT,"same","same","reason",NOW,NOW+timedelta(days=1))


def test_exception_requires_future_expiry():
    with pytest.raises(InvalidRiskInput):RiskException(uuid4(),uuid4(),RiskScope.COMBINED_ACCOUNT,"a","b","reason",NOW,NOW)


def test_aware_times_required(account_id):
    with pytest.raises(InvalidRiskInput):make_input(account_id,at=datetime(2025,1,1))
