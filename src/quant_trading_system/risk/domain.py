from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping
from uuid import UUID, uuid4

from .errors import InvalidRiskInput


def aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidRiskInput(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def dec(value) -> Decimal:
    return Decimal(str(value))


class RiskStage(StrEnum): PRE_TRADE="PRE_TRADE"; IN_FLIGHT="IN_FLIGHT"; POST_TRADE="POST_TRADE"
class RiskScope(StrEnum): ETF_TIMING="ETF_TIMING"; EQUITY_DAILY_SELECTION="EQUITY_DAILY_SELECTION"; COMBINED_ACCOUNT="COMBINED_ACCOUNT"
class RiskSeverity(StrEnum): HARD_BLOCK="HARD_BLOCK"; APPROVAL_REQUIRED="APPROVAL_REQUIRED"; WARNING="WARNING"
class ComparisonOperator(StrEnum): LT="LT"; LE="LE"; GT="GT"; GE="GE"; EQ="EQ"; IN="IN"; TRUE="TRUE"; FALSE="FALSE"
class RuleOutcome(StrEnum): PASS="PASS"; BLOCK="BLOCK"; APPROVAL_REQUIRED="APPROVAL_REQUIRED"; WARNING="WARNING"
class RiskDecision(StrEnum): PASS="PASS"; WARNING="WARNING"; APPROVAL_REQUIRED="APPROVAL_REQUIRED"; BLOCK="BLOCK"
class RiskRunStatus(StrEnum): RUNNING="RUNNING"; COMPLETED="COMPLETED"; FAILED="FAILED"
class ExceptionStatus(StrEnum): APPROVED="APPROVED"; REVOKED="REVOKED"; EXPIRED="EXPIRED"
class AlertStatus(StrEnum): OPEN="OPEN"; ACKNOWLEDGED="ACKNOWLEDGED"; ESCALATED="ESCALATED"; RESOLVED="RESOLVED"


@dataclass(frozen=True, slots=True)
class RiskRule:
    code: str; name: str; owner: str; description: str; rule_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        if not all(x.strip() for x in (self.code,self.name,self.owner,self.description)): raise InvalidRiskInput("rule metadata required")


@dataclass(frozen=True, slots=True)
class RiskRuleVersion:
    rule_id: UUID; version: str; stage: RiskStage; scope: RiskScope; metric: str; operator: ComparisonOperator; threshold: object; severity: RiskSeverity; effective_from: date; effective_to: date|None; owner: str; exception_allowed: bool=False; evaluator_key: str="metric"; version_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        if not self.version.strip() or not self.metric.strip() or not self.owner.strip() or not self.evaluator_key.strip(): raise InvalidRiskInput("invalid rule version")
        if self.effective_to is not None and self.effective_to<self.effective_from: raise InvalidRiskInput("invalid rule interval")
    def active_on(self,on_date:date)->bool:return self.effective_from<=on_date and (self.effective_to is None or on_date<=self.effective_to)


@dataclass(frozen=True, slots=True)
class RiskPolicyVersion:
    name: str; version: str; account_id: UUID; market: str; rule_version_ids: tuple[UUID,...]; required_scopes: tuple[RiskScope,...]; effective_from: date; effective_to: date|None; owner: str; max_input_age_seconds: int; policy_id: UUID=field(default_factory=uuid4); policy_version_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        if set(self.required_scopes)!={RiskScope.ETF_TIMING,RiskScope.EQUITY_DAILY_SELECTION,RiskScope.COMBINED_ACCOUNT}: raise InvalidRiskInput("all three risk scopes are required")
        if not self.rule_version_ids or len(set(self.rule_version_ids))!=len(self.rule_version_ids) or not all(x.strip() for x in (self.name,self.version,self.market,self.owner)) or self.max_input_age_seconds<0: raise InvalidRiskInput("invalid risk policy")
        if self.effective_to is not None and self.effective_to<self.effective_from: raise InvalidRiskInput("invalid policy interval")
    def active_on(self,on_date:date)->bool:return self.effective_from<=on_date and (self.effective_to is None or on_date<=self.effective_to)


@dataclass(frozen=True, slots=True)
class RiskCheckInput:
    account_id: UUID; object_id: UUID; stage: RiskStage; decision_at: datetime; account_snapshot_id: UUID; account_source: str; account_as_of: datetime; reconciled: bool; market_snapshot_id: UUID; market_as_of: datetime; data_snapshot_id: UUID; data_as_of: datetime; task_snapshot_id: UUID; task_as_of: datetime; scoped_values: Mapping[RiskScope,Mapping[str,object]]; content_hashes: Mapping[str,str]; target_portfolio_id: UUID|None=None; signal_id: UUID|None=None; fx_snapshot_id: UUID|None=None; fx_rates: Mapping[str,Decimal]=field(default_factory=dict)
    def __post_init__(self):
        for name in ("decision_at","account_as_of","market_as_of","data_as_of","task_as_of"):object.__setattr__(self,name,aware(getattr(self,name),name))
        object.__setattr__(self,"fx_rates",{k:dec(v) for k,v in self.fx_rates.items()})
        if set(self.scoped_values)!={RiskScope.ETF_TIMING,RiskScope.EQUITY_DAILY_SELECTION,RiskScope.COMBINED_ACCOUNT}:raise InvalidRiskInput("input must contain all three scopes")
        if not self.content_hashes or any(not x.strip() for x in self.content_hashes.values()):raise InvalidRiskInput("frozen content hashes required")
        if self.stage is RiskStage.POST_TRADE and self.account_source!="execution_ledger":raise InvalidRiskInput("post-trade checks require execution_ledger source")


@dataclass(frozen=True, slots=True)
class RiskCheckRun:
    account_id: UUID; object_id: UUID; policy_version_id: UUID; stage: RiskStage; decision_at: datetime; input_hash: str; status: RiskRunStatus; decision: RiskDecision; started_at: datetime; completed_at: datetime|None=None; error: str|None=None; run_id: UUID=field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    run_id: UUID; rule_version_id: UUID; object_id: UUID; scope: RiskScope; metric: str; observed: object; threshold: object; operator: ComparisonOperator; severity: RiskSeverity; outcome: RuleOutcome; explanation: str; evaluated_at: datetime; result_id: UUID=field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class RiskException:
    result_id: UUID; rule_version_id: UUID; scope: RiskScope; requested_by: str; approved_by: str; reason: str; approved_at: datetime; expires_at: datetime; status: ExceptionStatus=ExceptionStatus.APPROVED; version: int=0; exception_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        object.__setattr__(self,"approved_at",aware(self.approved_at,"approved_at"));object.__setattr__(self,"expires_at",aware(self.expires_at,"expires_at"))
        if not all(x.strip() for x in (self.requested_by,self.approved_by,self.reason)) or self.requested_by==self.approved_by or self.expires_at<=self.approved_at:raise InvalidRiskInput("invalid risk exception")


@dataclass(frozen=True, slots=True)
class RiskAlert:
    account_id: UUID; object_id: UUID; result_id: UUID; rule_version_id: UUID; scope: RiskScope; observation_window: str; dedupe_key: str; status: AlertStatus; opened_at: datetime; version: int=0; acknowledged_by: str|None=None; acknowledged_at: datetime|None=None; escalated_to: str|None=None; resolved_at: datetime|None=None; resolution_evidence: str|None=None; alert_id: UUID=field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class RiskEvent:
    event_type: str; account_id: UUID; object_id: UUID; occurred_at: datetime; payload: Mapping[str,str]; event_id: UUID=field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class RiskRunResult:
    run: RiskCheckRun; results: tuple[RiskCheckResult,...]; effective_decision: RiskDecision


@dataclass(frozen=True, slots=True)
class RiskState:
    account_id: UUID; as_of: datetime; active_alerts: tuple[RiskAlert,...]; blocking_reasons: tuple[str,...]; stale: bool; latest_run_id: UUID|None
