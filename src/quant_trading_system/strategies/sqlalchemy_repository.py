from datetime import timezone
from decimal import Decimal
from sqlalchemy import insert,select
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import RepositoryConflict
from .tables import candidates,contributions,definitions,events,evidence_table,runs,scores,versions
class SqlAlchemyStrategyRepository:
 def __init__(self,engine):self.engine=engine
 @staticmethod
 def _a(x):return x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x
 def save_definition(self,d,vs):
  try:
   with self.engine.begin() as c:
    c.execute(insert(definitions).values(definition_id=d.definition_id,name=d.name,kind=d.kind.value,purpose=d.purpose,asset_scope=d.asset_scope,decision_frequency=d.decision_frequency,rebalance_frequency=d.rebalance_frequency,benchmark=d.benchmark,owner=d.owner,invalidation_conditions=list(d.invalidation_conditions)))
    c.execute(insert(versions),[{"version_id":x.version_id,"definition_id":x.definition_id,"version":x.version,"code_version":x.code_version,"required_features":list(x.required_features),"default_parameters":dict(x.default_parameters),"active":x.active} for x in vs])
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_definition(self,i):
  with self.engine.connect() as c:r=c.execute(select(definitions).where(definitions.c.definition_id==i)).mappings().one_or_none()
  return None if r is None else StrategyDefinition(r.name,StrategyKind(r.kind),r.purpose,r.asset_scope,r.decision_frequency,r.rebalance_frequency,r.benchmark,r.owner,tuple(r.invalidation_conditions),r.definition_id)
 def get_version(self,i):
  with self.engine.connect() as c:r=c.execute(select(versions).where(versions.c.version_id==i)).mappings().one_or_none()
  return None if r is None else StrategyVersion(r.definition_id,r.version,r.code_version,tuple(r.required_features),r.default_parameters,r.active,r.version_id)
 def find_run(self,h):
  with self.engine.connect() as c:r=c.execute(select(runs).where(runs.c.input_hash==h)).mappings().one_or_none()
  return None if r is None else self._run(r)
 def active_run(self,kind,decision_at):
  with self.engine.connect() as c:rs=c.execute(select(runs).where(runs.c.kind==kind.value,runs.c.decision_at==decision_at,runs.c.status==RunStatus.COMPLETED.value)).mappings().all()
  superseded={r.supersedes_run_id for r in rs if r.supersedes_run_id is not None};active=[r for r in rs if r.run_id not in superseded]
  return self._run(active[-1]) if active else None
 def save_result(self,result,event):
  try:
   with self.engine.begin() as c:
    c.execute(insert(runs).values(self._rv(result.run)))
    if result.scores:c.execute(insert(scores),[self._scorev(x) for x in result.scores])
    if result.candidates:c.execute(insert(candidates),[self._candidatev(x) for x in result.candidates])
    if result.contributions:c.execute(insert(contributions),[self._contributionv(x) for x in result.contributions])
    c.execute(insert(events).values(event_id=event.event_id,event_type=event.event_type,run_id=event.run_id,occurred_at=event.occurred_at,reasons=list(event.reasons)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def save_failed(self,run,event):
  try:
   with self.engine.begin() as c:c.execute(insert(runs).values(self._rv(run)));c.execute(insert(events).values(event_id=event.event_id,event_type=event.event_type,run_id=event.run_id,occurred_at=event.occurred_at,reasons=list(event.reasons)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_result(self,i):
  with self.engine.connect() as c:
   r=c.execute(select(runs).where(runs.c.run_id==i)).mappings().one_or_none()
   if r is None or r.status!=RunStatus.COMPLETED.value:return None
   ss=c.execute(select(scores).where(scores.c.run_id==i)).mappings().all();cs=c.execute(select(candidates).where(candidates.c.run_id==i)).mappings().all();xs=c.execute(select(contributions).where(contributions.c.run_id==i)).mappings().all()
  return StrategyResult(self._run(r),tuple(StrategyScore(x.run_id,x.instrument_id,Decimal(x.raw_score),x.rank,x.score_id) for x in ss),tuple(StrategyCandidate(x.run_id,x.instrument_id,CandidateAction(x.action),None if x.raw_score is None else Decimal(x.raw_score),x.rank,Decimal(x.proposed_weight),tuple(x.reason_codes),x.candidate_id) for x in cs),tuple(FeatureContribution(x.run_id,x.instrument_id,x.feature_name,Decimal(x.feature_value),Decimal(x.weight),Decimal(x.contribution),x.contribution_id) for x in xs))
 def save_evidence(self,x):
  with self.engine.begin() as c:c.execute(insert(evidence_table).values(**{k:getattr(x,k) for k in ("evidence_id","strategy_version_id","evidence_type","sample_start","sample_end","artifact_ref","parameters_hash")}))
 def evidence(self,i):
  with self.engine.connect() as c:rs=c.execute(select(evidence_table).where(evidence_table.c.strategy_version_id==i)).mappings().all()
  return tuple(ResearchEvidence(r.strategy_version_id,r.evidence_type,r.sample_start,r.sample_end,r.artifact_ref,r.parameters_hash,r.evidence_id) for r in rs)
 def latest_event(self):
  with self.engine.connect() as c:r=c.execute(select(events).order_by(events.c.occurred_at.desc())).mappings().first()
  return None if r is None else StrategyEvent(r.event_type,r.run_id,self._a(r.occurred_at),tuple(r.reasons),r.event_id)
 @staticmethod
 def _rv(x):return {"run_id":x.run_id,"kind":x.kind.value,"version_id":x.version_id,"decision_at":x.decision_at,"universe_snapshot_id":x.universe_snapshot_id,"feature_set_id":x.feature_set_id,"data_snapshot_id":x.data_snapshot_id,"parameter_hash":x.parameter_hash,"input_hash":x.input_hash,"result_hash":x.result_hash,"status":x.status.value,"cash_gate":x.cash_gate,"previous_run_id":x.previous_run_id,"supersedes_run_id":x.supersedes_run_id}
 @classmethod
 def _run(cls,r):return StrategyRun(StrategyKind(r.kind),r.version_id,cls._a(r.decision_at),r.universe_snapshot_id,r.feature_set_id,r.data_snapshot_id,r.parameter_hash,r.input_hash,r.result_hash,RunStatus(r.status),r.cash_gate,r.previous_run_id,r.supersedes_run_id,r.run_id)
 @staticmethod
 def _scorev(x):return {"score_id":x.score_id,"run_id":x.run_id,"instrument_id":x.instrument_id,"raw_score":x.raw_score,"rank":x.rank}
 @staticmethod
 def _candidatev(x):return {"candidate_id":x.candidate_id,"run_id":x.run_id,"instrument_id":x.instrument_id,"action":x.action.value,"raw_score":x.raw_score,"rank":x.rank,"proposed_weight":x.proposed_weight,"reason_codes":list(x.reason_codes)}
 @staticmethod
 def _contributionv(x):return {"contribution_id":x.contribution_id,"run_id":x.run_id,"instrument_id":x.instrument_id,"feature_name":x.feature_name,"feature_value":x.feature_value,"weight":x.weight,"contribution":x.contribution}
