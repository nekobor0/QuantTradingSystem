from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from quant_trading_system.instruments import *
from quant_trading_system.instruments.in_memory import InMemoryInstrumentRepository
from quant_trading_system.signals import SignalService
from quant_trading_system.signals.in_memory import InMemorySignalRepository
from quant_trading_system.signals.sqlalchemy_repository import SqlAlchemySignalRepository
from quant_trading_system.signals.tables import metadata
@pytest.fixture(params=["memory","sqlalchemy"])
def repository(request):
 if request.param=="memory":yield InMemorySignalRepository();return
 e=create_engine("sqlite+pysqlite:///:memory:");metadata.create_all(e)
 try:yield SqlAlchemySignalRepository(e)
 finally:e.dispose()
@pytest.fixture
def signal_setup(repository):
 instruments=InstrumentService(InMemoryInstrumentRepository())
 def add(code):return instruments.register(RegisterInstrumentCommand(source="tushare",source_record_id=code,revision="1",batch_id="r",asset_type=AssetType.ETF_DOMESTIC,exchange=Exchange.SSE,board=Board.ETF,currency="CNY",name=code,list_date=date(2020,1,2),aliases=(AliasInput("tushare",code,date(2020,1,2)),),trading_specs=(TradingSpecInput(date(2020,1,2),100,Decimal(".01"),100),)))
 return SignalService(repository,instruments),repository,add("510300.SH"),add("512000.SH")
