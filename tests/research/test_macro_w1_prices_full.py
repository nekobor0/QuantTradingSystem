from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_trading_system.research.macro_data import w1_prices_history as prices
from scripts.data_lake.run_macro_w1_prices_full import (
    CURATED_NAME,
    DEFAULT_MANIFEST,
    PIT_A_END,
    PIT_A_START,
    REQUIRED_SCOPE,
    check_full_gate,
    run_full,
)


def _next_month(period: str) -> tuple[int, int]:
    year, month = (int(item) for item in period.split("-"))
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _cpi_html(period: str) -> bytes:
    year, month = period.split("-")
    release_year, release_month = _next_month(period)
    return f"""<html><head><meta name='ArticleTitle' content='{year}年{int(month)}月份居民消费价格同比上涨1.0%'><meta name='PubDate' content='{release_year:04d}/{release_month:02d}/09 09:30'></head><body><table><tr><th>指标</th><th>同比涨跌幅（%）</th></tr><tr><td>居民消费价格</td><td>1.0</td></tr><tr><td>不包括食品和能源</td><td>0.9</td></tr></table></body></html>""".encode()


def _ppi_html(period: str) -> bytes:
    year, month = period.split("-")
    release_year, release_month = _next_month(period)
    return f"""<html><head><meta name='ArticleTitle' content='{year}年{int(month)}月份工业生产者出厂价格同比上涨4.1%'><meta name='PubDate' content='{release_year:04d}/{release_month:02d}/09 09:30'></head><body><table><tr><th>指标</th><th>环比涨跌幅（%）</th><th>同比涨跌幅（%）</th></tr><tr><td>一、工业生产者出厂价格</td><td>-0.3</td><td>4.1</td></tr><tr><td>二、工业生产者购进价格</td><td>0.0</td><td>6.4</td></tr></table></body></html>""".encode()


def _interpretation_html(period: str, base_year: int) -> bytes:
    year, month = period.split("-")
    release_year, release_month = _next_month(period)
    return f"""<html><head><meta name='ArticleTitle' content='国家统计局城市司首席统计师解读{year}年{int(month)}月份CPI和PPI数据'><meta name='PubDate' content='{release_year:04d}/{release_month:02d}/09 09:30'></head><body>{base_year}年为基期，CPI和PPI统计制度说明。</body></html>""".encode()


def _manifest(path: Path, *, allowed: bool = True, blockers: list[str] | None = None, window: object = "exact", scope: str = REQUIRED_SCOPE) -> Path:
    package: dict[str, object] = {
        "package_id": "prices",
        "full_history_allowed": allowed,
        "full_blockers": blockers or [],
    }
    if window != "missing":
        package["full_window"] = window if window != "exact" else {"start": PIT_A_START, "end": PIT_A_END, "scope": scope}
    path.write_text(json.dumps({"schema_version": 2, "gate_version": 2, "packages": [package]}), encoding="utf-8")
    return path


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    output_root = tmp_path / "lake"
    periods: list[str] = []
    year, month = 2021, 1
    while (year, month) <= (2026, 7):
        periods.append(f"{year:04d}-{month:02d}")
        year, month = _next_month(f"{year:04d}-{month:02d}")
    payloads: dict[str, tuple[dict[str, object], bytes]] = {}
    candidates: dict[str, dict[str, dict[str, str]]] = {"cpi": {}, "ppi": {}, "interpretation": {}}
    for period in periods:
        for kind, payload in (
            ("cpi", _cpi_html(period)),
            ("ppi", _ppi_html(period)),
            ("interpretation", _interpretation_html(period, 2020 if period < "2026-01" else 2025)),
        ):
            url = f"https://www.stats.gov.cn/synthetic/{kind}/{period}.html"
            source_type = f"official_{kind}_release" if kind != "interpretation" else "official_interpretation"
            manifest = prices._capture(
                output_root,
                source_id=prices.SOURCE_ID,
                source_type=source_type,
                reference_period=period,
                request_method="GET",
                request_url=url,
                parameters=None,
                status=200,
                headers={"Content-Type": "text/html"},
                payload=payload,
                error=None,
            )
            payloads[url] = (manifest, payload)
            candidates[kind][period] = {"url": url, "title": ""}
    monkeypatch.setattr(
        prices,
        "_discover",
        lambda _root, _start, _end, *, full: {"listing": {"urls": [], "periods": periods, "failures": []}, "search": [], "candidates": candidates, "query_start": PIT_A_START},
    )
    monkeypatch.setattr(
        prices,
        "_methodology",
        lambda *_args, **_kwargs: (
            [
                {"regime": "2020_base_effective_2021-01", "base_year": "2020", "effective_period_start": "2021-01"},
                {"regime": "2025_base_effective_2026-01", "base_year": "2025", "effective_period_start": "2026-01"},
            ],
            [],
        ),
    )
    monkeypatch.setattr(prices, "_fetch_capture", lambda _root, **kwargs: payloads[str(kwargs["url"])])
    manifest_path = _manifest(tmp_path / "execution.json")
    return output_root, manifest_path


def test_audit_only_has_335_rows_and_never_writes_curated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root, manifest_path = _fixture(tmp_path, monkeypatch)
    curated = output_root / "curated" / CURATED_NAME
    curated.parent.mkdir(parents=True)
    curated.write_bytes(b"audit-only-sentinel")
    before = hashlib.sha256(curated.read_bytes()).hexdigest()
    result = run_full(output_root, PIT_A_START, PIT_A_END, "audit-only", manifest_path=manifest_path)
    assert result["validation"]["passed"] is True
    assert result["candidate_rows"] == 335
    assert result["audit"]["research_ready"] is False
    assert result["audit"]["sources"][0]["pit_grade"] == "A"
    assert result["curated_write"]["performed"] is False
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == before


def test_execute_writes_canonical_pit_a_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root, manifest_path = _fixture(tmp_path, monkeypatch)
    first = run_full(output_root, PIT_A_START, PIT_A_END, "execute", manifest_path=manifest_path)
    curated = output_root / "curated" / CURATED_NAME
    assert first["blocked"] is False
    assert first["curated_write"]["performed"] is True
    assert first["research_ready"] is False
    assert first["audit"]["research_ready"] is False
    assert Path(first["output"]).name == "w1_prices_full.json"
    frame = pd.read_parquet(curated)
    assert len(frame) == 335
    assert set(frame["pit_grade"]) == {"A"}
    assert set(frame["schema_version"]) == {2}
    assert all(str(value).endswith("+08:00") for value in frame["release_at"])
    first_hash = hashlib.sha256(curated.read_bytes()).hexdigest()
    second = run_full(output_root, PIT_A_START, PIT_A_END, "execute", manifest_path=manifest_path)
    assert second["curated_write"]["performed"] is True
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == first_hash
    assert len(pd.read_parquet(curated)) == 335


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"allowed": False}, "FULL_HISTORY_NOT_ALLOWED"),
        ({"blockers": ["review required"]}, "FULL_BLOCKERS_PRESENT"),
        ({"window": "missing"}, "FULL_WINDOW_MISSING"),
        ({"scope": "wrong_scope"}, "FULL_SCOPE_MISMATCH"),
        ({"window": {"start": "2021-02", "end": PIT_A_END, "scope": REQUIRED_SCOPE}}, "FULL_WINDOW_OUT_OF_RANGE"),
        ({"window": {"start": PIT_A_START, "end": "2026-06", "scope": REQUIRED_SCOPE}}, "FULL_WINDOW_OUT_OF_RANGE"),
    ],
)
def test_gate_v2_rejects_unsafe_manifest_windows(tmp_path: Path, kwargs: dict[str, object], code: str) -> None:
    path = _manifest(tmp_path / "execution.json", **kwargs)
    assert check_full_gate(path, PIT_A_START, PIT_A_END)[0]["code"] == code


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"gate_version": 2, "packages": []}, "MANIFEST_SCHEMA_VERSION_INVALID"),
        ({"schema_version": 2, "packages": []}, "MANIFEST_GATE_VERSION_INVALID"),
        ({"schema_version": 2, "gate_version": 2, "packages": []}, "PACKAGE_MISSING"),
        ({"schema_version": 2, "gate_version": 2, "packages": [None]}, "PACKAGE_MISSING"),
        ({"schema_version": 2, "gate_version": 2, "packages": [{"package_id": "prices", "full_history_allowed": "true", "full_blockers": [], "full_window": {"start": PIT_A_START, "end": PIT_A_END, "scope": REQUIRED_SCOPE}}]}, "FULL_HISTORY_ALLOWED_TYPE_INVALID"),
        ({"schema_version": 2, "gate_version": 2, "packages": [{"package_id": "prices", "full_history_allowed": True, "full_blockers": "", "full_window": {"start": PIT_A_START, "end": PIT_A_END, "scope": REQUIRED_SCOPE}}]}, "FULL_BLOCKERS_TYPE_INVALID"),
        ({"schema_version": 2, "gate_version": 2, "packages": [{"package_id": "prices", "full_history_allowed": True, "full_blockers": [], "full_window": {"start": 202101, "end": PIT_A_END, "scope": REQUIRED_SCOPE}}]}, "FULL_WINDOW_START_INVALID"),
        ({"schema_version": 2, "gate_version": 2, "packages": [{"package_id": "prices", "full_history_allowed": True, "full_blockers": [], "full_window": {"start": PIT_A_START, "end": PIT_A_END, "scope": ""}}]}, "FULL_WINDOW_SCOPE_INVALID"),
    ],
)
def test_prices_gate_v2_malformed_manifest_is_a_stable_rejection(tmp_path: Path, payload: dict[str, object], code: str) -> None:
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = check_full_gate(path, PIT_A_START, PIT_A_END)
    assert result and result[0]["code"] == code


def test_execute_rejection_preserves_existing_curated(tmp_path: Path) -> None:
    output_root = tmp_path / "lake"
    curated = output_root / "curated" / CURATED_NAME
    curated.parent.mkdir(parents=True)
    curated.write_bytes(b"sentinel")
    before = hashlib.sha256(curated.read_bytes()).hexdigest()
    manifest = _manifest(tmp_path / "closed.json", allowed=False)
    result = run_full(output_root, PIT_A_START, PIT_A_END, "execute", manifest_path=manifest)
    assert result["blocked"] is True
    assert result["blockers"][0]["code"] == "FULL_HISTORY_NOT_ALLOWED"
    assert hashlib.sha256(curated.read_bytes()).hexdigest() == before


def test_prices_real_gate_is_open_for_the_approved_pit_a_window() -> None:
    assert check_full_gate(DEFAULT_MANIFEST, PIT_A_START, PIT_A_END) == []


def test_narrow_window_reverse_validation_then_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root, manifest_path = _fixture(tmp_path, monkeypatch)
    narrowed = {"start": PIT_A_START, "end": "2026-06", "scope": REQUIRED_SCOPE}
    _manifest(manifest_path, window=narrowed)
    red = run_full(output_root, PIT_A_START, PIT_A_END, "execute", manifest_path=manifest_path)
    assert red["blockers"][0]["code"] == "FULL_WINDOW_OUT_OF_RANGE"
    _manifest(manifest_path)
    green = run_full(output_root, PIT_A_START, PIT_A_END, "execute", manifest_path=manifest_path)
    assert green["blocked"] is False
    assert green["candidate_rows"] == 335
