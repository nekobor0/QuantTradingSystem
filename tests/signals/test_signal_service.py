from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.signals import *
from quant_trading_system.signals.errors import *
from quant_trading_system.strategies import StrategyKind

NOW=datetime(2024,1,8,8,tzinfo=timezone.utc);VALID=date(2024,1,9);EXPIRES=NOW+timedelta(hours=12)
def fee(**kw):
 values=dict(commission_rate=Decimal(".0003"),min_commission=Decimal("5"),stamp_duty_rate=Decimal(".001"),price_buffer=Decimal(".001"),cash_buffer=Decimal("1000"),min_trade_value=Decimal("100"),max_price_age_seconds=3600,reprice_threshold=Decimal(".05"));values.update(kw);return FeePolicy(**values)
def account(quantities=None,sellable=None,cash=Decimal("100000"),reconciled=True,snapshot_id=None):return AccountExecutionInput(snapshot_id or uuid4(),"execution_ledger",NOW,reconciled,Decimal("100000"),Decimal(cash),quantities or {},sellable or {})
def make_command(instrument,*,target_weight=Decimal(".5"),quantity=0,sellable=0,cash=Decimal("100000"),reconciled=True,price=Decimal("10"),price_at=NOW,policy=None,target_id=None,account_id=None):
 acct=account({instrument.instrument_id:quantity},{instrument.instrument_id:sellable},cash,reconciled,account_id);target=TargetPortfolioInput(target_id or uuid4(),acct.snapshot_id,(TargetWeightInput(instrument.instrument_id,target_weight),) if target_weight else (),Decimal(1)-target_weight,"th");current=Decimal(quantity)*price/acct.nav;delta=target_weight-current;components=(SignalComponent(StrategyKind.ETF_TIMING,uuid4(),instrument.instrument_id,"GATE",delta/2,()),SignalComponent(StrategyKind.EQUITY_DAILY_SELECTION,uuid4(),instrument.instrument_id,"SELECT",delta/2,()));pricing=PricingSnapshot(uuid4(),(PriceInput(instrument.instrument_id,price,price_at),),"ph");return CreateSignal(target,acct,pricing,components,policy or fee(),NOW,VALID,EXPIRES)
def publish(service,result,decision=RiskDecision.PASS,now=NOW+timedelta(seconds=10)):
 service.attach_risk(result.signal.signal_id,uuid4(),decision);return service.publish(result.signal.signal_id,now)
def test_buy_quantity_price_and_fee(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));rec=result.recommendations[0];assert rec.side is Side.BUY and rec.quantity==5000 and rec.limit_price==Decimal("10.01") and rec.estimated_fee==Decimal("15.015000")
def test_sell_quantity_price_and_fee(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i,target_weight=Decimal(0),quantity=5000,sellable=5000,cash=Decimal("50000")));rec=result.recommendations[0];assert rec.side is Side.SELL and rec.quantity==5000 and rec.limit_price==Decimal("9.99") and rec.estimated_fee==Decimal("64.935000")
def test_sell_capped_by_settled_sellable(signal_setup):
 s,r,i,_=signal_setup;rec=s.create(make_command(i,target_weight=Decimal(0),quantity=5000,sellable=1000,cash=Decimal("50000"))).recommendations[0];assert rec.quantity==1000
def test_sell_with_no_settled_quantity_is_omitted(signal_setup):
 s,r,i,_=signal_setup;assert s.create(make_command(i,target_weight=Decimal(0),quantity=5000,sellable=0,cash=Decimal("50000"))).recommendations==()
def test_min_trade_and_round_lot_remove_zero_orders(signal_setup):
 s,r,i,_=signal_setup;assert s.create(make_command(i,target_weight=Decimal(".0005"))).recommendations==()
def test_projected_cash_gate(signal_setup):
 s,r,i,_=signal_setup
 with pytest.raises(SignalCreationRejected):s.create(make_command(i,target_weight=Decimal(1),cash=Decimal("1000")))
def test_sell_proceeds_release_cash_for_buy(signal_setup):
 s,r,a,b=signal_setup;acct=account({a.instrument_id:5000,b.instrument_id:0},{a.instrument_id:5000},Decimal("1000"));prices=(PriceInput(a.instrument_id,Decimal(10),NOW),PriceInput(b.instrument_id,Decimal(10),NOW));target=TargetPortfolioInput(uuid4(),acct.snapshot_id,(TargetWeightInput(b.instrument_id,Decimal(".4")),),Decimal(".6"),"t");components=[]
 for iid,delta in ((a.instrument_id,Decimal("-.5")),(b.instrument_id,Decimal(".4"))):components.extend((SignalComponent(StrategyKind.ETF_TIMING,uuid4(),iid,"x",delta/2,()),SignalComponent(StrategyKind.EQUITY_DAILY_SELECTION,uuid4(),iid,"x",delta/2,())))
 result=s.create(CreateSignal(target,acct,PricingSnapshot(uuid4(),prices,"p"),tuple(components),fee(cash_buffer=Decimal(0)),NOW,VALID,EXPIRES));assert {x.side for x in result.recommendations}=={Side.BUY,Side.SELL}
def test_component_reconciliation(signal_setup):
 s,r,i,_=signal_setup;c=make_command(i);bad=replace(c,components=tuple(replace(x,weight_contribution=Decimal(0)) for x in c.components))
 with pytest.raises(SignalCreationRejected):s.create(bad)
def test_both_strategy_components_required(signal_setup):
 s,r,i,_=signal_setup;c=make_command(i)
 with pytest.raises(SignalCreationRejected):s.create(replace(c,components=(c.components[0],)))
def test_account_target_snapshot_must_match(signal_setup):
 s,r,i,_=signal_setup;c=make_command(i)
 with pytest.raises(SignalCreationRejected):s.create(replace(c,target=replace(c.target,account_snapshot_id=uuid4())))
def test_stale_or_future_price_rejected(signal_setup):
 s,r,i,_=signal_setup
 with pytest.raises(SignalCreationRejected):s.create(make_command(i,price_at=NOW-timedelta(hours=2)))
def test_create_is_idempotent(signal_setup):
 s,r,i,_=signal_setup;c=make_command(i);assert s.create(c).signal.signal_id==s.create(c).signal.signal_id
def test_draft_not_actionable(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));assert s.get_actionable(NOW)==()
def test_publish_requires_risk(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i))
 with pytest.raises(PublishRejected):s.publish(result.signal.signal_id,NOW)
def test_hard_risk_cannot_publish(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));s.attach_risk(result.signal.signal_id,uuid4(),RiskDecision.HARD_FAIL)
 with pytest.raises(PublishRejected):s.publish(result.signal.signal_id,NOW)
def test_unreconciled_account_cannot_publish(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i,reconciled=False));s.attach_risk(result.signal.signal_id,uuid4(),RiskDecision.PASS)
 with pytest.raises(PublishRejected):s.publish(result.signal.signal_id,NOW)
def test_stale_price_cannot_publish(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));s.attach_risk(result.signal.signal_id,uuid4(),RiskDecision.PASS)
 with pytest.raises(PublishRejected):s.publish(result.signal.signal_id,NOW+timedelta(hours=2))
def test_publish_is_idempotent(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));published=publish(s,result);assert s.publish(result.signal.signal_id,NOW+timedelta(seconds=20))==published
def approve(service,result,kind=ApprovalKind.ACCEPT,quantity=None,reason="ok",decision_id=None,expected=0):
 rec=result.recommendations[0];d=ApprovalDecision(rec.recommendation_id,decision_id or uuid4(),kind,rec.quantity if quantity is None else quantity,reason,"user",NOW+timedelta(minutes=1),expected);return service.approve(d)
def test_full_approval_and_actionable(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result);updated,_=approve(s,result);assert updated.status is RecommendationStatus.APPROVED and s.get_actionable(NOW+timedelta(minutes=2))[0].remaining_quantity==updated.quantity
def test_partial_approval(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result);updated,_=approve(s,result,ApprovalKind.PARTIAL,1000,"reduced");assert updated.status is RecommendationStatus.PARTIALLY_APPROVED and updated.approved_quantity==1000
def test_partial_requires_reason_and_bounds(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result)
 with pytest.raises(ApprovalConflict):approve(s,result,ApprovalKind.PARTIAL,result.recommendations[0].quantity,"")
def test_rejection(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result);updated,_=approve(s,result,ApprovalKind.REJECT,0,"no");assert updated.status is RecommendationStatus.REJECTED and s.get_actionable(NOW+timedelta(minutes=2))==()
def test_approval_version_conflict(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result)
 with pytest.raises(ApprovalConflict):approve(s,result,expected=1)
def test_approval_decision_id_idempotent(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result);did=uuid4();a=s.approve(ApprovalDecision(result.recommendations[0].recommendation_id,did,ApprovalKind.ACCEPT,result.recommendations[0].quantity,"ok","u",NOW+timedelta(minutes=1),0));b=s.approve(ApprovalDecision(result.recommendations[0].recommendation_id,did,ApprovalKind.ACCEPT,result.recommendations[0].quantity,"ok","u",NOW+timedelta(minutes=1),0));assert a[1].approval_id==b[1].approval_id
def test_handoff_reduces_remaining(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result);updated,_=approve(s,result,ApprovalKind.PARTIAL,1000,"reduced");after=s.hand_off(updated.recommendation_id,400,updated.version);assert after.remaining_quantity==600
def test_handoff_cannot_exceed_remaining(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result);updated,_=approve(s,result,ApprovalKind.PARTIAL,1000,"reduced")
 with pytest.raises(ApprovalConflict):s.hand_off(updated.recommendation_id,1001,updated.version)
def test_expire_removes_actionability(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));publish(s,result);approve(s,result);s.expire(result.signal.signal_id,NOW+timedelta(hours=1));assert s.get_actionable(NOW+timedelta(hours=1))==()
def test_supersession(signal_setup):
 s,r,i,_=signal_setup;one=s.create(make_command(i));two=s.create(make_command(i,target_weight=Decimal(".4"),target_id=uuid4()));value=s.supersede(one.signal.signal_id,two.signal.signal_id,"new target",NOW);assert value.old_signal_id==one.signal.signal_id and s.get_daily_decision_board(one.signal.signal_id).signal.status is SignalStatus.SUPERSEDED
def test_board_keeps_both_strategy_components(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));assert {x.strategy_kind for x in s.get_daily_decision_board(result.signal.signal_id).components}=={StrategyKind.ETF_TIMING,StrategyKind.EQUITY_DAILY_SELECTION}
def test_reprice_within_threshold(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));assert s.check_reprice(result.signal.signal_id,{i.instrument_id:Decimal("10.2")},NOW+timedelta(minutes=1)) is True
def test_reprice_required_expires_signal(signal_setup):
 s,r,i,_=signal_setup;result=s.create(make_command(i));assert s.check_reprice(result.signal.signal_id,{i.instrument_id:Decimal("12")},NOW+timedelta(minutes=1)) is False and s.get_daily_decision_board(result.signal.signal_id).signal.status is SignalStatus.EXPIRED
