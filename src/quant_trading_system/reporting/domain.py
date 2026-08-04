from __future__ import annotations
from dataclasses import dataclass,field
from datetime import date,datetime,timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from quant_trading_system.strategies import StrategyKind
from .errors import InvalidReportInput

def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None:raise InvalidReportInput(f"{name} must be timezone-aware")
 return x.astimezone(timezone.utc)
def dec(x):return Decimal(str(x))
class ReportMode(StrEnum):LIVE="LIVE";PAPER="PAPER";BACKTEST="BACKTEST";RESEARCH="RESEARCH"
class ReportRunStatus(StrEnum):CREATED="CREATED";BUILDING="BUILDING";COMPLETED="COMPLETED";INCOMPLETE="INCOMPLETE";FAILED="FAILED"
class InputQuality(StrEnum):PASS="PASS";FAIL="FAIL"
class QualityOutcome(StrEnum):PASS="PASS";FAIL="FAIL"
class ArtifactFormat(StrEnum):HTML="HTML";CSV="CSV";CHART_DATA="CHART_DATA"
class SensitivityLevel(StrEnum):PUBLIC="PUBLIC";INTERNAL="INTERNAL";CONFIDENTIAL="CONFIDENTIAL"
class AttributionDimension(StrEnum):RETURN="RETURN";RISK="RISK";TURNOVER="TURNOVER";COST="COST"

@dataclass(frozen=True,slots=True)
class ReportDefinition:
 name:str;mode:ReportMode;audience:str;metric_version:str;template_version:str;code_version:str;required_source_types:tuple[str,...];benchmark:str;risk_free_rate:Decimal;annualization_days:int;base_currency:str;sensitivity:SensitivityLevel;required_template_fields:tuple[str,...];definition_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"risk_free_rate",dec(self.risk_free_rate))
  if not all(x.strip() for x in (self.name,self.audience,self.metric_version,self.template_version,self.code_version,self.benchmark)) or not self.required_source_types or self.annualization_days<=0 or len(self.base_currency)!=3:raise InvalidReportInput("invalid report definition")

@dataclass(frozen=True,slots=True)
class ReportPeriod:
 start:date;end:date
 def __post_init__(self):
  if self.end<self.start:raise InvalidReportInput("invalid report period")

@dataclass(frozen=True,slots=True)
class ReportInputSnapshot:
 source_type:str;source_id:UUID;as_of:datetime;content_hash:str;quality:InputQuality;source_mode:ReportMode;reference:str;facts:Mapping[str,object];reconciled:bool=True
 def __post_init__(self):
  object.__setattr__(self,"as_of",aware(self.as_of,"as_of"))
  if not self.source_type.strip() or not self.content_hash.strip() or not self.reference.strip():raise InvalidReportInput("input snapshot must be frozen and referenced")

@dataclass(frozen=True,slots=True)
class ReportCurvePoint:
 at:datetime;nav:Decimal;source_snapshot_id:UUID;source_reference:str;mode:ReportMode
 def __post_init__(self):
  object.__setattr__(self,"at",aware(self.at,"at"));object.__setattr__(self,"nav",dec(self.nav))
  if (self.nav.is_finite() and self.nav<=0) or not self.source_reference.strip():raise InvalidReportInput("invalid curve point")

@dataclass(frozen=True,slots=True)
class ReportTrade:
 instrument_id:UUID;occurred_at:datetime;gross:Decimal;fee:Decimal;currency:str;source_snapshot_id:UUID;source_reference:str;mode:ReportMode;filled:bool=True
 def __post_init__(self):
  object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"));object.__setattr__(self,"gross",dec(self.gross));object.__setattr__(self,"fee",dec(self.fee))
  if self.gross<0 or self.fee<0 or len(self.currency)!=3 or not self.source_reference.strip():raise InvalidReportInput("invalid report trade")

@dataclass(frozen=True,slots=True)
class AttributionInput:
 component:str;dimension:AttributionDimension;value:Decimal;source_run_id:UUID|None;source_reference:str;instrument_id:UUID|None=None
 def __post_init__(self):
  object.__setattr__(self,"value",dec(self.value))
  if self.component not in ("ETF_TIMING","EQUITY_DAILY_SELECTION","CROSS_CONSTRAINT","CASH") or not self.source_reference.strip():raise InvalidReportInput("invalid attribution component")
  if self.component in ("ETF_TIMING","EQUITY_DAILY_SELECTION") and self.source_run_id is None:raise InvalidReportInput("strategy attribution needs independent run id")

@dataclass(frozen=True,slots=True)
class StrategySummaryInput:
 kind:StrategyKind;strategy_run_id:UUID;select_count:int;keep_count:int;exit_count:int;candidate_stability:Decimal;turnover:Decimal;daily_gate:str|None=None;rebalance_days:tuple[date,...]=();cash_state:str|None=None
 def __post_init__(self):
  object.__setattr__(self,"candidate_stability",dec(self.candidate_stability));object.__setattr__(self,"turnover",dec(self.turnover))
  if min(self.select_count,self.keep_count,self.exit_count)<0 or not 0<=self.candidate_stability<=1 or self.turnover<0:raise InvalidReportInput("invalid strategy summary")
  if self.kind is StrategyKind.ETF_TIMING and (self.daily_gate is None or self.cash_state is None):raise InvalidReportInput("ETF summary needs gate and cash state")

@dataclass(frozen=True,slots=True)
class BuildReport:
 definition:ReportDefinition;period:ReportPeriod;inputs:tuple[ReportInputSnapshot,...];curve:tuple[ReportCurvePoint,...];trades:tuple[ReportTrade,...];attributions:tuple[AttributionInput,...];strategy_summaries:tuple[StrategySummaryInput,...];fx_snapshot_id:UUID|None;fx_rates:Mapping[str,Decimal];template_fields:Mapping[str,str];generated_at:datetime
 def __post_init__(self):object.__setattr__(self,"generated_at",aware(self.generated_at,"generated_at"));object.__setattr__(self,"fx_rates",{k:dec(v) for k,v in self.fx_rates.items()})

@dataclass(frozen=True,slots=True)
class ReportRun:
 definition_id:UUID;period:ReportPeriod;input_hash:str;content_hash:str;status:ReportRunStatus;mode:ReportMode;template_version:str;code_version:str;benchmark:str;risk_free_rate:Decimal;annualization_days:int;fx_snapshot_id:UUID|None;generated_at:datetime;run_id:UUID=field(default_factory=uuid4)

@dataclass(frozen=True,slots=True)
class ReportMetric:
 run_id:UUID;name:str;value:Decimal;unit:str;definition:str;formula:str;source_snapshot_ids:tuple[UUID,...];source_references:tuple[str,...];drilldown_reference:str;metric_id:UUID=field(default_factory=uuid4)

@dataclass(frozen=True,slots=True)
class SleeveAttribution:
 run_id:UUID;component:str;dimension:AttributionDimension;value:Decimal;source_run_id:UUID|None;source_reference:str;instrument_id:UUID|None=None;attribution_id:UUID=field(default_factory=uuid4)

@dataclass(frozen=True,slots=True)
class ReportStrategySummary:
 run_id:UUID;kind:StrategyKind;strategy_run_id:UUID;select_count:int;keep_count:int;exit_count:int;candidate_stability:Decimal;turnover:Decimal;daily_gate:str|None;rebalance_days:tuple[date,...];cash_state:str|None;summary_id:UUID=field(default_factory=uuid4)

@dataclass(frozen=True,slots=True)
class ReportArtifact:
 run_id:UUID;format:ArtifactFormat;reference:str;content:str;content_hash:str;generated_at:datetime;sensitivity:SensitivityLevel;publishable:bool;artifact_id:UUID=field(default_factory=uuid4)

@dataclass(frozen=True,slots=True)
class ReportQualityResult:
 run_id:UUID;check_name:str;outcome:QualityOutcome;observed:str;expected:str;explanation:str;quality_id:UUID=field(default_factory=uuid4)

@dataclass(frozen=True,slots=True)
class ReportEvent:
 event_type:str;run_id:UUID;occurred_at:datetime;payload:Mapping[str,str];event_id:UUID=field(default_factory=uuid4)

@dataclass(frozen=True,slots=True)
class ReportResult:
 run:ReportRun;inputs:tuple[ReportInputSnapshot,...];metrics:tuple[ReportMetric,...];attributions:tuple[SleeveAttribution,...];strategy_summaries:tuple[ReportStrategySummary,...];artifacts:tuple[ReportArtifact,...];quality:tuple[ReportQualityResult,...]

@dataclass(frozen=True,slots=True)
class MetricExplanation:
 metric:ReportMetric;input_snapshots:tuple[ReportInputSnapshot,...]
