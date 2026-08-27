from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quant_trading_system.research.macro_data.w1_pmi_history import (
    SERIES,
    discover_listing_pages,
    expected_by_series,
    expected_cells,
    parse_release,
    parse_release_vintages,
    run_full_candidate,
    verify_manifest_hashes,
)


def _page(periods: list[str], publication: str) -> bytes:
    def table(rows: list[list[str]]) -> str:
        return "<table>" + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows) + "</table>"

    mfg = [[period, str(51.0 + i), "50.0", str(52.0 + i), "49.0", "48.0", "50.0"] for i, period in enumerate(periods)]
    detail = [[period, str(53.0 + i), "50.0", "51.0", "52.0", "53.0", str(54.0 + i)] for i, period in enumerate(periods)]
    nonmfg = [[period, str(55.0 + i), str(56.0 + i), str(57.0 + i)] for i, period in enumerate(periods)]
    return (
        f'<html><head><meta name="PubDate" content="{publication} 09:30:00"></head><body>'
        + table(mfg)
        + table(detail)
        + table(nonmfg)
        + '<p>综合PMI产出指数为58.0%</p></body></html>'
    ).encode("utf-8")


def _archive(tmp_path: Path) -> Path:
    output_root = tmp_path / "lake"
    raw_root = output_root / "raw" / "nbs_pmi_release_archive"
    raw_root.mkdir(parents=True)
    pages: list[dict[str, str]] = []
    for index, (period, periods) in enumerate((("2018-01", ["2018-01"]), ("2018-02", ["2018-01", "2018-02"]))):
        payload = _page(periods, f"{period}-01")
        raw_path = raw_root / f"{period}.html"
        raw_path.write_bytes(payload)
        url = f"https://www.stats.gov.cn/sj/zxfb/{period.replace('-', '')}/release.html"
        manifest = {
            "schema_version": 1,
            "source_id": "nbs_pmi_release_archive",
            "retrieved_at": f"2026-08-27T00:00:0{index}+00:00",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "raw_path": str(raw_path.resolve()),
            "request": {"method": "GET", "url": url},
            "response": {"status": 200, "headers": {"content-type": "text/html"}},
        }
        (raw_root / f"{period}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        pages.append({"document_date": f"{period}-01", "layout": "rolling", "reference_period": period, "title": "PMI", "url": url})
    catalog = output_root / "catalogs"
    catalog.mkdir()
    (catalog / "pmi_release_pages.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    return output_root


def test_expected_calendar_is_series_period_grain() -> None:
    by_series = expected_by_series("2018-01", "2018-02")
    assert len(expected_cells("2018-01", "2018-02")) == 16
    assert all(periods == ["2018-01", "2018-02"] for periods in by_series.values())
    assert SERIES[0] in by_series


def test_full_vintage_parser_keeps_page_history_and_direct_projection(tmp_path: Path) -> None:
    output_root = _archive(tmp_path)
    result = run_full_candidate(output_root, "2018-01", "2018-02")
    audit = result["audit"]
    source = audit["sources"][0]
    frame = result["_frame"]
    assert audit["run_mode"] == "full"
    assert len(audit["expected_periods"]) == 16
    assert len(audit["observed_periods"]) == 16
    assert source["direct_projection_row_count"] == 16
    assert source["full_vintage_row_count"] == len(frame) > 16
    assert source["direct_projection_mismatches"] == []
    assert frame.duplicated(["series_id", "reference_period", "vintage_id"]).sum() == 0
    assert source["canonical_validation"]["passed"]
    assert audit["blocked"] is False
    assert {len(group) for _, group in frame.groupby("vintage_id")} == {8, 15}
    direct = parse_release(_page(["2018-01"], "2018-01-01"), "2018-01")
    vintage = parse_release_vintages(_page(["2018-01"], "2018-01-01"), "2018-01")
    assert len(direct.rows) == len(vintage.rows) == 8


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
    assert not verify_manifest_hashes([manifest])["valid"]
    raw.write_bytes(payload)
    manifest.write_text(json.dumps({key: value for key, value in document.items() if key != "sha256"}), encoding="utf-8")
    assert not verify_manifest_hashes([manifest])["valid"]
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
