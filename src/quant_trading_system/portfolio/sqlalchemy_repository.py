from datetime import timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import insert,select
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import RepositoryConflict
from .tables import constraints,contributions,deltas,events,policies,sleeves,targets,weights
class SqlAlchemyPortfolioRepository:
 def __init__(self,engine):self.engine=engine
 @staticmethod
 def _a(x):return x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x
 def save_policy(self,p):
  with self.engine.connect() as c:
   if c.execute(select(policies.c.policy_id).where(policies.c.policy_id==p.policy_id)).scalar_one_or_none() is not None:return
  try:
   with self.engine.begin() as c:
    c.execute(insert(policies).values(policy_id=p.policy_id,version=p.version,min_cash=p.min_cash,max_instrument=p.max_instrument,market_caps={k:str(v) for k,v in p.market_caps.items()},industry_caps={k:str(v) for k,v in p.industry_caps.items()},max_turnover=p.max_turnover,account_max_age_seconds=p.account_max_age_seconds,tolerance=p.tolerance))
    c.execute(insert(sleeves),[{"sleeve_id":x.sleeve_id,"policy_id":p.policy_id,"kind":x.kind.value,"budget":x.budget,"required":x.required,"priority":x.priority} for x in p.sleeves])
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def find(self,h):
  with self.engine.connect() as c:r=c.execute(select(targets).where(targets.c.input_hash==h)).mappings().one_or_none()
  return None if r is None else self._target(r)
 def save(self,result,event):
  try:
   with self.engine.begin() as c:
    c.execute(insert(targets).values(**self._tv(result.target)))
    if result.weights:c.execute(insert(weights),[self._wv(x) for x in result.weights])
    if result.contributions:c.execute(insert(contributions),[self._cv(x) for x in result.contributions])
    if result.constraints:c.execute(insert(constraints),[self._qv(x) for x in result.constraints])
    if result.deltas:c.execute(insert(deltas),[self._dv(x) for x in result.deltas])
    c.execute(insert(events).values(event_id=event.event_id,event_type=event.event_type,target_id=event.target_id,occurred_at=event.occurred_at,reasons=list(event.reasons)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def save_rejected(self,event,input_hash):
  with self.engine.begin() as c:c.execute(insert(events).values(event_id=event.event_id,event_type=event.event_type,target_id=event.target_id,occurred_at=event.occurred_at,reasons=list(event.reasons),input_hash=input_hash))
 def get(self,i):
  with self.engine.connect() as c:
   t=c.execute(select(targets).where(targets.c.target_id==i)).mappings().one_or_none()
   if t is None:return None
   ws=c.execute(select(weights).where(weights.c.target_id==i)).mappings().all();cs=c.execute(select(contributions).where(contributions.c.target_id==i)).mappings().all();qs=c.execute(select(constraints).where(constraints.c.target_id==i)).mappings().all();ds=c.execute(select(deltas).where(deltas.c.target_id==i)).mappings().all()
  return PortfolioResult(self._target(t),tuple(TargetWeight(r.target_id,r.instrument_id,Decimal(r.weight),r.weight_id) for r in ws),tuple(TargetContribution(r.target_id,r.sleeve,r.instrument_id,Decimal(r.raw_weight),Decimal(r.final_weight),Decimal(r.cash_contribution),r.contribution_id) for r in cs),tuple(ConstraintResult(r.target_id,r.rule,r.scope,Decimal(r.before),Decimal(r.after),Decimal(r.limit_value),r.binding,r.reason,ConstraintSeverity(r.severity),r.result_id) for r in qs),tuple(RebalanceDelta(r.target_id,r.instrument_id,Decimal(r.current_weight),Decimal(r.target_weight),Decimal(r.delta),r.delta_id) for r in ds))
 def latest_event(self):
  with self.engine.connect() as c:r=c.execute(select(events).order_by(events.c.occurred_at.desc())).mappings().first()
  return None if r is None else PortfolioEvent(r.event_type,r.target_id,self._a(r.occurred_at),tuple(r.reasons),r.event_id)
 @staticmethod
 def _tv(x):return {"target_id":x.target_id,"policy_id":x.policy_id,"strategy_run_ids":[str(i) for i in x.strategy_run_ids],"account_snapshot_id":x.account_snapshot_id,"built_at":x.built_at,"cash_weight":x.cash_weight,"input_hash":x.input_hash,"content_hash":x.content_hash}
 @classmethod
 def _target(cls,r):return TargetPortfolio(r.policy_id,tuple(UUID(x) for x in r.strategy_run_ids),r.account_snapshot_id,cls._a(r.built_at),Decimal(r.cash_weight),r.input_hash,r.content_hash,r.target_id)
 @staticmethod
 def _wv(x):return {"weight_id":x.weight_id,"target_id":x.target_id,"instrument_id":x.instrument_id,"weight":x.weight}
 @staticmethod
 def _cv(x):return {"contribution_id":x.contribution_id,"target_id":x.target_id,"sleeve":x.sleeve,"instrument_id":x.instrument_id,"raw_weight":x.raw_weight,"final_weight":x.final_weight,"cash_contribution":x.cash_contribution}
 @staticmethod
 def _qv(x):return {"result_id":x.result_id,"target_id":x.target_id,"rule":x.rule,"scope":x.scope,"before":x.before,"after":x.after,"limit_value":x.limit,"binding":x.binding,"reason":x.reason,"severity":x.severity.value}
 @staticmethod
 def _dv(x):return {"delta_id":x.delta_id,"target_id":x.target_id,"instrument_id":x.instrument_id,"current_weight":x.current_weight,"target_weight":x.target_weight,"delta":x.delta}
