from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from quant_trading_system.research.macro_data.w1_pmi_history import (
    SERIES,
    discover_listing_pages,
    expected_by_series,
    expected_cells,
    run_history_shadow,
    verify_manifest_hashes,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "macro_r011"


def test_expected_calendar_is_series_period_grain() -> None:
    by_series = expected_by_series("2009-06", "2026-07")
    assert sum(len(periods) for periods in by_series.values()) == 1282
    assert len(expected_cells("2009-06", "2026-07")) == 1282
    assert by_series[SERIES[0]][0] == "2009-06"
    assert by_series[SERIES[2]][0] == "2012-04"
    assert by_series[SERIES[4]][0] == "2014-11"
    assert by_series[SERIES[7]][0] == "2018-01"


def test_full_range_shadow_has_frozen_gap_and_metadata_evidence() -> None:
    result = run_history_shadow(ARTIFACTS, "2009-06", "2026-07")
    audit = result["audit"]
    source = audit["sources"][0]
    detail = source["history_detail"]
    assert len(audit["expected_periods"]) == 1282
    assert len(audit["observed_periods"]) == 1274
    assert len(detail["official_release_page_not_discovered"]) == 8
    assert all(item["reason"] == "OFFICIAL_RELEASE_PAGE_NOT_DISCOVERED" for item in audit["structural_omissions"])
    assert detail["raw_hash"]["checked"] == 204
    assert detail["raw_hash"]["failures"] == []
    assert source["canonical_validation"]["passed"]
    assert detail["pit_grade"] == "A"
    assert detail["license_scope"] == "internal_research"
    assert audit["research_ready"] is False


def test_manifest_tamper_and_required_field_loss_turn_hash_audit_red_then_green(tmp_path: Path) -> None:
    raw = tmp_path / "release.html"
    payload = b"official-release"
    raw.write_bytes(payload)
    manifest = tmp_path / "release.manifest.json"
    document = {
        "source_id": "nbs_pmi_release_archive",
        "retrieved_at": "2026-08-27T00:00:00+00:00",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "raw_path": str(raw),
        "request": {"method": "GET", "url": "https://www.stats.gov.cn/example.html"},
        "response": {"status": 200, "headers": {"content-type": "text/html"}},
    }
    manifest.write_text(json.dumps(document), encoding="utf-8")
    assert verify_manifest_hashes([manifest])["valid"]
    raw.write_bytes(b"tampered")
    tampered = verify_manifest_hashes([manifest])
    assert tampered["valid"] is False
    assert tampered["failures"]
    raw.write_bytes(payload)
    manifest.write_text(json.dumps({key: value for key, value in document.items() if key != "sha256"}), encoding="utf-8")
    missing_field = verify_manifest_hashes([manifest])
    assert missing_field["valid"] is False
    manifest.write_text(json.dumps(document), encoding="utf-8")
    assert verify_manifest_hashes([manifest])["valid"]


def test_listing_discovery_reuses_success_retries_failures_and_deduplicates_urls(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetcher(url: str) -> tuple[int, dict[str, str], bytes, str | None]:
        calls.append(url)
        if url.endswith("index_1.html"):
            return 503, {"Content-Type": "text/html"}, b"temporary", "HTTP_503"
        payload = '<a href="./202607/t20260731_1964253.html" title="采购经理指数运行情况">x</a><a href="./202607/t20260731_1964253.html">duplicate</a>'.encode("utf-8")
        return 200, {"Content-Type": "text/html"}, payload, None

    first = discover_listing_pages(tmp_path, page_count=2, retries=3, fetcher=fetcher)
    assert first["fetched_pages"] == 1
    assert len(first["candidate_urls"]) == 1
    assert len(first["failed_attempts"]) == 3
    assert calls.count("https://www.stats.gov.cn/sj/zxfb/") == 1
    second = discover_listing_pages(
        tmp_path, page_count=1, retries=3,
        fetcher=lambda url: (_ for _ in ()).throw(AssertionError("successful manifest was not reused")),
    )
    assert second["reused_pages"] == 1


def test_unified_runner_dispatches_shadow_and_keeps_full_blocked() -> None:
    base = [sys.executable, "scripts/data_lake/run_macro_w1_package.py", "--package", "pmi_state"]
    shadow = subprocess.run(
        [*base, "--mode", "shadow", "--start", "2009-06", "--end", "2026-07"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert shadow.returncode == 0, shadow.stdout + shadow.stderr
    assert "PACKAGE_RUNNER_NOT_DISPATCHED" not in shadow.stdout
    assert '"blocked": false' in shadow.stdout
    full = subprocess.run(
        [*base, "--mode", "full", "--start", "2009-06", "--end", "2026-07"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert full.returncode == 2
    assert "FULL_HISTORY_NOT_ALLOWED" in full.stdout
    assert "PACKAGE_RUNNER_NOT_DISPATCHED" not in full.stdout
