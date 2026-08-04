from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from quant_trading_system.portfolio import *
from quant_trading_system.portfolio.in_memory import InMemoryPortfolioRepository
from quant_trading_system.portfolio.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from quant_trading_system.portfolio.tables import metadata
from quant_trading_system.strategies import StrategyKind
@pytest.fixture(params=["memory","sqlalchemy"])
def repository(request):
 if request.param=="memory":yield InMemoryPortfolioRepository();return
 e=create_engine("sqlite+pysqlite:///:memory:");metadata.create_all(e)
 try:yield SqlAlchemyPortfolioRepository(e)
 finally:e.dispose()
@pytest.fixture
def portfolio_setup(repository):
 policy=PortfolioPolicy("1",(SleevePolicy(StrategyKind.ETF_TIMING,Decimal(".3")),SleevePolicy(StrategyKind.EQUITY_DAILY_SELECTION,Decimal(".6"))),Decimal(".1"),Decimal(".5"),{}, {},Decimal("2"),3600)
 return PortfolioService(repository),repository,policy
