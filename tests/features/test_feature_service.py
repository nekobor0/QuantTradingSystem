from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from quant_trading_system.features import *
from quant_trading_system.features.errors import *
NOW=datetime(2024,1,10,8,tzinfo=timezone.utc);ASOF=date(2024,1,10)
def observations(universe,data_id,available=NOW,extra_future=False):
 rows=[]
 for n,iid in enumerate(universe.member_ids):
  for day,value in ((8,10+n),(9,11+n),(10,12+n)):rows.append(InputObservation(iid,"close",date(2024,1,day),available,Decimal(value),f"{iid}-{day}",data_id))
 if extra_future:rows.append(InputObservation(universe.member_ids[0],"close",date(2024,1,11),NOW+timedelta(days=1),Decimal(999),"future",data_id))
 return tuple(rows)
def command(version,universe,data_id,rows,**kw):
 values=dict(purpose=FeaturePurpose.ETF_TIMING,version_ids=(version.version_id,),as_of_date=ASOF,decision_at=NOW,universe=universe,data_snapshot_id=data_id,observations=rows,factor_version="adj-v1");values.update(kw);return CalculateFeatureSet(**values)
def test_calculate_fixed_matrix(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();result=s.calculate_feature_set(command(v,u,data,observations(u,data)));_,rows=s.get_feature_matrix(result.feature_set_id);assert len(rows)==2 and all(x.quality is QualityFlag.OK for x in rows)
def test_momentum_values_are_hand_calculated(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();result=s.calculate_feature_set(command(v,u,data,observations(u,data)));vals=[x.value for x in s.get_feature_matrix(result.feature_set_id)[1]];assert abs(vals[0]-Decimal("0.2"))<Decimal("1e-9") and abs(vals[1]-(Decimal(13)/Decimal(11)-1))<Decimal("1e-9")
def test_idempotent_input_hash(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();c=command(v,u,data,observations(u,data));assert s.calculate_feature_set(c).feature_set_id==s.calculate_feature_set(c).feature_set_id
def test_future_append_does_not_change_historical_hash(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();a=s.calculate_feature_set(command(v,u,data,observations(u,data)));b=s.calculate_feature_set(command(v,u,data,observations(u,data,extra_future=True)));assert a.feature_set_id==b.feature_set_id
def test_available_future_input_rejected(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();rows=list(observations(u,data));rows[0]=replace(rows[0],available_at=NOW+timedelta(seconds=1))
 with pytest.raises(FeatureCalculationRejected):s.calculate_feature_set(command(v,u,data,tuple(rows)))
def test_data_snapshot_mismatch_rejected(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();rows=list(observations(u,data));rows[0]=replace(rows[0],data_snapshot_id=uuid4())
 with pytest.raises(FeatureCalculationRejected):s.calculate_feature_set(command(v,u,data,tuple(rows)))
def test_universe_purpose_mismatch(feature_setup):
 s,r,d,v,u=feature_setup;bad=replace(u,purpose=FeaturePurpose.EQUITY_DAILY_SELECTION);data=uuid4()
 with pytest.raises(SnapshotPurposeMismatch):s.calculate_feature_set(command(v,bad,data,observations(bad,data)))
def test_version_purpose_mismatch(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4()
 with pytest.raises(SnapshotPurposeMismatch):s.calculate_feature_set(command(v,u,data,observations(u,data),purpose=FeaturePurpose.EQUITY_DAILY_SELECTION))
def test_binding_cannot_be_changed_at_runtime(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4()
 with pytest.raises(FeatureCalculationRejected):s.calculate_feature_set(command(v,u,data,observations(u,data),version_ids=()))
def test_missing_reject_emits_rejected_event(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4()
 with pytest.raises(FeatureCalculationRejected):s.calculate_feature_set(command(v,u,data,()))
 assert r.latest_event().event_type=="FeatureSetRejected"
def test_keep_null_preserves_rows(repository):
 s=FeatureService(repository);d=FeatureDefinition("roe",FeaturePurpose.EQUITY_DAILY_SELECTION,FormulaKind.ROE,"quality",1,"1d","x");v=FeatureVersion(d.definition_id,"1","c",{}, {},1,MissingPolicy.KEEP_NULL);s.register(d,(v,));s.bind_required(d.purpose,(v.version_id,));u=UniverseSnapshotInput(uuid4(),d.purpose,(uuid4(),uuid4()),"h");data=uuid4();c=CalculateFeatureSet(d.purpose,(v.version_id,),ASOF,NOW,u,data,());result=s.calculate_feature_set(c);rows=s.get_feature_matrix(result.feature_set_id)[1];assert len(rows)==2 and all(x.quality is QualityFlag.MISSING_INPUT for x in rows)
def test_explain_returns_lineage(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();result=s.calculate_feature_set(command(v,u,data,observations(u,data)));row=s.explain_feature_value(result.feature_set_id,u.member_ids[0],v.version_id);assert len(row.input_refs)==3 and row.steps
def test_unknown_feature_set(feature_setup):
 s,*_=feature_setup
 with pytest.raises(FeatureSetNotFound):s.get_feature_matrix(uuid4())
def test_input_member_outside_snapshot_is_ignored(feature_setup):
 s,r,d,v,u=feature_setup;data=uuid4();rows=observations(u,data)+(InputObservation(uuid4(),"close",ASOF,NOW,Decimal(999),"outside",data),);result=s.calculate_feature_set(command(v,u,data,rows));assert len(s.get_feature_matrix(result.feature_set_id)[1])==2
