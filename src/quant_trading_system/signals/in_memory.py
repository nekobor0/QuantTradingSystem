class InMemorySignalRepository:
 def __init__(self):self.signals={};self.hashes={};self.results={};self.recommendations={};self.approvals={};self.supersessions=[];self.events=[]
 def find(self,h):return self.hashes.get(h)
 def save_draft(self,result,event):self.signals[result.signal.signal_id]=result.signal;self.hashes[result.signal.input_hash]=result.signal;self.results[result.signal.signal_id]=result;self.recommendations.update({x.recommendation_id:x for x in result.recommendations});self.events.append(event)
 def update_signal(self,signal,event):self.signals[signal.signal_id]=signal;old=self.results[signal.signal_id];self.results[signal.signal_id]=type(old)(signal,old.recommendations,old.components);self.events.append(event)
 def get_result(self,i):return self.results.get(i)
 def get_recommendation(self,i):return self.recommendations.get(i)
 def apply_approval(self,recommendation,approval,event):self.recommendations[recommendation.recommendation_id]=recommendation;result=self.results[recommendation.signal_id];self.results[recommendation.signal_id]=type(result)(result.signal,tuple(recommendation if x.recommendation_id==recommendation.recommendation_id else x for x in result.recommendations),result.components);self.approvals[approval.decision_id]=approval;self.events.append(event)
 def get_approval(self,i):return self.approvals.get(i)
 def save_supersession(self,value,old,new,event):self.supersessions.append(value);self.update_signal(old,event);self.signals[new.signal_id]=new
 def all_results(self):return tuple(self.results.values())
 def latest_event(self):return self.events[-1] if self.events else None
