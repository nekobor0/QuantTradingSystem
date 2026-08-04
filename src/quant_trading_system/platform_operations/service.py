from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Callable
from uuid import UUID

from .domain import *
from .errors import FencingConflict, LeaseConflict, NotFound, StateConflict
from .ports import AlertSink, EventTransport, HealthProbe, OperationsRepository

REQUIRED_STRATEGIES=(TaskType.RUN_ETF_DAILY_GATE,TaskType.RUN_EQUITY_DAILY_SELECTION)

class OperationsService:
    def __init__(self, repository:OperationsRepository, probe:HealthProbe, alert_sink:AlertSink, lease_duration:timedelta=timedelta(minutes=10), outbox_max_age:timedelta=timedelta(minutes=15), dataset_max_age:timedelta=timedelta(days=1), backup_max_age:timedelta=timedelta(days=1), restore_max_age:timedelta=timedelta(days=30)):
        self.repository=repository; self.probe=probe; self.alert_sink=alert_sink; self.lease_duration=lease_duration; self.outbox_max_age=outbox_max_age; self.dataset_max_age=dataset_max_age; self.backup_max_age=backup_max_age; self.restore_max_age=restore_max_age
    def start_task(self, task_type:TaskType, business_date:date, input_hash:str, correlation_id:str, max_attempts:int=3)->TaskRun:
        current=self.repository.latest_task(task_type,business_date,input_hash)
        if current is not None:return current
        value=TaskRun(task_type,business_date,input_hash,correlation_id,max_attempts=max_attempts); self.repository.save_task(value); self.repository.save_audit(OperationalAudit("scheduler","platform_operations","START_TASK",value.task_run_id,"CREATED",datetime.now(timezone.utc),correlation_id)); return value
    def schedule_daily(self,business_date:date,input_hashes:dict[TaskType,str],correlation_id:str,etf_rebalance_due:bool)->tuple[TaskRun,...]:
        ordered=[TaskType.RUN_ETF_DAILY_GATE,TaskType.RUN_EQUITY_DAILY_SELECTION]
        if etf_rebalance_due:ordered.append(TaskType.RUN_ETF_SCHEDULED_REBALANCE)
        return tuple(self.start_task(kind,business_date,input_hashes[kind],correlation_id) for kind in ordered)
    def register_batch(self,value:DatasetBatch)->DatasetBatch:self.repository.save_batch(value);return value
    def register_configuration(self,value:ConfigurationVersion)->ConfigurationVersion:self.repository.save_configuration(value);return value
    def record_backup(self,value:BackupRecord)->BackupRecord:self.repository.save_backup(value);return value
    def acquire(self, task_run_id:UUID, owner:str, now:datetime)->TaskRun:
        value=self._task(task_run_id); point=aware(now,"now")
        if value.status is TaskStatus.RUNNING and value.lease_expires_at is not None and value.lease_expires_at>point: raise LeaseConflict("active lease")
        if value.status not in (TaskStatus.PENDING,TaskStatus.RUNNING): raise StateConflict("task is not claimable")
        updated=replace(value,status=TaskStatus.RUNNING,lease_owner=owner,lease_expires_at=point+self.lease_duration,fencing_token=value.fencing_token+1,started_at=value.started_at or point)
        self.repository.replace_task(updated,value.fencing_token); return updated
    def complete(self, task_run_id:UUID, owner:str, token:int, result:dict[str,str], now:datetime)->TaskRun:
        value=self._owned(task_run_id,owner,token,now); point=aware(now,"now"); updated=replace(value,status=TaskStatus.SUCCEEDED,finished_at=point,lease_owner=None,lease_expires_at=None)
        event=OutboxEvent("TaskSucceeded",value.task_run_id,{"task_type":value.task_type.value,**result},1,point,point,value.correlation_id,value.task_run_id)
        self.repository.save_task_and_event(updated,event,token); return updated
    def fail(self, task_run_id:UUID, owner:str, token:int, error_class:str, now:datetime)->TaskRun:
        value=self._owned(task_run_id,owner,token,now); point=aware(now,"now"); retryable=value.attempt<value.max_attempts; status=TaskStatus.FAILED_RETRYABLE if retryable else TaskStatus.FAILED_FINAL
        updated=replace(value,status=status,error_class=error_class,finished_at=point,lease_owner=None,lease_expires_at=None); event=OutboxEvent("TaskFailed",value.task_run_id,{"task_type":value.task_type.value,"error_class":error_class},1,point,point,value.correlation_id,value.task_run_id); self.repository.save_task_and_event(updated,event,token)
        self.alert("TASK_FAILED",f"{value.task_type.value}:{error_class}",value.correlation_id,point); return updated
    def retry(self, task_run_id:UUID, expected_status:TaskStatus)->TaskRun:
        old=self._task(task_run_id)
        if old.status is not expected_status or old.status is not TaskStatus.FAILED_RETRYABLE: raise StateConflict("task is not retryable")
        value=replace(old,task_run_id=__import__('uuid').uuid4(),attempt=old.attempt+1,status=TaskStatus.PENDING,lease_owner=None,lease_expires_at=None,fencing_token=0,started_at=None,finished_at=None,error_class=None,previous_run_id=old.task_run_id); self.repository.save_task(value); return value
    def bundle_ready(self,business_date:date)->tuple[bool,tuple[str,...]]:
        missing=[]
        for task_type in REQUIRED_STRATEGIES:
            value=self.repository.latest_task(task_type,business_date)
            if value is None or value.status is not TaskStatus.SUCCEEDED: missing.append(task_type.value)
        return not missing,tuple(missing)
    def start_combined(self,business_date:date,input_hash:str,correlation_id:str)->TaskRun:
        ready,missing=self.bundle_ready(business_date)
        if not ready: self.alert("BUNDLE_BLOCKED",",".join(missing),correlation_id,datetime.now(timezone.utc)); raise StateConflict("required strategy runs missing: "+",".join(missing))
        return self.start_task(TaskType.BUILD_COMBINED_PORTFOLIO,business_date,input_hash,correlation_id)
    def claim_outbox(self,limit:int,owner:str,now:datetime)->tuple[OutboxEvent,...]:
        point=aware(now,"now"); claimed:list[OutboxEvent]=[]
        for value in sorted(self.repository.pending_events(),key=lambda x:x.recorded_at):
            if len(claimed)>=limit:break
            if value.status is DeliveryStatus.LEASED and value.lease_expires_at is not None and value.lease_expires_at>point:continue
            updated=replace(value,status=DeliveryStatus.LEASED,lease_owner=owner,lease_expires_at=point+self.lease_duration,attempts=value.attempts+1); self.repository.replace_event(updated); claimed.append(updated)
        return tuple(claimed)
    def publish_outbox(self,transport:EventTransport,limit:int,owner:str,now:datetime)->int:
        delivered=0
        for value in self.claim_outbox(limit,owner,now):
            try: transport.publish(value)
            except Exception: self.repository.replace_event(replace(value,status=DeliveryStatus.FAILED,lease_owner=None,lease_expires_at=None)); continue
            self.repository.replace_event(replace(value,status=DeliveryStatus.DELIVERED,delivered_at=aware(now,"now"),lease_owner=None,lease_expires_at=None)); delivered+=1
        return delivered
    def consume_once(self,consumer:str,event:OutboxEvent,handler:Callable[[OutboxEvent],str],now:datetime)->str:
        existing=self.repository.checkpoint(consumer,event.event_id)
        if existing is not None:return existing.result_hash
        result=handler(event); digest=sha256(result.encode()).hexdigest(); self.repository.save_checkpoint(ConsumerCheckpoint(consumer,event.event_id,now,digest)); return digest
    def readiness(self,business_date:date,required_datasets:tuple[str,...],now:datetime)->ReadinessResult:
        point=aware(now,"now"); checks={"database":self.probe.database_ok(),"account_reconciled":self.probe.account_reconciled(business_date),"risk":self.probe.risk_succeeded(business_date)}; bundle,_=self.bundle_ready(business_date); checks["strategy_bundle"]=bundle
        for dataset in required_datasets:
            batch=self.repository.latest_batch(dataset); checks[f"dataset:{dataset}"]=batch is not None and batch.status is BatchStatus.PUBLISHED and batch.quality is QualityStatus.PASS and batch.published_at is not None and point-batch.published_at<=self.dataset_max_age
        checks["outbox"]=all(point-x.recorded_at<=self.outbox_max_age for x in self.repository.pending_events())
        backup=self.repository.latest_backup(); checks["backup"]=backup is not None and backup.succeeded and point-backup.finished_at<=self.backup_max_age and backup.restored_at is not None and point-backup.restored_at<=self.restore_max_age
        reasons=tuple(k for k,v in checks.items() if not v); return ReadinessResult(point,not reasons,checks,reasons)
    def alert(self,category,message,correlation_id,now):
        delivered=False
        try: delivered=self.alert_sink.send(category,message,correlation_id)
        except Exception: pass
        record=AlertRecord(category,self._sanitize(message),now,correlation_id,delivered,not delivered); self.repository.save_alert(record); return record
    @staticmethod
    def _sanitize(value):
        import re
        return re.sub(r"(?i)(password|token|secret|api_key)=\S+",r"\1=***",value)
    def _task(self,i):
        value=self.repository.get_task(i)
        if value is None:raise NotFound("task not found")
        return value
    def _owned(self,i,owner,token,now):
        value=self._task(i); point=aware(now,"now")
        if value.status is not TaskStatus.RUNNING or value.lease_owner!=owner or value.fencing_token!=token or value.lease_expires_at is None or value.lease_expires_at<=point:raise FencingConflict()
        return value
