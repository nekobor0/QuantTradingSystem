from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
import pytest
from quant_trading_system.platform_operations.domain import *
from quant_trading_system.platform_operations.errors import FencingConflict,LeaseConflict,StateConflict
from .conftest import DAY,NOW

def start_claim(stack,kind=TaskType.RUN_ETF_DAILY_GATE,key="h",max_attempts=3):
 task=stack[3].start_task(kind,DAY,key,"corr",max_attempts);return stack[3].acquire(task.task_run_id,"worker-1",NOW)
def test_start_is_idempotent(stack):
 a=stack[3].start_task(TaskType.RUN_ETF_DAILY_GATE,DAY,"h","c");b=stack[3].start_task(TaskType.RUN_ETF_DAILY_GATE,DAY,"h","c")
 assert a.task_run_id==b.task_run_id and len(stack[0].tasks)==1
 assert len(stack[0].audits)==1
def test_schedule_daily_only_adds_weekly_rebalance_when_due(stack):
 hashes={TaskType.RUN_ETF_DAILY_GATE:"e",TaskType.RUN_EQUITY_DAILY_SELECTION:"q",TaskType.RUN_ETF_SCHEDULED_REBALANCE:"r"}
 assert len(stack[3].schedule_daily(DAY,hashes,"c",False))==2
 assert len(stack[3].schedule_daily(DAY,hashes,"c",True))==3
def test_active_lease_cannot_be_stolen(stack):
 task=start_claim(stack)
 with pytest.raises(LeaseConflict):stack[3].acquire(task.task_run_id,"worker-2",NOW+timedelta(minutes=1))
def test_expired_lease_takeover_increments_fence(stack):
 task=start_claim(stack);new=stack[3].acquire(task.task_run_id,"worker-2",NOW+timedelta(minutes=10))
 assert new.fencing_token==2 and new.lease_owner=="worker-2"
def test_old_worker_cannot_overwrite_takeover(stack):
 task=start_claim(stack);stack[3].acquire(task.task_run_id,"worker-2",NOW+timedelta(minutes=10))
 with pytest.raises(FencingConflict):stack[3].complete(task.task_run_id,"worker-1",task.fencing_token,{},NOW+timedelta(minutes=10,seconds=1))
def test_complete_writes_fact_and_outbox_atomically(stack):
 task=start_claim(stack);done=stack[3].complete(task.task_run_id,"worker-1",task.fencing_token,{"result":"ok"},NOW+timedelta(seconds=1))
 assert done.status is TaskStatus.SUCCEEDED and len(stack[0].events)==1
def test_failure_is_retryable_and_preserves_old_attempt(stack):
 task=start_claim(stack);failed=stack[3].fail(task.task_run_id,"worker-1",task.fencing_token,"Timeout",NOW+timedelta(seconds=1));retry=stack[3].retry(failed.task_run_id,TaskStatus.FAILED_RETRYABLE)
 assert retry.attempt==2 and retry.previous_run_id==failed.task_run_id and len(stack[0].tasks)==2
def test_max_attempt_failure_is_final(stack):
 task=start_claim(stack,max_attempts=1);failed=stack[3].fail(task.task_run_id,"worker-1",task.fencing_token,"BadInput",NOW+timedelta(seconds=1))
 assert failed.status is TaskStatus.FAILED_FINAL
 with pytest.raises(StateConflict):stack[3].retry(failed.task_run_id,TaskStatus.FAILED_FINAL)
def complete_kind(stack,kind,key):
 task=start_claim(stack,kind,key);return stack[3].complete(task.task_run_id,"worker-1",task.fencing_token,{},NOW+timedelta(seconds=1))
@pytest.mark.parametrize("missing",[TaskType.RUN_ETF_DAILY_GATE,TaskType.RUN_EQUITY_DAILY_SELECTION])
def test_combined_blocked_when_either_strategy_missing(stack,missing):
 other=TaskType.RUN_EQUITY_DAILY_SELECTION if missing is TaskType.RUN_ETF_DAILY_GATE else TaskType.RUN_ETF_DAILY_GATE;complete_kind(stack,other,"other")
 with pytest.raises(StateConflict):stack[3].start_combined(DAY,"combined","corr")
 assert missing.value in stack[0].alerts[-1].message
def test_combined_starts_once_after_both_succeed(stack):
 complete_kind(stack,TaskType.RUN_ETF_DAILY_GATE,"e");complete_kind(stack,TaskType.RUN_EQUITY_DAILY_SELECTION,"q")
 a=stack[3].start_combined(DAY,"combined","c");b=stack[3].start_combined(DAY,"combined","c")
 assert a.task_run_id==b.task_run_id
class Transport:
 def __init__(self,fail=False):self.fail=fail;self.events=[]
 def publish(self,e):
  if self.fail:raise RuntimeError()
  self.events.append(e.event_id)
def event(stack):
 task=start_claim(stack);stack[3].complete(task.task_run_id,"worker-1",task.fencing_token,{},NOW+timedelta(seconds=1));return next(iter(stack[0].events.values()))
def test_outbox_eventually_delivered_after_transport_failure(stack):
 event(stack);assert stack[3].publish_outbox(Transport(True),10,"d",NOW+timedelta(seconds=2))==0
 transport=Transport();assert stack[3].publish_outbox(transport,10,"d",NOW+timedelta(seconds=3))==1
def test_duplicate_consumption_has_no_side_effect(stack):
 value=event(stack);calls=[];handler=lambda e:(calls.append(e.event_id) or "ok")
 a=stack[3].consume_once("consumer",value,handler,NOW);b=stack[3].consume_once("consumer",value,handler,NOW)
 assert a==b and len(calls)==1
def seed_ready(stack):
 complete_kind(stack,TaskType.RUN_ETF_DAILY_GATE,"e");complete_kind(stack,TaskType.RUN_EQUITY_DAILY_SELECTION,"q")
 stack[0].save_batch(DatasetBatch("source","prices","h",NOW-timedelta(hours=1),NOW,BatchStatus.PUBLISHED,QualityStatus.PASS,NOW))
 stack[0].save_backup(BackupRecord(uuid4(),NOW-timedelta(hours=1),NOW,True,"h","014",NOW))
def test_readiness_passes_complete_state(stack):seed_ready(stack);assert stack[3].readiness(DAY,("prices",),NOW).ready
@pytest.mark.parametrize("failure",["db","reconciled","risk"])
def test_readiness_fails_health_inputs(stack,failure):
 seed_ready(stack);setattr(stack[1],failure,False);result=stack[3].readiness(DAY,("prices",),NOW);assert not result.ready
def test_readiness_fails_stale_dataset(stack):
 seed_ready(stack);stack[0].save_batch(DatasetBatch("source","fundamentals","x",NOW-timedelta(days=3),NOW-timedelta(days=2),BatchStatus.PUBLISHED,QualityStatus.PASS,NOW-timedelta(days=2)))
 assert not stack[3].readiness(DAY,("fundamentals",),NOW).ready
def test_readiness_fails_outbox_backlog(stack):seed_ready(stack);event(stack);assert not stack[3].readiness(DAY,("prices",),NOW+timedelta(minutes=16)).ready
def test_readiness_fails_backup_without_restore(stack):
 seed_ready(stack);stack[0].save_backup(BackupRecord(uuid4(),NOW,NOW,True,"new","014",None));assert not stack[3].readiness(DAY,("prices",),NOW).ready
def test_alert_failure_has_persistent_fallback(stack):stack[2].ok=False;record=stack[3].alert("BACKUP_FAILED","password=bad","c",NOW);assert record.fallback_persisted and "bad" not in record.message
