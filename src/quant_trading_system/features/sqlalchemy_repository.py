from datetime import timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import delete,insert,select
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import RepositoryConflict
from .tables import bindings,definitions,events,feature_values_table,sets,versions
class SqlAlchemyFeatureRepository:
 def __init__(self,engine):self.engine=engine
 @staticmethod
 def _a(x):return x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x
 def save_definition(self,d,vs):
  try:
   with self.engine.begin() as c:
    c.execute(insert(definitions).values(definition_id=d.definition_id,name=d.name,purpose=d.purpose.value,formula=d.formula.value,economic_meaning=d.economic_meaning,direction=d.direction,frequency=d.frequency,owner=d.owner))
    c.execute(insert(versions),[{"version_id":x.version_id,"definition_id":x.definition_id,"version":x.version,"code_version":x.code_version,"parameters":dict(x.parameters),"dependency_versions":dict(x.dependency_versions),"min_history":x.min_history,"missing_policy":x.missing_policy.value,"transform":x.transform.value,"active":x.active} for x in vs])
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_definition(self,i):
  with self.engine.connect() as c:r=c.execute(select(definitions).where(definitions.c.definition_id==i)).mappings().one_or_none()
  return None if r is None else FeatureDefinition(r.name,FeaturePurpose(r.purpose),FormulaKind(r.formula),r.economic_meaning,r.direction,r.frequency,r.owner,r.definition_id)
 def get_version(self,i):
  with self.engine.connect() as c:r=c.execute(select(versions).where(versions.c.version_id==i)).mappings().one_or_none()
  return None if r is None else FeatureVersion(r.definition_id,r.version,r.code_version,r.parameters,r.dependency_versions,r.min_history,MissingPolicy(r.missing_policy),TransformKind(r.transform),r.active,r.version_id)
 def bind(self,purpose,version_ids):
  with self.engine.begin() as c:c.execute(delete(bindings).where(bindings.c.purpose==purpose.value));c.execute(insert(bindings).values(purpose=purpose.value,version_ids=[str(x) for x in version_ids]))
 def binding(self,purpose):
  with self.engine.connect() as c:r=c.execute(select(bindings.c.version_ids).where(bindings.c.purpose==purpose.value)).scalar_one_or_none()
  return () if r is None else tuple(UUID(x) for x in r)
 def find_set(self,h):
  with self.engine.connect() as c:r=c.execute(select(sets).where(sets.c.input_hash==h)).mappings().one_or_none()
  return None if r is None else self._set(r)
 def save_set(self,s,rows,event):
  try:
   with self.engine.begin() as c:
    c.execute(insert(sets).values(**self._sv(s)));c.execute(insert(feature_values_table),[self._vv(x) for x in rows]);c.execute(insert(events).values(event_id=event.event_id,event_type=event.event_type,feature_set_id=event.feature_set_id,occurred_at=event.occurred_at,reasons=list(event.reasons)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def save_rejected_event(self,event):
  with self.engine.begin() as c:c.execute(insert(events).values(event_id=event.event_id,event_type=event.event_type,feature_set_id=event.feature_set_id,occurred_at=event.occurred_at,reasons=list(event.reasons)))
 def latest_event(self):
  with self.engine.connect() as c:r=c.execute(select(events).order_by(events.c.occurred_at.desc())).mappings().first()
  return None if r is None else FeatureEvent(r.event_type,r.feature_set_id,self._a(r.occurred_at),tuple(r.reasons),r.event_id)
 def get_set(self,i):
  with self.engine.connect() as c:r=c.execute(select(sets).where(sets.c.feature_set_id==i)).mappings().one_or_none()
  return None if r is None else self._set(r)
 def values(self,i):
  with self.engine.connect() as c:rs=c.execute(select(feature_values_table).where(feature_values_table.c.feature_set_id==i)).mappings().all()
  return tuple(FeatureValue(r.feature_set_id,r.instrument_id,r.as_of_date,r.version_id,r.data_snapshot_id,None if r.value is None else Decimal(r.value),QualityFlag(r.quality),tuple(r.input_refs),tuple(r.steps),r.value_id) for r in rs)
 @staticmethod
 def _sv(x):return {"feature_set_id":x.feature_set_id,"purpose":x.purpose.value,"as_of_date":x.as_of_date,"decision_at":x.decision_at,"universe_snapshot_id":x.universe_snapshot_id,"data_snapshot_id":x.data_snapshot_id,"version_ids":[str(i) for i in x.version_ids],"member_ids":[str(i) for i in x.member_ids],"input_hash":x.input_hash,"content_hash":x.content_hash,"factor_version":x.factor_version}
 @staticmethod
 def _vv(x):return {"value_id":x.value_id,"feature_set_id":x.feature_set_id,"instrument_id":x.instrument_id,"as_of_date":x.as_of_date,"version_id":x.version_id,"data_snapshot_id":x.data_snapshot_id,"value":x.value,"quality":x.quality.value,"input_refs":list(x.input_refs),"steps":list(x.steps)}
 @classmethod
 def _set(cls,r):return FeatureSet(FeaturePurpose(r.purpose),r.as_of_date,cls._a(r.decision_at),r.universe_snapshot_id,r.data_snapshot_id,tuple(UUID(x) for x in r.version_ids),tuple(UUID(x) for x in r.member_ids),r.input_hash,r.content_hash,r.factor_version,r.feature_set_id)
