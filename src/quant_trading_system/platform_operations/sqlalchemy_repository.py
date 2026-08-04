from datetime import timezone
from sqlalchemy import insert,select,update
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import FencingConflict,StateConflict
from .tables import *

class SqlAlchemyOperationsRepository:
    def __init__(self,engine):self.engine=engine
    @staticmethod
    def _a(x):return x.replace(tzinfo=timezone.utc) if x is not None and x.tzinfo is None else x
    @staticmethod
    def _tv(x):return {"task_run_id":x.task_run_id,"task_type":x.task_type.value,"business_date":x.business_date,"input_hash":x.input_hash,"correlation_id":x.correlation_id,"attempt":x.attempt,"max_attempts":x.max_attempts,"status":x.status.value,"lease_owner":x.lease_owner,"lease_expires_at":x.lease_expires_at,"fencing_token":x.fencing_token,"started_at":x.started_at,"finished_at":x.finished_at,"error_class":x.error_class,"previous_run_id":x.previous_run_id}
    @classmethod
    def _task(cls,r):return TaskRun(TaskType(r.task_type),r.business_date,r.input_hash,r.correlation_id,r.attempt,r.max_attempts,TaskStatus(r.status),r.lease_owner,cls._a(r.lease_expires_at),r.fencing_token,cls._a(r.started_at),cls._a(r.finished_at),r.error_class,r.previous_run_id,r.task_run_id)
    @staticmethod
    def _ev(x):return {"event_id":x.event_id,"event_type":x.event_type,"aggregate_id":x.aggregate_id,"payload":dict(x.payload),"schema_version":x.schema_version,"occurred_at":x.occurred_at,"recorded_at":x.recorded_at,"correlation_id":x.correlation_id,"causation_id":x.causation_id,"status":x.status.value,"attempts":x.attempts,"lease_owner":x.lease_owner,"lease_expires_at":x.lease_expires_at,"delivered_at":x.delivered_at}
    @classmethod
    def _event(cls,r):return OutboxEvent(r.event_type,r.aggregate_id,r.payload,r.schema_version,cls._a(r.occurred_at),cls._a(r.recorded_at),r.correlation_id,r.causation_id,DeliveryStatus(r.status),r.attempts,r.lease_owner,cls._a(r.lease_expires_at),cls._a(r.delivered_at),r.event_id)
    def latest_task(self,t,b,input_hash=None):
        q=select(task_runs).where(task_runs.c.task_type==t.value,task_runs.c.business_date==b)
        if input_hash is not None:q=q.where(task_runs.c.input_hash==input_hash)
        with self.engine.connect() as c:r=c.execute(q.order_by(task_runs.c.attempt.desc())).mappings().first()
        return None if r is None else self._task(r)
    def get_task(self,i):
        with self.engine.connect() as c:r=c.execute(select(task_runs).where(task_runs.c.task_run_id==i)).mappings().one_or_none()
        return None if r is None else self._task(r)
    def save_task(self,x):
        try:
            with self.engine.begin() as c:c.execute(insert(task_runs).values(**self._tv(x)))
        except IntegrityError as e:raise StateConflict(str(e.orig)) from e
    def replace_task(self,x,expected_fencing_token):
        with self.engine.begin() as c:r=c.execute(update(task_runs).where(task_runs.c.task_run_id==x.task_run_id,task_runs.c.fencing_token==expected_fencing_token).values(**self._tv(x)))
        if r.rowcount!=1:raise FencingConflict()
    def save_task_and_event(self,x,e,expected_fencing_token):
        with self.engine.begin() as c:
            r=c.execute(update(task_runs).where(task_runs.c.task_run_id==x.task_run_id,task_runs.c.fencing_token==expected_fencing_token).values(**self._tv(x)))
            if r.rowcount!=1:raise FencingConflict()
            c.execute(insert(outbox_events).values(**self._ev(e)))
    def pending_events(self):
        with self.engine.connect() as c:rows=c.execute(select(outbox_events).where(outbox_events.c.status!=DeliveryStatus.DELIVERED.value)).mappings().all()
        return tuple(self._event(x) for x in rows)
    def replace_event(self,x):
        with self.engine.begin() as c:c.execute(update(outbox_events).where(outbox_events.c.event_id==x.event_id).values(**self._ev(x)))
    def checkpoint(self,cname,eid):
        with self.engine.connect() as c:r=c.execute(select(consumer_checkpoints).where(consumer_checkpoints.c.consumer==cname,consumer_checkpoints.c.event_id==eid)).mappings().one_or_none()
        return None if r is None else ConsumerCheckpoint(r.consumer,r.event_id,self._a(r.processed_at),r.result_hash,r.checkpoint_id)
    def save_checkpoint(self,x):
        try:
            with self.engine.begin() as c:c.execute(insert(consumer_checkpoints).values(checkpoint_id=x.checkpoint_id,consumer=x.consumer,event_id=x.event_id,processed_at=x.processed_at,result_hash=x.result_hash))
        except IntegrityError:pass
    def save_batch(self,x):
        with self.engine.begin() as c:c.execute(insert(dataset_batches).values(batch_id=x.batch_id,source=x.source,dataset=x.dataset,checksum=x.checksum,window_start=x.window_start,window_end=x.window_end,status=x.status.value,quality=x.quality.value,published_at=x.published_at))
    def latest_batch(self,d):
        with self.engine.connect() as c:r=c.execute(select(dataset_batches).where(dataset_batches.c.dataset==d).order_by(dataset_batches.c.window_end.desc())).mappings().first()
        return None if r is None else DatasetBatch(r.source,r.dataset,r.checksum,self._a(r.window_start),self._a(r.window_end),BatchStatus(r.status),QualityStatus(r.quality),self._a(r.published_at),r.batch_id)
    def save_configuration(self,x):
        with self.engine.begin() as c:c.execute(insert(configuration_versions).values(configuration_id=x.configuration_id,environment=x.environment,version=x.version,values=dict(x.values),secret_refs=dict(x.secret_refs),effective_from=x.effective_from,effective_to=x.effective_to,content_hash=x.content_hash))
    def active_configuration(self,e,a):
        q=select(configuration_versions).where(configuration_versions.c.environment==e,configuration_versions.c.effective_from<=a,(configuration_versions.c.effective_to.is_(None))|(configuration_versions.c.effective_to>a)).order_by(configuration_versions.c.version.desc())
        with self.engine.connect() as c:r=c.execute(q).mappings().first()
        return None if r is None else ConfigurationVersion(r.environment,r.version,r["values"],r.secret_refs,self._a(r.effective_from),self._a(r.effective_to),r.content_hash,r.configuration_id)
    def save_backup(self,x):
        with self.engine.begin() as c:c.execute(insert(backup_records).values(backup_id=x.backup_id,started_at=x.started_at,finished_at=x.finished_at,succeeded=x.succeeded,checksum=x.checksum,schema_version=x.schema_version,restored_at=x.restored_at))
    def latest_backup(self):
        with self.engine.connect() as c:r=c.execute(select(backup_records).order_by(backup_records.c.finished_at.desc())).mappings().first()
        return None if r is None else BackupRecord(r.backup_id,self._a(r.started_at),self._a(r.finished_at),r.succeeded,r.checksum,r.schema_version,self._a(r.restored_at))
    def save_alert(self,x):
        with self.engine.begin() as c:c.execute(insert(alert_records).values(alert_id=x.alert_id,category=x.category,message=x.message,occurred_at=x.occurred_at,correlation_id=x.correlation_id,primary_delivered=x.primary_delivered,fallback_persisted=x.fallback_persisted))
    def save_audit(self,x):
        with self.engine.begin() as c:c.execute(insert(audit_logs).values(audit_id=x.audit_id,actor=x.actor,service=x.service,command=x.command,object_id=x.object_id,result=x.result,occurred_at=x.occurred_at,correlation_id=x.correlation_id))
