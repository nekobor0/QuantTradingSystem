from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime,timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from quant_trading_system.strategies import RunStatus,StrategyKind
from .errors import InvalidPortfolio
class ConstraintSeverity(StrEnum):INFO="INFO";WARNING="WARNING";ERROR="ERROR"
def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None:raise InvalidPortfolio(f"{name} must be timezone-aware")
 return x.astimezone(timezone.utc)
def dec(x):return Decimal(str(x))
@dataclass(frozen=True,slots=True)
class SleevePolicy:
 kind:StrategyKind;budget:Decimal;required:bool=True;priority:int=1;sleeve_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"budget",dec(self.budget))
  if self.budget<0 or self.budget>1 or self.priority<1:raise InvalidPortfolio("invalid sleeve policy")
@dataclass(frozen=True,slots=True)
class PortfolioPolicy:
 version:str;sleeves:tuple[SleevePolicy,...];min_cash:Decimal;max_instrument:Decimal;market_caps:Mapping[str,Decimal];industry_caps:Mapping[str,Decimal];max_turnover:Decimal;account_max_age_seconds:int;tolerance:Decimal=Decimal("0.00000001");policy_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  for name in ("min_cash","max_instrument","max_turnover","tolerance"):object.__setattr__(self,name,dec(getattr(self,name)))
  object.__setattr__(self,"market_caps",{k:dec(v) for k,v in self.market_caps.items()});object.__setattr__(self,"industry_caps",{k:dec(v) for k,v in self.industry_caps.items()})
  if not self.version.strip() or sum((x.budget for x in self.sleeves),Decimal())>1 or len({x.kind for x in self.sleeves})!=len(self.sleeves):raise InvalidPortfolio("invalid sleeve budgets")
  if not 0<=self.min_cash<=1 or not 0<self.max_instrument<=1 or self.max_turnover<0 or self.account_max_age_seconds<0 or self.tolerance<=0:raise InvalidPortfolio("invalid policy limits")
  if any(not 0<=x<=1 for x in (*self.market_caps.values(),*self.industry_caps.values())):raise InvalidPortfolio("invalid group cap")
@dataclass(frozen=True,slots=True)
class StrategyTargetWeight:
 instrument_id:UUID;weight:Decimal
 def __post_init__(self):
  object.__setattr__(self,"weight",dec(self.weight))
  if self.weight<0 or self.weight>1:raise InvalidPortfolio("strategy target weight out of range")
@dataclass(frozen=True,slots=True)
class StrategyRunTarget:
 run_id:UUID;kind:StrategyKind;status:RunStatus;decision_at:datetime;cash_gate:bool;weights:tuple[StrategyTargetWeight,...]
 def __post_init__(self):object.__setattr__(self,"decision_at",aware(self.decision_at,"decision_at"))
@dataclass(frozen=True,slots=True)
class AccountSnapshotInput:
 snapshot_id:UUID;as_of:datetime;weights:Mapping[UUID,Decimal];cash_weight:Decimal;tradable:Mapping[UUID,bool];market:Mapping[UUID,str];industry:Mapping[UUID,str]
 def __post_init__(self):
  object.__setattr__(self,"as_of",aware(self.as_of,"as_of"));object.__setattr__(self,"weights",{k:dec(v) for k,v in self.weights.items()});object.__setattr__(self,"cash_weight",dec(self.cash_weight))
  if any(x<0 for x in self.weights.values()) or self.cash_weight<0:raise InvalidPortfolio("actual weights must be long-only")
@dataclass(frozen=True,slots=True)
class TargetPortfolio:
 policy_id:UUID;strategy_run_ids:tuple[UUID,...];account_snapshot_id:UUID;built_at:datetime;cash_weight:Decimal;input_hash:str;content_hash:str;target_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"built_at",aware(self.built_at,"built_at"));object.__setattr__(self,"cash_weight",dec(self.cash_weight))
  if self.cash_weight<0 or self.cash_weight>1:raise InvalidPortfolio("cash weight out of range")
@dataclass(frozen=True,slots=True)
class TargetWeight:
 target_id:UUID;instrument_id:UUID;weight:Decimal;weight_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"weight",dec(self.weight))
  if self.weight<0 or self.weight>1:raise InvalidPortfolio("target must be long-only")
@dataclass(frozen=True,slots=True)
class TargetContribution:
 target_id:UUID;sleeve:str;instrument_id:UUID|None;raw_weight:Decimal;final_weight:Decimal;cash_contribution:Decimal;contribution_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  for name in ("raw_weight","final_weight","cash_contribution"):object.__setattr__(self,name,dec(getattr(self,name)))
  if any(getattr(self,name)<0 for name in ("raw_weight","final_weight","cash_contribution")):raise InvalidPortfolio("contributions must be nonnegative")
@dataclass(frozen=True,slots=True)
class ConstraintResult:
 target_id:UUID;rule:str;scope:str;before:Decimal;after:Decimal;limit:Decimal;binding:bool;reason:str;severity:ConstraintSeverity;result_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class RebalanceDelta:
 target_id:UUID;instrument_id:UUID;current_weight:Decimal;target_weight:Decimal;delta:Decimal;delta_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  for name in ("current_weight","target_weight","delta"):object.__setattr__(self,name,dec(getattr(self,name)))
  if self.current_weight<0 or self.target_weight<0 or self.delta!=self.target_weight-self.current_weight:raise InvalidPortfolio("invalid rebalance delta")
@dataclass(frozen=True,slots=True)
class PortfolioEvent:
 event_type:str;target_id:UUID;occurred_at:datetime;reasons:tuple[str,...]=();event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))
@dataclass(frozen=True,slots=True)
class BuildTargetPortfolio:
 runs:tuple[StrategyRunTarget,...];account:AccountSnapshotInput;policy:PortfolioPolicy;built_at:datetime
@dataclass(frozen=True,slots=True)
class PortfolioResult:
 target:TargetPortfolio;weights:tuple[TargetWeight,...];contributions:tuple[TargetContribution,...];constraints:tuple[ConstraintResult,...];deltas:tuple[RebalanceDelta,...]
