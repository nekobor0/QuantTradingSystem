from dataclasses import replace
from datetime import timezone
from decimal import Decimal
from sqlalchemy import insert,select
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import RepositoryConflict
from .tables import events, facts, filings, metric_definitions, quality, share_capital_changes, source_mappings
class SqlAlchemyFundamentalRepository:
 def __init__(self,engine): self.engine=engine
 def save_definition(self,m,ms):
  try:
   with self.engine.begin() as c:
    c.execute(insert(metric_definitions).values(metric_id=m.metric_id,canonical_name=m.canonical_name,unit=m.unit,value_kind=m.value_kind.value,is_flow=m.is_flow))
    c.execute(insert(source_mappings),[{"mapping_id":x.mapping_id,"source":x.source,"source_field":x.source_field,"metric_id":x.metric_id,"source_unit":x.source_unit,"scale":x.scale} for x in ms])
  except IntegrityError as e: raise RepositoryConflict(str(e.orig)) from e
 def get_mapping(self,s,f):
  with self.engine.connect() as c:r=c.execute(select(source_mappings).where(source_mappings.c.source==s.strip().lower(),source_mappings.c.source_field==f)).mappings().one_or_none()
  return None if r is None else SourceMapping(r.source,r.source_field,r.metric_id,r.source_unit,Decimal(r.scale),r.mapping_id)
 def get_metric(self,i):
  with self.engine.connect() as c:r=c.execute(select(metric_definitions).where(metric_definitions.c.metric_id==i)).mappings().one_or_none()
  return None if r is None else MetricDefinition(r.canonical_name,r.unit,ValueKind(r.value_kind),r.is_flow,r.metric_id)
 def find_filing(self,s,i,v):
  with self.engine.connect() as c:r=c.execute(select(filings).where(filings.c.source==s.strip().lower(),filings.c.source_filing_id==i,filings.c.revision==v)).mappings().one_or_none()
  return None if r is None else self._filing(r)
 def filing_revisions(self,s,i):
  with self.engine.connect() as c:rs=c.execute(select(filings).where(filings.c.source==s.strip().lower(),filings.c.source_filing_id==i)).mappings().all()
  return tuple(self._filing(r) for r in rs)
 def save_rejected(self,f,identity,results):
  try:
   with self.engine.begin() as c:
    if f:c.execute(insert(filings).values(self._fv(replace(f,status=FilingStatus.REJECTED))))
    c.execute(insert(quality),[{"result_id":x.result_id,"source":identity[0],"source_filing_id":identity[1],"revision":identity[2],"code":x.code,"message":x.message,"field":x.field} for x in results])
  except IntegrityError as e: raise RepositoryConflict(str(e.orig)) from e
 def publish(self,f,fs,e):
  try:
   with self.engine.begin() as c:
    c.execute(insert(filings).values(self._fv(replace(f,status=FilingStatus.PUBLISHED))))
    c.execute(insert(facts),[self._factv(x) for x in fs]); c.execute(insert(events).values(event_id=e.event_id,filing_id=e.filing_id,instrument_id=e.instrument_id,old_revision=e.old_revision,new_revision=e.new_revision,affected=[[d.isoformat(),str(m)] for d,m in e.affected],occurred_at=e.occurred_at))
  except IntegrityError as x: raise RepositoryConflict(str(x.orig)) from x
 def published_facts(self):
  with self.engine.connect() as c:rs=c.execute(select(facts,filings).join(filings,facts.c.filing_id==filings.c.filing_id).where(filings.c.status=="PUBLISHED")).mappings().all()
  return tuple((self._fact(r),self._filing(r)) for r in rs)
 def quality_results(self,i):
  with self.engine.connect() as c:rs=c.execute(select(quality).where(quality.c.source==i[0],quality.c.source_filing_id==i[1],quality.c.revision==i[2])).mappings().all()
  return tuple(QualityResult(r.code,r.message,r.field,r.result_id) for r in rs)
 def latest_event(self):
  with self.engine.connect() as c:r=c.execute(select(events).order_by(events.c.occurred_at.desc())).mappings().first()
  if r is None:return None
  return FundamentalRevisionEvent(r.filing_id,r.instrument_id,r.old_revision,r.new_revision,tuple((date.fromisoformat(x[0]),UUID(x[1])) for x in r.affected),self._a(r.occurred_at),r.event_id)
 def save_share_change(self,x):
  try:
   with self.engine.begin() as c:c.execute(insert(share_capital_changes).values(change_id=x.change_id,instrument_id=x.instrument_id,effective_date=x.effective_date,total_shares=x.total_shares,float_shares=x.float_shares,source=x.source,announced_at=x.announced_at,available_at=x.available_at))
  except IntegrityError as e: raise RepositoryConflict(str(e.orig)) from e
 def share_changes(self,instrument_id):
  with self.engine.connect() as c:rs=c.execute(select(share_capital_changes).where(share_capital_changes.c.instrument_id==instrument_id)).mappings().all()
  return tuple(ShareCapitalChange(r.instrument_id,r.effective_date,Decimal(r.total_shares),Decimal(r.float_shares),r.source,self._a(r.announced_at),self._a(r.available_at),r.change_id) for r in rs)
 @staticmethod
 def _a(x): return x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x
 @classmethod
 def _filing(cls,r): return Filing(r.instrument_id,r.source,r.source_filing_id,r.revision,r.report_type,r.period_end,cls._a(r.announced_at),cls._a(r.available_at),cls._a(r.ingested_at),r.raw_uri,r.payload_hash,FilingStatus(r.status),r.filing_id)
 @staticmethod
 def _fv(x): return {k:(getattr(x,k).value if k=="status" else getattr(x,k)) for k in ("filing_id","instrument_id","source","source_filing_id","revision","report_type","period_end","announced_at","available_at","ingested_at","raw_uri","payload_hash","status")}
 @staticmethod
 def _factv(x): return {k:(getattr(x,k).value if k=="period_type" else [str(v) for v in x.lineage] if k=="lineage" else getattr(x,k)) for k in ("fact_id","filing_id","instrument_id","metric_id","period_end","period_type","source","revision","value","unit","currency","raw_value","lineage")}
 @staticmethod
 def _fact(r): return FundamentalFact(r.filing_id,r.instrument_id,r.metric_id,r.period_end,PeriodType(r.period_type),r.source,r.revision,None if r.value is None else Decimal(r.value),r.unit,r.currency,r.raw_value,tuple(UUID(x) for x in r.lineage),r.fact_id)
