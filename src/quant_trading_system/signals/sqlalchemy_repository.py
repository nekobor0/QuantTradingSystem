from datetime import timezone
from decimal import Decimal
from sqlalchemy import insert,select,update
from sqlalchemy.exc import IntegrityError
from .domain import *
from .errors import ApprovalConflict,RepositoryConflict
from .tables import approvals,components,events,recommendations,risk_refs,signals,supersessions
class SqlAlchemySignalRepository:
 def __init__(self,engine):self.engine=engine
 @staticmethod
 def _a(x):return x.replace(tzinfo=timezone.utc) if x.tzinfo is None else x
 def find(self,h):
  with self.engine.connect() as c:r=c.execute(select(signals).where(signals.c.input_hash==h)).mappings().one_or_none()
  return None if r is None else self._signal(r)
 def save_draft(self,result,event):
  try:
   with self.engine.begin() as c:
    c.execute(insert(signals).values(self._sv(result.signal)))
    if result.components:c.execute(insert(components),[self._cv(result.signal.signal_id,x) for x in result.components])
    if result.recommendations:c.execute(insert(recommendations),[self._rv(x) for x in result.recommendations])
    c.execute(insert(events).values(self._ev(event)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def update_signal(self,s,event):
  with self.engine.begin() as c:
   c.execute(update(signals).where(signals.c.signal_id==s.signal_id).values(status=s.status.value,risk_result_id=s.risk_result_id,risk_decision=None if s.risk_decision is None else s.risk_decision.value))
   if s.risk_result_id is not None and c.execute(select(risk_refs.c.signal_id).where(risk_refs.c.signal_id==s.signal_id)).scalar_one_or_none() is None:c.execute(insert(risk_refs).values(signal_id=s.signal_id,risk_result_id=s.risk_result_id,decision=s.risk_decision.value))
   c.execute(insert(events).values(self._ev(event)))
 def get_result(self,i):
  with self.engine.connect() as c:
   s=c.execute(select(signals).where(signals.c.signal_id==i)).mappings().one_or_none()
   if s is None:return None
   rs=c.execute(select(recommendations).where(recommendations.c.signal_id==i)).mappings().all();cs=c.execute(select(components).where(components.c.signal_id==i)).mappings().all()
  return SignalResult(self._signal(s),tuple(self._rec(x) for x in rs),tuple(self._component(x) for x in cs))
 def get_recommendation(self,i):
  with self.engine.connect() as c:r=c.execute(select(recommendations).where(recommendations.c.recommendation_id==i)).mappings().one_or_none()
  return None if r is None else self._rec(r)
 def apply_approval(self,rec,approval,event):
  try:
   with self.engine.begin() as c:
    changed=c.execute(update(recommendations).where(recommendations.c.recommendation_id==rec.recommendation_id,recommendations.c.version==approval.expected_version).values(status=rec.status.value,approved_quantity=rec.approved_quantity,handed_off_quantity=rec.handed_off_quantity,version=rec.version))
    if changed.rowcount!=1:raise ApprovalConflict("APPROVAL_CONFLICT")
    c.execute(insert(approvals).values(approval_id=approval.approval_id,recommendation_id=approval.recommendation_id,decision_id=approval.decision_id,kind=approval.kind.value,quantity=approval.quantity,reason=approval.reason,operator_id=approval.operator_id,decided_at=approval.decided_at,expected_version=approval.expected_version));c.execute(insert(events).values(self._ev(event)))
  except IntegrityError as e:raise RepositoryConflict(str(e.orig)) from e
 def get_approval(self,i):
  with self.engine.connect() as c:r=c.execute(select(approvals).where(approvals.c.decision_id==i)).mappings().one_or_none()
  return None if r is None else ApprovalDecision(r.recommendation_id,r.decision_id,ApprovalKind(r.kind),r.quantity,r.reason,r.operator_id,self._a(r.decided_at),r.expected_version,r.approval_id)
 def save_supersession(self,value,old,new,event):
  with self.engine.begin() as c:c.execute(update(signals).where(signals.c.signal_id==old.signal_id).values(status=old.status.value));c.execute(insert(supersessions).values(supersession_id=value.supersession_id,old_signal_id=value.old_signal_id,new_signal_id=value.new_signal_id,reason=value.reason,superseded_at=value.superseded_at));c.execute(insert(events).values(self._ev(event)))
 def all_results(self):
  with self.engine.connect() as c:ids=c.execute(select(signals.c.signal_id)).scalars().all()
  return tuple(x for i in ids if (x:=self.get_result(i)) is not None)
 def latest_event(self):
  with self.engine.connect() as c:r=c.execute(select(events).order_by(events.c.occurred_at.desc())).mappings().first()
  return None if r is None else SignalEvent(r.event_type,r.signal_id,self._a(r.occurred_at),r.payload,r.event_id)
 @staticmethod
 def _sv(x):return {"signal_id":x.signal_id,"target_id":x.target_id,"account_snapshot_id":x.account_snapshot_id,"pricing_snapshot_id":x.pricing_snapshot_id,"decision_at":x.decision_at,"valid_for_date":x.valid_for_date,"expires_at":x.expires_at,"status":x.status.value,"input_hash":x.input_hash,"content_hash":x.content_hash,"account_reconciled":x.account_reconciled,"oldest_price_at":x.oldest_price_at,"max_price_age_seconds":x.max_price_age_seconds,"reprice_threshold":x.reprice_threshold,"risk_result_id":x.risk_result_id,"risk_decision":None if x.risk_decision is None else x.risk_decision.value}
 @classmethod
 def _signal(cls,r):return Signal(r.target_id,r.account_snapshot_id,r.pricing_snapshot_id,cls._a(r.decision_at),r.valid_for_date,cls._a(r.expires_at),SignalStatus(r.status),r.input_hash,r.content_hash,r.account_reconciled,cls._a(r.oldest_price_at),r.max_price_age_seconds,Decimal(r.reprice_threshold),r.risk_result_id,None if r.risk_decision is None else RiskDecision(r.risk_decision),r.signal_id)
 @staticmethod
 def _rv(x):return {"recommendation_id":x.recommendation_id,"signal_id":x.signal_id,"instrument_id":x.instrument_id,"side":x.side.value,"target_weight":x.target_weight,"current_weight":x.current_weight,"delta_weight":x.delta_weight,"quantity":x.quantity,"limit_price":x.limit_price,"estimated_fee":x.estimated_fee,"reason_codes":list(x.reason_codes),"status":x.status.value,"approved_quantity":x.approved_quantity,"handed_off_quantity":x.handed_off_quantity,"version":x.version}
 @staticmethod
 def _rec(r):return Recommendation(r.signal_id,r.instrument_id,Side(r.side),Decimal(r.target_weight),Decimal(r.current_weight),Decimal(r.delta_weight),r.quantity,Decimal(r.limit_price),Decimal(r.estimated_fee),tuple(r.reason_codes),RecommendationStatus(r.status),r.approved_quantity,r.handed_off_quantity,r.version,r.recommendation_id)
 @staticmethod
 def _cv(signal_id,x):return {"component_id":x.component_id,"signal_id":signal_id,"strategy_kind":x.strategy_kind.value,"run_id":x.run_id,"instrument_id":x.instrument_id,"state":x.state,"weight_contribution":x.weight_contribution,"reason_codes":list(x.reason_codes)}
 @staticmethod
 def _component(r):return SignalComponent(StrategyKind(r.strategy_kind),r.run_id,r.instrument_id,r.state,Decimal(r.weight_contribution),tuple(r.reason_codes),r.component_id)
 @staticmethod
 def _ev(x):return {"event_id":x.event_id,"event_type":x.event_type,"signal_id":x.signal_id,"occurred_at":x.occurred_at,"payload":dict(x.payload)}
