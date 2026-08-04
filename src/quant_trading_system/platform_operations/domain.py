from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Mapping
from uuid import UUID, uuid4

from .errors import ValidationError


def aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None: raise ValidationError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class TaskType(StrEnum):
    RUN_ETF_DAILY_GATE="RUN_ETF_DAILY_GATE"; RUN_ETF_SCHEDULED_REBALANCE="RUN_ETF_SCHEDULED_REBALANCE"; RUN_EQUITY_DAILY_SELECTION="RUN_EQUITY_DAILY_SELECTION"; BUILD_COMBINED_PORTFOLIO="BUILD_COMBINED_PORTFOLIO"; RUN_RISK="RUN_RISK"; RECONCILE_ACCOUNT="RECONCILE_ACCOUNT"
class TaskStatus(StrEnum): PENDING="PENDING"; RUNNING="RUNNING"; SUCCEEDED="SUCCEEDED"; FAILED_RETRYABLE="FAILED_RETRYABLE"; FAILED_FINAL="FAILED_FINAL"; CANCELLED="CANCELLED"
class BatchStatus(StrEnum): STAGED="STAGED"; PUBLISHED="PUBLISHED"; REJECTED="REJECTED"
class QualityStatus(StrEnum): PASS="PASS"; FAIL="FAIL"; WARN="WARN"
class DeliveryStatus(StrEnum): PENDING="PENDING"; LEASED="LEASED"; DELIVERED="DELIVERED"; FAILED="FAILED"


@dataclass(frozen=True, slots=True)
class TaskRun:
    task_type: TaskType; business_date: date; input_hash: str; correlation_id: str; attempt: int=1; max_attempts: int=3; status: TaskStatus=TaskStatus.PENDING; lease_owner: str|None=None; lease_expires_at: datetime|None=None; fencing_token: int=0; started_at: datetime|None=None; finished_at: datetime|None=None; error_class: str|None=None; previous_run_id: UUID|None=None; task_run_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        if not self.input_hash or not self.correlation_id or self.attempt < 1 or self.max_attempts < self.attempt: raise ValidationError("invalid task run")
        for name in ("lease_expires_at", "started_at", "finished_at"):
            value=getattr(self,name)
            if value is not None: object.__setattr__(self,name,aware(value,name))
    @property
    def business_key(self): return f"{self.task_type.value}:{self.business_date.isoformat()}:{self.input_hash}"


@dataclass(frozen=True, slots=True)
class DatasetBatch:
    source: str; dataset: str; checksum: str; window_start: datetime; window_end: datetime; status: BatchStatus; quality: QualityStatus; published_at: datetime|None=None; batch_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        object.__setattr__(self,"window_start",aware(self.window_start,"window_start")); object.__setattr__(self,"window_end",aware(self.window_end,"window_end"))
        if self.published_at is not None: object.__setattr__(self,"published_at",aware(self.published_at,"published_at"))
        if not self.source or not self.dataset or not self.checksum or self.window_end < self.window_start: raise ValidationError("invalid dataset batch")


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_type: str; aggregate_id: UUID; payload: Mapping[str,str]; schema_version: int; occurred_at: datetime; recorded_at: datetime; correlation_id: str; causation_id: UUID|None=None; status: DeliveryStatus=DeliveryStatus.PENDING; attempts: int=0; lease_owner: str|None=None; lease_expires_at: datetime|None=None; delivered_at: datetime|None=None; event_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        for name in ("occurred_at","recorded_at","lease_expires_at","delivered_at"):
            value=getattr(self,name)
            if value is not None: object.__setattr__(self,name,aware(value,name))
        if not self.event_type or not self.correlation_id or self.schema_version < 1: raise ValidationError("invalid outbox event")


@dataclass(frozen=True, slots=True)
class ConsumerCheckpoint:
    consumer: str; event_id: UUID; processed_at: datetime; result_hash: str; checkpoint_id: UUID=field(default_factory=uuid4)
    def __post_init__(self): object.__setattr__(self,"processed_at",aware(self.processed_at,"processed_at"))


@dataclass(frozen=True, slots=True)
class ConfigurationVersion:
    environment: str; version: int; values: Mapping[str,str]; secret_refs: Mapping[str,str]; effective_from: datetime; effective_to: datetime|None; content_hash: str; configuration_id: UUID=field(default_factory=uuid4)
    def __post_init__(self):
        object.__setattr__(self,"effective_from",aware(self.effective_from,"effective_from"))
        if self.effective_to is not None: object.__setattr__(self,"effective_to",aware(self.effective_to,"effective_to"))
        forbidden=("password","secret","token","api_key")
        if any(any(word in k.lower() for word in forbidden) for k in self.values): raise ValidationError("secrets must be references")
        if not self.environment or self.version < 1 or not self.content_hash: raise ValidationError("invalid configuration")


@dataclass(frozen=True, slots=True)
class BackupRecord:
    backup_id: UUID; started_at: datetime; finished_at: datetime; succeeded: bool; checksum: str; schema_version: str; restored_at: datetime|None=None
    def __post_init__(self):
        for name in ("started_at","finished_at","restored_at"):
            value=getattr(self,name)
            if value is not None: object.__setattr__(self,name,aware(value,name))


@dataclass(frozen=True, slots=True)
class AlertRecord:
    category: str; message: str; occurred_at: datetime; correlation_id: str; primary_delivered: bool; fallback_persisted: bool; alert_id: UUID=field(default_factory=uuid4)
    def __post_init__(self): object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))

@dataclass(frozen=True, slots=True)
class OperationalAudit:
    actor: str; service: str; command: str; object_id: UUID; result: str; occurred_at: datetime; correlation_id: str; audit_id: UUID=field(default_factory=uuid4)
    def __post_init__(self): object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    as_of: datetime; ready: bool; checks: Mapping[str,bool]; reasons: tuple[str,...]
    def __post_init__(self): object.__setattr__(self,"as_of",aware(self.as_of,"as_of"))
