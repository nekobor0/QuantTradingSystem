from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from quant_trading_system.features import *
from quant_trading_system.features.in_memory import InMemoryFeatureRepository
from quant_trading_system.features.sqlalchemy_repository import SqlAlchemyFeatureRepository
from quant_trading_system.features.tables import metadata
@pytest.fixture(params=["memory","sqlalchemy"])
def repository(request):
 if request.param=="memory":yield InMemoryFeatureRepository();return
 e=create_engine("sqlite+pysqlite:///:memory:");metadata.create_all(e)
 try:yield SqlAlchemyFeatureRepository(e)
 finally:e.dispose()
@pytest.fixture
def feature_setup(repository):
 service=FeatureService(repository);definition=FeatureDefinition("mom",FeaturePurpose.ETF_TIMING,FormulaKind.MOMENTUM,"trend",1,"1d","research")
 version=FeatureVersion(definition.definition_id,"1","abc",{"window":"2"},{"market_data":"1"},3,MissingPolicy.REJECT)
 service.register(definition,(version,));service.bind_required(FeaturePurpose.ETF_TIMING,(version.version_id,))
 members=(uuid4(),uuid4());universe=UniverseSnapshotInput(uuid4(),FeaturePurpose.ETF_TIMING,members,"universe-hash")
 return service,repository,definition,version,universe
