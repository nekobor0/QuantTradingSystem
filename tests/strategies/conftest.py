from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from quant_trading_system.strategies import *
from quant_trading_system.strategies.in_memory import InMemoryStrategyRepository
from quant_trading_system.strategies.sqlalchemy_repository import SqlAlchemyStrategyRepository
from quant_trading_system.strategies.tables import metadata
@pytest.fixture(params=["memory","sqlalchemy"])
def repository(request):
 if request.param=="memory":yield InMemoryStrategyRepository();return
 e=create_engine("sqlite+pysqlite:///:memory:");metadata.create_all(e)
 try:yield SqlAlchemyStrategyRepository(e)
 finally:e.dispose()
@pytest.fixture
def strategy_setup(repository):
 service=StrategyService(repository)
 etf_d=StrategyDefinition("ETF timing",StrategyKind.ETF_TIMING,"timing","ETF","daily","weekly","","owner",("drawdown",))
 etf_features=("momentum","volatility","max_drawdown","liquidity")
 etf_v=StrategyVersion(etf_d.definition_id,"1","c1",etf_features,{"top_n":2,"feature_weights":{"momentum":"0.4","volatility":"0.2","max_drawdown":"0.2","liquidity":"0.2"},"rebalance_weekday":0,"trend_min":"0","vol_max":"1","drawdown_floor":"-1","liquidity_min":"0"})
 eq_d=StrategyDefinition("Equity daily",StrategyKind.EQUITY_DAILY_SELECTION,"selection","equity","daily","daily","","owner",("quality",))
 eq_features=("value","quality","momentum")
 eq_v=StrategyVersion(eq_d.definition_id,"1","c1",eq_features,{"top_n":2,"feature_weights":{"value":"0.4","quality":"0.3","momentum":"0.3"}})
 service.register(etf_d,(etf_v,));service.register(eq_d,(eq_v,))
 return service,repository,etf_v,eq_v
