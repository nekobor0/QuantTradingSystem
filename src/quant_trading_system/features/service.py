from __future__ import annotations
import hashlib,json
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal
from math import sqrt
from uuid import UUID,uuid4
from .domain import *
from .errors import *
from .formulas import calculate
from .ports import FeatureRepository
FIELDS={FormulaKind.MOMENTUM:("close",),FormulaKind.VOLATILITY:("close",),FormulaKind.MAX_DRAWDOWN:("close",),FormulaKind.LIQUIDITY:("turnover",),FormulaKind.EARNINGS_YIELD:("net_income","market_cap"),FormulaKind.ROE:("roe",),FormulaKind.GROWTH:("growth",)}
class FeatureService:
 def __init__(self,repository:FeatureRepository):self.repository=repository
 def register(self,d:FeatureDefinition,versions:tuple[FeatureVersion,...]):
  if any(x.definition_id!=d.definition_id for x in versions):raise InvalidFeature("version definition mismatch")
  self.repository.save_definition(d,versions)
 def bind_required(self,purpose:FeaturePurpose,version_ids:tuple[UUID,...]):
  if not version_ids:raise InvalidFeature("binding must not be empty")
  for i in version_ids:
   v=self.repository.get_version(i);d=None if v is None else self.repository.get_definition(v.definition_id)
   if v is None or d is None or d.purpose is not purpose or not v.active:raise SnapshotPurposeMismatch("binding contains wrong-purpose or inactive version")
  self.repository.bind(purpose,version_ids)
 def get_required_feature_set(self,purpose:FeaturePurpose)->tuple[UUID,...]:return tuple(self.repository.binding(purpose))
 def calculate_feature_set(self,c:CalculateFeatureSet)->FeatureSet:
  decision=aware(c.decision_at,"decision_at")
  if c.universe.purpose is not c.purpose:raise SnapshotPurposeMismatch("universe purpose mismatch")
  if len(set(c.universe.member_ids))!=len(c.universe.member_ids):raise FeatureCalculationRejected("duplicate universe member")
  versions=[]
  for i in c.version_ids:
   v=self.repository.get_version(i);d=None if v is None else self.repository.get_definition(v.definition_id)
   if v is None or d is None or d.purpose is not c.purpose or not v.active:raise SnapshotPurposeMismatch("feature version purpose mismatch")
   versions.append((v,d))
  if tuple(c.version_ids)!=tuple(self.repository.binding(c.purpose)):raise FeatureCalculationRejected("versions differ from frozen purpose binding")
  selected=[x for x in c.observations if x.instrument_id in c.universe.member_ids and x.observed_on<=c.as_of_date]
  if any(x.data_snapshot_id!=c.data_snapshot_id for x in selected):raise FeatureCalculationRejected("data snapshot mismatch")
  if any(x.available_at>decision for x in selected):raise FeatureCalculationRejected("future input is not available at decision_at")
  input_payload={"purpose":c.purpose.value,"versions":[str(x) for x in c.version_ids],"as_of":c.as_of_date.isoformat(),"decision":decision.isoformat(),"universe":c.universe.content_hash,"data":str(c.data_snapshot_id),"factor_version":c.factor_version,"observations":[(str(x.instrument_id),x.field_name,x.observed_on.isoformat(),str(x.value),x.source_ref) for x in sorted(selected,key=lambda x:(str(x.instrument_id),x.field_name,x.observed_on,x.source_ref))]}
  input_hash=hashlib.sha256(json.dumps(input_payload,sort_keys=True).encode()).hexdigest();existing=self.repository.find_set(input_hash)
  if existing:return existing
  set_id=uuid4();rows=[];reasons=[]
  for version,definition in versions:
   window=int(version.parameters.get("window","1"));version_rows=[]
   for instrument_id in c.universe.member_ids:
    required=FIELDS[definition.formula];observations=[]
    for field_name in required:
     candidates=[x for x in selected if x.instrument_id==instrument_id and x.field_name==field_name]
     observations.extend(sorted(candidates,key=lambda x:x.observed_on))
    try:
     value,steps=calculate(definition.formula,observations,window)
     row=FeatureValue(set_id,instrument_id,c.as_of_date,version.version_id,c.data_snapshot_id,value,QualityFlag.OK,tuple(x.source_ref for x in observations),steps)
    except InvalidFeature as exc:
     flag=QualityFlag.INSUFFICIENT_HISTORY if "INSUFFICIENT_HISTORY" in str(exc) else QualityFlag.MISSING_INPUT
     if version.missing_policy is MissingPolicy.REJECT:reasons.append(f"{definition.name}:{instrument_id}:{flag.value}");continue
     row=FeatureValue(set_id,instrument_id,c.as_of_date,version.version_id,c.data_snapshot_id,None,flag,tuple(x.source_ref for x in observations),(str(exc),))
    version_rows.append(row)
   if version.transform is TransformKind.WINSOR_ZSCORE:
    try:version_rows=self._transform(version_rows,version)
    except InvalidFeature as exc:reasons.append(f"{definition.name}:{exc}")
   rows.extend(version_rows)
  if reasons:
   self.repository.save_rejected_event(FeatureEvent("FeatureSetRejected",set_id,datetime.now(timezone.utc),tuple(reasons)))
   raise FeatureCalculationRejected(";".join(reasons))
  if len(rows)!=len(c.universe.member_ids)*len(versions):raise FeatureCalculationRejected("fixed matrix shape violated")
  content=hashlib.sha256(json.dumps([(str(x.instrument_id),str(x.version_id),str(x.value),x.quality.value) for x in rows],sort_keys=True).encode()).hexdigest()
  result=FeatureSet(c.purpose,c.as_of_date,decision,c.universe.snapshot_id,c.data_snapshot_id,tuple(c.version_ids),tuple(c.universe.member_ids),input_hash,content,c.factor_version,set_id)
  self.repository.save_set(result,rows,FeatureEvent("FeatureSetCalculated",set_id,datetime.now(timezone.utc)));return result
 @staticmethod
 def _transform(rows:list[FeatureValue],version:FeatureVersion)->list[FeatureValue]:
  if any(x.value is None for x in rows):raise InvalidFeature("transform cannot consume null")
  ordered=sorted((x.value for x in rows if x.value is not None));n=len(ordered)
  if n<2:raise InvalidFeature("ZERO_VARIANCE")
  lower_q=Decimal(version.parameters.get("winsor_lower","0.05"));upper_q=Decimal(version.parameters.get("winsor_upper","0.95"))
  low=ordered[int((n-1)*lower_q)];high=ordered[int((n-1)*upper_q)];clipped=[min(high,max(low,x.value)) for x in rows if x.value is not None]
  mean=sum(clipped,Decimal())/n;variance=sum(((x-mean)**2 for x in clipped),Decimal())/n
  if variance==0:raise InvalidFeature("ZERO_VARIANCE")
  std=Decimal(str(sqrt(float(variance))))
  return [replace(row,value=(min(high,max(low,row.value))-mean)/std,steps=row.steps+(f"winsor[{low},{high}]",f"zscore mean={mean} std={std}"),value_id=uuid4()) for row in rows if row.value is not None]
 def get_feature_matrix(self,set_id:UUID):
  value=self.repository.get_set(set_id)
  if value is None:raise FeatureSetNotFound(str(set_id))
  return value,tuple(self.repository.values(set_id))
 def explain_feature_value(self,set_id:UUID,instrument_id:UUID,version_id:UUID)->FeatureValue:
  matches=[x for x in self.repository.values(set_id) if x.instrument_id==instrument_id and x.version_id==version_id]
  if len(matches)!=1:raise FeatureSetNotFound("feature value not found")
  return matches[0]
