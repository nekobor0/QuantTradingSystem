from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import ApiUiError
from .service import ApiUiService


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class ApprovalRequest(StrictModel):
    expected_version: int = Field(ge=0)
    decision: Literal["ACCEPT", "PARTIAL", "REJECT"]
    quantity: int = Field(ge=0)
    reason: str = ""

    @model_validator(mode="after")
    def partial_requires_reason(self):
        if self.decision == "PARTIAL" and not self.reason.strip():
            raise ValueError("reason required for partial approval")
        return self


class OrderRequest(StrictModel):
    expected_version: int = Field(ge=0)
    instrument_id: UUID
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    submitted_at: datetime
    source: Literal["RECOMMENDATION", "MANUAL"]
    recommendation_id: UUID | None = None
    manual_reason: str | None = None

    @field_validator("submitted_at")
    @classmethod
    def aware_submitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value


class FillRequest(StrictModel):
    expected_version: int = Field(ge=0)
    order_id: UUID
    broker_fill_id: str | None = None
    stable_row_hash: str | None = None
    manually_confirmed: bool = False
    filled_at: datetime
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    commission: Decimal = Field(ge=0)
    tax: Decimal = Field(ge=0)
    other_fee: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    instrument_id: UUID

    @field_validator("filled_at")
    @classmethod
    def aware_filled_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value


class ImportPreviewRequest(StrictModel):
    file_hash: str = Field(min_length=16, max_length=128)
    format_version: str = Field(min_length=1, max_length=64)
    columns: tuple[str, ...]
    row_count: int = Field(ge=0)


class ImportCommitRequest(StrictModel):
    file_hash: str = Field(min_length=16, max_length=128)
    expected_version: int = Field(ge=0)


class PreferenceRequest(StrictModel):
    theme: str
    timezone_name: str
    page_size: int
    expected_version: int = Field(ge=0)


def create_app(service: ApiUiService) -> FastAPI:
    app = FastAPI(title="Quant Trading System API", version="1.0.0")

    @app.middleware("http")
    async def context(request: Request, call_next):
        request.state.correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-Duration-Ms"] = f"{(time.perf_counter() - started) * 1000:.3f}"
        return response

    @app.exception_handler(ApiUiError)
    async def api_error(request: Request, error: ApiUiError):
        return JSONResponse(status_code=error.status_code, content=_error_body(request, error))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        fields = {".".join(str(x) for x in item["loc"]): item["msg"] for item in error.errors()}
        return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR", "message": "request validation failed", "correlation_id": request.state.correlation_id, "field_errors": fields, "retryable": False})

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "internal server error", "correlation_id": request.state.correlation_id, "field_errors": {}, "retryable": False})

    def now() -> datetime:
        return datetime.now(timezone.utc)

    @app.post("/login")
    def login(body: LoginRequest):
        value = service.login(body.username, body.password, now())
        return {"session_token": value.session_token, "csrf_token": value.csrf_token, "session_id": str(value.session_id), "expires_at": value.expires_at.isoformat(), "account_id": str(value.account_id)}

    @app.post("/logout", status_code=204)
    def logout(request: Request, session: str = Header(alias="X-Session-Token"), csrf: str = Header(alias="X-CSRF-Token")):
        service.logout(session, csrf, now(), request.state.correlation_id)

    @app.get("/daily-status")
    def daily_status(as_of: datetime, session: str = Header(alias="X-Session-Token")):
        return service.query(session, "daily_status", as_of, now())

    @app.get("/signals/{signal_id}")
    def signal(signal_id: UUID, session: str = Header(alias="X-Session-Token")):
        return service.query(session, "signal", None, now(), signal_id)

    @app.get("/daily-decisions")
    def daily_decisions(as_of: datetime, session: str = Header(alias="X-Session-Token")):
        return service.query(session, "daily_decisions", as_of, now())

    @app.get("/risk-state")
    def risk_state(as_of: datetime, session: str = Header(alias="X-Session-Token")):
        return service.query(session, "risk_state", as_of, now())

    @app.get("/reports/{report_id}")
    def report(report_id: UUID, session: str = Header(alias="X-Session-Token")):
        return service.query(session, "report", None, now(), report_id)

    @app.post("/recommendations/{recommendation_id}/approval")
    def approve(recommendation_id: UUID, body: ApprovalRequest, request: Request, session: str = Header(alias="X-Session-Token"), csrf: str = Header(alias="X-CSRF-Token"), key: str = Header(alias="Idempotency-Key")):
        return service.execute(session, csrf, "APPROVE_RECOMMENDATION", key, body.expected_version, body.model_dump(exclude={"expected_version"}), now(), request.state.correlation_id, recommendation_id)

    @app.post("/orders")
    def order(body: OrderRequest, request: Request, session: str = Header(alias="X-Session-Token"), csrf: str = Header(alias="X-CSRF-Token"), key: str = Header(alias="Idempotency-Key")):
        return service.execute(session, csrf, "RECORD_ORDER", key, body.expected_version, body.model_dump(exclude={"expected_version"}), now(), request.state.correlation_id)

    @app.post("/fills")
    def fill(body: FillRequest, request: Request, session: str = Header(alias="X-Session-Token"), csrf: str = Header(alias="X-CSRF-Token"), key: str = Header(alias="Idempotency-Key")):
        return service.execute(session, csrf, "RECORD_FILL", key, body.expected_version, body.model_dump(exclude={"expected_version"}), now(), request.state.correlation_id, body.order_id)

    @app.post("/broker-imports:preview")
    def preview(body: ImportPreviewRequest, request: Request, session: str = Header(alias="X-Session-Token"), csrf: str = Header(alias="X-CSRF-Token"), key: str = Header(alias="Idempotency-Key")):
        return service.preview_import(session, csrf, key, body.file_hash, body.format_version, body.columns, body.row_count, now(), request.state.correlation_id)

    @app.post("/broker-imports/{import_session_id}:commit")
    def commit(import_session_id: UUID, body: ImportCommitRequest, request: Request, session: str = Header(alias="X-Session-Token"), csrf: str = Header(alias="X-CSRF-Token"), key: str = Header(alias="Idempotency-Key")):
        return service.commit_import(session, csrf, key, import_session_id, body.file_hash, body.expected_version, now(), request.state.correlation_id)

    @app.post("/ui-preferences")
    def preference(body: PreferenceRequest, request: Request, session: str = Header(alias="X-Session-Token"), csrf: str = Header(alias="X-CSRF-Token"), key: str = Header(alias="Idempotency-Key")):
        return service.execute(session, csrf, "SAVE_UI_PREFERENCE", key, body.expected_version, body.model_dump(exclude={"expected_version"}), now(), request.state.correlation_id)

    return app


def _error_body(request: Request, error: ApiUiError) -> dict[str, object]:
    return {"code": error.code, "message": error.message, "correlation_id": request.state.correlation_id, "field_errors": error.field_errors, "retryable": error.retryable}
