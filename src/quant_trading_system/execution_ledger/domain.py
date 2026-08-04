from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime,timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from .errors import InvalidLedgerInput
class AccountStatus(StrEnum):ACTIVE="ACTIVE";BLOCKED_FOR_SIGNAL="BLOCKED_FOR_SIGNAL";DISABLED="DISABLED"
class OrderSource(StrEnum):RECOMMENDATION="RECOMMENDATION";MANUAL="MANUAL"
class OrderSide(StrEnum):BUY="BUY";SELL="SELL"
class OrderStatus(StrEnum):DRAFT="DRAFT";SUBMITTED="SUBMITTED";PARTIALLY_FILLED="PARTIALLY_FILLED";FILLED="FILLED";CANCELLED="CANCELLED";REJECTED="REJECTED"
class EntryType(StrEnum):POSITION="POSITION";SETTLEMENT="SETTLEMENT";CASH="CASH";REALIZED_PNL="REALIZED_PNL"
class CashEventType(StrEnum):DEPOSIT="DEPOSIT";WITHDRAWAL="WITHDRAWAL";DIVIDEND="DIVIDEND";TAX="TAX";FEE="FEE";FX="FX";ADJUSTMENT="ADJUSTMENT"
class ReconciliationStatus(StrEnum):MATCHED="MATCHED";DIFFERENCE="DIFFERENCE";RESOLVED="RESOLVED"
def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None:raise InvalidLedgerInput(f"{name} must be timezone-aware")
 return x.astimezone(timezone.utc)
def dec(x):return Decimal(str(x))
@dataclass(frozen=True,slots=True)
class Account:
 broker:str;base_currency:str;market_permissions:tuple[str,...];status:AccountStatus=AccountStatus.ACTIVE;masked_number:str="***";account_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  if not self.broker.strip() or len(self.base_currency)!=3:raise InvalidLedgerInput("invalid account")
@dataclass(frozen=True,slots=True)
class Order:
 account_id:UUID;instrument_id:UUID;source:OrderSource;side:OrderSide;quantity:int;currency:str;submitted_at:datetime;idempotency_key:str;recommendation_id:UUID|None=None;manual_reason:str|None=None;broker_order_id:str|None=None;limit_price:Decimal|None=None;status:OrderStatus=OrderStatus.SUBMITTED;filled_quantity:int=0;version:int=0;order_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"submitted_at",aware(self.submitted_at,"submitted_at"))
  if self.quantity<=0 or self.filled_quantity<0 or self.filled_quantity>self.quantity or len(self.currency)!=3 or not self.idempotency_key.strip():raise InvalidLedgerInput("invalid order")
  if self.source is OrderSource.RECOMMENDATION and self.recommendation_id is None:raise InvalidLedgerInput("recommendation order needs reference")
  if self.source is OrderSource.MANUAL and not (self.manual_reason and self.manual_reason.strip()):raise InvalidLedgerInput("manual order needs reason")
  if self.limit_price is not None and dec(self.limit_price)<=0:raise InvalidLedgerInput("limit price must be positive")
@dataclass(frozen=True,slots=True)
class Fill:
 order_id:UUID;account_id:UUID;instrument_id:UUID;broker:str;broker_fill_id:str;filled_at:datetime;recorded_at:datetime;quantity:int;price:Decimal;commission:Decimal;tax:Decimal;other_fee:Decimal;currency:str;raw_code:str;sellable_on:datetime;payload_hash:str;reverses_fill_id:UUID|None=None;fill_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  for n in ("filled_at","recorded_at","sellable_on"):object.__setattr__(self,n,aware(getattr(self,n),n))
  for n in ("price","commission","tax","other_fee"):object.__setattr__(self,n,dec(getattr(self,n)))
  if self.quantity<=0 or self.price<=0 or any(getattr(self,n)<0 for n in ("commission","tax","other_fee")) or len(self.currency)!=3 or not self.broker_fill_id.strip():raise InvalidLedgerInput("invalid fill")
  if self.sellable_on<self.filled_at:raise InvalidLedgerInput("sellable_on precedes fill")
 @property
 def fee(self):return self.commission+self.tax+self.other_fee
@dataclass(frozen=True,slots=True)
class CashEvent:
 account_id:UUID;event_type:CashEventType;currency:str;amount:Decimal;effective_at:datetime;external_ref:str;reason:str;counter_currency:str|None=None;source_rate:Decimal|None=None;event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"amount",dec(self.amount));object.__setattr__(self,"effective_at",aware(self.effective_at,"effective_at"))
  if self.amount==0 or len(self.currency)!=3 or not self.external_ref.strip() or not self.reason.strip():raise InvalidLedgerInput("invalid cash event")
@dataclass(frozen=True,slots=True)
class LedgerEntry:
 account_id:UUID;entry_type:EntryType;currency:str;effective_at:datetime;recorded_at:datetime;source_type:str;source_id:UUID;instrument_id:UUID|None=None;quantity_delta:int=0;cash_delta:Decimal=Decimal();cost_delta:Decimal=Decimal();realized_pnl_delta:Decimal=Decimal();entry_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"effective_at",aware(self.effective_at,"effective_at"));object.__setattr__(self,"recorded_at",aware(self.recorded_at,"recorded_at"))
  for n in ("cash_delta","cost_delta","realized_pnl_delta"):object.__setattr__(self,n,dec(getattr(self,n)))
@dataclass(frozen=True,slots=True)
class PositionSnapshot:
 instrument_id:UUID;quantity:int;sellable_quantity:int;cost:Decimal
@dataclass(frozen=True,slots=True)
class AccountSnapshot:
 account_id:UUID;as_of:datetime;cash:Mapping[str,Decimal];positions:tuple[PositionSnapshot,...];content_hash:str;entry_watermark:tuple[UUID,...];source:str="execution_ledger";snapshot_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"as_of",aware(self.as_of,"as_of"))
@dataclass(frozen=True,slots=True)
class ReconciliationItem:
 key:str;system_value:Decimal;broker_value:Decimal;difference:Decimal;material:bool;resolved_reason:str|None=None;item_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class Reconciliation:
 account_id:UUID;as_of:datetime;status:ReconciliationStatus;items:tuple[ReconciliationItem,...];broker_snapshot_hash:str;created_at:datetime;resolved_at:datetime|None=None;resolution_reason:str|None=None;reconciliation_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"as_of",aware(self.as_of,"as_of"));object.__setattr__(self,"created_at",aware(self.created_at,"created_at"))
@dataclass(frozen=True,slots=True)
class StatementImport:
 account_id:UUID;file_hash:str;format_version:str;preview_hash:str;confirmed:bool;import_id:UUID=field(default_factory=uuid4)
@dataclass(frozen=True,slots=True)
class LedgerEvent:
 event_type:str;account_id:UUID;occurred_at:datetime;recorded_at:datetime;payload:Mapping[str,str];event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"));object.__setattr__(self,"recorded_at",aware(self.recorded_at,"recorded_at"))
@dataclass(frozen=True,slots=True)
class OrderInput:
 account_id:UUID;instrument_id:UUID;source:OrderSource;side:OrderSide;quantity:int;currency:str;submitted_at:datetime;idempotency_key:str;recommendation_id:UUID|None=None;approved_remaining_quantity:int|None=None;manual_reason:str|None=None;broker_order_id:str|None=None;limit_price:Decimal|None=None
@dataclass(frozen=True,slots=True)
class FillInput:
 broker_fill_id:str|None;stable_row_hash:str|None;manually_confirmed:bool;filled_at:datetime;quantity:int;price:Decimal;commission:Decimal;tax:Decimal;other_fee:Decimal;currency:str;raw_code:str;sellable_on:datetime
