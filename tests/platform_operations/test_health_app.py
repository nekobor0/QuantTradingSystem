from fastapi.testclient import TestClient
from quant_trading_system.platform_operations.health_app import app

def test_liveness_is_process_only():assert TestClient(app).get("/health/live").json()=={"status":"UP"}
def test_readiness_fails_closed_without_database(monkeypatch):
 monkeypatch.delenv("QTS_DATABASE_URL",raising=False);response=TestClient(app).get("/health/ready");assert response.status_code==503 and response.json()["checks"]["database"] is False
def test_readiness_hides_database_exception(monkeypatch):
 monkeypatch.setenv("QTS_DATABASE_URL","not-a-valid-url");response=TestClient(app).get("/health/ready");assert response.status_code==503 and "not-a-valid-url" not in response.text
