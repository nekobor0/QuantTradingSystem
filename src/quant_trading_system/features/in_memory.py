from .errors import RepositoryConflict
class InMemoryFeatureRepository:
 def __init__(self):self.definitions={};self.versions={};self.bindings={};self.sets={};self.hashes={};self.value_rows={};self.events=[]
 def save_definition(self,d,versions):
  if d.definition_id in self.definitions:raise RepositoryConflict("definition exists")
  self.definitions[d.definition_id]=d
  for x in versions:self.versions[x.version_id]=x
 def get_definition(self,i):return self.definitions.get(i)
 def get_version(self,i):return self.versions.get(i)
 def bind(self,purpose,version_ids):self.bindings[purpose]=tuple(version_ids)
 def binding(self,purpose):return self.bindings.get(purpose,())
 def find_set(self,h):return self.hashes.get(h)
 def save_set(self,s,values,event):self.sets[s.feature_set_id]=s;self.hashes[s.input_hash]=s;self.value_rows[s.feature_set_id]=tuple(values);self.events.append(event)
 def get_set(self,i):return self.sets.get(i)
 def values(self,i):return self.value_rows.get(i,())
 def save_rejected_event(self,event):self.events.append(event)
 def latest_event(self):return self.events[-1] if self.events else None
