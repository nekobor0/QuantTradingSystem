"""Fail-closed registry for the three frozen V5 index-enhancement baselines."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from quant_trading_system.research.alpha_phase1.portfolio_v5 import performance_metrics


BASELINES = {
    "equal_style_p0": "style_baseline_portfolio_v5",
    "historical_icir": "style_historical_icir_portfolio_v5",
    "rolling_regression_24m": "style_rolling_regression_24m_portfolio_v5",
}
BENCHMARKS = ("000300.SH", "000852.SH")
VALIDATION_START = pd.Timestamp("2023-07-01")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parquet_summary(path: Path, keys: list[str]) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    frame = pd.read_parquet(path, columns=keys)
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": parquet.metadata.num_rows,
        "columns": parquet.schema_arrow.names,
        "duplicate_keys": int(frame.duplicated(keys).sum()),
    }


def _json_summary(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _assert_metrics_match(
    reported: dict[str, Any],
    recomputed: dict[str, Any],
    *,
    baseline: str,
    benchmark: str,
) -> None:
    for key, value in recomputed.items():
        if key not in reported:
            raise ValueError(f"{baseline}/{benchmark} missing metric {key}")
        reported_value = reported[key]
        if isinstance(value, float):
            if not np.isclose(value, reported_value, rtol=0.0, atol=1e-12, equal_nan=True):
                raise ValueError(
                    f"{baseline}/{benchmark} metric drift for {key}: "
                    f"{reported_value!r} != {value!r}"
                )
        elif reported_value != value:
            raise ValueError(
                f"{baseline}/{benchmark} metric drift for {key}: "
                f"{reported_value!r} != {value!r}"
            )


def build_registry_snapshot(
    project_root: Path,
    goal_path: Path,
    evaluator_spec_path: Path,
) -> dict[str, Any]:
    artifact_dir = project_root / "artifacts" / "alpha_phase1"
    baselines: dict[str, Any] = {}
    for name, stem in BASELINES.items():
        evaluation_path = artifact_dir / f"{stem}_evaluation.json"
        monthly_path = artifact_dir / f"{stem}_monthly.parquet"
        holdings_path = artifact_dir / f"{stem}_holdings.parquet"
        capacity_path = artifact_dir / f"{stem}_capacity.json"
        for path in (evaluation_path, monthly_path, holdings_path, capacity_path):
            if not path.exists():
                raise FileNotFoundError(path)

        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        monthly = pd.read_parquet(monthly_path)
        if set(monthly["index_code"].unique()) != set(BENCHMARKS):
            raise ValueError(f"{name} benchmark set drift")
        benchmark_metrics: dict[str, Any] = {}
        for benchmark in BENCHMARKS:
            group = monthly[monthly["index_code"].eq(benchmark)].copy()
            validation = group[group["signal_date"].ge(VALIDATION_START)]
            recomputed = performance_metrics(validation)
            reported = evaluation["benchmarks"][benchmark]["fixed_validation"]
            _assert_metrics_match(
                reported,
                recomputed,
                baseline=name,
                benchmark=benchmark,
            )
            benchmark_metrics[benchmark] = reported

        baselines[name] = {
            "stem": stem,
            "evaluation": _json_summary(evaluation_path),
            "monthly": _parquet_summary(
                monthly_path, ["index_code", "signal_date"]
            ),
            "holdings": _parquet_summary(
                holdings_path, ["index_code", "signal_date", "ts_code"]
            ),
            "capacity": _json_summary(capacity_path),
            "fixed_validation": benchmark_metrics,
        }
        if baselines[name]["monthly"]["duplicate_keys"]:
            raise ValueError(f"{name} monthly duplicate keys")
        if baselines[name]["holdings"]["duplicate_keys"]:
            raise ValueError(f"{name} holdings duplicate keys")

    return {
        "version": 6,
        "registry": "frozen_v5_index_enhancement_baselines",
        "goal": _json_summary(goal_path),
        "evaluator_spec": _json_summary(evaluator_spec_path),
        "protocol": {
            "development_start": "2018-07-02",
            "development_end": "2023-06-30",
            "fixed_validation_start": "2023-07-01",
            "fixed_validation_end": "2026-06-30",
            "signal": "T month-end",
            "execution": "T+1 adjusted open",
            "minimum_round_trip_cost": 0.0005,
            "benchmarks": list(BENCHMARKS),
        },
        "baselines": baselines,
    }


def assert_registry_matches(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    if expected != actual:
        raise ValueError("frozen V5 baseline registry drift detected")


def write_registry_atomic(snapshot: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output)

