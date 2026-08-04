import json

import pytest

from quant_trading_system.research.v6.live_shadow import (
    append_shadow_correction,
    append_shadow_record,
    canonical_hash,
)


def record() -> dict:
    digest = canonical_hash({"version": 1})
    return {
        "strategy_id": "rolling_24m",
        "signal_time": "2026-07-31T15:00:00+08:00",
        "data_manifest_hash": digest,
        "config_hash": digest,
        "code_hash": digest,
        "factor_exposures": {"value": 0.2},
        "target_holdings": {"A": 0.6, "B": 0.4},
        "actual_holdings": {"A": 0.6, "B": 0.4},
        "unfilled_reasons": {},
        "simulated_open_prices": {"A": 10.0, "B": 20.0},
        "slippage": 0.0,
        "turnover": 0.1,
        "fees": 0.00005,
        "industry_exposure": {"I1": 1.0},
        "style_exposure": {"value": 0.2},
        "beta": 0.95,
        "capacity": 10_000_000,
        "shadow_nav": 1.0,
        "benchmark_nav": 1.0,
        "backtest_deviation": 0.0,
    }


def test_live_shadow_is_append_only_and_corrections_preserve_original(tmp_path):
    original = append_shadow_record(tmp_path, record())
    original_bytes = original.read_bytes()
    with pytest.raises(FileExistsError, match="cannot be overwritten"):
        append_shadow_record(tmp_path, record())
    correction = append_shadow_correction(
        tmp_path,
        "rolling_24m",
        "20260731",
        "2026-08-01T09:00:00+08:00",
        "late source correction",
        {"capacity": 9_900_000},
    )
    assert original.read_bytes() == original_bytes
    assert json.loads(correction.read_text(encoding="utf-8"))[
        "original_record_hash"
    ] == json.loads(original_bytes)["record_hash"]


def test_live_shadow_rejects_missing_hash(tmp_path):
    payload = record()
    payload.pop("data_manifest_hash")
    with pytest.raises(ValueError, match="missing"):
        append_shadow_record(tmp_path, payload)


def test_live_shadow_rejects_non_finite_numbers_and_unsafe_strategy(tmp_path):
    payload = record()
    payload["beta"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        append_shadow_record(tmp_path, payload)
    payload = record()
    payload["strategy_id"] = "../escape"
    with pytest.raises(ValueError, match="unsafe"):
        append_shadow_record(tmp_path, payload)
