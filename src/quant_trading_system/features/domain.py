from __future__ import annotations
from dataclasses import dataclass,field
from datetime import date,datetime,timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from .errors import InvalidFeature
class FeaturePurpose(StrEnum):ETF_TIMING="ETF_TIMING";EQUITY_DAILY_SELECTION="EQUITY_DAILY_SELECTION"
class FormulaKind(StrEnum):MOMENTUM="MOMENTUM";VOLATILITY="VOLATILITY";MAX_DRAWDOWN="MAX_DRAWDOWN";LIQUIDITY="LIQUIDITY";EARNINGS_YIELD="EARNINGS_YIELD";ROE="ROE";GROWTH="GROWTH"
class MissingPolicy(StrEnum):REJECT="REJECT";KEEP_NULL="KEEP_NULL"
class TransformKind(StrEnum):NONE="NONE";WINSOR_ZSCORE="WINSOR_ZSCORE"
class QualityFlag(StrEnum):OK="OK";INSUFFICIENT_HISTORY="INSUFFICIENT_HISTORY";MISSING_INPUT="MISSING_INPUT";ZERO_VARIANCE="ZERO_VARIANCE"
def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None:raise InvalidFeature(f"{name} must be timezone-aware")
 return x.astimezone(timezone.utc)
@dataclass(frozen=True,slots=True)
class FeatureDefinition:
 name:str;purpose:FeaturePurpose;formula:FormulaKind;economic_meaning:str;direction:int;frequency:str;owner:str;definition_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  if not all(x.strip() for x in (self.name,self.economic_meaning,self.frequency,self.owner)) or self.direction not in (-1,1):raise InvalidFeature("invalid feature definition")
@dataclass(frozen=True,slots=True)
class FeatureVersion:
 definition_id:UUID;version:str;code_version:str;parameters:Mapping[str,str];dependency_versions:Mapping[str,str];min_history:int;missing_policy:MissingPolicy;transform:TransformKind=TransformKind.NONE;active:bool=True;version_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  if not self.version.strip() or not self.code_version.strip() or self.min_history<1:raise InvalidFeature("invalid feature version")
@dataclass(frozen=True,slots=True)
class InputObservation:
 instrument_id:UUID;field_name:str;observed_on:date;available_at:datetime;value:Decimal|None;source_ref:str;data_snapshot_id:UUID
 def __post_init__(self):
  object.__setattr__(self,"available_at",aware(self.available_at,"available_at"))
  if self.value is not None:object.__setattr__(self,"value",Decimal(str(self.value)))
  if not self.field_name.strip() or not self.source_ref.strip():raise InvalidFeature("input identity required")
@dataclass(frozen=True,slots=True)
class FeatureValue:
 feature_set_id:UUID;instrument_id:UUID;as_of_date:date;version_id:UUID;data_snapshot_id:UUID;value:Decimal|None;quality:QualityFlag;input_refs:tuple[str,...];steps:tuple[str,...];value_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class FeatureSet:
 purpose:FeaturePurpose;as_of_date:date;decision_at:datetime;universe_snapshot_id:UUID;data_snapshot_id:UUID;version_ids:tuple[UUID,...];member_ids:tuple[UUID,...];input_hash:str;content_hash:str;factor_version:str|None;feature_set_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"decision_at",aware(self.decision_at,"decision_at"))
@dataclass(frozen=True,slots=True)
class FeatureDiagnostic:
 version_id:UUID;as_of_date:date;metric:str;value:Decimal;research_only:bool=True;diagnostic_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  if not self.research_only:raise InvalidFeature("diagnostics must remain research-only")
@dataclass(frozen=True,slots=True)
class FeatureEvent:
 event_type:str;feature_set_id:UUID;occurred_at:datetime;reasons:tuple[str,...]=();event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))
@dataclass(frozen=True,slots=True)
class UniverseSnapshotInput:
 snapshot_id:UUID;purpose:FeaturePurpose;member_ids:tuple[UUID,...];content_hash:str
@dataclass(frozen=True,slots=True)
class CalculateFeatureSet:
 purpose:FeaturePurpose;version_ids:tuple[UUID,...];as_of_date:date;decision_at:datetime;universe:UniverseSnapshotInput;data_snapshot_id:UUID;observations:tuple[InputObservation,...];factor_version:str|None=None
