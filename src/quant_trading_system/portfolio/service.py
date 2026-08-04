from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID,uuid4
from .domain import *
from .errors import *
from .ports import PortfolioRepository
class PortfolioService:
 def __init__(self,repository:PortfolioRepository):self.repository=repository
 def build(self,c:BuildTargetPortfolio)->PortfolioResult:
  built_at=aware(c.built_at,"built_at");self.repository.save_policy(c.policy);ordered=tuple(sorted(c.runs,key=lambda x:(x.kind.value,str(x.run_id))));payload={"runs":[str(x.run_id) for x in ordered],"account":str(c.account.snapshot_id),"policy":self._policy_hash(c.policy)};input_hash=self._hash(payload);existing=self.repository.find(input_hash)
  if existing:
   value=self.repository.get(existing.target_id)
   if value is None:raise PortfolioNotFound(str(existing.target_id))
   return value
  target_id=uuid4()
  try:return self._build(target_id,input_hash,ordered,c.account,c.policy,built_at)
  except Exception as exc:
   self.repository.save_rejected(PortfolioEvent("TargetPortfolioRejected",target_id,datetime.now(timezone.utc),(str(exc),)),input_hash)
   if isinstance(exc,PortfolioError):raise
   raise PortfolioRejected(str(exc)) from exc
 def _build(self,target_id,input_hash,runs,account,policy,built_at):
  if (built_at-account.as_of).total_seconds()>policy.account_max_age_seconds or account.as_of>built_at:raise PortfolioRejected("account snapshot is stale or from future")
  run_by_kind={x.kind:x for x in runs}
  if len(run_by_kind)!=len(runs):raise PortfolioRejected("duplicate strategy kind")
  required={x.kind for x in policy.sleeves if x.required}
  if not required.issubset(run_by_kind):raise PortfolioRejected("required strategy run missing")
  policy_by_kind={x.kind:x for x in policy.sleeves};raw_by_sleeve={};merged={};cash_by_sleeve={}
  for run in runs:
   if run.kind not in policy_by_kind or run.status is not RunStatus.COMPLETED or run.decision_at>built_at:raise PortfolioRejected("invalid strategy run")
   sleeve=policy_by_kind[run.kind];weights={x.instrument_id:x.weight for x in run.weights}
   if len(weights)!=len(run.weights):raise PortfolioRejected("duplicate strategy target")
   total=sum(weights.values(),Decimal())
   if run.cash_gate:
    if total>policy.tolerance:raise PortfolioRejected("cash-gated run has risk weight")
    cash_by_sleeve[run.kind.value]=sleeve.budget;raw_by_sleeve[run.kind.value]={}
   else:
    if abs(total-1)>policy.tolerance:raise PortfolioRejected("strategy weights must sum to one")
    values={i:w*sleeve.budget for i,w in weights.items()};raw_by_sleeve[run.kind.value]=values;cash_by_sleeve[run.kind.value]=Decimal()
    for i,w in values.items():merged[i]=merged.get(i,Decimal())+w
  unallocated=Decimal(1)-sum((x.budget for x in policy.sleeves),Decimal())+sum(cash_by_sleeve.values(),Decimal())
  constraints=[];frozen={i:w for i,w in account.weights.items() if w>0 and not account.tradable.get(i,True)}
  if sum(frozen.values(),Decimal())>1-policy.min_cash+policy.tolerance:raise PortfolioRejected("frozen positions make minimum cash infeasible")
  for i,w in frozen.items():
   before=merged.get(i,Decimal());merged[i]=w;constraints.append(ConstraintResult(target_id,"FROZEN_POSITION",str(i),before,w,w,True,"untradable actual holding preserved",ConstraintSeverity.WARNING))
  for i in sorted(merged,key=str):
   if i in frozen:continue
   before=merged[i];merged[i]=min(before,policy.max_instrument);constraints.append(ConstraintResult(target_id,"MAX_INSTRUMENT",str(i),before,merged[i],policy.max_instrument,before>policy.max_instrument,"clipped to instrument cap",ConstraintSeverity.INFO))
  self._group_cap(target_id,merged,frozen,account.market,policy.market_caps,"MARKET_CAP",constraints)
  self._group_cap(target_id,merged,frozen,account.industry,policy.industry_caps,"INDUSTRY_CAP",constraints)
  all_ids=set(merged)|set(account.weights);turnover=sum((abs(merged.get(i,Decimal())-account.weights.get(i,Decimal())) for i in all_ids),Decimal())
  if turnover>policy.max_turnover:
   movable=[i for i in all_ids if i not in frozen];fixed_turn=sum((abs(merged.get(i,Decimal())-account.weights.get(i,Decimal())) for i in frozen),Decimal())
   if fixed_turn>policy.max_turnover+policy.tolerance:raise PortfolioRejected("turnover cap infeasible")
   ratio=(policy.max_turnover-fixed_turn)/(turnover-fixed_turn) if turnover>fixed_turn else Decimal()
   for i in movable:merged[i]=account.weights.get(i,Decimal())+(merged.get(i,Decimal())-account.weights.get(i,Decimal()))*ratio
   constraints.append(ConstraintResult(target_id,"MAX_TURNOVER","portfolio",turnover,policy.max_turnover,policy.max_turnover,True,"blended toward actual weights",ConstraintSeverity.INFO))
  risk=sum(merged.values(),Decimal());max_risk=Decimal(1)-policy.min_cash
  if risk>max_risk+policy.tolerance:
   frozen_sum=sum(frozen.values(),Decimal());movable_sum=risk-frozen_sum
   if frozen_sum>max_risk or movable_sum<=0:raise PortfolioRejected("minimum cash infeasible")
   ratio=(max_risk-frozen_sum)/movable_sum
   for i in list(merged):
    if i not in frozen:merged[i]*=ratio
   constraints.append(ConstraintResult(target_id,"MIN_CASH","portfolio",Decimal(1)-risk,policy.min_cash,policy.min_cash,True,"scaled tradable risk weights",ConstraintSeverity.INFO))
  merged={i:w for i,w in merged.items() if w>policy.tolerance};risk=sum(merged.values(),Decimal());cash=Decimal(1)-risk
  if cash<policy.min_cash-policy.tolerance or any(w<0 for w in merged.values()) or abs(risk+cash-1)>policy.tolerance:raise PortfolioRejected("weight conservation failed")
  rows=tuple(TargetWeight(target_id,i,w) for i,w in sorted(merged.items(),key=lambda x:str(x[0])))
  contributions=[]
  for sleeve,values in raw_by_sleeve.items():
   for i,raw in values.items():
    total_raw=sum((x.get(i,Decimal()) for x in raw_by_sleeve.values()),Decimal());final=merged.get(i,Decimal())*(raw/total_raw) if total_raw>0 else Decimal();contributions.append(TargetContribution(target_id,sleeve,i,raw,final,Decimal()))
   contributions.append(TargetContribution(target_id,sleeve,None,Decimal(),Decimal(),cash_by_sleeve[sleeve]))
  for i,w in frozen.items():
   raw_total=sum((x.get(i,Decimal()) for x in raw_by_sleeve.values()),Decimal())
   if w>raw_total:contributions.append(TargetContribution(target_id,"FROZEN_ACCOUNT",i,Decimal(),w-raw_total,Decimal()))
  attributed_cash=sum((x.cash_contribution for x in contributions),Decimal())
  if cash>attributed_cash:contributions.append(TargetContribution(target_id,"CONSTRAINT_AND_UNALLOCATED_CASH",None,Decimal(),Decimal(),cash-attributed_cash))
  deltas=tuple(RebalanceDelta(target_id,i,account.weights.get(i,Decimal()),merged.get(i,Decimal()),merged.get(i,Decimal())-account.weights.get(i,Decimal())) for i in sorted(set(account.weights)|set(merged),key=str))
  content=self._hash({"weights":[(str(x.instrument_id),str(x.weight)) for x in rows],"cash":str(cash)})
  target=TargetPortfolio(policy.policy_id,tuple(x.run_id for x in runs),account.snapshot_id,built_at,cash,input_hash,content,target_id);result=PortfolioResult(target,rows,tuple(contributions),tuple(constraints),deltas);self.repository.save(result,PortfolioEvent("TargetPortfolioBuilt",target_id,datetime.now(timezone.utc)));return result
 @staticmethod
 def _group_cap(target_id,weights,frozen,labels,caps,rule,results):
  for group,cap in sorted(caps.items()):
   ids=[i for i in weights if labels.get(i)==group];before=sum((weights[i] for i in ids),Decimal());frozen_sum=sum((weights[i] for i in ids if i in frozen),Decimal())
   if frozen_sum>cap:raise PortfolioRejected(f"{rule} infeasible for {group}")
   movable=[i for i in ids if i not in frozen]
   if before>cap and movable:
    movable_sum=before-frozen_sum;ratio=(cap-frozen_sum)/movable_sum
    for i in movable:weights[i]*=ratio
   after=sum((weights[i] for i in ids),Decimal());results.append(ConstraintResult(target_id,rule,group,before,after,cap,before>cap,"group proportional cap",ConstraintSeverity.INFO))
 @staticmethod
 def _hash(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
 @classmethod
 def _policy_hash(cls,p):return cls._hash({"id":str(p.policy_id),"version":p.version,"sleeves":[(x.kind.value,str(x.budget),x.required,x.priority) for x in sorted(p.sleeves,key=lambda x:x.kind.value)],"cash":str(p.min_cash),"instrument":str(p.max_instrument),"market":p.market_caps,"industry":p.industry_caps,"turnover":str(p.max_turnover),"age":p.account_max_age_seconds})
 def get_target_portfolio(self,target_id):
  value=self.repository.get(target_id)
  if value is None:raise PortfolioNotFound(str(target_id))
  return value
 def explain_weight(self,target_id,instrument_id):
  value=self.get_target_portfolio(target_id);return (next((x for x in value.weights if x.instrument_id==instrument_id),None),tuple(x for x in value.contributions if x.instrument_id==instrument_id),tuple(x for x in value.constraints if x.scope in (str(instrument_id),"portfolio")),next((x for x in value.deltas if x.instrument_id==instrument_id),None))
 def get_sleeve_contributions(self,target_id):return self.get_target_portfolio(target_id).contributions
