from datetime import timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import insert,select,update
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import RepositoryConflict
from .tables import batches_table,classifications,definitions,events,memberships,quality,snapshots
class SqlAlchemyUniverseRepository:
 def __init__(self,engine):self.engine=engine
 @staticmethod
 def _a(x):return x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x
 def save_definition(self,x):
  try:
   with self.engine.begin() as c:c.execute(insert(definitions).values(universe_id=x.universe_id,name=x.name,kind=x.kind.value,source=x.source,version=x.version,rule_description=x.rule_description,max_change_ratio=x.max_change_ratio,max_staleness_days=x.max_staleness_days))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_definition(self,i):
  with self.engine.connect() as c:r=c.execute(select(definitions).where(definitions.c.universe_id==i)).mappings().one_or_none()
  return None if r is None else self._definition(r)
 def list_definitions(self):
  with self.engine.connect() as c:rs=c.execute(select(definitions)).mappings().all()
  return tuple(self._definition(r) for r in rs)
 @staticmethod
 def _definition(r):return UniverseDefinition(r.name,StrategyUniverseKind(r.kind),r.source,r.version,r.rule_description,Decimal(r.max_change_ratio),r.max_staleness_days,r.universe_id)
 def get_batch(self,i,s):
  with self.engine.connect() as c:r=c.execute(select(batches_table).where(batches_table.c.universe_id==i,batches_table.c.source_batch_id==s)).mappings().one_or_none()
  return None if r is None else self._batch(r)
 def batches(self,i):
  with self.engine.connect() as c:rs=c.execute(select(batches_table).where(batches_table.c.universe_id==i)).mappings().all()
  return tuple(self._batch(r) for r in rs)
 @classmethod
 def _batch(cls,r):return MembershipBatch(r.universe_id,r.source_batch_id,r.effective_date,cls._a(r.announced_at),cls._a(r.available_at),r.payload_hash,BatchStatus(r.status),r.member_count,r.batch_id)
 @staticmethod
 def _bv(x):return {k:(getattr(x,k).value if k=="status" else getattr(x,k)) for k in ("batch_id","universe_id","source_batch_id","effective_date","announced_at","available_at","payload_hash","status","member_count")}
 def active_periods_before(self,i,d):return tuple(x for x in self.periods(i) if x.active(d))
 def periods(self,i):
  with self.engine.connect() as c:rs=c.execute(select(memberships).where(memberships.c.universe_id==i)).mappings().all()
  return tuple(self._period(r) for r in rs)
 @classmethod
 def _period(cls,r):return MembershipPeriod(r.universe_id,r.instrument_id,r.valid_from,r.valid_to,cls._a(r.announced_at),cls._a(r.available_at),r.source_batch_id,r.membership_id)
 @staticmethod
 def _pv(x):return {k:getattr(x,k) for k in ("membership_id","universe_id","instrument_id","valid_from","valid_to","announced_at","available_at","source_batch_id")}
 def apply_batch(self,batch,closed,opened,event):
  try:
   with self.engine.begin() as c:
    c.execute(insert(batches_table).values(self._bv(batch)))
    for x in closed:c.execute(update(memberships).where(memberships.c.membership_id==x.membership_id,memberships.c.valid_to.is_(None)).values(valid_to=x.valid_to))
    if opened:c.execute(insert(memberships),[self._pv(x) for x in opened])
    c.execute(insert(events).values(event_id=event.event_id,universe_id=event.universe_id,batch_id=event.batch_id,joined=[str(x) for x in event.joined],removed=[str(x) for x in event.removed],effective_date=event.effective_date,occurred_at=event.occurred_at))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def reject_batch(self,batch,results):
  try:
   with self.engine.begin() as c:
    c.execute(insert(batches_table).values(self._bv(batch)));c.execute(insert(quality),[{"result_id":x.result_id,"batch_id":batch.batch_id,"code":x.code,"message":x.message,"source_code":x.source_code} for x in results])
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def quality_results(self,i):
  with self.engine.connect() as c:rs=c.execute(select(quality).where(quality.c.batch_id==i)).mappings().all()
  return tuple(UniverseQualityResult(r.code,r.message,r.source_code,r.result_id) for r in rs)
 def save_snapshot(self,x):
  with self.engine.begin() as c:c.execute(insert(snapshots).values(snapshot_id=x.snapshot_id,universe_id=x.universe_id,decision_at=x.decision_at,data_snapshot_id=x.data_snapshot_id,member_ids=[str(i) for i in x.member_ids],member_hash=x.member_hash,source_batch_ids=list(x.source_batch_ids)))
 def get_snapshot(self,i):
  with self.engine.connect() as c:r=c.execute(select(snapshots).where(snapshots.c.snapshot_id==i)).mappings().one_or_none()
  return None if r is None else UniverseSnapshot(r.universe_id,self._a(r.decision_at),r.data_snapshot_id,tuple(UUID(x) for x in r.member_ids),r.member_hash,tuple(r.source_batch_ids),r.snapshot_id)
 def save_classification(self,x):
  with self.engine.begin() as c:c.execute(insert(classifications).values(**{k:getattr(x,k) for k in ("classification_id","instrument_id","provider","system","version","level","code","name","valid_from","valid_to","available_at")}))
 def classifications(self,i):
  with self.engine.connect() as c:rs=c.execute(select(classifications).where(classifications.c.instrument_id==i)).mappings().all()
  return tuple(ClassificationMembership(r.instrument_id,r.provider,r.system,r.version,r.level,r.code,r.name,r.valid_from,r.valid_to,self._a(r.available_at),r.classification_id) for r in rs)
