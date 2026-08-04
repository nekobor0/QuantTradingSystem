from dataclasses import replace
from .domain import *
from .errors import RepositoryConflict
class InMemoryUniverseRepository:
 def __init__(self):self.definitions={};self.batch_values={};self.period_values=[];self.snapshot_values={};self.classification_values=[];self.quality={};self.events=[]
 def save_definition(self,x):
  if x.universe_id in self.definitions:raise RepositoryConflict("definition exists")
  self.definitions[x.universe_id]=x
 def get_definition(self,i):return self.definitions.get(i)
 def list_definitions(self):return tuple(self.definitions.values())
 def get_batch(self,i,s):return self.batch_values.get((i,s))
 def active_periods_before(self,i,d):return tuple(x for x in self.period_values if x.universe_id==i and x.active(d))
 def apply_batch(self,batch,closed,opened,event):
  key=(batch.universe_id,batch.source_batch_id)
  if key in self.batch_values:raise RepositoryConflict("batch exists")
  closed_by_id={x.membership_id:x for x in closed};self.period_values=[closed_by_id.get(x.membership_id,x) for x in self.period_values];self.period_values.extend(opened);self.batch_values[key]=batch;self.events.append(event)
 def reject_batch(self,batch,results):self.batch_values[(batch.universe_id,batch.source_batch_id)]=batch;self.quality[batch.batch_id]=tuple(results)
 def periods(self,i):return tuple(x for x in self.period_values if x.universe_id==i)
 def batches(self,i):return tuple(x for x in self.batch_values.values() if x.universe_id==i)
 def save_snapshot(self,x):
  if x.snapshot_id in self.snapshot_values:raise RepositoryConflict("snapshot exists")
  self.snapshot_values[x.snapshot_id]=x
 def get_snapshot(self,i):return self.snapshot_values.get(i)
 def save_classification(self,x):self.classification_values.append(x)
 def classifications(self,i):return tuple(x for x in self.classification_values if x.instrument_id==i)
 def quality_results(self,i):return self.quality.get(i,())
