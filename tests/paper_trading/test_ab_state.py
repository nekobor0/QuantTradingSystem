from __future__ import annotations

import json

from paper_trading.models import PaperState
from paper_trading.state import StateRepository


def test_v3_state_round_trip_preserves_both_independent_strategies(tmp_path) -> None:
    path = tmp_path / "state.json"
    state = PaperState(start_date="2026-08-17")
    state.strategies["A"].dividend_book.cash -= 123.45
    state.strategies["B"].voltrend_book.cash -= 67.89
    state.strategies["A"].voltrend_book.nav_history.append(
        {"date": "2026-08-17", "nav": 750_100.0}
    )
    state.strategies["B"].dividend_book.model_weights = {"600000.SH": 1.0}

    StateRepository(path).save(state)
    restored = StateRepository(path).load()

    assert restored.version == 3
    assert set(restored.strategies) == {"A", "B"}
    assert restored.strategies["A"].dividend_book.cash == 249_876.55
    assert restored.strategies["B"].voltrend_book.cash == 249_932.11
    assert restored.strategies["A"].voltrend_book.nav_history[-1]["nav"] == 750_100.0
    assert restored.strategies["B"].dividend_book.model_weights == {"600000.SH": 1.0}


def test_v2_state_is_blocked_and_migrated_to_a_plus_empty_b(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "start_date": "2026-08-17",
                "dividend_book": {"name": "dividend", "cash": 249_000.0},
                "voltrend_book": {"name": "voltrend", "cash": 749_000.0},
            }
        ),
        encoding="utf-8",
    )

    restored = StateRepository(path).load()

    assert restored.legacy_import is True
    assert restored.strategies["A"].dividend_book.cash == 249_000.0
    assert restored.strategies["A"].voltrend_book.cash == 749_000.0
    assert restored.strategies["B"].dividend_book.cash == 750_000.0
    assert restored.strategies["B"].voltrend_book.cash == 250_000.0
