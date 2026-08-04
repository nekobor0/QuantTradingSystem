class InMemoryReportingRepository:
 def __init__(self):self.definitions={};self.runs={};self.input_runs={};self.results={};self.events=[]
 def save_definition(self,x):self.definitions[x.definition_id]=x
 def find_run(self,h):return self.input_runs.get(h)
 def save_result(self,x,event):self.runs[x.run.run_id]=x.run;self.input_runs[x.run.input_hash]=x.run;self.results[x.run.run_id]=x;self.events.append(event)
 def get_result(self,i):return self.results.get(i)

