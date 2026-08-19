from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import paper_trading.app as web
from paper_trading.market import DataStore
from paper_trading.state import StateRepository


def test_update_failure_is_persisted_for_dashboard_visibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = StateRepository(tmp_path / "state.json")
    monkeypatch.setattr(web, "repository", repository)
    monkeypatch.setattr(web, "store", DataStore(tmp_path))

    def fail_update(trade_date: str):
        raise ConnectionError("temporary transport failure")

    monkeypatch.setattr(web, "update_all", fail_update)
    response = TestClient(web.app, raise_server_exceptions=False).post("/api/update_data")
    assert response.status_code == 503
    assert repository.load().last_data_update["status"] == "FAIL"
    assert "temporary transport failure" in repository.load().last_data_update["errors"][0]["error"]
