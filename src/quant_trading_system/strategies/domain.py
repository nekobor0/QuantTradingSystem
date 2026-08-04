from __future__ import annotations
from dataclasses import dataclass,field,replace
from datetime import datetime,timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from .errors import InvalidStrategy
class StrategyKind(StrEnum):ETF_TIMING="ETF_TIMING";EQUITY_DAILY_SELECTION="EQUITY_DAILY_SELECTION"
class RunStatus(StrEnum):CREATED="CREATED";INPUTS_FROZEN="INPUTS_FROZEN";RUNNING="RUNNING";COMPLETED="COMPLETED";FAILED="FAILED";REJECTED="REJECTED"
class CandidateAction(StrEnum):SELECT="SELECT";KEEP="KEEP";EXIT="EXIT"
def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None:raise InvalidStrategy(f"{name} must be timezone-aware")
 return x.astimezone(timezone.utc)
@dataclass(frozen=True,slots=True)
class StrategyDefinition:
 name:str;kind:StrategyKind;purpose:str;asset_scope:str;decision_frequency:str;rebalance_frequency:str;benchmark:str;owner:str;invalidation_conditions:tuple[str,...];definition_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  if not all(x.strip() for x in (self.name,self.purpose,self.asset_scope,self.decision_frequency,self.rebalance_frequency,self.owner)):raise InvalidStrategy("definition text required")
@dataclass(frozen=True,slots=True)
class StrategyVersion:
 definition_id:UUID;version:str;code_version:str;required_features:tuple[str,...];default_parameters:Mapping[str,object];active:bool=True;version_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  if not self.version.strip() or not self.code_version.strip() or not self.required_features:raise InvalidStrategy("invalid version")
@dataclass(frozen=True,slots=True)
class StrategyFeatureValue:
 instrument_id:UUID;feature_name:str;value:Decimal|None;quality:str="OK"
 def __post_init__(self):
  if self.value is not None:object.__setattr__(self,"value",Decimal(str(self.value)))
@dataclass(frozen=True,slots=True)
class FrozenStrategyInputs:
 kind:StrategyKind;decision_at:datetime;universe_snapshot_id:UUID;universe_purpose:str;universe_hash:str;feature_set_id:UUID;feature_purpose:str;feature_hash:str;data_snapshot_id:UUID;member_ids:tuple[UUID,...];feature_values:tuple[StrategyFeatureValue,...];eligibility:Mapping[UUID,tuple[str,...]]=field(default_factory=dict)
 def __post_init__(self):object.__setattr__(self,"decision_at",aware(self.decision_at,"decision_at"))
@dataclass(frozen=True,slots=True)
class StrategyRun:
 kind:StrategyKind;version_id:UUID;decision_at:datetime;universe_snapshot_id:UUID;feature_set_id:UUID;data_snapshot_id:UUID;parameter_hash:str;input_hash:str;result_hash:str;status:RunStatus;cash_gate:bool;previous_run_id:UUID|None=None;supersedes_run_id:UUID|None=None;run_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"decision_at",aware(self.decision_at,"decision_at"))
 def transition(self,next_status:RunStatus)->"StrategyRun":
  allowed={RunStatus.CREATED:{RunStatus.INPUTS_FROZEN,RunStatus.REJECTED},RunStatus.INPUTS_FROZEN:{RunStatus.RUNNING,RunStatus.FAILED},RunStatus.RUNNING:{RunStatus.COMPLETED,RunStatus.FAILED}}
  if next_status not in allowed.get(self.status,set()):raise InvalidStrategy(f"invalid transition {self.status}->{next_status}")
  return replace(self,status=next_status)
@dataclass(frozen=True,slots=True)
class StrategyScore:
 run_id:UUID;instrument_id:UUID;raw_score:Decimal;rank:int;score_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class FeatureContribution:
 run_id:UUID;instrument_id:UUID;feature_name:str;feature_value:Decimal;weight:Decimal;contribution:Decimal;contribution_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class StrategyCandidate:
 run_id:UUID;instrument_id:UUID;action:CandidateAction;raw_score:Decimal|None;rank:int|None;proposed_weight:Decimal;reason_codes:tuple[str,...];candidate_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"proposed_weight",Decimal(str(self.proposed_weight)))
  if self.proposed_weight<0 or self.proposed_weight>1:raise InvalidStrategy("candidate weight out of range")
@dataclass(frozen=True,slots=True)
class ResearchEvidence:
 strategy_version_id:UUID;evidence_type:str;sample_start:str;sample_end:str;artifact_ref:str;parameters_hash:str;evidence_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class StrategyEvent:
 event_type:str;run_id:UUID;occurred_at:datetime;reasons:tuple[str,...]=();event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))
@dataclass(frozen=True,slots=True)
class RunStrategy:
 version_id:UUID;kind:StrategyKind;decision_at:datetime;inputs:FrozenStrategyInputs;parameters:Mapping[str,object];previous_run_id:UUID|None=None;supersede_run_id:UUID|None=None
@dataclass(frozen=True,slots=True)
class StrategyResult:
 run:StrategyRun;scores:tuple[StrategyScore,...];candidates:tuple[StrategyCandidate,...];contributions:tuple[FeatureContribution,...]
