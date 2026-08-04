from datetime import timedelta
import pytest
from quant_trading_system.platform_operations.domain import *
from quant_trading_system.platform_operations.errors import ValidationError
from .conftest import DAY,NOW

@pytest.mark.parametrize("suffix",range(100))
def test_task_business_key_is_stable(suffix):
 x=TaskRun(TaskType.RUN_ETF_DAILY_GATE,DAY,f"hash-{suffix}","corr")
 assert x.business_key==f"RUN_ETF_DAILY_GATE:2026-07-28:hash-{suffix}"
def test_naive_time_rejected():
 with pytest.raises(ValidationError):DatasetBatch("s","d","h",NOW.replace(tzinfo=None),NOW,BatchStatus.PUBLISHED,QualityStatus.PASS,NOW)
@pytest.mark.parametrize("key",["password","db_password","TOKEN","api_key","client_secret"])
def test_configuration_rejects_inline_secrets(key):
 with pytest.raises(ValidationError):ConfigurationVersion("prod",1,{key:"plain"},{},NOW,None,"h")
def test_configuration_accepts_secret_refs():assert ConfigurationVersion("prod",1,{"workers":"1"},{"database":"QTS_DATABASE_URL"},NOW,None,"h").version==1
def test_dataset_window_validation():
 with pytest.raises(ValidationError):DatasetBatch("s","d","h",NOW,NOW-timedelta(seconds=1),BatchStatus.PUBLISHED,QualityStatus.PASS,NOW)
