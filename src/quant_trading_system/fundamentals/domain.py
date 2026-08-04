from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID, uuid4

from .errors import InvalidFundamental

class ValueKind(StrEnum): AMOUNT="AMOUNT"; PERCENT="PERCENT"; NUMBER="NUMBER"
class PeriodType(StrEnum): INSTANT="INSTANT"; QUARTER="QUARTER"; YTD="YTD"; TTM="TTM"
class FilingStatus(StrEnum): RECEIVED="RECEIVED"; REJECTED="REJECTED"; PUBLISHED="PUBLISHED"
class QueryPolicy(StrEnum): LATEST_AVAILABLE="LATEST_AVAILABLE"; SOURCE_PRIORITY="SOURCE_PRIORITY"

def aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None: raise InvalidFundamental(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)

@dataclass(frozen=True, slots=True)
class MetricDefinition:
    canonical_name: str; unit: str; value_kind: ValueKind; is_flow: bool
    metric_id: UUID = dc_field(default_factory=uuid4)
    def __post_init__(self):
        if not self.canonical_name.strip() or not self.unit.strip(): raise InvalidFundamental("metric name and unit are required")

@dataclass(frozen=True, slots=True)
class SourceMapping:
    source: str; source_field: str; metric_id: UUID; source_unit: str; scale: Decimal=Decimal("1")
    mapping_id: UUID = dc_field(default_factory=uuid4)
    def __post_init__(self):
        object.__setattr__(self,"source",self.source.strip().lower()); object.__setattr__(self,"scale",Decimal(str(self.scale)))
        if not self.source or not self.source_field.strip() or self.scale <= 0: raise InvalidFundamental("invalid source mapping")

@dataclass(frozen=True, slots=True)
class Filing:
    instrument_id: UUID; source: str; source_filing_id: str; revision: str; report_type: str
    period_end: date; announced_at: datetime; available_at: datetime; ingested_at: datetime
    raw_uri: str; payload_hash: str; status: FilingStatus=FilingStatus.RECEIVED; filing_id: UUID=dc_field(default_factory=uuid4)
    def __post_init__(self):
        object.__setattr__(self,"source",self.source.strip().lower())
        for name in ("announced_at","available_at","ingested_at"): object.__setattr__(self,name,aware(getattr(self,name),name))
        if self.available_at < self.announced_at: raise InvalidFundamental("INVALID_AVAILABILITY")
        if not self.source_filing_id.strip() or not self.revision.strip() or not self.payload_hash.strip(): raise InvalidFundamental("filing identity is required")

@dataclass(frozen=True, slots=True)
class FundamentalFact:
    filing_id: UUID; instrument_id: UUID; metric_id: UUID; period_end: date; period_type: PeriodType
    source: str; revision: str; value: Decimal|None; unit: str; currency: str|None; raw_value: str|None
    lineage: tuple[UUID,...]=(); fact_id: UUID=dc_field(default_factory=uuid4)
    def __post_init__(self):
        if self.value is not None: object.__setattr__(self,"value",Decimal(str(self.value)))
        if not self.unit.strip(): raise InvalidFundamental("fact unit is required")

@dataclass(frozen=True, slots=True)
class ShareCapitalChange:
    instrument_id: UUID; effective_date: date; total_shares: Decimal; float_shares: Decimal
    source: str; announced_at: datetime; available_at: datetime; change_id: UUID=dc_field(default_factory=uuid4)
    def __post_init__(self):
        object.__setattr__(self,"total_shares",Decimal(str(self.total_shares))); object.__setattr__(self,"float_shares",Decimal(str(self.float_shares)))
        object.__setattr__(self,"announced_at",aware(self.announced_at,"announced_at")); object.__setattr__(self,"available_at",aware(self.available_at,"available_at"))
        if self.available_at < self.announced_at or self.total_shares <= 0 or self.float_shares < 0 or self.float_shares > self.total_shares: raise InvalidFundamental("invalid share capital change")

@dataclass(frozen=True, slots=True)
class QualityResult:
    code: str; message: str; field: str|None=None; result_id: UUID=dc_field(default_factory=uuid4)

@dataclass(frozen=True, slots=True)
class FundamentalRevisionEvent:
    filing_id: UUID; instrument_id: UUID; old_revision: str|None; new_revision: str
    affected: tuple[tuple[date,UUID],...]; occurred_at: datetime; event_id: UUID=dc_field(default_factory=uuid4)
    def __post_init__(self): object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))

@dataclass(frozen=True, slots=True)
class FactInput:
    source_field: str; period_end: date; period_type: PeriodType; raw_value: str|Decimal|None; source_unit: str; currency: str|None=None

@dataclass(frozen=True, slots=True)
class IngestFilingCommand:
    source: str; source_filing_id: str; revision: str; source_code: str; report_type: str
    period_end: date; announced_at: datetime|None; available_at: datetime|None; ingested_at: datetime
    raw_uri: str; facts: tuple[FactInput,...]; payload: Mapping[str,object]=dc_field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class SourcePriorityPolicy:
    sources: tuple[str,...]
