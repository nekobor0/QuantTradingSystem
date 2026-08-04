from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from quant_trading_system.api_ui.app import create_app

from conftest import NOW


@pytest.fixture
def client_stack(stack):
    client = TestClient(create_app(stack[2]), raise_server_exceptions=False)
    login = client.post("/login", json={"username": "operator", "password": "correct"}).json()
    headers = {"X-Session-Token": login["session_token"], "X-CSRF-Token": login["csrf_token"], "Idempotency-Key": "key-1", "X-Correlation-ID": "corr-1"}
    return client, headers, stack


@pytest.mark.parametrize("route", ["/daily-status", "/daily-decisions", "/risk-state"])
def test_queries_require_auth(route, client_stack):
    response = client_stack[0].get(route, params={"as_of": NOW.isoformat()})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("route", ["/daily-status", "/daily-decisions", "/risk-state"])
def test_query_contract(route, client_stack):
    client, headers, _ = client_stack
    response = client.get(route, params={"as_of": NOW.isoformat()}, headers=headers)
    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "corr-1"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_bad_login_uses_unified_error(client_stack):
    response = client_stack[0].post("/login", json={"username": "operator", "password": "bad"})
    assert response.status_code == 401
    assert set(response.json()) == {"code", "message", "correlation_id", "field_errors", "retryable"}


def test_unknown_fields_are_rejected(client_stack):
    response = client_stack[0].post("/login", json={"username": "operator", "password": "correct", "admin": True})
    assert response.status_code == 422


def test_naive_order_time_rejected(client_stack):
    client, headers, _ = client_stack
    response = client.post("/orders", headers=headers, json={"expected_version": 0, "instrument_id": str(uuid4()), "side": "BUY", "quantity": 100, "currency": "CNY", "submitted_at": "2026-07-28T08:00:00", "source": "MANUAL", "manual_reason": "manual correction"})
    assert response.status_code == 422


def test_order_uses_instrument_uuid_and_structured_fields(client_stack):
    client, headers, stack = client_stack
    response = client.post("/orders", headers=headers, json={"expected_version": 0, "instrument_id": str(uuid4()), "side": "BUY", "quantity": 100, "currency": "CNY", "submitted_at": NOW.isoformat(), "source": "MANUAL", "manual_reason": "manual correction"})
    assert response.status_code == 200
    assert stack[1].commands[-1][0] == "RECORD_ORDER"


def test_missing_csrf_is_validation_error(client_stack):
    client, headers, _ = client_stack
    headers = {"X-Session-Token": headers["X-Session-Token"], "Idempotency-Key": "x"}
    response = client.post(f"/recommendations/{uuid4()}/approval", headers=headers, json={"expected_version": 0, "decision": "ACCEPT", "quantity": 100})
    assert response.status_code == 422


def test_invalid_csrf_is_403(client_stack):
    client, headers, _ = client_stack; headers["X-CSRF-Token"] = "bad"
    response = client.post(f"/recommendations/{uuid4()}/approval", headers=headers, json={"expected_version": 0, "decision": "ACCEPT", "quantity": 100})
    assert response.status_code == 403 and response.json()["code"] == "CSRF_INVALID"


def test_hard_block_is_409_and_no_write(client_stack):
    client, headers, stack = client_stack; stack[1].hard_block = True
    response = client.post(f"/recommendations/{uuid4()}/approval", headers=headers, json={"expected_version": 0, "decision": "ACCEPT", "quantity": 100})
    assert response.status_code == 409 and response.json()["code"] == "BUSINESS_BLOCK"
    assert stack[1].commands == []


def test_partial_approval_requires_reason(client_stack):
    client, headers, _ = client_stack
    response = client.post(f"/recommendations/{uuid4()}/approval", headers=headers, json={"expected_version": 0, "decision": "PARTIAL", "quantity": 50})
    assert response.status_code == 422


def test_internal_error_hides_exception(client_stack):
    client, headers, stack = client_stack; stack[1].fail = True
    response = client.get("/daily-status", params={"as_of": NOW.isoformat()}, headers=headers)
    assert response.status_code == 500 and "secret internal detail" not in response.text


def test_logout_revokes(client_stack):
    client, headers, _ = client_stack
    assert client.post("/logout", headers=headers).status_code == 204
    assert client.get("/daily-status", params={"as_of": NOW.isoformat()}, headers=headers).status_code == 401


def test_api_idempotency_double_click(client_stack):
    client, headers, stack = client_stack
    body = {"expected_version": 0, "decision": "ACCEPT", "quantity": 100}
    route = f"/recommendations/{uuid4()}/approval"
    assert client.post(route, headers=headers, json=body).json() == client.post(route, headers=headers, json=body).json()
    assert len(stack[1].commands) == 1


def test_api_preference_is_idempotent(client_stack):
    client, headers, stack = client_stack
    body = {"expected_version": 0, "theme": "dark", "timezone_name": "Asia/Shanghai", "page_size": 50}
    first = client.post("/ui-preferences", headers=headers, json=body)
    second = client.post("/ui-preferences", headers=headers, json=body)
    assert first.status_code == 200 and first.json() == second.json() and len(stack[0].preferences) == 1


def test_api_import_preview_and_commit(client_stack):
    client, headers, stack = client_stack
    preview = client.post("/broker-imports:preview", headers=headers, json={"file_hash": "a" * 64, "format_version": "v1", "columns": list(stack[2].REQUIRED_IMPORT_COLUMNS), "row_count": 2})
    assert preview.status_code == 200 and preview.json()["preview_passed"]
    headers["Idempotency-Key"] = "commit"
    result = client.post(f"/broker-imports/{preview.json()['import_session_id']}:commit", headers=headers, json={"file_hash": "a" * 64, "expected_version": 0})
    assert result.status_code == 200 and result.json()["version"] == 1
