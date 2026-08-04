from datetime import timedelta
from uuid import uuid4

from sqlalchemy import create_engine, func, select

from quant_trading_system.api_ui.domain import ApiUiEvent, AuthSession, IdempotentCommand, ImportSession, UiPreference, UserActionAudit
from quant_trading_system.api_ui.sqlalchemy_repository import SqlAlchemyApiUiRepository
from quant_trading_system.api_ui.tables import audits, commands, events, imports, metadata, preferences, sessions

from conftest import ACCOUNT_ID, NOW


def repository():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    return engine, SqlAlchemyApiUiRepository(engine)


def test_sqlite_full_contract_round_trip():
    engine, repo = repository()
    session = AuthSession("u", ACCOUNT_ID, "t", "c", NOW, NOW + timedelta(hours=1)); repo.save_session(session)
    assert repo.find_session_by_token_hash("t") == session
    pref = UiPreference("u", "dark", "UTC", 25, NOW, 1); command = IdempotentCommand("u", "SAVE", "k", "h", 200, {"ok": True}, NOW); audit = UserActionAudit("u", ACCOUNT_ID, "SAVE", pref.preference_id, 0, 1, "SUCCEEDED", NOW, "corr", {}); event = ApiUiEvent("Saved", ACCOUNT_ID, NOW, "corr", {})
    repo.save_preference_and_command(pref, command, audit, event)
    assert repo.get_preference("u") == pref and repo.find_command("u", "SAVE", "k") == command
    with engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(audits)) == 1
        assert c.scalar(select(func.count()).select_from(events)) == 1


def test_import_and_command_are_atomic_and_round_trip():
    engine, repo = repository()
    value = ImportSession(ACCOUNT_ID, "u", "a" * 64, "v1", ("price",), 1, True, {}, NOW, NOW + timedelta(minutes=30))
    command = IdempotentCommand("u", "PREVIEW", "k", "h", 200, {}, NOW); audit = UserActionAudit("u", ACCOUNT_ID, "PREVIEW", value.import_session_id, 0, 0, "SUCCEEDED", NOW, "corr", {}); event = ApiUiEvent("Previewed", ACCOUNT_ID, NOW, "corr", {})
    repo.save_import_and_command(value, command, audit, event)
    assert repo.get_import(value.import_session_id) == value
    assert repo.find_import(ACCOUNT_ID, "a" * 64, "v1") == value


def test_schema_has_no_raw_file_or_password_columns():
    names = {column.name for table in (sessions, audits, preferences, imports, commands, events) for column in table.columns}
    assert "raw_file" not in names and "password" not in names and "token" not in names


def test_postgresql_migration_has_required_constraints():
    text = open("migrations/013_api_ui.sql", encoding="utf-8").read().lower()
    for marker in ("timestamptz", "unique(user_id,action,idempotency_key)", "check (expires_at > created_at)", "file_hash", "csrf_hash"):
        assert marker in text
