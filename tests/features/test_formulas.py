from datetime import date,datetime,timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from quant_trading_system.features import FormulaKind,InputObservation
from quant_trading_system.features.errors import InvalidFeature
from quant_trading_system.features.formulas import calculate
NOW=datetime(2024,1,10,tzinfo=timezone.utc);IID=uuid4();SNAP=uuid4()
def obs(values,field="close"):
 return [InputObservation(IID,field,date(2024,1,i+1),NOW,Decimal(str(x)),f"r{i}",SNAP) for i,x in enumerate(values)]
@pytest.mark.parametrize("values,window,expected",[([10,11,12],2,"0.2"),([5,10],1,"1"),([10,5],1,"-0.5"),([3,3,3],2,"0")])
def test_momentum_golden(values,window,expected):assert calculate(FormulaKind.MOMENTUM,obs(values),window)[0]==Decimal(expected)
@pytest.mark.parametrize("values,window",[([1],1),([1,2],2),([0,1],1)])
def test_momentum_insufficient_or_zero_lag(values,window):
 with pytest.raises(InvalidFeature):calculate(FormulaKind.MOMENTUM,obs(values),window)
def test_volatility_constant_returns_zero():assert calculate(FormulaKind.VOLATILITY,obs([1,2,4]),2)[0]==0
def test_volatility_golden():assert abs(calculate(FormulaKind.VOLATILITY,obs([100,110,99]),2)[0]-Decimal("0.14142135623730953"))<Decimal("1e-15")
@pytest.mark.parametrize("values,expected",[([10,12,9,11],"-0.25"),([10,11,12],"0"),([10,5,4],"-0.6")])
def test_drawdown_golden(values,expected):assert calculate(FormulaKind.MAX_DRAWDOWN,obs(values),len(values))[0]==Decimal(expected)
@pytest.mark.parametrize("values,window,expected",[([10,20,30],3,"20"),([1,3],2,"2")])
def test_liquidity_mean(values,window,expected):assert calculate(FormulaKind.LIQUIDITY,obs(values,"turnover"),window)[0]==Decimal(expected)
@pytest.mark.parametrize("income,cap,expected",[(10,100,"0.1"),(-5,100,"-0.05"),(0,100,"0")])
def test_earnings_yield(income,cap,expected):
 values=obs([income],"net_income")+obs([cap],"market_cap");assert calculate(FormulaKind.EARNINGS_YIELD,values,1)[0]==Decimal(expected)
@pytest.mark.parametrize("formula",[FormulaKind.ROE,FormulaKind.GROWTH])
def test_direct_fundamental_formula(formula):assert calculate(formula,obs([Decimal(".12")],formula.value.lower()),1)[0]==Decimal(".12")
@pytest.mark.parametrize("formula,values,window",[(FormulaKind.VOLATILITY,[1],1),(FormulaKind.MAX_DRAWDOWN,[1],2),(FormulaKind.LIQUIDITY,[1],2),(FormulaKind.ROE,[],1)])
def test_formula_missing_inputs(formula,values,window):
 with pytest.raises(InvalidFeature):calculate(formula,obs(values),window)
