from __future__ import annotations
from decimal import Decimal,getcontext
from math import sqrt
from typing import Sequence
from .domain import FormulaKind,InputObservation
from .errors import InvalidFeature
getcontext().prec=28
def calculate(formula:FormulaKind,values:Sequence[InputObservation],window:int)->tuple[Decimal,tuple[str,...]]:
 xs=[x.value for x in sorted(values,key=lambda x:x.observed_on) if x.value is not None]
 if formula is FormulaKind.MOMENTUM:
  if len(xs)<window+1 or xs[-window-1]==0:raise InvalidFeature("INSUFFICIENT_HISTORY")
  return xs[-1]/xs[-window-1]-1,(f"last/lag({window})-1",)
 if formula is FormulaKind.VOLATILITY:
  if len(xs)<window+1:raise InvalidFeature("INSUFFICIENT_HISTORY")
  returns=[xs[i]/xs[i-1]-1 for i in range(len(xs)-window,len(xs))]
  mean=sum(returns,Decimal())/len(returns);variance=sum(((x-mean)**2 for x in returns),Decimal())/(len(returns)-1) if len(returns)>1 else Decimal()
  return Decimal(str(sqrt(float(variance)))),("sample_std(returns)",)
 if formula is FormulaKind.MAX_DRAWDOWN:
  if len(xs)<window:raise InvalidFeature("INSUFFICIENT_HISTORY")
  peak=xs[-window];worst=Decimal()
  for x in xs[-window:]:peak=max(peak,x);worst=min(worst,x/peak-1)
  return worst,("min(price/running_peak-1)",)
 if formula is FormulaKind.LIQUIDITY:
  if len(xs)<window:raise InvalidFeature("INSUFFICIENT_HISTORY")
  return sum(xs[-window:],Decimal())/window,(f"mean({window})",)
 if formula is FormulaKind.EARNINGS_YIELD:
  if len(xs)!=2 or xs[1]==0:raise InvalidFeature("MISSING_INPUT")
  return xs[0]/xs[1],("net_income/market_cap",)
 if formula in (FormulaKind.ROE,FormulaKind.GROWTH):
  if not xs:raise InvalidFeature("MISSING_INPUT")
  return xs[-1],("latest PIT value",)
 raise InvalidFeature("unsupported formula")
