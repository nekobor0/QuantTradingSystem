from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.macro_data.contracts import validate_canonical_v2
from quant_trading_system.research.macro_data.w1_pmi_history import run_full_candidate
from scripts.data_lake.run_macro_w1_pmi_state_full import run_full


def _archive(tmp_path: Path) -> Path:
    output_root = tmp_path / "lake"
    raw_root = output_root / "raw" / "nbs_pmi_release_archive"
    raw_root.mkdir(parents=True)
    pages: list[dict[str, str]] = []
    for index, period in enumerate(("2018-01", "2018-02")):
        periods = ("2018-01",) if index == 0 else ("2018-01", "2018-02")

        def table(rows: list[list[str]]) -> str:
            return "<table>" + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows) + "</table>"

        payload = (
            f'<html><head><meta name="PubDate" content="{period}-01 09:30:00"></head><body>'
            + table([[item, "51.0", "50.0", "52.0", "49.0", "48.0", "50.0"] for item in periods])
            + table([[item, "53.0", "50.0", "51.0", "52.0", "53.0", "54.0"] for item in periods])
            + table([[item, "55.0", "56.0", "57.0"] for item in periods])
            + "<p>综合PMI产出指数为58.0%</p></body></html>"
        ).encode("utf-8")
        raw_path = raw_root / f"{period}.html"
        raw_path.write_bytes(payload)
        url = f"https://www.stats.gov.cn/sj/zxfb/{period.replace('-', '')}/release.html"
        manifest = {
            "schema_version": 1,
            "source_id": "nbs_pmi_release_archive",
            "retrieved_at": f"2026-08-27T00:00:0{index}+00:00",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "raw_path": str(raw_path.resolve()),
            "request": {"method": "GET", "url": url},
            "response": {"status": 200, "headers": {"content-type": "text/html"}},
        }
        (raw_root / f"{period}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        pages.append({"document_date": f"{period}-01", "reference_period": period, "url": url})
    catalog = output_root / "catalogs"
    catalog.mkdir()
    (catalog / "pmi_release_pages.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    return output_root


def test_audit_only_writes_candidate_audit_without_curated(tmp_path: Path) -> None:
    output_root = _archive(tmp_path)
    result = run_full(output_root, "2018-01", "2018-02", "audit-only")
    assert result["audit"]["run_mode"] == "full"
    assert result["audit"]["sources"][0]["full_vintage_row_count"] > 16
    assert result["curated_write"]["performed"] is False
    assert not (output_root / "curated" / "w1_pmi_state_official_release_vintages.parquet").exists()
    assert Path(result["output"]).exists()


def test_execute_is_rejected_by_closed_gate_and_curated_is_unchanged(tmp_path: Path) -> None:
    output_root = tmp_path / "lake"
    curated = output_root / "curated" / "w1_pmi_state_official_release_vintages.parquet"
    curated.parent.mkdir(parents=True)
    curated.write_bytes(b"sentinel")
    before = hashlib.sha256(curated.read_bytes()).hexdigest()
    result = run_full(output_root, "2018-01", "2018-02", "execute")
    assert result["blocked"] is True
    assert all(item["code"] == "FULL_HISTORY_NOT_ALLOWED" for item in result["blockers"])
    assert result["curated_sha256_before"] == before
    assert result["curated_sha256_after"] == before
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == before


def test_duplicate_vintage_primary_key_is_rejected(tmp_path: Path) -> None:
    frame = run_full_candidate(_archive(tmp_path), "2018-01", "2018-02")["_frame"]
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    validation = validate_canonical_v2(duplicate)
    assert validation["passed"] is False
    assert "unique_series_period_vintage" in validation["failures"]
