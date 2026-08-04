from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from quant_trading_system.api_ui.domain import CommandResult
from quant_trading_system.api_ui.in_memory import InMemoryApiUiRepository
from quant_trading_system.api_ui.service import ApiUiService

NOW = datetime(2026, 7, 28, 8, tzinfo=timezone.utc)
ACCOUNT_ID = UUID("10000000-0000-0000-0000-000000000001")


class Verifier:
    def verify(self, username, password):
        return ("operator", ACCOUNT_ID) if (username, password) == ("operator", "correct") else None


class Backend:
    def __init__(self):
        self.commands = []
        self.hard_block = False
        self.fail = False

    def query(self, name, account_id, as_of, object_id=None):
        if self.fail:
            raise RuntimeError("secret internal detail")
        if name == "daily_status":
            return {"hard_block": self.hard_block, "blocking_reason": "positions unreconciled", "account_id": str(account_id)}
        if name == "daily_decisions":
            return {"as_of": (as_of or NOW).isoformat(), "mode": "PAPER", "hard_block": self.hard_block, "blocking_reasons": ["positions unreconciled"] if self.hard_block else [], "etf": {"daily_gate": "OPEN", "rebalance": False}, "equity": {"select": 2, "keep": 3, "exit": 1}, "sleeve_contributions": [], "net_recommendations": []}
        return {"name": name, "account_id": str(account_id), "object_id": None if object_id is None else str(object_id), "token": "must-not-leak", "account_number": "6222021234567890"}

    def command(self, action, account_id, object_id, payload):
        result_id = object_id or uuid4()
        self.commands.append((action, account_id, result_id, dict(payload)))
        return CommandResult(result_id, int(payload.get("expected_version", 0)) + 1, {"status": "RECORDED"}, action + "Committed")


@pytest.fixture
def stack():
    repository = InMemoryApiUiRepository()
    backend = Backend()
    service = ApiUiService(repository, backend, Verifier())
    credentials = service.login("operator", "correct", NOW)
    return repository, backend, service, credentials
