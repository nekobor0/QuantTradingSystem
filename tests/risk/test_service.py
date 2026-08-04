from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.risk import *
from quant_trading_system.risk.errors import *
from quant_trading_system.signals import RiskDecision as SignalRiskDecision

from .conftest import NOW, SCOPES, make_input


def by_metric(output, metric): return next(item for item in output.results if item.metric == metric)


def test_all_pass_returns_pass_with_three_scopes(service, policy, account_id):
    output=service.run_pre_trade_checks(make_input(account_id),policy.policy_version_id)
    assert output.run.decision is output.effective_decision is RiskDecision.PASS
    assert set(item.scope for item in output.results)==set(SCOPES)
    assert all(item.outcome is RuleOutcome.PASS for item in output.results)


def test_same_input_and_policy_is_idempotent(service,repo,policy,account_id):
    value=make_input(account_id)
    first=service.run_pre_trade_checks(value,policy.policy_version_id);second=service.run_pre_trade_checks(value,policy.policy_version_id)
    assert second.run.run_id==first.run.run_id and second.results==first.results
    assert len(repo.run_results)==1


@pytest.mark.parametrize("field,value,metric", [("reconciled",False,"ACCOUNT_RECONCILED"),("cash",Decimal("-1"),"NONNEGATIVE_CASH"),("negative_position",True,"NONNEGATIVE_POSITION")])
def test_mandatory_invariant_blocks(service,policy,account_id,field,value,metric):
    output=service.run_pre_trade_checks(make_input(account_id,**{field:value}),policy.policy_version_id)
    assert output.run.decision is RiskDecision.BLOCK
    assert by_metric(output,metric).outcome is RuleOutcome.BLOCK


@pytest.mark.parametrize("ages", [3601,7200,86400])
def test_stale_input_blocks(service,policy,account_id,ages):
    output=service.run_pre_trade_checks(make_input(account_id,ages=ages),policy.policy_version_id)
    assert by_metric(output,"INPUT_FRESHNESS").outcome is RuleOutcome.BLOCK


def test_future_snapshot_blocks_as_lookahead(service,policy,account_id):
    output=service.run_pre_trade_checks(make_input(account_id,ages=-1),policy.policy_version_id)
    assert by_metric(output,"INPUT_FRESHNESS").outcome is RuleOutcome.BLOCK


@pytest.mark.parametrize("expires,outcome", [(NOW+timedelta(seconds=1),RuleOutcome.PASS),(NOW,RuleOutcome.BLOCK),(NOW-timedelta(seconds=1),RuleOutcome.BLOCK)])
def test_signal_expiry_boundary(service,policy,account_id,expires,outcome):
    output=service.run_pre_trade_checks(make_input(account_id,signal_expires_at=expires),policy.policy_version_id)
    assert by_metric(output,"SIGNAL_NOT_EXPIRED").outcome is outcome


@pytest.mark.parametrize("stock_weight,outcome", [("0.099",RuleOutcome.PASS),("0.1",RuleOutcome.PASS),("0.1001",RuleOutcome.BLOCK)])
def test_hard_block_threshold_boundary(service,policy,account_id,stock_weight,outcome):
    output=service.run_pre_trade_checks(make_input(account_id,stock_weight=Decimal(stock_weight)),policy.policy_version_id)
    result=by_metric(output,"max_weight")
    assert result.outcome is outcome and result.scope is RiskScope.EQUITY_DAILY_SELECTION


@pytest.mark.parametrize("liquidity,outcome,decision", [("101",RuleOutcome.PASS,RiskDecision.PASS),("100",RuleOutcome.PASS,RiskDecision.PASS),("99",RuleOutcome.WARNING,RiskDecision.WARNING)])
def test_warning_threshold_boundary(service,policy,account_id,liquidity,outcome,decision):
    output=service.run_pre_trade_checks(make_input(account_id,etf_liquidity=Decimal(liquidity)),policy.policy_version_id)
    assert by_metric(output,"liquidity").outcome is outcome
    assert output.run.decision is decision


@pytest.mark.parametrize("weight,outcome,decision", [("0.8",RuleOutcome.PASS,RiskDecision.PASS),("0.81",RuleOutcome.APPROVAL_REQUIRED,RiskDecision.APPROVAL_REQUIRED)])
def test_approval_required_threshold(service,policy,account_id,weight,outcome,decision):
    output=service.run_pre_trade_checks(make_input(account_id,market_weight=Decimal(weight)),policy.policy_version_id)
    assert by_metric(output,"market_weight").outcome is outcome and output.run.decision is decision


def test_etf_pass_equity_block_aggregates_block(service,policy,account_id):
    output=service.run_pre_trade_checks(make_input(account_id,etf_liquidity=Decimal("200"),stock_weight=Decimal("0.2")),policy.policy_version_id)
    assert by_metric(output,"liquidity").outcome is RuleOutcome.PASS
    assert by_metric(output,"max_weight").outcome is RuleOutcome.BLOCK
    assert output.run.decision is RiskDecision.BLOCK


def test_etf_warning_equity_pass_preserves_scope(service,policy,account_id):
    output=service.run_pre_trade_checks(make_input(account_id,etf_liquidity=Decimal("1"),stock_weight=Decimal("0.05")),policy.policy_version_id)
    assert output.run.decision is RiskDecision.WARNING
    assert by_metric(output,"liquidity").scope is RiskScope.ETF_TIMING
    assert by_metric(output,"max_weight").scope is RiskScope.EQUITY_DAILY_SELECTION


def test_block_dominates_approval_and_warning(service,policy,account_id):
    output=service.run_pre_trade_checks(make_input(account_id,etf_liquidity=Decimal("1"),stock_weight=Decimal("1"),market_weight=Decimal("1")),policy.policy_version_id)
    assert output.run.decision is RiskDecision.BLOCK


@pytest.mark.parametrize("stage,method", [(RiskStage.PRE_TRADE,"run_pre_trade_checks"),(RiskStage.IN_FLIGHT,"run_in_flight_checks"),(RiskStage.POST_TRADE,"run_post_trade_checks")])
def test_stage_mismatch_rejected(service,policy,account_id,stage,method):
    value=make_input(account_id,stage=RiskStage.PRE_TRADE)
    if stage is RiskStage.PRE_TRADE:return
    with pytest.raises(InvalidRiskInput):getattr(service,method)(value,policy.policy_version_id)


def test_unknown_policy_rejected(service,account_id):
    with pytest.raises(PolicyNotFound):service.run_pre_trade_checks(make_input(account_id),uuid4())


def test_policy_account_mismatch(service,policy):
    with pytest.raises(InvalidRiskInput):service.run_pre_trade_checks(make_input(uuid4()),policy.policy_version_id)


def test_policy_inactive_at_decision(service,policy,account_id):
    inactive=replace(policy,policy_version_id=uuid4(),effective_from=date(2030,1,1));service.register_policy(inactive)
    with pytest.raises(InvalidRiskInput):service.run_pre_trade_checks(make_input(account_id),inactive.policy_version_id)


def test_policy_requires_known_rules(service,account_id):
    value=RiskPolicyVersion("p","v",account_id,"CN",(uuid4(),uuid4(),uuid4()),SCOPES,date(2020,1,1),None,"o",60)
    with pytest.raises(RuleNotFound):service.register_policy(value)


def test_policy_requires_rule_for_each_scope(service,account_id):
    versions=[]
    for index in range(3):
        rule=RiskRule(f"r{index}",f"r{index}","o","d")
        version=RiskRuleVersion(rule.rule_id,"v",RiskStage.PRE_TRADE,RiskScope.COMBINED_ACCOUNT,f"m{index}",ComparisonOperator.EQ,1,RiskSeverity.WARNING,date(2020,1,1),None,"o")
        service.register_rule(rule,version);versions.append(version.version_id)
    value=RiskPolicyVersion("p","v",account_id,"CN",tuple(versions),SCOPES,date(2020,1,1),None,"o",60)
    with pytest.raises(InvalidRiskInput):service.register_policy(value)


@pytest.mark.parametrize("operator,observed,threshold,passed", [(ComparisonOperator.LT,1,2,True),(ComparisonOperator.LE,2,2,True),(ComparisonOperator.GT,3,2,True),(ComparisonOperator.GE,2,2,True),(ComparisonOperator.EQ,"A","A",True),(ComparisonOperator.TRUE,True,True,True),(ComparisonOperator.FALSE,False,False,True),(ComparisonOperator.IN,"A",("A","B"),True),(ComparisonOperator.LT,2,1,False)])
def test_metric_evaluator_operators(operator,observed,threshold,passed):
    version=RiskRuleVersion(uuid4(),"v",RiskStage.PRE_TRADE,RiskScope.COMBINED_ACCOUNT,"x",operator,threshold,RiskSeverity.WARNING,date(2020,1,1),None,"o")
    assert RiskService._metric_evaluator(version,observed,None)==passed


def test_evaluator_error_fails_closed_and_alerts(service,repo,policy,rules,account_id):
    broken=replace(rules[0],evaluator_key="broken",version_id=uuid4());repo.save_rule_version(broken)
    broken_policy=replace(policy,policy_version_id=uuid4(),rule_version_ids=(broken.version_id,rules[1].version_id,rules[2].version_id));repo.save_policy(broken_policy)
    service.register_evaluator("broken",lambda rule,observed,value:(_ for _ in ()).throw(RuntimeError("boom")))
    output=service.run_pre_trade_checks(make_input(account_id),broken_policy.policy_version_id)
    error=by_metric(output,"RISK_ENGINE_ERROR")
    assert error.outcome is RuleOutcome.BLOCK and output.run.decision is RiskDecision.BLOCK
    assert any(alert.result_id==error.result_id for alert in repo.alerts.values())


def test_missing_metric_fails_closed(service,policy,account_id):
    value=make_input(account_id);scoped=dict(value.scoped_values);scoped[RiskScope.ETF_TIMING]={}
    output=service.run_pre_trade_checks(replace(value,scoped_values=scoped),policy.policy_version_id)
    assert by_metric(output,"RISK_ENGINE_ERROR").outcome is RuleOutcome.BLOCK


@pytest.mark.parametrize("currency,base,rate,expected", [("CNY","CNY",None,"100"),("HKD","CNY","0.9","90"),("USD","CNY","7.2","720")])
def test_explicit_fx_conversion(account_id,currency,base,rate,expected):
    value=make_input(account_id)
    if rate is not None:value=replace(value,fx_snapshot_id=uuid4(),fx_rates={f"{currency}/{base}":Decimal(rate)})
    assert RiskService.convert(Decimal("100"),currency,base,value)==Decimal(expected)


def test_missing_fx_snapshot_rejected(account_id):
    with pytest.raises(InvalidRiskInput):RiskService.convert(Decimal("1"),"HKD","CNY",make_input(account_id))


def test_signal_mapping_only_pass_maps_pass(service,policy,account_id):
    passed=service.run_pre_trade_checks(make_input(account_id),policy.policy_version_id)
    warned=service.run_pre_trade_checks(make_input(account_id,etf_liquidity=Decimal("1"),hashes={"x":"2"}),policy.policy_version_id)
    assert service.to_signal_decision(passed.run.run_id,NOW) is SignalRiskDecision.PASS
    assert service.to_signal_decision(warned.run.run_id,NOW) is SignalRiskDecision.HARD_FAIL
