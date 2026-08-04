from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine,func,select
from quant_trading_system.platform_operations.domain import *
from quant_trading_system.platform_operations.sqlalchemy_repository import SqlAlchemyOperationsRepository
from quant_trading_system.platform_operations.tables import metadata,task_runs,outbox_events,consumer_checkpoints,dataset_batches,configuration_versions,backup_records,alert_records
from .conftest import DAY,NOW

def repository():
 engine=create_engine("sqlite://");metadata.create_all(engine);return engine,SqlAlchemyOperationsRepository(engine)
def test_sqlite_task_fence_and_transactional_outbox():
 engine,repo=repository();task=TaskRun(TaskType.RUN_ETF_DAILY_GATE,DAY,"h","c");repo.save_task(task);running=__import__('dataclasses').replace(task,status=TaskStatus.RUNNING,fencing_token=1,lease_owner="w",lease_expires_at=NOW+timedelta(minutes=1));repo.replace_task(running,0);done=__import__('dataclasses').replace(running,status=TaskStatus.SUCCEEDED);event=OutboxEvent("TaskSucceeded",task.task_run_id,{},1,NOW,NOW,"c");repo.save_task_and_event(done,event,1)
 assert repo.get_task(task.task_run_id).status is TaskStatus.SUCCEEDED and len(repo.pending_events())==1
def test_sqlite_operational_records_roundtrip():
 engine,repo=repository();batch=DatasetBatch("s","prices","h",NOW,NOW,BatchStatus.PUBLISHED,QualityStatus.PASS,NOW);repo.save_batch(batch);config=ConfigurationVersion("prod",1,{"workers":"1"},{"db":"QTS_DATABASE_URL"},NOW,None,"h");repo.save_configuration(config);backup=BackupRecord(uuid4(),NOW,NOW,True,"h","014",NOW);repo.save_backup(backup);alert=AlertRecord("X","message",NOW,"c",False,True);repo.save_alert(alert)
 assert repo.latest_batch("prices")==batch and repo.active_configuration("prod",NOW)==config and repo.latest_backup()==backup
def test_migration_contains_fencing_outbox_and_unique_checkpoints():
 text=Path("migrations/014_platform_operations.sql").read_text(encoding="utf-8").lower()
 for marker in ("fencing_token","timestamptz","unique(consumer,event_id)","ops_outbox_dispatch_idx","failed_retryable","secret_refs"):assert marker in text
def test_all_owned_tables_exist_and_exclude_business_facts():
 names={x.name for x in metadata.tables.values()};assert names=={"ops_task_runs","ops_outbox_events","ops_consumer_checkpoints","ops_dataset_batches","ops_configuration_versions","ops_backup_records","ops_alert_records","ops_audit_logs"}
 assert "ops_audit_logs" in names
 assert not any(any(word in c.name for word in ("instrument","order","fill","position")) for t in metadata.tables.values() for c in t.columns)
def test_compose_does_not_publish_database_or_embed_password():
 text=Path("deploy/compose.yaml").read_text(encoding="utf-8");db=text.split("  api:")[0]
 assert "ports:" not in db and "POSTGRES_PASSWORD_FILE" in db and "CHANGE_ME" not in text
def test_env_example_contains_references_not_real_secrets():
 text=Path("deploy/.env.example").read_text(encoding="utf-8")
 assert "_FILE=" in text and "session_secret" in text and "sk-" not in text
def test_restore_drill_refuses_production_like_target():
 text=Path("scripts/ops/restore_drill.ps1").read_text(encoding="utf-8").lower()
 assert "refusing restore drill" in text and "--exit-on-error" in text and "on_error_stop" in text and "backup checksum mismatch" in text and "schema version mismatch" in text and "critical row count mismatch" in text
def test_dependency_manifest_declares_runtime_contract():
 text=Path("pyproject.toml").read_text(encoding="utf-8").lower()
 for dependency in ("fastapi","pydantic","streamlit","uvicorn","psycopg[binary]","sqlalchemy"):assert dependency in text
