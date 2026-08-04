from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import pytest
from quant_trading_system.portfolio import *
from quant_trading_system.portfolio.errors import InvalidPortfolio
from quant_trading_system.strategies import StrategyKind
NOW=datetime(2024,1,8,tzinfo=timezone.utc)
@pytest.mark.parametrize("budget",["-0.1","1.1"])
def test_sleeve_budget_bounds(budget):
 with pytest.raises(InvalidPortfolio):SleevePolicy(StrategyKind.ETF_TIMING,Decimal(budget))
@pytest.mark.parametrize("priority",[0,-1])
def test_sleeve_priority_positive(priority):
 with pytest.raises(InvalidPortfolio):SleevePolicy(StrategyKind.ETF_TIMING,Decimal(".5"),priority=priority)
def base_policy(**changes):
 values=dict(version="1",sleeves=(SleevePolicy(StrategyKind.ETF_TIMING,Decimal(".4")),SleevePolicy(StrategyKind.EQUITY_DAILY_SELECTION,Decimal(".5"))),min_cash=Decimal(".1"),max_instrument=Decimal(".5"),market_caps={},industry_caps={},max_turnover=Decimal("2"),account_max_age_seconds=10);values.update(changes);return PortfolioPolicy(**values)
def test_sleeve_budgets_cannot_exceed_one():
 with pytest.raises(InvalidPortfolio):base_policy(sleeves=(SleevePolicy(StrategyKind.ETF_TIMING,Decimal(".6")),SleevePolicy(StrategyKind.EQUITY_DAILY_SELECTION,Decimal(".6"))))
def test_duplicate_sleeve_kind_rejected():
 with pytest.raises(InvalidPortfolio):base_policy(sleeves=(SleevePolicy(StrategyKind.ETF_TIMING,Decimal(".4")),SleevePolicy(StrategyKind.ETF_TIMING,Decimal(".4"))))
@pytest.mark.parametrize("field,value",[("min_cash","-1"),("min_cash","1.1"),("max_instrument","0"),("max_instrument","1.1"),("max_turnover","-1"),("tolerance","0")])
def test_policy_numeric_bounds(field,value):
 with pytest.raises(InvalidPortfolio):base_policy(**{field:Decimal(value)})
@pytest.mark.parametrize("field,value",[("market_caps",{"M":Decimal("-1")}),("market_caps",{"M":Decimal("1.1")}),("industry_caps",{"I":Decimal("-1")})])
def test_group_cap_bounds(field,value):
 with pytest.raises(InvalidPortfolio):base_policy(**{field:value})
def test_account_age_nonnegative():
 with pytest.raises(InvalidPortfolio):base_policy(account_max_age_seconds=-1)
@pytest.mark.parametrize("weight",["-0.1","1.1"])
def test_strategy_target_weight_bounds(weight):
 with pytest.raises(InvalidPortfolio):StrategyTargetWeight(uuid4(),Decimal(weight))
@pytest.mark.parametrize("weight",["-0.1","1.1"])
def test_target_weight_bounds(weight):
 with pytest.raises(InvalidPortfolio):TargetWeight(uuid4(),uuid4(),Decimal(weight))
def test_account_is_long_only():
 with pytest.raises(InvalidPortfolio):AccountSnapshotInput(uuid4(),NOW,{uuid4():Decimal("-.1")},Decimal("1.1"),{}, {}, {})
def test_account_time_aware():
 with pytest.raises(InvalidPortfolio):AccountSnapshotInput(uuid4(),NOW.replace(tzinfo=None),{},Decimal(1),{}, {}, {})
@pytest.mark.parametrize("cash",["-0.1","1.1"])
def test_target_cash_bounds(cash):
 with pytest.raises(InvalidPortfolio):TargetPortfolio(uuid4(),(),uuid4(),NOW,Decimal(cash),"i","c")
def test_contribution_cannot_be_negative():
 with pytest.raises(InvalidPortfolio):TargetContribution(uuid4(),"s",uuid4(),Decimal("-1"),Decimal(),Decimal())
def test_delta_must_reconcile():
 with pytest.raises(InvalidPortfolio):RebalanceDelta(uuid4(),uuid4(),Decimal(".1"),Decimal(".2"),Decimal(".2"))
@pytest.mark.parametrize("severity",list(ConstraintSeverity))
def test_severity_roundtrip(severity):assert ConstraintSeverity(severity.value) is severity
DDL=Path(__file__).parents[2]/"migrations"/"007_portfolio.sql"
def test_all_owned_tables_present():
 sql=DDL.read_text(encoding="utf-8")
 for table in ("portfolio_policies","portfolio_sleeve_policies","target_portfolios","target_weights","target_contributions","constraint_results","rebalance_deltas","portfolio_events"):assert f"CREATE TABLE {table}" in sql
def test_target_weight_long_only_constraint():assert "CHECK(weight BETWEEN 0 AND 1)" in DDL.read_text(encoding="utf-8")
def test_target_input_hash_unique():assert "input_hash char(64) UNIQUE NOT NULL" in DDL.read_text(encoding="utf-8")
def test_delta_unique_key():assert "UNIQUE(target_id,instrument_id)" in DDL.read_text(encoding="utf-8")
def test_cash_weight_explicit():assert "cash_weight numeric NOT NULL CHECK(cash_weight BETWEEN 0 AND 1)" in DDL.read_text(encoding="utf-8")
