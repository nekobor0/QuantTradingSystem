from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID,uuid4
from sqlalchemy import insert,select
from sqlalchemy.exc import IntegrityError
from quant_trading_system.strategies import StrategyKind
from .domain import *
from .errors import RepositoryConflict
from .tables import artifacts,attributions,definitions,events,inputs,metrics,quality,runs,summaries
class SqlAlchemyReportingRepository:
 def __init__(self,engine):self.engine=engine
 @staticmethod
 def _a(x):return x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x
 @classmethod
 def _j(cls,x):
  if isinstance(x,Decimal):return {"decimal":str(x)}
  if isinstance(x,datetime):return {"datetime":x.isoformat()}
  if isinstance(x,dict):return {str(k):cls._j(v) for k,v in x.items()}
  if isinstance(x,(tuple,list)):return [cls._j(v) for v in x]
  return x
 @classmethod
 def _u(cls,x):
  if isinstance(x,dict) and set(x)=={"decimal"}:return Decimal(x["decimal"])
  if isinstance(x,dict) and set(x)=={"datetime"}:return datetime.fromisoformat(x["datetime"])
  if isinstance(x,dict):return {k:cls._u(v) for k,v in x.items()}
  if isinstance(x,list):return tuple(cls._u(v) for v in x)
  return x
 def save_definition(self,x):
  with self.engine.begin() as c:
   if c.execute(select(definitions.c.definition_id).where(definitions.c.definition_id==x.definition_id)).scalar_one_or_none() is None:c.execute(insert(definitions).values(**self._dv(x)))
 def find_run(self,h):
  with self.engine.connect() as c:r=c.execute(select(runs).where(runs.c.input_hash==h)).mappings().one_or_none()
  return None if r is None else self._run(r)
 def save_result(self,x,event):
  try:
   with self.engine.begin() as c:
    c.execute(insert(runs).values(**self._rv(x.run)))
    c.execute(insert(inputs),[self._iv(x.run.run_id,pos,v) for pos,v in enumerate(x.inputs)])
    c.execute(insert(metrics),[self._mv(v) for v in x.metrics]);c.execute(insert(attributions),[self._av(v) for v in x.attributions]);c.execute(insert(summaries),[self._sv(v) for v in x.strategy_summaries]);c.execute(insert(artifacts),[self._artv(v) for v in x.artifacts]);c.execute(insert(quality),[self._qv(v) for v in x.quality]);c.execute(insert(events).values(event_id=event.event_id,event_type=event.event_type,run_id=event.run_id,occurred_at=event.occurred_at,payload=dict(event.payload)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_result(self,i):
  with self.engine.connect() as c:
   r=c.execute(select(runs).where(runs.c.run_id==i)).mappings().one_or_none()
   if r is None:return None
   iv=c.execute(select(inputs).where(inputs.c.run_id==i).order_by(inputs.c.position)).mappings().all();mv=c.execute(select(metrics).where(metrics.c.run_id==i)).mappings().all();av=c.execute(select(attributions).where(attributions.c.run_id==i)).mappings().all();sv=c.execute(select(summaries).where(summaries.c.run_id==i)).mappings().all();artv=c.execute(select(artifacts).where(artifacts.c.run_id==i)).mappings().all();qv=c.execute(select(quality).where(quality.c.run_id==i)).mappings().all()
  return ReportResult(self._run(r),tuple(self._input(x) for x in iv),tuple(self._metric(x) for x in mv),tuple(self._attr(x) for x in av),tuple(self._summary(x) for x in sv),tuple(self._artifact(x) for x in artv),tuple(self._quality(x) for x in qv))
 @staticmethod
 def _dv(x):return {"definition_id":x.definition_id,"name":x.name,"mode":x.mode.value,"audience":x.audience,"metric_version":x.metric_version,"template_version":x.template_version,"code_version":x.code_version,"required_source_types":list(x.required_source_types),"benchmark":x.benchmark,"risk_free_rate":x.risk_free_rate,"annualization_days":x.annualization_days,"base_currency":x.base_currency,"sensitivity":x.sensitivity.value,"required_template_fields":list(x.required_template_fields)}
 @staticmethod
 def _rv(x):return {"run_id":x.run_id,"definition_id":x.definition_id,"period_start":x.period.start,"period_end":x.period.end,"input_hash":x.input_hash,"content_hash":x.content_hash,"status":x.status.value,"mode":x.mode.value,"template_version":x.template_version,"code_version":x.code_version,"benchmark":x.benchmark,"risk_free_rate":x.risk_free_rate,"annualization_days":x.annualization_days,"fx_snapshot_id":x.fx_snapshot_id,"generated_at":x.generated_at}
 @classmethod
 def _run(cls,r):return ReportRun(r.definition_id,ReportPeriod(r.period_start,r.period_end),r.input_hash,r.content_hash,ReportRunStatus(r.status),ReportMode(r.mode),r.template_version,r.code_version,r.benchmark,Decimal(r.risk_free_rate),r.annualization_days,r.fx_snapshot_id,cls._a(r.generated_at),r.run_id)
 @classmethod
 def _iv(cls,run_id,pos,x):return {"binding_id":uuid4(),"run_id":run_id,"position":pos,"source_type":x.source_type,"source_id":x.source_id,"as_of":x.as_of,"content_hash":x.content_hash,"quality":x.quality.value,"source_mode":x.source_mode.value,"reference":x.reference,"facts":cls._j(dict(x.facts)),"reconciled":x.reconciled}
 @classmethod
 def _input(cls,r):return ReportInputSnapshot(r.source_type,r.source_id,cls._a(r.as_of),r.content_hash,InputQuality(r.quality),ReportMode(r.source_mode),r.reference,cls._u(r.facts),r.reconciled)
 @staticmethod
 def _mv(x):return {"metric_id":x.metric_id,"run_id":x.run_id,"name":x.name,"value":x.value,"unit":x.unit,"definition":x.definition,"formula":x.formula,"source_snapshot_ids":[str(v) for v in x.source_snapshot_ids],"source_references":list(x.source_references),"drilldown_reference":x.drilldown_reference}
 @staticmethod
 def _metric(r):return ReportMetric(r.run_id,r.name,Decimal(r.value),r.unit,r.definition,r.formula,tuple(UUID(v) for v in r.source_snapshot_ids),tuple(r.source_references),r.drilldown_reference,r.metric_id)
 @staticmethod
 def _av(x):return {"attribution_id":x.attribution_id,"run_id":x.run_id,"component":x.component,"dimension":x.dimension.value,"value":x.value,"source_run_id":x.source_run_id,"source_reference":x.source_reference,"instrument_id":x.instrument_id}
 @staticmethod
 def _attr(r):return SleeveAttribution(r.run_id,r.component,AttributionDimension(r.dimension),Decimal(r.value),r.source_run_id,r.source_reference,r.instrument_id,r.attribution_id)
 @staticmethod
 def _sv(x):return {"summary_id":x.summary_id,"run_id":x.run_id,"kind":x.kind.value,"strategy_run_id":x.strategy_run_id,"select_count":x.select_count,"keep_count":x.keep_count,"exit_count":x.exit_count,"candidate_stability":x.candidate_stability,"turnover":x.turnover,"daily_gate":x.daily_gate,"rebalance_days":[str(v) for v in x.rebalance_days],"cash_state":x.cash_state}
 @staticmethod
 def _summary(r):return ReportStrategySummary(r.run_id,StrategyKind(r.kind),r.strategy_run_id,r.select_count,r.keep_count,r.exit_count,Decimal(r.candidate_stability),Decimal(r.turnover),r.daily_gate,tuple(__import__("datetime").date.fromisoformat(v) for v in r.rebalance_days),r.cash_state,r.summary_id)
 @staticmethod
 def _artv(x):return {"artifact_id":x.artifact_id,"run_id":x.run_id,"format":x.format.value,"reference":x.reference,"content":x.content,"content_hash":x.content_hash,"generated_at":x.generated_at,"sensitivity":x.sensitivity.value,"publishable":x.publishable}
 @classmethod
 def _artifact(cls,r):return ReportArtifact(r.run_id,ArtifactFormat(r.format),r.reference,r.content,r.content_hash,cls._a(r.generated_at),SensitivityLevel(r.sensitivity),r.publishable,r.artifact_id)
 @staticmethod
 def _qv(x):return {"quality_id":x.quality_id,"run_id":x.run_id,"check_name":x.check_name,"outcome":x.outcome.value,"observed":x.observed,"expected":x.expected,"explanation":x.explanation}
 @staticmethod
 def _quality(r):return ReportQualityResult(r.run_id,r.check_name,QualityOutcome(r.outcome),r.observed,r.expected,r.explanation,r.quality_id)
