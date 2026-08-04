from __future__ import annotations

import pandas as pd

from scripts.alpha_phase1 import fetch_tushare_event_data as module


class _Limiter:
    def acquire(self) -> None:
        return None


def test_month_ranges_clip_first_and_last_month() -> None:
    assert module.month_ranges("20240115", "20240210") == [
        ("202401", "20240115", "20240131"),
        ("202402", "20240201", "20240210"),
    ]


def test_fetch_month_follows_offset_after_full_page(tmp_path, monkeypatch) -> None:
    offsets = []

    class Client:
        def query(self, api_name: str, **kwargs) -> pd.DataFrame:
            offsets.append(kwargs["offset"])
            rows = 6000 if kwargs["offset"] == 0 else 2
            start = kwargs["offset"]
            return pd.DataFrame(
                {
                    "ts_code": [f"{number:06d}.SZ" for number in range(start, start + rows)],
                    "ann_date": ["20240101"] * rows,
                    "proc": ["实施"] * rows,
                }
            )

    monkeypatch.setattr(module.ts, "pro_api", lambda token: Client())
    result = module.fetch_month(
        "repurchase",
        "repurchase",
        ["ts_code", "ann_date", "proc"],
        "202401",
        "20240101",
        "20240131",
        tmp_path,
        "secret",
        _Limiter(),
        1,
    )

    assert offsets == [0, 6000]
    assert result["rows"] == 6002
    assert len(pd.read_parquet(tmp_path / "event_shards" / "repurchase" / "202401.parquet")) == 6002
