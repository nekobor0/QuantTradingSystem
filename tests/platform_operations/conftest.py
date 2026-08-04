from datetime import date,datetime,timezone
import pytest
from quant_trading_system.platform_operations.in_memory import InMemoryOperationsRepository
from quant_trading_system.platform_operations.service import OperationsService

NOW=datetime(2026,7,28,8,tzinfo=timezone.utc); DAY=date(2026,7,28)
class Probe:
 def __init__(self):self.db=True;self.reconciled=True;self.risk=True
 def database_ok(self):return self.db
 def account_reconciled(self,b):return self.reconciled
 def risk_succeeded(self,b):return self.risk
class Alerts:
 def __init__(self):self.ok=True;self.calls=[]
 def send(self,c,m,i):self.calls.append((c,m,i));return self.ok
@pytest.fixture
def stack():
 repo=InMemoryOperationsRepository();probe=Probe();alerts=Alerts();return repo,probe,alerts,OperationsService(repo,probe,alerts)
