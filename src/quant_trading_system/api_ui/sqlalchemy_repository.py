from datetime import timezone

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .domain import ApiUiEvent, AuthSession, IdempotentCommand, ImportSession, ImportStatus, UiPreference, UserActionAudit
from .errors import IdempotencyConflict, VersionConflict
from .tables import audits, commands, events, imports, preferences, sessions


class SqlAlchemyApiUiRepository:
    def __init__(self, engine): self.engine = engine
    @staticmethod
    def _a(value): return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value
    @staticmethod
    def _session(r): return AuthSession(r.user_id, r.account_id, r.token_hash, r.csrf_hash, SqlAlchemyApiUiRepository._a(r.created_at), SqlAlchemyApiUiRepository._a(r.expires_at), SqlAlchemyApiUiRepository._a(r.revoked_at), r.session_id)
    @staticmethod
    def _command(r): return IdempotentCommand(r.user_id, r.action, r.idempotency_key, r.payload_hash, r.status_code, r.response, SqlAlchemyApiUiRepository._a(r.created_at), r.command_id)
    @staticmethod
    def _import(r): return ImportSession(r.account_id, r.user_id, r.file_hash, r.format_version, tuple(r.columns), r.row_count, r.preview_passed, r.summary, SqlAlchemyApiUiRepository._a(r.created_at), SqlAlchemyApiUiRepository._a(r.expires_at), ImportStatus(r.status), r.committed_result_id, r.version, r.import_session_id)
    @staticmethod
    def _preference(r): return UiPreference(r.user_id, r.theme, r.timezone_name, r.page_size, SqlAlchemyApiUiRepository._a(r.updated_at), r.version, r.preference_id)
    @staticmethod
    def _session_values(x): return {"session_id": x.session_id, "user_id": x.user_id, "account_id": x.account_id, "token_hash": x.token_hash, "csrf_hash": x.csrf_hash, "created_at": x.created_at, "expires_at": x.expires_at, "revoked_at": x.revoked_at}
    @staticmethod
    def _command_values(x): return {"command_id": x.command_id, "user_id": x.user_id, "action": x.action, "idempotency_key": x.idempotency_key, "payload_hash": x.payload_hash, "status_code": x.status_code, "response": dict(x.response), "created_at": x.created_at}
    @staticmethod
    def _audit_values(x): return {"audit_id": x.audit_id, "user_id": x.user_id, "account_id": x.account_id, "action": x.action, "object_id": x.object_id, "before_version": x.before_version, "after_version": x.after_version, "result": x.result, "occurred_at": x.occurred_at, "correlation_id": x.correlation_id, "details": dict(x.details)}
    @staticmethod
    def _event_values(x): return {"event_id": x.event_id, "event_type": x.event_type, "account_id": x.account_id, "occurred_at": x.occurred_at, "correlation_id": x.correlation_id, "payload": dict(x.payload)}
    @staticmethod
    def _import_values(x): return {"import_session_id": x.import_session_id, "account_id": x.account_id, "user_id": x.user_id, "file_hash": x.file_hash, "format_version": x.format_version, "columns": list(x.columns), "row_count": x.row_count, "preview_passed": x.preview_passed, "summary": dict(x.summary), "created_at": x.created_at, "expires_at": x.expires_at, "status": x.status.value, "committed_result_id": x.committed_result_id, "version": x.version}
    @staticmethod
    def _preference_values(x): return {"preference_id": x.preference_id, "user_id": x.user_id, "theme": x.theme, "timezone_name": x.timezone_name, "page_size": x.page_size, "updated_at": x.updated_at, "version": x.version}
    def save_session(self, value):
        with self.engine.begin() as c: c.execute(insert(sessions).values(**self._session_values(value)))
    def find_session_by_token_hash(self, value):
        with self.engine.connect() as c: row = c.execute(select(sessions).where(sessions.c.token_hash == value)).mappings().one_or_none()
        return None if row is None else self._session(row)
    def update_session(self, value):
        with self.engine.begin() as c: c.execute(update(sessions).where(sessions.c.session_id == value.session_id).values(**self._session_values(value)))
    def find_command(self, user_id, action, key):
        with self.engine.connect() as c: row = c.execute(select(commands).where(commands.c.user_id == user_id, commands.c.action == action, commands.c.idempotency_key == key)).mappings().one_or_none()
        return None if row is None else self._command(row)
    def save_command_and_audit(self, command, audit, event):
        try:
            with self.engine.begin() as c: self._write_command(c, command, audit, event)
        except IntegrityError as error: raise IdempotencyConflict() from error
    def save_audit(self, value, event):
        with self.engine.begin() as c: c.execute(insert(audits).values(**self._audit_values(value))); c.execute(insert(events).values(**self._event_values(event)))
    def save_import(self, value):
        with self.engine.begin() as c: c.execute(insert(imports).values(**self._import_values(value)))
    def find_import(self, account_id, file_hash, format_version):
        with self.engine.connect() as c: row = c.execute(select(imports).where(imports.c.account_id == account_id, imports.c.file_hash == file_hash, imports.c.format_version == format_version)).mappings().one_or_none()
        return None if row is None else self._import(row)
    def get_import(self, value):
        with self.engine.connect() as c: row = c.execute(select(imports).where(imports.c.import_session_id == value)).mappings().one_or_none()
        return None if row is None else self._import(row)
    def save_import_and_command(self, import_value, command, audit, event):
        with self.engine.begin() as c: c.execute(insert(imports).values(**self._import_values(import_value))); self._write_command(c, command, audit, event)
    def update_import_and_command(self, import_value, command, audit, event):
        with self.engine.begin() as c:
            result = c.execute(update(imports).where(imports.c.import_session_id == import_value.import_session_id, imports.c.version == import_value.version - 1).values(**self._import_values(import_value)))
            if result.rowcount != 1: raise VersionConflict()
            self._write_command(c, command, audit, event)
    def save_preference(self, value):
        with self.engine.begin() as c:
            current = c.execute(select(preferences.c.version).where(preferences.c.user_id == value.user_id)).scalar_one_or_none()
            if current is None: c.execute(insert(preferences).values(**self._preference_values(value)))
            elif current == value.version - 1: c.execute(update(preferences).where(preferences.c.user_id == value.user_id, preferences.c.version == current).values(**self._preference_values(value)))
            else: raise VersionConflict()
    def save_preference_and_command(self, value, command, audit, event):
        with self.engine.begin() as c:
            current = c.execute(select(preferences.c.version).where(preferences.c.user_id == value.user_id)).scalar_one_or_none()
            if current is None: c.execute(insert(preferences).values(**self._preference_values(value)))
            elif current == value.version - 1: c.execute(update(preferences).where(preferences.c.user_id == value.user_id, preferences.c.version == current).values(**self._preference_values(value)))
            else: raise VersionConflict()
            self._write_command(c, command, audit, event)
    def get_preference(self, user_id):
        with self.engine.connect() as c: row = c.execute(select(preferences).where(preferences.c.user_id == user_id)).mappings().one_or_none()
        return None if row is None else self._preference(row)
    @staticmethod
    def _write_command(c, command, audit, event): c.execute(insert(commands).values(**SqlAlchemyApiUiRepository._command_values(command))); c.execute(insert(audits).values(**SqlAlchemyApiUiRepository._audit_values(audit))); c.execute(insert(events).values(**SqlAlchemyApiUiRepository._event_values(event)))
