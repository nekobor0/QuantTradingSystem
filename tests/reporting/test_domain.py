from dataclasses import replace
from datetime import date,datetime
from decimal import Decimal
from uuid import uuid4
import pytest
from quant_trading_system.reporting import *
from quant_trading_system.reporting.errors import InvalidReportInput
from quant_trading_system.strategies import StrategyKind
from .conftest import NOW,D1

@pytest.mark.parametrize("mode",list(ReportMode))
def test_definition_accepts_modes(mode):
 value=ReportDefinition("r",mode,"a","m","t","c",("source",),"b",Decimal(),252,"CNY",SensitivityLevel.INTERNAL,("title",));assert value.mode is mode
@pytest.mark.parametrize("days,currency",[(0,"CNY"),(-1,"CNY"),(252,"CN"),(252,"CNYY")])
def test_definition_rejects_bad_annualization_or_currency(days,currency):
 with pytest.raises(InvalidReportInput):ReportDefinition("r",ReportMode.LIVE,"a","m","t","c",("s",),"b",Decimal(),days,currency,SensitivityLevel.INTERNAL,("title",))
@pytest.mark.parametrize("field",["name","audience","metric_version","template_version","code_version","benchmark"])
def test_definition_requires_text(field):
 values=dict(name="r",mode=ReportMode.LIVE,audience="a",metric_version="m",template_version="t",code_version="c",required_source_types=("s",),benchmark="b",risk_free_rate=Decimal(),annualization_days=252,base_currency="CNY",sensitivity=SensitivityLevel.INTERNAL,required_template_fields=("title",));values[field]=""
 with pytest.raises(InvalidReportInput):ReportDefinition(**values)
def test_period_rejects_inverted():
 with pytest.raises(InvalidReportInput):ReportPeriod(date(2025,2,1),date(2025,1,1))
@pytest.mark.parametrize("quality",list(InputQuality))
def test_input_accepts_quality(quality):assert ReportInputSnapshot("s",uuid4(),NOW,"h",quality,ReportMode.LIVE,"ref",{}).quality is quality
@pytest.mark.parametrize("field",["source_type","content_hash","reference"])
def test_input_requires_frozen_reference(field):
 values=dict(source_type="s",source_id=uuid4(),as_of=NOW,content_hash="h",quality=InputQuality.PASS,source_mode=ReportMode.LIVE,reference="r",facts={});values[field]=""
 with pytest.raises(InvalidReportInput):ReportInputSnapshot(**values)
@pytest.mark.parametrize("nav",["1","100","0.01","999999"])
def test_curve_accepts_positive_nav(nav):assert ReportCurvePoint(NOW,Decimal(nav),uuid4(),"r",ReportMode.LIVE).nav==Decimal(nav)
@pytest.mark.parametrize("nav",["0","-1"])
def test_curve_rejects_nonpositive_nav(nav):
 with pytest.raises(InvalidReportInput):ReportCurvePoint(NOW,Decimal(nav),uuid4(),"r",ReportMode.LIVE)
@pytest.mark.parametrize("gross,fee",[("0","0"),("1","0"),("1","1"),("100","0.1")])
def test_trade_accepts_nonnegative_values(gross,fee):ReportTrade(uuid4(),NOW,Decimal(gross),Decimal(fee),"CNY",uuid4(),"r",ReportMode.LIVE)
@pytest.mark.parametrize("gross,fee,currency",[("-1","0","CNY"),("1","-1","CNY"),("1","0","CN")])
def test_trade_rejects_invalid_values(gross,fee,currency):
 with pytest.raises(InvalidReportInput):ReportTrade(uuid4(),NOW,Decimal(gross),Decimal(fee),currency,uuid4(),"r",ReportMode.LIVE)
@pytest.mark.parametrize("component",["ETF_TIMING","EQUITY_DAILY_SELECTION","CROSS_CONSTRAINT","CASH"])
def test_attribution_accepts_required_components(component):AttributionInput(component,AttributionDimension.RETURN,Decimal(),uuid4() if "TIMING" in component or "SELECTION" in component else None,"r")
def test_strategy_attribution_requires_run_id():
 with pytest.raises(InvalidReportInput):AttributionInput("ETF_TIMING",AttributionDimension.RETURN,Decimal(),None,"r")
def test_equity_summary_counts_and_stability():
 value=StrategySummaryInput(StrategyKind.EQUITY_DAILY_SELECTION,uuid4(),1,2,3,Decimal(".5"),Decimal(".1"));assert value.exit_count==3
def test_etf_summary_requires_gate_and_cash():
 with pytest.raises(InvalidReportInput):StrategySummaryInput(StrategyKind.ETF_TIMING,uuid4(),1,2,3,Decimal(".5"),Decimal(".1"))
@pytest.mark.parametrize("stability,turnover",[("-0.1","0"),("1.1","0"),("0.5","-1")])
def test_summary_rejects_invalid_rates(stability,turnover):
 with pytest.raises(InvalidReportInput):StrategySummaryInput(StrategyKind.EQUITY_DAILY_SELECTION,uuid4(),1,1,1,Decimal(stability),Decimal(turnover))
def test_naive_time_rejected():
 with pytest.raises(InvalidReportInput):ReportCurvePoint(datetime(2025,1,1),Decimal("1"),uuid4(),"r",ReportMode.LIVE)
