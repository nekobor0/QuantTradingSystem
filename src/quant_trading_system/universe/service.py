from __future__ import annotations
import hashlib,json
from dataclasses import replace
from datetime import date,datetime,timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo
from quant_trading_system.instruments import AssetType,InstrumentService
from .domain import *
from .errors import *
from .ports import UniverseRepository

class UniverseService:
 def __init__(self,repository:UniverseRepository,instruments:InstrumentService):self.repository=repository;self.instruments=instruments
 def create_definition(self,value:UniverseDefinition)->None:self.repository.save_definition(value)
 def apply_membership_batch(self,command:ApplyMembershipBatch)->MembershipBatch:
  definition=self.repository.get_definition(command.universe_id)
  if definition is None:raise UniverseNotFound(str(command.universe_id))
  payload_hash=hashlib.sha256(json.dumps({"effective":command.effective_date.isoformat(),"announced":str(command.announced_at),"available":str(command.available_at),"codes":sorted(command.source_codes)},sort_keys=True).encode()).hexdigest()
  existing=self.repository.get_batch(command.universe_id,command.source_batch_id)
  if existing:
   if existing.payload_hash!=payload_hash:raise BatchConflict("idempotency key has different content")
   return existing
  batch=MembershipBatch(command.universe_id,command.source_batch_id,command.effective_date,command.announced_at,command.available_at,payload_hash,BatchStatus.PUBLISHED,len(command.source_codes))
  failures=[];resolved={}
  if not command.source_codes:failures.append(UniverseQualityResult("EMPTY_UNIVERSE","empty full list is rejected"))
  for code in command.source_codes:
   try:
    instrument=self.instruments.resolve(definition.source,code,command.effective_date).instrument
    if instrument.instrument_id in resolved:raise InvalidUniverse("duplicate canonical member")
    allowed=self._allowed(definition.kind,instrument.asset_type)
    if not allowed:raise InvalidUniverse(f"asset type {instrument.asset_type} is invalid for {definition.kind}")
    resolved[instrument.instrument_id]=instrument
   except Exception as exc:failures.append(UniverseQualityResult("UNRESOLVED_MEMBER",str(exc),code))
  current={x.instrument_id:x for x in self.repository.active_periods_before(command.universe_id,command.effective_date)}
  if current:
   changed=len(set(current)^set(resolved));ratio=Decimal(changed)/Decimal(len(current))
   if ratio>definition.max_change_ratio:failures.append(UniverseQualityResult("ABNORMAL_CHANGE",f"change ratio {ratio}"))
  same_day=[x for x in self.repository.batches(command.universe_id) if x.effective_date==command.effective_date and x.status is BatchStatus.PUBLISHED]
  if same_day:failures.append(UniverseQualityResult("EFFECTIVE_DATE_CONFLICT","another revision is already published"))
  if failures:
   rejected=replace(batch,status=BatchStatus.REJECTED);self.repository.reject_batch(rejected,failures);raise BatchRejected(",".join(x.code for x in failures))
  removed=set(current)-set(resolved);joined=set(resolved)-set(current)
  closed=tuple(replace(current[i],valid_to=command.effective_date) for i in removed)
  opened=tuple(MembershipPeriod(command.universe_id,i,command.effective_date,None,command.announced_at,command.available_at,command.source_batch_id) for i in joined)
  event=UniverseMembershipChanged(command.universe_id,batch.batch_id,tuple(sorted(joined,key=str)),tuple(sorted(removed,key=str)),command.effective_date,datetime.now(timezone.utc))
  self.repository.apply_batch(batch,closed,opened,event);return batch
 @staticmethod
 def _allowed(kind,asset_type):
  if kind is StrategyUniverseKind.ETF_TIMING_POOL:return asset_type in {AssetType.ETF_DOMESTIC,AssetType.ETF_OVERSEAS_LINKED}
  if kind is StrategyUniverseKind.EQUITY_DAILY_POOL:return asset_type in {AssetType.A_SHARE,AssetType.HK_STOCK_CONNECT_ELIGIBLE_SECURITY}
  return True
 def get_members(self,universe_id:UUID,decision_at:datetime)->tuple[MembershipPeriod,...]:
  decision_at=aware(decision_at,"decision_at");definition=self.repository.get_definition(universe_id)
  if definition is None:raise UniverseNotFound(str(universe_id))
  local_date=decision_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
  values=[x for x in self.repository.periods(universe_id) if x.active(local_date) and x.available_at<=decision_at and self.instruments.is_tradable(x.instrument_id,local_date)]
  return tuple(sorted(values,key=lambda x:str(x.instrument_id)))
 def explain_membership(self,universe_id,instrument_id,decision_at)->MembershipExplanation:
  decision_at=aware(decision_at,"decision_at");local_date=decision_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
  periods=[x for x in self.repository.periods(universe_id) if x.instrument_id==instrument_id and x.active(local_date)]
  if not periods:return MembershipExplanation(universe_id,instrument_id,False,"NO_ACTIVE_MEMBERSHIP",None)
  value=max(periods,key=lambda x:x.available_at)
  if value.available_at>decision_at:return MembershipExplanation(universe_id,instrument_id,False,"NOT_YET_AVAILABLE",value)
  if not self.instruments.is_tradable(instrument_id,local_date):return MembershipExplanation(universe_id,instrument_id,False,"INSTRUMENT_NOT_TRADABLE",value)
  return MembershipExplanation(universe_id,instrument_id,True,"ELIGIBLE",value)
 def freeze_snapshot(self,universe_id:UUID,decision_at:datetime,data_snapshot_id:UUID)->UniverseSnapshot:
  members=self.get_members(universe_id,decision_at);ids=tuple(x.instrument_id for x in members);batches=tuple(sorted({x.source_batch_id for x in members}))
  digest=hashlib.sha256((str(universe_id)+"|"+str(data_snapshot_id)+"|"+"|".join(map(str,ids))).encode()).hexdigest()
  value=UniverseSnapshot(universe_id,decision_at,data_snapshot_id,ids,digest,batches);self.repository.save_snapshot(value);return value
 def get_strategy_universe(self,kind:StrategyUniverseKind,decision_at:datetime,data_snapshot_id:UUID)->UniverseSnapshot:
  definitions=[x for x in self.repository.list_definitions() if x.kind is kind]
  if len(definitions)!=1:raise UniverseNotFound(f"expected exactly one {kind}")
  latest=max(self.repository.batches(definitions[0].universe_id),key=lambda x:x.available_at,default=None)
  if latest is None or (aware(decision_at,"decision_at").date()-latest.available_at.date()).days>definitions[0].max_staleness_days:raise StaleUniverse(str(kind))
  return self.freeze_snapshot(definitions[0].universe_id,decision_at,data_snapshot_id)
 def add_classification(self,value:ClassificationMembership)->None:
  for x in self.repository.classifications(value.instrument_id):
   same=(x.provider,x.system,x.version,x.level)==(value.provider,value.system,value.version,value.level)
   if same and value.valid_from<(x.valid_to or date.max) and x.valid_from<(value.valid_to or date.max):raise InvalidUniverse("classification intervals overlap")
  self.repository.save_classification(value)
 def get_classification(self,instrument_id,decision_at,*,provider,system,version,level):
  d=aware(decision_at,"decision_at");on=d.astimezone(ZoneInfo("Asia/Shanghai")).date()
  return tuple(x for x in self.repository.classifications(instrument_id) if (x.provider,x.system,x.version,x.level)==(provider,system,version,level) and x.valid_from<=on and (x.valid_to is None or on<x.valid_to) and x.available_at<=d)
