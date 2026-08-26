from pathlib import Path

import pandas as pd
import pytest

from quant_trading_system.research.macro_data.repair import (
    detect_shibor_on_3m_swap,
    repair_shibor_bronze,
)


def _fixtures(tmp_path: Path, *, extra_mismatch: bool = False) -> tuple[Path, Path, Path]:
    dates = pd.to_datetime([
        "2022-04-18", "2022-04-19", "2022-04-20", "2022-04-21",
        "2022-04-22", "2022-04-24", "2022-04-25", "2022-04-26",
        "2022-04-27", "2022-04-28", "2022-04-29", "2022-05-05",
        "2022-05-06", "2022-05-07", "2022-05-09", "2022-05-10",
        "2022-05-11", "2022-05-12", "2022-05-13", "2022-05-16",
        "2022-05-17",
    ])
    fields = ["on", "1w", "2w", "1m", "3m", "6m", "9m", "1y"]
    series = ["ON", "1W", "2W", "1M", "3M", "6M", "9M", "1Y"]
    bronze_rows = []
    official_rows = []
    for position, day in enumerate(dates):
        values = {field: float(position + offset + 1) for offset, field in enumerate(fields)}
        bronze = {"date": day.strftime("%Y%m%d"), **values}
        bronze["on"], bronze["3m"] = bronze["3m"], bronze["on"]
        bronze_rows.append(bronze)
        for field, tenor in zip(fields, series):
            official_rows.append({
                "series_id": f"CN.SHIBOR.{tenor}",
                "reference_period": day.strftime("%Y-%m-%d"),
                "value": values[field],
            })
    if extra_mismatch:
        bronze_rows[0]["1w"] += 0.1
    official_path = tmp_path / "official.parquet"
    bronze_path = tmp_path / "shibor.parquet"
    shard_path = tmp_path / "2022.parquet"
    pd.DataFrame(official_rows).to_parquet(official_path, index=False)
    pd.DataFrame(bronze_rows).to_parquet(bronze_path, index=False)
    pd.DataFrame(list(reversed(bronze_rows))).to_parquet(shard_path, index=False)
    return official_path, bronze_path, shard_path


def test_detect_and_repair_exact_shibor_swap(tmp_path: Path):
    official, bronze, shard = _fixtures(tmp_path)
    detection, _ = detect_shibor_on_3m_swap(official, bronze)
    assert detection["mismatch_cells"] == 42
    assert detection["exact_on_3m_swap_only"] is True

    result = repair_shibor_bronze(
        official_path=official,
        bronze_path=bronze,
        shard_path=shard,
        repair_root=tmp_path / "repair",
    )
    assert result["after"]["reconciliation"]["mismatch_cells"] == 0
    assert Path(result["before"]["aggregate"]["backup_path"]).exists()
    repaired = pd.read_parquet(bronze).sort_values("date").reset_index(drop=True)
    repaired_shard = pd.read_parquet(shard).sort_values("date").reset_index(drop=True)
    assert repaired.equals(repaired_shard)


def test_repair_refuses_any_non_swap_mismatch(tmp_path: Path):
    official, bronze, shard = _fixtures(tmp_path, extra_mismatch=True)
    with pytest.raises(ValueError, match="Refusing repair"):
        repair_shibor_bronze(
            official_path=official,
            bronze_path=bronze,
            shard_path=shard,
            repair_root=tmp_path / "repair",
        )
