from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from quant_trading_system.reporting import *
from quant_trading_system.reporting.in_memory import InMemoryReportingRepository
from quant_trading_system.strategies import StrategyKind

UTC=timezone.utc;NOW=datetime(2025,1,31,8,tzinfo=UTC);D1=NOW-timedelta(days=2);D2=NOW-timedelta(days=1)

@pytest.fixture
def repo():return InMemoryReportingRepository()
@pytest.fixture
def service(repo):return ReportingService(repo)
@pytest.fixture
def definition():return ReportDefinition("live daily",ReportMode.LIVE,"portfolio manager", "metrics-v1","template-v1","code-v1",("execution_ledger","risk"),"000300.SH",Decimal("0.02"),252,"CNY",SensitivityLevel.CONFIDENTIAL,("title",))

def make_command(definition,*,reconciled=True,quality=InputQuality.PASS,mode=None,source_type="execution_ledger",content_hash="ledger-v1",missing_days=0,total_difference=Decimal(),include_unfilled=False,account_label="account 123456789012",generated_at=NOW):
 mode=mode or definition.mode;source_id=uuid4();risk_id=uuid4();inputs=(ReportInputSnapshot(source_type,source_id,NOW,content_hash,quality,mode,"ledger://snapshot",{"account_cash":Decimal("400"),"account_position_value":Decimal("600"),"account_total":Decimal("1000")+total_difference,"missing_trading_days":missing_days,"account_label":account_label},reconciled),ReportInputSnapshot("risk",risk_id,NOW,"risk-v1",quality,mode,"risk://run",{},True))
 curve=(ReportCurvePoint(D1,Decimal("100"),source_id,"ledger://nav/1",mode),ReportCurvePoint(D2,Decimal("110"),source_id,"ledger://nav/2",mode),ReportCurvePoint(NOW,Decimal("105"),source_id,"ledger://nav/3",mode));trades=[ReportTrade(uuid4(),D2,Decimal("10"),Decimal("1"),"CNY",source_id,"ledger://fill/1",mode),ReportTrade(uuid4(),NOW,Decimal("20"),Decimal("2"),"CNY",source_id,"ledger://fill/2",mode)]
 if include_unfilled:trades.append(ReportTrade(uuid4(),NOW,Decimal("999"),Decimal(),"CNY",source_id,"signal://recommendation",mode,False))
 values={AttributionDimension.RETURN:Decimal("0.0500000000"),AttributionDimension.RISK:Decimal("-0.0454545455"),AttributionDimension.TURNOVER:Decimal("0.2857142857"),AttributionDimension.COST:Decimal("3.0000000000")};attrs=[]
 for dimension,value in values.items():
  for component in ("ETF_TIMING","EQUITY_DAILY_SELECTION","CROSS_CONSTRAINT","CASH"):attrs.append(AttributionInput(component,dimension,value if component=="ETF_TIMING" else Decimal(),uuid4() if component in ("ETF_TIMING","EQUITY_DAILY_SELECTION") else None,f"portfolio://attribution/{dimension.value}/{component}"))
 summaries=(StrategySummaryInput(StrategyKind.ETF_TIMING,uuid4(),1,1,1,Decimal("0.8"),Decimal("0.1"),"RISK_ON",(D1.date(),),"INVESTED"),StrategySummaryInput(StrategyKind.EQUITY_DAILY_SELECTION,uuid4(),10,20,3,Decimal("0.7"),Decimal("0.2")))
 return BuildReport(definition,ReportPeriod(D1.date(),NOW.date()),inputs,curve,tuple(trades),tuple(attrs),summaries,None,{}, {"title":"Daily Report "+account_label},generated_at)

