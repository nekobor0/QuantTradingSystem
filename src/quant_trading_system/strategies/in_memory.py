from .errors import RepositoryConflict
class InMemoryStrategyRepository:
 def __init__(self):self.definitions={};self.versions={};self.runs={};self.hashes={};self.results={};self.events=[];self.evidence_values=[]
 def save_definition(self,d,versions):
  if d.definition_id in self.definitions:raise RepositoryConflict("definition exists")
  self.definitions[d.definition_id]=d
  for x in versions:self.versions[x.version_id]=x
 def get_definition(self,i):return self.definitions.get(i)
 def get_version(self,i):return self.versions.get(i)
 def find_run(self,h):return self.hashes.get(h)
 def active_run(self,kind,decision_at):
  superseded={x.supersedes_run_id for x in self.runs.values() if x.supersedes_run_id is not None}
  return next((x for x in self.runs.values() if x.kind is kind and x.decision_at==decision_at and x.status.value=="COMPLETED" and x.run_id not in superseded),None)
 def save_result(self,result,event):self.runs[result.run.run_id]=result.run;self.hashes[result.run.input_hash]=result.run;self.results[result.run.run_id]=result;self.events.append(event)
 def save_failed(self,run,event):self.runs[run.run_id]=run;self.hashes[run.input_hash]=run;self.events.append(event)
 def get_result(self,i):return self.results.get(i)
 def save_evidence(self,e):self.evidence_values.append(e)
 def evidence(self,i):return tuple(x for x in self.evidence_values if x.strategy_version_id==i)
 def latest_event(self):return self.events[-1] if self.events else None
