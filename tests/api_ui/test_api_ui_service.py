from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from quant_trading_system.api_ui.errors import AuthenticationError, BusinessBlock, CsrfError, IdempotencyConflict, ValidationError, VersionConflict

from conftest import NOW


def test_login_rejects_bad_credentials(stack):
    with pytest.raises(AuthenticationError): stack[2].login("operator", "bad", NOW)
def test_session_expiry(stack):
    with pytest.raises(AuthenticationError): stack[2].authenticate(stack[3].session_token, NOW + timedelta(hours=8))
def test_logout_revokes_session(stack):
    stack[2].logout(stack[3].session_token, stack[3].csrf_token, NOW, "c")
    with pytest.raises(AuthenticationError): stack[2].authenticate(stack[3].session_token, NOW)
def test_csrf_required(stack):
    with pytest.raises(CsrfError): stack[2].execute(stack[3].session_token, "bad", "RECORD_ORDER", "key", 0, {}, NOW, "c")
def test_hard_block_prevents_approval(stack):
    stack[1].hard_block = True
    with pytest.raises(BusinessBlock): stack[2].execute(stack[3].session_token, stack[3].csrf_token, "APPROVE_RECOMMENDATION", "key", 0, {}, NOW, "c", uuid4())
    assert stack[1].commands == []
def test_same_command_is_idempotent(stack):
    a = stack[2].execute(stack[3].session_token, stack[3].csrf_token, "RECORD_ORDER", "key", 0, {"quantity": 100}, NOW, "c")
    b = stack[2].execute(stack[3].session_token, stack[3].csrf_token, "RECORD_ORDER", "key", 0, {"quantity": 100}, NOW, "c")
    assert a == b and len(stack[1].commands) == 1
def test_key_reuse_with_different_payload_fails(stack):
    service, credentials = stack[2], stack[3]; service.execute(credentials.session_token, credentials.csrf_token, "RECORD_ORDER", "key", 0, {"quantity": 100}, NOW, "c")
    with pytest.raises(IdempotencyConflict): service.execute(credentials.session_token, credentials.csrf_token, "RECORD_ORDER", "key", 0, {"quantity": 200}, NOW, "c")
def test_query_sanitizes_secrets_and_account_numbers(stack):
    result = stack[2].query(stack[3].session_token, "signal", NOW, NOW)
    assert "token" not in result and result["account_number"] == "************7890"
def test_preview_missing_columns_is_non_committable(stack):
    result = stack[2].preview_import(stack[3].session_token, stack[3].csrf_token, "p", "a" * 64, "v1", ("price",), 2, NOW, "c")
    assert result["preview_passed"] is False
    with pytest.raises(ValidationError): stack[2].commit_import(stack[3].session_token, stack[3].csrf_token, "c1", UUID(result["import_session_id"]), "a" * 64, 0, NOW, "c")
def test_preview_commit_hash_binding_and_atomic_result(stack):
    preview = stack[2].preview_import(stack[3].session_token, stack[3].csrf_token, "p", "a" * 64, "v1", stack[2].REQUIRED_IMPORT_COLUMNS, 2, NOW, "c"); import_id = UUID(preview["import_session_id"])
    with pytest.raises(ValidationError): stack[2].commit_import(stack[3].session_token, stack[3].csrf_token, "bad", import_id, "b" * 64, 0, NOW, "c")
    result = stack[2].commit_import(stack[3].session_token, stack[3].csrf_token, "ok", import_id, "a" * 64, 0, NOW, "c")
    assert result["version"] == 1 and stack[0].imports[import_id].status.value == "COMMITTED"
def test_import_expiry(stack):
    preview = stack[2].preview_import(stack[3].session_token, stack[3].csrf_token, "p", "a" * 64, "v1", stack[2].REQUIRED_IMPORT_COLUMNS, 1, NOW, "c")
    with pytest.raises(ValidationError): stack[2].commit_import(stack[3].session_token, stack[3].csrf_token, "c", UUID(preview["import_session_id"]), "a" * 64, 0, NOW + timedelta(minutes=30), "c")
def test_preference_version_and_idempotency(stack):
    service, credentials = stack[2], stack[3]; payload = {"theme": "dark", "timezone_name": "Asia/Shanghai", "page_size": 50}
    result = service.execute(credentials.session_token, credentials.csrf_token, "SAVE_UI_PREFERENCE", "pref", 0, payload, NOW, "c")
    assert result["version"] == 1 and service.execute(credentials.session_token, credentials.csrf_token, "SAVE_UI_PREFERENCE", "pref", 0, payload, NOW, "c") == result
    with pytest.raises(VersionConflict): service.execute(credentials.session_token, credentials.csrf_token, "SAVE_UI_PREFERENCE", "pref2", 0, {"theme": "light", "timezone_name": "UTC", "page_size": 20}, NOW, "c")
@pytest.mark.parametrize("key", ["", "x" * 129])
def test_invalid_idempotency_key(stack, key):
    with pytest.raises(ValidationError): stack[2].execute(stack[3].session_token, stack[3].csrf_token, "RECORD_ORDER", key, 0, {}, NOW, "c")
