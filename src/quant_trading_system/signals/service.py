from __future__ import annotations
import hashlib,json
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
from uuid import UUID
from quant_trading_system.instruments import InstrumentService
from quant_trading_system.strategies import StrategyKind
from .domain import *
from .errors import *
from .ports import SignalRepository
class SignalService:
 def __init__(self,repository:SignalRepository,instruments:InstrumentService):self.repository=repository;self.instruments=instruments
 def create(self,c:CreateSignal)->SignalResult:
  decision=aware(c.decision_at,"decision_at");expires=aware(c.expires_at,"expires_at")
  payload={"target":str(c.target.target_id)+c.target.content_hash,"account":str(c.account.snapshot_id),"pricing":str(c.pricing.snapshot_id)+c.pricing.content_hash,"decision":decision.isoformat(),"valid":c.valid_for_date.isoformat(),"expires":expires.isoformat(),"fee":str(c.fee_policy.policy_id),"components":sorted(str(x.component_id) for x in c.components)};input_hash=self._hash(payload);existing=self.repository.find(input_hash)
  if existing:
   result=self.repository.get_result(existing.signal_id)
   if result is None:raise SignalNotFound(str(existing.signal_id))
   return result
  if c.target.account_snapshot_id!=c.account.snapshot_id:raise SignalCreationRejected("target/account snapshot mismatch")
  if {x.strategy_kind for x in c.components}!={StrategyKind.ETF_TIMING,StrategyKind.EQUITY_DAILY_SELECTION}:raise SignalCreationRejected("both strategy components are required")
  prices={x.instrument_id:x for x in c.pricing.prices}
  if len(prices)!=len(c.pricing.prices):raise SignalCreationRejected("duplicate price")
  oldest=min((x.available_at for x in prices.values()),default=decision)
  if any(x.available_at>decision or (decision-x.available_at).total_seconds()>c.fee_policy.max_price_age_seconds for x in prices.values()):raise SignalCreationRejected("STALE_INPUT")
  targets={x.instrument_id:x.target_weight for x in c.target.weights};all_ids=set(targets)|set(c.account.quantities);draft=[];sell_proceeds=Decimal();buy_cost=Decimal()
  for iid in sorted(all_ids,key=str):
   price_input=prices.get(iid)
   if price_input is None:
    if targets.get(iid,Decimal())>0 or c.account.quantities.get(iid,0)>0:raise SignalCreationRejected(f"missing price for {iid}")
    continue
   price=price_input.price;current_qty=c.account.quantities.get(iid,0);current_weight=Decimal(current_qty)*price/c.account.nav;target_weight=targets.get(iid,Decimal());delta=target_weight-current_weight;trade_value=abs(delta)*c.account.nav
   if trade_value<c.fee_policy.min_trade_value:continue
   spec=self.instruments.get_trading_spec(iid,c.valid_for_date);quantity=int((trade_value/price)//spec.lot_size)*spec.lot_size
   if quantity<=0:continue
   side=Side.BUY if delta>0 else Side.SELL
   if side is Side.SELL:quantity=min(quantity,c.account.settled_sellable.get(iid,0));quantity=(quantity//spec.lot_size)*spec.lot_size
   if quantity<=0:continue
   limit=self._limit_price(price,spec.tick_size,c.fee_policy.price_buffer,side);gross=limit*quantity;fee=max(c.fee_policy.min_commission,gross*c.fee_policy.commission_rate)+(gross*c.fee_policy.stamp_duty_rate if side is Side.SELL else Decimal())
   if side is Side.SELL:sell_proceeds+=gross-fee
   else:buy_cost+=gross+fee
   component_sum=sum((x.weight_contribution for x in c.components if x.instrument_id==iid),Decimal())
   if abs(component_sum-delta)>Decimal("0.00000001"):raise SignalCreationRejected(f"component reconciliation failed for {iid}")
   draft.append((iid,side,target_weight,current_weight,delta,quantity,limit,fee))
  if buy_cost>c.account.cash+sell_proceeds-c.fee_policy.cash_buffer:raise SignalCreationRejected("insufficient projected cash")
  signal_id=UUID(bytes=hashlib.sha256(input_hash.encode()).digest()[:16]);content=self._hash([(str(i),s.value,str(q),str(p)) for i,s,_,_,_,q,p,_ in draft]);signal=Signal(c.target.target_id,c.account.snapshot_id,c.pricing.snapshot_id,decision,c.valid_for_date,expires,SignalStatus.DRAFT,input_hash,content,c.account.reconciled,oldest,c.fee_policy.max_price_age_seconds,c.fee_policy.reprice_threshold,signal_id=signal_id)
  recommendations=tuple(Recommendation(signal_id,i,s,t,w,d,q,p,f,("NET_TARGET_DELTA",)) for i,s,t,w,d,q,p,f in draft);result=SignalResult(signal,recommendations,c.components);self.repository.save_draft(result,SignalEvent("SignalDrafted",signal_id,datetime.now(timezone.utc),{}));return result
 @staticmethod
 def _current_weight(i,account,price):return Decimal() if price is None else Decimal(account.quantities.get(i,0))*price/account.nav
 @staticmethod
 def _limit_price(price,tick,buffer,side):
  raw=price*(Decimal(1)+buffer if side is Side.BUY else Decimal(1)-buffer);units=(raw/tick).to_integral_value(rounding=ROUND_CEILING if side is Side.BUY else ROUND_FLOOR);return units*tick
 @staticmethod
 def _hash(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
 def attach_risk(self,signal_id,risk_result_id,decision):
  result=self._result(signal_id);signal=result.signal
  if signal.status is not SignalStatus.DRAFT:raise PublishRejected("risk may attach only to draft")
  updated=replace(signal,status=SignalStatus.RISK_CHECKED,risk_result_id=risk_result_id,risk_decision=decision);self.repository.update_signal(updated,SignalEvent("SignalRiskChecked",signal_id,datetime.now(timezone.utc),{"decision":decision.value}));return updated
 def publish(self,signal_id,now):
  now=aware(now,"now");signal=self._result(signal_id).signal
  if signal.status is SignalStatus.PUBLISHED:return signal
  if signal.status is not SignalStatus.RISK_CHECKED or signal.risk_decision is not RiskDecision.PASS:raise PublishRejected("risk is not PASS")
  if not signal.account_reconciled:raise PublishRejected("account is not reconciled")
  if now>=signal.expires_at or (now-signal.oldest_price_at).total_seconds()>signal.max_price_age_seconds:raise PublishRejected("signal expired or price stale")
  updated=replace(signal,status=SignalStatus.PUBLISHED);self.repository.update_signal(updated,SignalEvent("SignalPublished",signal_id,now,{}));return updated
 def approve(self,decision:ApprovalDecision):
  existing=self.repository.get_approval(decision.decision_id)
  if existing:return self.repository.get_recommendation(existing.recommendation_id),existing
  rec=self.repository.get_recommendation(decision.recommendation_id)
  if rec is None:raise SignalNotFound(str(decision.recommendation_id))
  signal=self._result(rec.signal_id).signal
  if signal.status is not SignalStatus.PUBLISHED or decision.decided_at>=signal.expires_at:raise ApprovalConflict("signal not actionable")
  if rec.version!=decision.expected_version or rec.status is not RecommendationStatus.PENDING:raise ApprovalConflict("APPROVAL_CONFLICT")
  if decision.kind is ApprovalKind.ACCEPT:
   if decision.quantity!=rec.quantity:raise ApprovalConflict("accept must use full suggested quantity")
   updated=replace(rec,status=RecommendationStatus.APPROVED,approved_quantity=rec.quantity,version=rec.version+1)
  elif decision.kind is ApprovalKind.PARTIAL:
   if not 0<decision.quantity<rec.quantity or not decision.reason.strip():raise ApprovalConflict("partial approval needs reduced quantity and reason")
   updated=replace(rec,status=RecommendationStatus.PARTIALLY_APPROVED,approved_quantity=decision.quantity,version=rec.version+1)
  else:
   if decision.quantity!=0 or not decision.reason.strip():raise ApprovalConflict("rejection needs zero quantity and reason")
   updated=replace(rec,status=RecommendationStatus.REJECTED,version=rec.version+1)
  self.repository.apply_approval(updated,decision,SignalEvent("RecommendationApproved",rec.signal_id,decision.decided_at,{"kind":decision.kind.value}));return updated,decision
 def hand_off(self,recommendation_id,quantity,expected_version):
  rec=self.repository.get_recommendation(recommendation_id)
  if rec is None:raise SignalNotFound(str(recommendation_id))
  if rec.version!=expected_version or quantity<=0 or quantity>rec.remaining_quantity:raise ApprovalConflict("handoff quantity/version conflict")
  updated=replace(rec,handed_off_quantity=rec.handed_off_quantity+quantity,status=RecommendationStatus.HANDED_OFF if quantity==rec.remaining_quantity else rec.status,version=rec.version+1);audit=ApprovalDecision(rec.recommendation_id,UUID(int=uuid_int(updated.version,rec.recommendation_id)),ApprovalKind.PARTIAL,quantity,"execution handoff","system",datetime.now(timezone.utc),expected_version);self.repository.apply_approval(updated,audit,SignalEvent("RecommendationHandedOff",rec.signal_id,audit.decided_at,{"quantity":str(quantity)}));return updated
 def expire(self,signal_id,now):
  signal=self._result(signal_id).signal;updated=replace(signal,status=SignalStatus.EXPIRED);self.repository.update_signal(updated,SignalEvent("SignalExpired",signal_id,aware(now,"now"),{}));return updated
 def check_reprice(self,signal_id,current_prices:Mapping[UUID,Decimal],now):
  result=self._result(signal_id);signal=result.signal
  for rec in result.recommendations:
   current=current_prices.get(rec.instrument_id)
   if current is None or abs(dec(current)/rec.limit_price-1)>signal.reprice_threshold:
    updated=replace(signal,status=SignalStatus.EXPIRED);self.repository.update_signal(updated,SignalEvent("SignalExpired",signal_id,aware(now,"now"),{"reason":"REPRICE_REQUIRED"}));return False
  return True
 def supersede(self,old_signal_id,new_signal_id,reason,now):
  old=self._result(old_signal_id).signal;new=self._result(new_signal_id).signal
  if old.status not in (SignalStatus.DRAFT,SignalStatus.RISK_CHECKED,SignalStatus.PUBLISHED) or not reason.strip():raise InvalidSignal("cannot supersede")
  updated=replace(old,status=SignalStatus.SUPERSEDED);value=SignalSupersession(old_signal_id,new_signal_id,reason,now);self.repository.save_supersession(value,updated,new,SignalEvent("SignalSuperseded",old_signal_id,aware(now,"now"),{"new":str(new_signal_id)}));return value
 def get_actionable(self,as_of):
  now=aware(as_of,"as_of");return tuple(rec for result in self.repository.all_results() if result.signal.status is SignalStatus.PUBLISHED and now<result.signal.expires_at for rec in result.recommendations if rec.status in (RecommendationStatus.APPROVED,RecommendationStatus.PARTIALLY_APPROVED) and rec.remaining_quantity>0)
 def get_daily_decision_board(self,signal_id):return self._result(signal_id)
 def _result(self,i):
  value=self.repository.get_result(i)
  if value is None:raise SignalNotFound(str(i))
  return value
def uuid_int(version:int,value:UUID)->int:return (value.int+version)%(1<<128)
