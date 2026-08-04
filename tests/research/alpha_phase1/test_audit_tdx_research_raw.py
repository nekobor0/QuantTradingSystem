from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.alpha_phase1.audit_tdx_research_raw import audit


def _payload(symbol: str, rows: int) -> dict:
    dates = [f"2024010{number}" for number in range(2, 2 + rows)]
    values = {
        "Date": dates,
        "Open": ["10"] * rows,
        "High": ["11"] * rows,
        "Low": ["9"] * rows,
        "Close": ["10"] * rows,
        "Volume": ["100"] * rows,
        "Amount": ["1"] * rows,
        "ForwardFactor": ["1"] * rows,
        "VolInStock": ["1000"] * rows,
        "ErrorId": "0",
    }
    return {"result": {"Value": {symbol: values}}}


def _universe(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol", "name", "asset_type"))
        writer.writerow(("600000.SH", "A", "A_SHARE"))


def test_audit_selects_longest_payload_and_reports_invalid_files(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "short.json").write_text(json.dumps(_payload("600000.SH", 1)), encoding="utf-8")
    (raw / "long.json").write_text(json.dumps(_payload("600000.SH", 2)), encoding="utf-8")
    (raw / "broken.json").write_text("{}", encoding="utf-8")
    universe = tmp_path / "universe.csv"
    _universe(universe)

    result = audit(raw, universe)

    assert result["selected_a_share_symbols"] == 1
    assert result["a_share_universe_coverage"] == 1.0
    assert result["selected_rows"] == 2
    assert result["selected"]["600000.SH"]["file"] == "long.json"
    assert result["selected"]["600000.SH"]["factor_last"] == 1.0
    assert result["rejected_files"] == 1
