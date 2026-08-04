from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.risk import *
from quant_trading_system.risk.in_memory import InMemoryRiskRepository

UTC = timezone.utc
NOW = datetime(2025, 1, 2, 8, tzinfo=UTC)
SCOPES = (RiskScope.ETF_TIMING, RiskScope.EQUITY_DAILY_SELECTION, RiskScope.COMBINED_ACCOUNT)


@pytest.fixture
def repo(): return InMemoryRiskRepository()


@pytest.fixture
def service(repo): return RiskService(repo)


@pytest.fixture
def account_id(): return uuid4()


@pytest.fixture
def rules(service):
    values=[]
    configs=(
        ("ETF_LIQUIDITY",RiskScope.ETF_TIMING,"liquidity",ComparisonOperator.GE,Decimal("100"),RiskSeverity.WARNING,False),
        ("STOCK_WEIGHT",RiskScope.EQUITY_DAILY_SELECTION,"max_weight",ComparisonOperator.LE,Decimal("0.1"),RiskSeverity.HARD_BLOCK,False),
        ("COMBINED_MARKET",RiskScope.COMBINED_ACCOUNT,"market_weight",ComparisonOperator.LE,Decimal("0.8"),RiskSeverity.APPROVAL_REQUIRED,True),
    )
    for code,scope,metric,operator,threshold,severity,allowed in configs:
        rule=RiskRule(code,code,"risk-owner",code+" description")
        version=RiskRuleVersion(rule.rule_id,"v1",RiskStage.PRE_TRADE,scope,metric,operator,threshold,severity,date(2020,1,1),None,"risk-owner",allowed)
        service.register_rule(rule,version);values.append(version)
    return tuple(values)


@pytest.fixture
def policy(service, rules, account_id):
    value=RiskPolicyVersion("default","v1",account_id,"CN",tuple(x.version_id for x in rules),SCOPES,date(2020,1,1),None,"risk-owner",3600)
    service.register_policy(value);return value


def make_input(account_id, *, stage=RiskStage.PRE_TRADE, at=NOW, reconciled=True, cash=Decimal("1000"), negative_position=False, etf_liquidity=Decimal("200"), stock_weight=Decimal("0.05"), market_weight=Decimal("0.5"), object_id=None, hashes=None, account_source="execution_ledger", ages=0, signal_expires_at=None):
    combined={"cash":cash,"negative_position":negative_position,"market_weight":market_weight}
    if signal_expires_at is not None:combined["signal_expires_at"]=signal_expires_at
    point=at-timedelta(seconds=ages)
    return RiskCheckInput(account_id,object_id or uuid4(),stage,at,uuid4(),account_source,point,reconciled,uuid4(),point,uuid4(),point,uuid4(),point,{RiskScope.ETF_TIMING:{"liquidity":etf_liquidity},RiskScope.EQUITY_DAILY_SELECTION:{"max_weight":stock_weight},RiskScope.COMBINED_ACCOUNT:combined},hashes if hashes is not None else {"account":"a","market":"m","data":"d","task":"t"},target_portfolio_id=uuid4())
