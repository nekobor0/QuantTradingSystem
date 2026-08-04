from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import insert,select,update
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import RepositoryConflict
from .tables import alerts,events,exceptions,policies,policy_bindings,results,rule_versions,rules,runs

class SqlAlchemyRiskRepository:
 def __init__(self,engine):self.engine=engine
 @staticmethod
 def _a(x):return x.replace(tzinfo=timezone.utc) if x is not None and x.tzinfo is None else x
 @classmethod
 def _j(cls,x):
  if isinstance(x,Decimal):return {"decimal":str(x)}
  if isinstance(x,datetime):return {"datetime":x.isoformat()}
  if isinstance(x,(tuple,list,set,frozenset)):return {"list":[cls._j(v) for v in x]}
  if isinstance(x,(str,int,float,bool)) or x is None:return x
  return {"string":str(x)}
 @classmethod
 def _u(cls,x):
  if isinstance(x,dict) and "decimal" in x:return Decimal(x["decimal"])
  if isinstance(x,dict) and "datetime" in x:return datetime.fromisoformat(x["datetime"])
  if isinstance(x,dict) and "list" in x:return tuple(cls._u(v) for v in x["list"])
  if isinstance(x,dict) and "string" in x:return x["string"]
  return x
 def save_rule(self,x):
  with self.engine.begin() as c:
   if c.execute(select(rules.c.rule_id).where(rules.c.rule_id==x.rule_id)).scalar_one_or_none() is None:c.execute(insert(rules).values(rule_id=x.rule_id,code=x.code,name=x.name,owner=x.owner,description=x.description))
 def save_rule_version(self,x):
  with self.engine.begin() as c:
   if c.execute(select(rule_versions.c.version_id).where(rule_versions.c.version_id==x.version_id)).scalar_one_or_none() is None:c.execute(insert(rule_versions).values(**self._vv(x)))
 def get_rule_version(self,i):
  with self.engine.connect() as c:r=c.execute(select(rule_versions).where(rule_versions.c.version_id==i)).mappings().one_or_none()
  return None if r is None else self._version(r)
 def save_policy(self,x):
  try:
   with self.engine.begin() as c:
    c.execute(insert(policies).values(policy_version_id=x.policy_version_id,policy_id=x.policy_id,name=x.name,version=x.version,account_id=x.account_id,market=x.market,required_scopes=[v.value for v in x.required_scopes],effective_from=x.effective_from,effective_to=x.effective_to,owner=x.owner,max_input_age_seconds=x.max_input_age_seconds))
    c.execute(insert(policy_bindings),[{"policy_version_id":x.policy_version_id,"rule_version_id":v,"position":position} for position,v in enumerate(x.rule_version_ids)])
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_policy(self,i):
  with self.engine.connect() as c:
   r=c.execute(select(policies).where(policies.c.policy_version_id==i)).mappings().one_or_none()
   if r is None:return None
   ids=c.execute(select(policy_bindings.c.rule_version_id).where(policy_bindings.c.policy_version_id==i).order_by(policy_bindings.c.position)).scalars().all()
  return RiskPolicyVersion(r.name,r.version,r.account_id,r.market,tuple(ids),tuple(RiskScope(v) for v in r.required_scopes),r.effective_from,r.effective_to,r.owner,r.max_input_age_seconds,r.policy_id,r.policy_version_id)
 def find_run(self,h):
  with self.engine.connect() as c:r=c.execute(select(runs).where(runs.c.input_hash==h)).mappings().one_or_none()
  return None if r is None else self._run(r)
 def save_run_result(self,v,new_alerts,event):
  try:
   with self.engine.begin() as c:
    c.execute(insert(runs).values(**self._runv(v.run)))
    if v.results:c.execute(insert(results),[self._resultv(x) for x in v.results])
    if new_alerts:c.execute(insert(alerts),[self._alertv(x) for x in new_alerts])
    c.execute(insert(events).values(**self._eventv(event)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_run_result(self,i):
  with self.engine.connect() as c:
   r=c.execute(select(runs).where(runs.c.run_id==i)).mappings().one_or_none()
   if r is None:return None
   rr=c.execute(select(results).where(results.c.run_id==i)).mappings().all()
  run=self._run(r);values=tuple(self._result(x) for x in rr);return RiskRunResult(run,values,run.decision)
 def get_result(self,i):
  with self.engine.connect() as c:r=c.execute(select(results).where(results.c.result_id==i)).mappings().one_or_none()
  return None if r is None else self._result(r)
 def save_exception(self,x,event):
  with self.engine.begin() as c:
   exists=c.execute(select(exceptions.c.exception_id).where(exceptions.c.exception_id==x.exception_id)).scalar_one_or_none()
   if exists is None:c.execute(insert(exceptions).values(**self._exceptionv(x)))
   else:c.execute(update(exceptions).where(exceptions.c.exception_id==x.exception_id).values(**self._exceptionv(x)))
   c.execute(insert(events).values(**self._eventv(event)))
 def get_exception(self,i):
  with self.engine.connect() as c:r=c.execute(select(exceptions).where(exceptions.c.exception_id==i)).mappings().one_or_none()
  return None if r is None else self._exception(r)
 def exceptions_for(self,i):
  with self.engine.connect() as c:rows=c.execute(select(exceptions).where(exceptions.c.result_id==i)).mappings().all()
  return tuple(self._exception(x) for x in rows)
 def get_alert(self,i):
  with self.engine.connect() as c:r=c.execute(select(alerts).where(alerts.c.alert_id==i)).mappings().one_or_none()
  return None if r is None else self._alert(r)
 def find_alert(self,k):
  with self.engine.connect() as c:r=c.execute(select(alerts).where(alerts.c.dedupe_key==k)).mappings().one_or_none()
  return None if r is None else self._alert(r)
 def update_alert(self,x,event):
  with self.engine.begin() as c:
   changed=c.execute(update(alerts).where(alerts.c.alert_id==x.alert_id,alerts.c.version==x.version-1).values(**self._alertv(x)))
   if changed.rowcount!=1:raise RepositoryConflict("alert version conflict")
   c.execute(insert(events).values(**self._eventv(event)))
 def alerts_for_account(self,i):
  with self.engine.connect() as c:rows=c.execute(select(alerts).where(alerts.c.account_id==i)).mappings().all()
  return tuple(self._alert(x) for x in rows)
 def runs_for_account(self,i):
  with self.engine.connect() as c:rows=c.execute(select(runs).where(runs.c.account_id==i)).mappings().all()
  return tuple(self._run(x) for x in rows)
 def runs_for_target(self,i):
  with self.engine.connect() as c:ids=c.execute(select(runs.c.run_id).where(runs.c.object_id==i)).scalars().all()
  return tuple(x for run_id in ids if (x:=self.get_run_result(run_id)) is not None)
 @classmethod
 def _vv(cls,x):return {"version_id":x.version_id,"rule_id":x.rule_id,"version":x.version,"stage":x.stage.value,"scope":x.scope.value,"metric":x.metric,"operator":x.operator.value,"threshold":cls._j(x.threshold),"severity":x.severity.value,"effective_from":x.effective_from,"effective_to":x.effective_to,"owner":x.owner,"exception_allowed":x.exception_allowed,"evaluator_key":x.evaluator_key}
 @classmethod
 def _version(cls,r):return RiskRuleVersion(r.rule_id,r.version,RiskStage(r.stage),RiskScope(r.scope),r.metric,ComparisonOperator(r.operator),cls._u(r.threshold),RiskSeverity(r.severity),r.effective_from,r.effective_to,r.owner,r.exception_allowed,r.evaluator_key,r.version_id)
 @staticmethod
 def _runv(x):return {"run_id":x.run_id,"account_id":x.account_id,"object_id":x.object_id,"policy_version_id":x.policy_version_id,"stage":x.stage.value,"decision_at":x.decision_at,"input_hash":x.input_hash,"status":x.status.value,"decision":x.decision.value,"started_at":x.started_at,"completed_at":x.completed_at,"error":x.error}
 @classmethod
 def _run(cls,r):return RiskCheckRun(r.account_id,r.object_id,r.policy_version_id,RiskStage(r.stage),cls._a(r.decision_at),r.input_hash,RiskRunStatus(r.status),RiskDecision(r.decision),cls._a(r.started_at),cls._a(r.completed_at),r.error,r.run_id)
 @classmethod
 def _resultv(cls,x):return {"result_id":x.result_id,"run_id":x.run_id,"rule_version_id":x.rule_version_id,"object_id":x.object_id,"scope":x.scope.value,"metric":x.metric,"observed":cls._j(x.observed),"threshold":cls._j(x.threshold),"operator":x.operator.value,"severity":x.severity.value,"outcome":x.outcome.value,"explanation":x.explanation,"evaluated_at":x.evaluated_at}
 @classmethod
 def _result(cls,r):return RiskCheckResult(r.run_id,r.rule_version_id,r.object_id,RiskScope(r.scope),r.metric,cls._u(r.observed),cls._u(r.threshold),ComparisonOperator(r.operator),RiskSeverity(r.severity),RuleOutcome(r.outcome),r.explanation,cls._a(r.evaluated_at),r.result_id)
 @staticmethod
 def _exceptionv(x):return {n:(getattr(x,n).value if n in ("scope","status") else getattr(x,n)) for n in ("exception_id","result_id","rule_version_id","scope","requested_by","approved_by","reason","approved_at","expires_at","status","version")}
 @classmethod
 def _exception(cls,r):return RiskException(r.result_id,r.rule_version_id,RiskScope(r.scope),r.requested_by,r.approved_by,r.reason,cls._a(r.approved_at),cls._a(r.expires_at),ExceptionStatus(r.status),r.version,r.exception_id)
 @staticmethod
 def _alertv(x):return {n:(getattr(x,n).value if n in ("scope","status") else getattr(x,n)) for n in ("alert_id","account_id","object_id","result_id","rule_version_id","scope","observation_window","dedupe_key","status","opened_at","version","acknowledged_by","acknowledged_at","escalated_to","resolved_at","resolution_evidence")}
 @classmethod
 def _alert(cls,r):return RiskAlert(r.account_id,r.object_id,r.result_id,r.rule_version_id,RiskScope(r.scope),r.observation_window,r.dedupe_key,AlertStatus(r.status),cls._a(r.opened_at),r.version,r.acknowledged_by,cls._a(r.acknowledged_at),r.escalated_to,cls._a(r.resolved_at),r.resolution_evidence,r.alert_id)
 @staticmethod
 def _eventv(x):return {"event_id":x.event_id,"event_type":x.event_type,"account_id":x.account_id,"object_id":x.object_id,"occurred_at":x.occurred_at,"payload":dict(x.payload)}
