from datetime import date, datetime
from .domain import *
from .errors import FencingConflict, StateConflict

class InMemoryOperationsRepository:
    def __init__(self): self.tasks={}; self.events={}; self.checkpoints={}; self.batches={}; self.configurations=[]; self.backups=[]; self.alerts=[]; self.audits=[]
    def latest_task(self,t,b,input_hash=None):
        rows=[x for x in self.tasks.values() if x.task_type==t and x.business_date==b and (input_hash is None or x.input_hash==input_hash)]
        return max(rows,key=lambda x:x.attempt,default=None)
    def get_task(self,i): return self.tasks.get(i)
    def save_task(self,x):
        if x.task_run_id in self.tasks: raise StateConflict("task already exists")
        self.tasks[x.task_run_id]=x
    def replace_task(self,x,expected_fencing_token):
        old=self.tasks.get(x.task_run_id)
        if old is None or old.fencing_token!=expected_fencing_token: raise FencingConflict()
        self.tasks[x.task_run_id]=x
    def save_task_and_event(self,x,e,expected_fencing_token): self.replace_task(x,expected_fencing_token); self.events[e.event_id]=e
    def pending_events(self): return tuple(x for x in self.events.values() if x.status is not DeliveryStatus.DELIVERED)
    def replace_event(self,x): self.events[x.event_id]=x
    def checkpoint(self,c,e): return self.checkpoints.get((c,e))
    def save_checkpoint(self,x): self.checkpoints.setdefault((x.consumer,x.event_id),x)
    def save_batch(self,x): self.batches[x.batch_id]=x
    def latest_batch(self,d): return max((x for x in self.batches.values() if x.dataset==d),key=lambda x:x.window_end,default=None)
    def save_configuration(self,x): self.configurations.append(x)
    def active_configuration(self,e,a): return max((x for x in self.configurations if x.environment==e and x.effective_from<=a and (x.effective_to is None or a<x.effective_to)),key=lambda x:x.version,default=None)
    def save_backup(self,x): self.backups.append(x)
    def latest_backup(self): return self.backups[-1] if self.backups else None
    def save_alert(self,x): self.alerts.append(x)
    def save_audit(self,x): self.audits.append(x)
