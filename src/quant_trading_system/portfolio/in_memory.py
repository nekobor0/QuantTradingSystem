class InMemoryPortfolioRepository:
 def __init__(self):self.targets={};self.hashes={};self.results={};self.events=[];self.rejections={};self.policies={}
 def save_policy(self,p):self.policies.setdefault(p.policy_id,p)
 def find(self,h):return self.hashes.get(h)
 def save(self,result,event):self.targets[result.target.target_id]=result.target;self.hashes[result.target.input_hash]=result.target;self.results[result.target.target_id]=result;self.events.append(event)
 def save_rejected(self,event,input_hash):self.events.append(event);self.rejections[input_hash]=event
 def get(self,i):return self.results.get(i)
 def latest_event(self):return self.events[-1] if self.events else None
