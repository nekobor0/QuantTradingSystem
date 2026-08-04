from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import pytest
from quant_trading_system.signals import *
from quant_trading_system.signals.errors import InvalidSignal
NOW=datetime(2024,1,8,tzinfo=timezone.utc)
def fee(**changes):
 values=dict(commission_rate=Decimal(".001"),min_commission=Decimal(5),stamp_duty_rate=Decimal(".001"),price_buffer=Decimal(0),cash_buffer=Decimal(0),min_trade_value=Decimal(100),max_price_age_seconds=1,reprice_threshold=Decimal(".05"));values.update(changes);return FeePolicy(**values)
@pytest.mark.parametrize("field",["commission_rate","min_commission","stamp_duty_rate","price_buffer","cash_buffer","min_trade_value","reprice_threshold"])
def test_fee_values_nonnegative(field):
 with pytest.raises(InvalidSignal):fee(**{field:Decimal("-1")})
def test_fee_age_nonnegative():
 with pytest.raises(InvalidSignal):fee(max_price_age_seconds=-1)
@pytest.mark.parametrize("weight",["-0.1","1.1"])
def test_target_weight_bounds(weight):
 with pytest.raises(InvalidSignal):TargetWeightInput(uuid4(),Decimal(weight))
@pytest.mark.parametrize("source,nav,cash",[("manual","100","10"),("execution_ledger","0","10"),("execution_ledger","100","-1")])
def test_account_origin_and_money(source,nav,cash):
 with pytest.raises(InvalidSignal):AccountExecutionInput(uuid4(),source,NOW,True,Decimal(nav),Decimal(cash),{}, {})
def test_account_quantities_nonnegative():
 with pytest.raises(InvalidSignal):AccountExecutionInput(uuid4(),"execution_ledger",NOW,True,Decimal(100),Decimal(10),{uuid4():-1},{})
def test_account_time_aware():
 with pytest.raises(InvalidSignal):AccountExecutionInput(uuid4(),"execution_ledger",NOW.replace(tzinfo=None),True,Decimal(100),Decimal(10),{}, {})
@pytest.mark.parametrize("price",["0","-1"])
def test_price_positive(price):
 with pytest.raises(InvalidSignal):PriceInput(uuid4(),Decimal(price),NOW)
def test_price_time_aware():
 with pytest.raises(InvalidSignal):PriceInput(uuid4(),Decimal(1),NOW.replace(tzinfo=None))
def signal(**changes):
 values=dict(target_id=uuid4(),account_snapshot_id=uuid4(),pricing_snapshot_id=uuid4(),decision_at=NOW,valid_for_date=date(2024,1,9),expires_at=NOW+timedelta(hours=1),status=SignalStatus.DRAFT,input_hash="i",content_hash="c",account_reconciled=True,oldest_price_at=NOW,max_price_age_seconds=1,reprice_threshold=Decimal(".05"));values.update(changes);return Signal(**values)
def test_signal_expiry_after_decision():
 with pytest.raises(InvalidSignal):signal(expires_at=NOW)
def test_signal_times_aware():
 with pytest.raises(InvalidSignal):signal(decision_at=NOW.replace(tzinfo=None))
def recommendation(**changes):
 values=dict(signal_id=uuid4(),instrument_id=uuid4(),side=Side.BUY,target_weight=Decimal(".5"),current_weight=Decimal(0),delta_weight=Decimal(".5"),quantity=100,limit_price=Decimal(10),estimated_fee=Decimal(5),reason_codes=());values.update(changes);return Recommendation(**values)
@pytest.mark.parametrize("changes",[{"quantity":0},{"limit_price":Decimal(0)},{"estimated_fee":Decimal("-1")},{"approved_quantity":101},{"approved_quantity":10,"handed_off_quantity":11}])
def test_recommendation_invariants(changes):
 with pytest.raises(InvalidSignal):recommendation(**changes)
def test_approval_operator_required():
 with pytest.raises(InvalidSignal):ApprovalDecision(uuid4(),uuid4(),ApprovalKind.ACCEPT,1,"r","",NOW,0)
def test_approval_time_aware():
 with pytest.raises(InvalidSignal):ApprovalDecision(uuid4(),uuid4(),ApprovalKind.ACCEPT,1,"r","u",NOW.replace(tzinfo=None),0)
@pytest.mark.parametrize("status",list(SignalStatus))
def test_signal_status_roundtrip(status):assert SignalStatus(status.value) is status
@pytest.mark.parametrize("status",list(RecommendationStatus))
def test_recommendation_status_roundtrip(status):assert RecommendationStatus(status.value) is status
@pytest.mark.parametrize("side",list(Side))
def test_side_roundtrip(side):assert Side(side.value) is side
@pytest.mark.parametrize("decision",list(RiskDecision))
def test_risk_roundtrip(decision):assert RiskDecision(decision.value) is decision
@pytest.mark.parametrize("kind",list(ApprovalKind))
def test_approval_kind_roundtrip(kind):assert ApprovalKind(kind.value) is kind
DDL=Path(__file__).parents[2]/"migrations"/"008_signals.sql"
def test_all_owned_tables_present():
 sql=DDL.read_text(encoding="utf-8")
 for table in ("signals","signal_components","recommendations","recommendation_risk_refs","approval_decisions","signal_supersessions","signal_events"):assert f"CREATE TABLE {table}" in sql
def test_one_recommendation_per_instrument():assert "UNIQUE(signal_id,instrument_id)" in DDL.read_text(encoding="utf-8")
def test_approval_decision_id_unique():assert "decision_id uuid UNIQUE NOT NULL" in DDL.read_text(encoding="utf-8")
def test_quantity_check():assert "CHECK(quantity>0)" in DDL.read_text(encoding="utf-8")
def test_signal_input_hash_unique():assert "input_hash char(64) UNIQUE NOT NULL" in DDL.read_text(encoding="utf-8")
