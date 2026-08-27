from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.data_lake.update_strategy_calendar import extend_calendar, update_calendar


RULES = {
    "exchange": "SSE",
    "valid_from": "2026-01-01",
    "valid_to": "2026-12-31",
    "closed_dates": [],
    "source": {"url": "https://official.example.invalid"},
}


def _base() -> pd.DataFrame:
    return pd.DataFrame([
        {"exchange": "SSE", "cal_date": "20260819", "is_open": "1", "pretrade_date": "20260818"}
    ])


def test_extend_calendar_includes_weekends_and_next_sessions() -> None:
    result = extend_calendar(_base(), RULES, "2026-08-26")
    added = result[result["cal_date"].gt("20260819")]
    assert added["cal_date"].tolist() == [
        "20260820", "20260821", "20260822", "20260823", "20260824", "20260825", "20260826"
    ]
    assert added["is_open"].tolist() == ["1", "1", "0", "0", "1", "1", "1"]
    assert added["pretrade_date"].tolist() == [
        "20260819", "20260820", "20260821", "20260821", "20260821", "20260824", "20260825"
    ]


def test_extend_calendar_refuses_dates_outside_versioned_rules() -> None:
    with pytest.raises(ValueError, match="outside rule coverage"):
        extend_calendar(_base(), RULES, "2027-01-04")


def test_update_calendar_writes_hash_manifest(tmp_path: Path) -> None:
    base_path = tmp_path / "base.parquet"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "calendar.parquet"
    _base().to_parquet(base_path, index=False)
    rules_path.write_text(json.dumps(RULES), encoding="utf-8")
    manifest = update_calendar(base_path, rules_path, output_path, "2026-08-26")
    assert manifest["coverage"]["max"] == "20260826"
    assert manifest["actual_session_evidence"] is False
    assert len(manifest["output"]["sha256"]) == 64
    assert output_path.with_suffix(".manifest.json").exists()
