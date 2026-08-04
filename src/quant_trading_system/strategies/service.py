from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID,uuid4
from zoneinfo import ZoneInfo
from .domain import *
from .errors import *
from .ports import StrategyRepository
PURPOSES={StrategyKind.ETF_TIMING:("ETF_TIMING_POOL","ETF_TIMING"),StrategyKind.EQUITY_DAILY_SELECTION:("EQUITY_DAILY_POOL","EQUITY_DAILY_SELECTION")}
class StrategyService:
 def __init__(self,repository:StrategyRepository):self.repository=repository
 def register(self,d:StrategyDefinition,versions:tuple[StrategyVersion,...]):
  if any(x.definition_id!=d.definition_id for x in versions):raise InvalidStrategy("version definition mismatch")
  self.repository.save_definition(d,versions)
 def run(self,c:RunStrategy)->StrategyResult:
  decision=aware(c.decision_at,"decision_at");parameter_hash=self._hash(c.parameters)
  payload={"kind":c.kind.value,"version":str(c.version_id),"decision":decision.isoformat(),"universe":str(c.inputs.universe_snapshot_id)+c.inputs.universe_hash,"feature":str(c.inputs.feature_set_id)+c.inputs.feature_hash,"data":str(c.inputs.data_snapshot_id),"parameters":parameter_hash,"previous":str(c.previous_run_id),"supersede":str(c.supersede_run_id)}
  input_hash=self._hash(payload);existing=self.repository.find_run(input_hash)
  if existing:
   existing_result=self.repository.get_result(existing.run_id)
   if existing_result is None:raise StrategyRunRejected("identical prior run failed")
   return existing_result
  run=StrategyRun(c.kind,c.version_id,decision,c.inputs.universe_snapshot_id,c.inputs.feature_set_id,c.inputs.data_snapshot_id,parameter_hash,input_hash,"",RunStatus.CREATED,False,c.previous_run_id,c.supersede_run_id)
  try:
   version=self.repository.get_version(c.version_id);definition=None if version is None else self.repository.get_definition(version.definition_id)
   if version is None or definition is None or not version.active or definition.kind is not c.kind:raise SnapshotMismatch("strategy version kind mismatch")
   expected_universe,expected_feature=PURPOSES[c.kind]
   if c.inputs.kind is not c.kind or c.inputs.universe_purpose!=expected_universe or c.inputs.feature_purpose!=expected_feature:raise SnapshotMismatch("snapshot purpose mismatch")
   if c.inputs.decision_at!=decision:raise SnapshotMismatch("input decision_at mismatch")
   if len(set(c.inputs.member_ids))!=len(c.inputs.member_ids) or not c.inputs.member_ids:raise StrategyRunRejected("empty or duplicate universe")
   active=self.repository.active_run(c.kind,decision)
   if active and c.supersede_run_id!=active.run_id:raise StrategyRunRejected("active run requires explicit supersede")
   run=run.transition(RunStatus.INPUTS_FROZEN).transition(RunStatus.RUNNING)
   weights,top_n,merged_parameters=self._parameters(c.parameters,version)
   matrix=self._matrix(c.inputs,version.required_features)
   previous=self._previous(c.previous_run_id,c.kind)
   if c.kind is StrategyKind.ETF_TIMING:computed=self._run_etf(run,matrix,c.inputs,weights,top_n,merged_parameters,previous)
   else:computed=self._run_equity(run,matrix,c.inputs,weights,top_n,previous)
   self.repository.save_result(computed,StrategyEvent("StrategyRunCompleted",computed.run.run_id,datetime.now(timezone.utc)));return computed
  except Exception as exc:
   failed=StrategyRun(run.kind,run.version_id,run.decision_at,run.universe_snapshot_id,run.feature_set_id,run.data_snapshot_id,run.parameter_hash,run.input_hash,"",RunStatus.REJECTED if isinstance(exc,(SnapshotMismatch,StrategyRunRejected,InvalidStrategy)) else RunStatus.FAILED,False,run.previous_run_id,run.supersedes_run_id,run.run_id)
   self.repository.save_failed(failed,StrategyEvent("StrategyRunFailed",failed.run_id,datetime.now(timezone.utc),(str(exc),)))
   if isinstance(exc,StrategyError):raise
   raise StrategyRunRejected(str(exc)) from exc
 @staticmethod
 def _hash(value)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
 @staticmethod
 def _parameters(parameters,version):
  merged=dict(version.default_parameters);merged.update(parameters);top_n=int(merged.get("top_n",0));raw=merged.get("feature_weights")
  if top_n<=0 or not isinstance(raw,dict) or not raw:raise InvalidStrategy("top_n and feature_weights are required")
  weights={str(k):Decimal(str(v)) for k,v in raw.items()}
  if any(x<0 for x in weights.values()) or sum(weights.values(),Decimal())!=1:raise InvalidStrategy("feature weights must be nonnegative and sum to 1")
  if set(weights)!=set(version.required_features):raise InvalidStrategy("feature weights must match required features")
  return weights,top_n,merged
 @staticmethod
 def _matrix(inputs,required):
  result={}
  for iid in inputs.member_ids:
   rows={x.feature_name:x for x in inputs.feature_values if x.instrument_id==iid}
   if set(rows)!=set(required) or any(rows[x].quality!="OK" or rows[x].value is None for x in required):raise StrategyRunRejected(f"incomplete feature matrix for {iid}")
   result[iid]={name:rows[name].value for name in required}
  return result
 def _previous(self,run_id,kind):
  if run_id is None:return None
  value=self.repository.get_result(run_id)
  if value is None or value.run.kind is not kind or value.run.status is not RunStatus.COMPLETED:raise StrategyRunRejected("invalid previous run")
  return value
 @staticmethod
 def _score(run_id,matrix,weights,eligibility):
  values=[];contributions=[]
  for iid,row in matrix.items():
   if eligibility.get(iid,()):continue
   score=Decimal()
   for name,weight in weights.items():
    contribution=row[name]*weight;score+=contribution;contributions.append(FeatureContribution(run_id,iid,name,row[name],weight,contribution))
   values.append((iid,score))
  values.sort(key=lambda x:(-x[1],str(x[0])))
  return tuple(StrategyScore(run_id,iid,score,n+1) for n,(iid,score) in enumerate(values)),tuple(contributions)
 def _run_etf(self,run,matrix,inputs,weights,top_n,parameters,previous):
  weekday=int(parameters.get("rebalance_weekday",0));
  if weekday<0 or weekday>4:raise InvalidStrategy("rebalance_weekday must be 0..4")
  thresholds={"momentum":("trend_min",lambda x,t:x>=t),"volatility":("vol_max",lambda x,t:x<=t),"max_drawdown":("drawdown_floor",lambda x,t:x>=t),"liquidity":("liquidity_min",lambda x,t:x>=t)}
  gate_reasons={}
  for iid,row in matrix.items():
   reasons=list(inputs.eligibility.get(iid,()))
   for name,(key,predicate) in thresholds.items():
    if name in row and key in parameters and not predicate(row[name],Decimal(str(parameters[key]))):reasons.append(f"{key.upper()}_FAILED")
   gate_reasons[iid]=tuple(reasons)
  scores,contributions=self._score(run.run_id,matrix,weights,gate_reasons);passing=[x.instrument_id for x in scores]
  is_rebalance=run.decision_at.astimezone(ZoneInfo("Asia/Shanghai")).weekday()==weekday
  previous_ids=set() if previous is None else {x.instrument_id for x in previous.candidates if x.proposed_weight>0}
  if not is_rebalance and previous is None:raise StrategyRunRejected("non-rebalance ETF run requires previous run")
  selected=passing[:top_n] if is_rebalance else [x for x in previous_ids if x in passing]
  selected=set(selected);weight=Decimal(1)/len(selected) if selected else Decimal()
  rank={x.instrument_id:x.rank for x in scores};score={x.instrument_id:x.raw_score for x in scores};candidates=[]
  for iid in sorted(set(inputs.member_ids)|previous_ids,key=str):
   if iid in selected:candidates.append(StrategyCandidate(run.run_id,iid,CandidateAction.KEEP if iid in previous_ids else CandidateAction.SELECT,score.get(iid),rank.get(iid),weight,("RISK_GATE_PASS","REBALANCE" if is_rebalance else "HOLD")))
   elif iid in previous_ids or gate_reasons.get(iid):candidates.append(StrategyCandidate(run.run_id,iid,CandidateAction.EXIT,score.get(iid),rank.get(iid),Decimal(),gate_reasons.get(iid) or ("NOT_SELECTED",)))
  return self._complete(run,scores,tuple(candidates),contributions,not selected)
 def _run_equity(self,run,matrix,inputs,weights,top_n,previous):
  scores,contributions=self._score(run.run_id,matrix,weights,inputs.eligibility);selected={x.instrument_id for x in scores[:top_n]};previous_ids=set() if previous is None else {x.instrument_id for x in previous.candidates if x.proposed_weight>0};weight=Decimal(1)/len(selected) if selected else Decimal();lookup={x.instrument_id:x for x in scores};candidates=[]
  for iid in sorted(selected,key=lambda x:(lookup[x].rank,str(x))):
   x=lookup[iid];candidates.append(StrategyCandidate(run.run_id,iid,CandidateAction.KEEP if iid in previous_ids else CandidateAction.SELECT,x.raw_score,x.rank,weight,("TOP_N",)))
  for iid in sorted(previous_ids-selected,key=str):candidates.append(StrategyCandidate(run.run_id,iid,CandidateAction.EXIT,None,None,Decimal(),("DROPPED_FROM_TOP_N",)))
  if not selected:raise StrategyRunRejected("equity selection is empty")
  return self._complete(run,scores,tuple(candidates),contributions,False)
 def _complete(self,run,scores,candidates,contributions,cash_gate):
  payload=[(str(x.instrument_id),x.action.value,str(x.proposed_weight),x.rank) for x in candidates];digest=self._hash(payload);completed=run.transition(RunStatus.COMPLETED);completed=StrategyRun(completed.kind,completed.version_id,completed.decision_at,completed.universe_snapshot_id,completed.feature_set_id,completed.data_snapshot_id,completed.parameter_hash,completed.input_hash,digest,completed.status,cash_gate,completed.previous_run_id,completed.supersedes_run_id,completed.run_id)
  return StrategyResult(completed,scores,candidates,contributions)
 def get_strategy_result(self,run_id):
  result=self.repository.get_result(run_id)
  if result is None:raise StrategyRunNotFound(str(run_id))
  return result
 def explain_candidate(self,run_id,instrument_id):
  result=self.get_strategy_result(run_id);c=[x for x in result.candidates if x.instrument_id==instrument_id];return (c[0] if c else None,tuple(x for x in result.contributions if x.instrument_id==instrument_id))
 def get_daily_selection(self,run_id):
  result=self.get_strategy_result(run_id)
  if result.run.kind is not StrategyKind.EQUITY_DAILY_SELECTION:raise SnapshotMismatch("not an equity daily run")
  return result.candidates
 def add_research_evidence(self,value):self.repository.save_evidence(value)
