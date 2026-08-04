from __future__ import annotations
from dataclasses import dataclass,field,replace
from datetime import date,datetime,timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from quant_trading_system.strategies import StrategyKind
from .errors import InvalidSignal
class SignalStatus(StrEnum):DRAFT="DRAFT";RISK_CHECKED="RISK_CHECKED";PUBLISHED="PUBLISHED";EXPIRED="EXPIRED";SUPERSEDED="SUPERSEDED";CLOSED="CLOSED"
class RecommendationStatus(StrEnum):PENDING="PENDING";APPROVED="APPROVED";PARTIALLY_APPROVED="PARTIALLY_APPROVED";REJECTED="REJECTED";HANDED_OFF="HANDED_OFF"
class Side(StrEnum):BUY="BUY";SELL="SELL"
class RiskDecision(StrEnum):PASS="PASS";HARD_FAIL="HARD_FAIL"
class ApprovalKind(StrEnum):ACCEPT="ACCEPT";PARTIAL="PARTIAL";REJECT="REJECT"
def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None:raise InvalidSignal(f"{name} must be timezone-aware")
 return x.astimezone(timezone.utc)
def dec(x):return Decimal(str(x))
@dataclass(frozen=True,slots=True)
class FeePolicy:
 commission_rate:Decimal;min_commission:Decimal;stamp_duty_rate:Decimal;price_buffer:Decimal;cash_buffer:Decimal;min_trade_value:Decimal;max_price_age_seconds:int;reprice_threshold:Decimal;policy_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  for n in ("commission_rate","min_commission","stamp_duty_rate","price_buffer","cash_buffer","min_trade_value","reprice_threshold"):object.__setattr__(self,n,dec(getattr(self,n)))
  if any(getattr(self,n)<0 for n in ("commission_rate","min_commission","stamp_duty_rate","price_buffer","cash_buffer","min_trade_value","reprice_threshold")) or self.max_price_age_seconds<0:raise InvalidSignal("invalid fee policy")
@dataclass(frozen=True,slots=True)
class TargetWeightInput:
 instrument_id:UUID;target_weight:Decimal
 def __post_init__(self):
  object.__setattr__(self,"target_weight",dec(self.target_weight))
  if self.target_weight<0 or self.target_weight>1:raise InvalidSignal("target weight out of range")
@dataclass(frozen=True,slots=True)
class TargetPortfolioInput:
 target_id:UUID;account_snapshot_id:UUID;weights:tuple[TargetWeightInput,...];cash_weight:Decimal;content_hash:str
@dataclass(frozen=True,slots=True)
class AccountExecutionInput:
 snapshot_id:UUID;source:str;as_of:datetime;reconciled:bool;nav:Decimal;cash:Decimal;quantities:Mapping[UUID,int];settled_sellable:Mapping[UUID,int]
 def __post_init__(self):
  object.__setattr__(self,"as_of",aware(self.as_of,"as_of"));object.__setattr__(self,"nav",dec(self.nav));object.__setattr__(self,"cash",dec(self.cash))
  if self.source!="execution_ledger" or self.nav<=0 or self.cash<0 or any(x<0 for x in (*self.quantities.values(),*self.settled_sellable.values())):raise InvalidSignal("account must be a valid execution_ledger snapshot")
@dataclass(frozen=True,slots=True)
class PriceInput:
 instrument_id:UUID;price:Decimal;available_at:datetime
 def __post_init__(self):
  object.__setattr__(self,"price",dec(self.price));object.__setattr__(self,"available_at",aware(self.available_at,"available_at"))
  if self.price<=0:raise InvalidSignal("price must be positive")
@dataclass(frozen=True,slots=True)
class PricingSnapshot:
 snapshot_id:UUID;prices:tuple[PriceInput,...];content_hash:str
@dataclass(frozen=True,slots=True)
class SignalComponent:
 strategy_kind:StrategyKind;run_id:UUID;instrument_id:UUID|None;state:str;weight_contribution:Decimal;reason_codes:tuple[str,...];component_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"weight_contribution",dec(self.weight_contribution))
@dataclass(frozen=True,slots=True)
class Signal:
 target_id:UUID;account_snapshot_id:UUID;pricing_snapshot_id:UUID;decision_at:datetime;valid_for_date:date;expires_at:datetime;status:SignalStatus;input_hash:str;content_hash:str;account_reconciled:bool;oldest_price_at:datetime;max_price_age_seconds:int;reprice_threshold:Decimal;risk_result_id:UUID|None=None;risk_decision:RiskDecision|None=None;signal_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"decision_at",aware(self.decision_at,"decision_at"));object.__setattr__(self,"expires_at",aware(self.expires_at,"expires_at"));object.__setattr__(self,"oldest_price_at",aware(self.oldest_price_at,"oldest_price_at"));object.__setattr__(self,"reprice_threshold",dec(self.reprice_threshold))
  if self.expires_at<=self.decision_at:raise InvalidSignal("signal must expire after decision")
@dataclass(frozen=True,slots=True)
class Recommendation:
 signal_id:UUID;instrument_id:UUID;side:Side;target_weight:Decimal;current_weight:Decimal;delta_weight:Decimal;quantity:int;limit_price:Decimal;estimated_fee:Decimal;reason_codes:tuple[str,...];status:RecommendationStatus=RecommendationStatus.PENDING;approved_quantity:int=0;handed_off_quantity:int=0;version:int=0;recommendation_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  for n in ("target_weight","current_weight","delta_weight","limit_price","estimated_fee"):object.__setattr__(self,n,dec(getattr(self,n)))
  if self.quantity<=0 or self.limit_price<=0 or self.estimated_fee<0 or self.approved_quantity<0 or self.handed_off_quantity<0 or self.handed_off_quantity>self.approved_quantity or self.approved_quantity>self.quantity:raise InvalidSignal("invalid recommendation")
 @property
 def remaining_quantity(self):return self.approved_quantity-self.handed_off_quantity
@dataclass(frozen=True,slots=True)
class ApprovalDecision:
 recommendation_id:UUID;decision_id:UUID;kind:ApprovalKind;quantity:int;reason:str;operator_id:str;decided_at:datetime;expected_version:int;approval_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"decided_at",aware(self.decided_at,"decided_at"))
  if not self.operator_id.strip():raise InvalidSignal("operator required")
@dataclass(frozen=True,slots=True)
class SignalSupersession:
 old_signal_id:UUID;new_signal_id:UUID;reason:str;superseded_at:datetime;supersession_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"superseded_at",aware(self.superseded_at,"superseded_at"))
@dataclass(frozen=True,slots=True)
class SignalEvent:
 event_type:str;signal_id:UUID;occurred_at:datetime;payload:Mapping[str,str];event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))
@dataclass(frozen=True,slots=True)
class CreateSignal:
 target:TargetPortfolioInput;account:AccountExecutionInput;pricing:PricingSnapshot;components:tuple[SignalComponent,...];fee_policy:FeePolicy;decision_at:datetime;valid_for_date:date;expires_at:datetime
@dataclass(frozen=True,slots=True)
class SignalResult:
 signal:Signal;recommendations:tuple[Recommendation,...];components:tuple[SignalComponent,...]
