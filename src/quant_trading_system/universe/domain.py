from __future__ import annotations
from dataclasses import dataclass,field
from datetime import date,datetime,timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from .errors import InvalidUniverse

class StrategyUniverseKind(StrEnum): ETF_TIMING_POOL="ETF_TIMING_POOL"; EQUITY_DAILY_POOL="EQUITY_DAILY_POOL"; GENERAL="GENERAL"
class BatchStatus(StrEnum): REJECTED="REJECTED"; PUBLISHED="PUBLISHED"
def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None: raise InvalidUniverse(f"{name} must be timezone-aware")
 return x.astimezone(timezone.utc)
@dataclass(frozen=True,slots=True)
class UniverseDefinition:
 name:str;kind:StrategyUniverseKind;source:str;version:str;rule_description:str;max_change_ratio:Decimal=Decimal("0.5");max_staleness_days:int=3;universe_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"source",self.source.strip().lower());object.__setattr__(self,"max_change_ratio",Decimal(str(self.max_change_ratio)))
  if not self.name.strip() or not self.source or not self.version.strip() or not self.rule_description.strip():raise InvalidUniverse("definition text is required")
  if not Decimal("0")<=self.max_change_ratio<=Decimal("1") or self.max_staleness_days<0:raise InvalidUniverse("invalid thresholds")
@dataclass(frozen=True,slots=True)
class MembershipPeriod:
 universe_id:UUID;instrument_id:UUID;valid_from:date;valid_to:date|None;announced_at:datetime;available_at:datetime;source_batch_id:str;membership_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"announced_at",aware(self.announced_at,"announced_at"));object.__setattr__(self,"available_at",aware(self.available_at,"available_at"))
  if self.valid_to is not None and self.valid_to<=self.valid_from:raise InvalidUniverse("valid_to must follow valid_from")
  if self.available_at<self.announced_at:raise InvalidUniverse("available_at precedes announced_at")
 def active(self,on:date)->bool:return self.valid_from<=on and (self.valid_to is None or on<self.valid_to)
@dataclass(frozen=True,slots=True)
class ClassificationMembership:
 instrument_id:UUID;provider:str;system:str;version:str;level:int;code:str;name:str;valid_from:date;valid_to:date|None;available_at:datetime;classification_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"available_at",aware(self.available_at,"available_at"))
  if self.level<1 or not all(x.strip() for x in (self.provider,self.system,self.version,self.code,self.name)):raise InvalidUniverse("invalid classification")
  if self.valid_to is not None and self.valid_to<=self.valid_from:raise InvalidUniverse("invalid classification interval")
@dataclass(frozen=True,slots=True)
class MembershipBatch:
 universe_id:UUID;source_batch_id:str;effective_date:date;announced_at:datetime;available_at:datetime;payload_hash:str;status:BatchStatus;member_count:int;batch_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"announced_at",aware(self.announced_at,"announced_at"));object.__setattr__(self,"available_at",aware(self.available_at,"available_at"))
  if self.available_at<self.announced_at or self.member_count<0:raise InvalidUniverse("invalid batch")
@dataclass(frozen=True,slots=True)
class UniverseQualityResult:
 code:str;message:str;source_code:str|None=None;result_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class UniverseMembershipChanged:
 universe_id:UUID;batch_id:UUID;joined:tuple[UUID,...];removed:tuple[UUID,...];effective_date:date;occurred_at:datetime;event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))
@dataclass(frozen=True,slots=True)
class UniverseSnapshot:
 universe_id:UUID;decision_at:datetime;data_snapshot_id:UUID;member_ids:tuple[UUID,...];member_hash:str;source_batch_ids:tuple[str,...];snapshot_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"decision_at",aware(self.decision_at,"decision_at"))
@dataclass(frozen=True,slots=True)
class MembershipExplanation:
 universe_id:UUID;instrument_id:UUID;eligible:bool;reason:str;period:MembershipPeriod|None
@dataclass(frozen=True,slots=True)
class ApplyMembershipBatch:
 universe_id:UUID;source_batch_id:str;effective_date:date;announced_at:datetime;available_at:datetime;source_codes:tuple[str,...]
