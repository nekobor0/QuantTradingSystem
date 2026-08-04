from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from quant_trading_system.portfolio import *
from quant_trading_system.portfolio.errors import *
from quant_trading_system.strategies import RunStatus,StrategyKind
NOW=datetime(2024,1,8,9,tzinfo=timezone.utc)
def run(kind,weights,cash=False,when=NOW,status=RunStatus.COMPLETED):return StrategyRunTarget(uuid4(),kind,status,when,cash,tuple(StrategyTargetWeight(i,Decimal(str(w))) for i,w in weights.items()))
def account(weights=None,tradable=None,market=None,industry=None,as_of=NOW):
 weights=weights or {};return AccountSnapshotInput(uuid4(),as_of,{i:Decimal(str(w)) for i,w in weights.items()},Decimal(1)-sum((Decimal(str(w)) for w in weights.values()),Decimal()),tradable or {},market or {},industry or {})
def command(policy,runs,acct=None):return BuildTargetPortfolio(tuple(runs),acct or account(),policy,NOW)
def normal_runs():
 a,b,c=uuid4(),uuid4(),uuid4();return (run(StrategyKind.ETF_TIMING,{a:".5",b:".5"}),run(StrategyKind.EQUITY_DAILY_SELECTION,{b:".5",c:".5"})),(a,b,c)
def test_dual_sleeve_golden(portfolio_setup):
 s,r,p=portfolio_setup;runs,ids=normal_runs();result=s.build(command(p,runs));got={x.instrument_id:x.weight for x in result.weights};assert got[ids[0]]==Decimal(".15") and got[ids[1]]==Decimal(".45") and got[ids[2]]==Decimal(".3") and result.target.cash_weight==Decimal(".1")
def test_weight_conservation(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();result=s.build(command(p,runs));assert abs(sum((x.weight for x in result.weights),Decimal())+result.target.cash_weight-1)<=p.tolerance
def test_long_only(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();assert all(x.weight>=0 for x in s.build(command(p,runs)).weights)
def test_input_order_independent(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();acct=account();a=s.build(command(p,runs,acct));b=s.build(command(p,tuple(reversed(runs)),acct));assert a.target.target_id==b.target.target_id and a.target.content_hash==b.target.content_hash
def test_idempotent(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();c=command(p,runs);assert s.build(c).target.target_id==s.build(c).target.target_id
@pytest.mark.parametrize("missing",[StrategyKind.ETF_TIMING,StrategyKind.EQUITY_DAILY_SELECTION])
def test_required_run_missing(portfolio_setup,missing):
 s,r,p=portfolio_setup;runs,_=normal_runs()
 with pytest.raises(PortfolioRejected):s.build(command(p,[x for x in runs if x.kind is not missing]))
def test_run_must_be_completed(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();runs=(replace(runs[0],status=RunStatus.FAILED),runs[1])
 with pytest.raises(PortfolioRejected):s.build(command(p,runs))
def test_duplicate_kind_rejected(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs()
 with pytest.raises(PortfolioRejected):s.build(command(p,(runs[0],replace(runs[0],run_id=uuid4()))))
def test_cash_gate_explicit(portfolio_setup):
 s,r,p=portfolio_setup;i=uuid4();runs=(run(StrategyKind.ETF_TIMING,{},True),run(StrategyKind.EQUITY_DAILY_SELECTION,{i:1}));result=s.build(command(p,runs));assert {x.instrument_id:x.weight for x in result.weights}[i]==Decimal(".5") and result.target.cash_weight==Decimal(".5")
def test_all_cash(portfolio_setup):
 s,r,p=portfolio_setup;runs=(run(StrategyKind.ETF_TIMING,{},True),run(StrategyKind.EQUITY_DAILY_SELECTION,{},True));result=s.build(command(p,runs));assert result.weights==() and result.target.cash_weight==1
def test_cash_gated_run_cannot_hold_risk(portfolio_setup):
 s,r,p=portfolio_setup;i=uuid4();runs=(run(StrategyKind.ETF_TIMING,{i:1},True),run(StrategyKind.EQUITY_DAILY_SELECTION,{},True))
 with pytest.raises(PortfolioRejected):s.build(command(p,runs))
def test_strategy_weights_must_sum_one(portfolio_setup):
 s,r,p=portfolio_setup;i=uuid4();runs=(run(StrategyKind.ETF_TIMING,{i:".5"}),run(StrategyKind.EQUITY_DAILY_SELECTION,{},True))
 with pytest.raises(PortfolioRejected):s.build(command(p,runs))
def test_stale_account_rejected(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs()
 with pytest.raises(PortfolioRejected):s.build(command(p,runs,account(as_of=NOW-timedelta(hours=2))))
def test_future_account_rejected(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs()
 with pytest.raises(PortfolioRejected):s.build(command(p,runs,account(as_of=NOW+timedelta(seconds=1))))
def test_frozen_position_preserved(portfolio_setup):
 s,r,p=portfolio_setup;runs,ids=normal_runs();frozen=uuid4();acct=account({frozen:".2"},{frozen:False});result=s.build(command(p,runs,acct));assert {x.instrument_id:x.weight for x in result.weights}[frozen]==Decimal(".2") and any(x.rule=="FROZEN_POSITION" for x in result.constraints)
def test_frozen_position_can_make_cash_infeasible(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();frozen=uuid4();acct=account({frozen:".95"},{frozen:False})
 with pytest.raises(PortfolioRejected):s.build(command(p,runs,acct))
def test_instrument_cap(portfolio_setup):
 s,r,p=portfolio_setup;i,j=uuid4(),uuid4();runs=(run(StrategyKind.ETF_TIMING,{i:1}),run(StrategyKind.EQUITY_DAILY_SELECTION,{i:1}));result=s.build(command(p,runs));assert {x.instrument_id:x.weight for x in result.weights}[i]<=p.max_instrument and any(x.rule=="MAX_INSTRUMENT" and x.binding for x in result.constraints)
@pytest.mark.parametrize("group_field,cap_field,rule",[("market","market_caps","MARKET_CAP"),("industry","industry_caps","INDUSTRY_CAP")])
def test_group_caps(portfolio_setup,group_field,cap_field,rule):
 s,r,p=portfolio_setup;runs,ids=normal_runs();p=replace(p,**{cap_field:{"G":Decimal(".4")}});kwargs={group_field:{i:"G" for i in ids}};result=s.build(command(p,runs,account(**kwargs)));assert sum((x.weight for x in result.weights if kwargs[group_field].get(x.instrument_id)=="G"),Decimal())<=Decimal(".4") and any(x.rule==rule and x.binding for x in result.constraints)
def test_frozen_group_cap_infeasible(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();i=uuid4();p=replace(p,market_caps={"M":Decimal(".1")});acct=account({i:".2"},{i:False},{i:"M"})
 with pytest.raises(PortfolioRejected):s.build(command(p,runs,acct))
def test_turnover_blend(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();p=replace(p,max_turnover=Decimal(".1"));result=s.build(command(p,runs));turn=sum((abs(x.delta) for x in result.deltas),Decimal());assert turn<=Decimal(".1")+p.tolerance and any(x.rule=="MAX_TURNOVER" for x in result.constraints)
def test_min_cash_scales_risk(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();p=replace(p,min_cash=Decimal(".5"));result=s.build(command(p,runs));assert result.target.cash_weight>=Decimal(".5") and any(x.rule=="MIN_CASH" for x in result.constraints)
def test_new_account_snapshot_creates_new_target(portfolio_setup):
 s,r,p=portfolio_setup;runs,_=normal_runs();a=s.build(command(p,runs));b=s.build(command(p,runs,account()));assert a.target.target_id!=b.target.target_id
def test_explain_weight(portfolio_setup):
 s,r,p=portfolio_setup;runs,ids=normal_runs();result=s.build(command(p,runs));weight,contrib,steps,delta=s.explain_weight(result.target.target_id,ids[1]);assert weight and len(contrib)==2 and delta
def test_rejected_event(portfolio_setup):
 s,r,p=portfolio_setup
 with pytest.raises(PortfolioRejected):s.build(command(p,()))
 assert r.latest_event().event_type=="TargetPortfolioRejected"
