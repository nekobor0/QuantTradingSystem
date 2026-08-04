class InMemoryRiskRepository:
 def __init__(self):self.rules={};self.versions={};self.policies={};self.runs={};self.input_runs={};self.run_results={};self.results={};self.exceptions={};self.alerts={};self.alert_keys={};self.events=[]
 def save_rule(self,x):self.rules[x.rule_id]=x
 def save_rule_version(self,x):self.versions[x.version_id]=x
 def get_rule_version(self,i):return self.versions.get(i)
 def save_policy(self,x):self.policies[x.policy_version_id]=x
 def get_policy(self,i):return self.policies.get(i)
 def find_run(self,h):return self.input_runs.get(h)
 def save_run_result(self,v,alerts,event):
  self.runs[v.run.run_id]=v.run;self.input_runs[v.run.input_hash]=v.run;self.run_results[v.run.run_id]=v
  for x in v.results:self.results[x.result_id]=x
  for x in alerts:self.alerts[x.alert_id]=x;self.alert_keys[x.dedupe_key]=x
  self.events.append(event)
 def get_run_result(self,i):return self.run_results.get(i)
 def get_result(self,i):return self.results.get(i)
 def save_exception(self,x,event):self.exceptions[x.exception_id]=x;self.events.append(event)
 def get_exception(self,i):return self.exceptions.get(i)
 def exceptions_for(self,i):return tuple(x for x in self.exceptions.values() if x.result_id==i)
 def get_alert(self,i):return self.alerts.get(i)
 def find_alert(self,k):return self.alert_keys.get(k)
 def update_alert(self,x,event):self.alerts[x.alert_id]=x;self.alert_keys[x.dedupe_key]=x;self.events.append(event)
 def alerts_for_account(self,i):return tuple(x for x in self.alerts.values() if x.account_id==i)
 def runs_for_account(self,i):return tuple(x for x in self.runs.values() if x.account_id==i)
 def runs_for_target(self,i):return tuple(x for x in self.run_results.values() if x.run.object_id==i)
