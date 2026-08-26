"""Deterministic parsers for official Shibor and PMI releases."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import CANONICAL_COLUMNS, RawSnapshot, SeriesSpec


PARSER_VERSION = "r011.2"
RATES_PARSER_VERSION = "r011.w1.rates.v1"
SHANGHAI = ZoneInfo("Asia/Shanghai")
PMI_FIELDS = (
    ("CN.PMI.MFG.HEADLINE", "manufacturing_pmi", 0),
    ("CN.PMI.MFG.PRODUCTION", "production", 1),
    ("CN.PMI.MFG.NEW_ORDERS", "new_orders", 2),
    ("CN.PMI.MFG.RAW_MATERIAL_INVENTORY", "raw_material_inventory", 3),
    ("CN.PMI.MFG.EMPLOYMENT", "employment", 4),
    ("CN.PMI.MFG.SUPPLIER_DELIVERY_TIME", "supplier_delivery_time", 5),
)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            table: list[list[str]] = []
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table_stack:
            if self._row:
                self._table_stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()


def _base_record(
    *,
    series_id: str,
    reference_period: str,
    value: float,
    unit: str,
    seasonal_adjustment: str,
    source_id: str,
    source_record_id: str,
    release_at: datetime,
    available_at: datetime,
    tradable_at: datetime,
    availability_evidence: str,
    snapshot: RawSnapshot,
    parser_version: str = PARSER_VERSION,
) -> dict[str, Any]:
    retrieved = pd.Timestamp(snapshot.retrieved_at)
    vintage_id = f"{snapshot.source_id}:{snapshot.sha256[:16]}"
    return {
        "series_id": series_id,
        "reference_period": reference_period,
        "value": value,
        "unit": unit,
        "seasonal_adjustment": seasonal_adjustment,
        "source_id": source_id,
        "source_record_id": source_record_id,
        "release_at": release_at.isoformat(),
        "available_at": available_at.isoformat(),
        "tradable_at": tradable_at.isoformat(),
        "availability_evidence": availability_evidence,
        "retrieved_at": retrieved.isoformat(),
        "vintage_id": vintage_id,
        "raw_sha256": snapshot.sha256,
        "parser_version": parser_version,
    }


def parse_shibor(
    payload: bytes,
    snapshot: RawSnapshot,
    series_specs: tuple[SeriesSpec, ...],
) -> pd.DataFrame:
    document = json.loads(payload.decode("utf-8"))
    if str(document.get("head", {}).get("rep_code")) != "200":
        raise ValueError(f"Shibor response rejected: {document.get('head')}")
    by_field = {item.source_field: item for item in series_specs}
    expected = {"ON", "1W", "2W", "1M", "3M", "6M", "9M", "1Y"}
    if set(by_field) != expected:
        raise ValueError(f"Shibor registry tenor mismatch: {sorted(set(by_field) ^ expected)}")
    retrieved = datetime.fromisoformat(snapshot.retrieved_at).astimezone(SHANGHAI)
    records: list[dict[str, Any]] = []
    for row in document.get("records", []):
        reference_date = datetime.strptime(row["showDateCN"], "%Y-%m-%d").date()
        release_at = datetime.combine(reference_date, time(11, 0), SHANGHAI)
        tradable_at = max(retrieved, release_at + timedelta(minutes=5))
        for field in sorted(expected, key=lambda item: list(by_field).index(item)):
            spec = by_field[field]
            records.append(
                _base_record(
                    series_id=spec.series_id,
                    reference_period=reference_date.isoformat(),
                    value=float(row[field]),
                    unit=spec.unit,
                    seasonal_adjustment=spec.seasonal_adjustment,
                    source_id=snapshot.source_id,
                    source_record_id=f"{reference_date.isoformat()}|{field}",
                    release_at=release_at,
                    available_at=release_at,
                    tradable_at=tradable_at,
                    availability_evidence="official_scheduled_publication_time_not_observed_latency",
                    snapshot=snapshot,
                )
            )
    if not records:
        raise ValueError("Shibor response contains no records")
    return pd.DataFrame(records).sort_values(["reference_period", "series_id"]).reset_index(drop=True)


def next_strategy_trading_day(reference_date: str, trading_dates: frozenset[str]) -> datetime:
    """Return the next explicitly supplied strategy session at 09:30 Asia/Shanghai."""
    later_dates = sorted(item for item in trading_dates if item > reference_date)
    if not later_dates:
        raise ValueError(f"strategy calendar has no trading date after {reference_date}")
    return datetime.combine(datetime.strptime(later_dates[0], "%Y-%m-%d").date(), time(9, 30), SHANGHAI)


def _empty_rates_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_COLUMNS)


def parse_cfets_repo_json(
    payload: bytes,
    snapshot: RawSnapshot,
    *,
    requested_date: str,
    index_type: str,
    series_id: str,
    strategy_trading_dates: frozenset[str],
) -> pd.DataFrame:
    """Parse exactly one official CFETS R007 or DR007 weighted-average response."""
    expected = {
        "markVOList": ("CN.REPO.R007", "R007"),
        "markInterBankVOList": ("CN.REPO.DR007", "DR007"),
    }
    if index_type not in expected or expected[index_type][0] != series_id:
        raise ValueError(f"unsupported CFETS index_type/series_id: {index_type}/{series_id}")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("CFETS response is not valid JSON") from exc
    if not isinstance(document, dict) or str(document.get("head", {}).get("rep_code")) != "200":
        raise ValueError(f"CFETS response rejected: {document.get('head') if isinstance(document, dict) else None}")
    data = document.get("data")
    if not isinstance(data, dict) or data.get("lastDate") != requested_date:
        raise ValueError(f"CFETS response date mismatch: expected {requested_date}, got {data}")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("CFETS response contains no records")
    instrument_code = expected[index_type][1]
    matches = [item for item in records if isinstance(item, dict) and item.get("instrmntCd") == instrument_code]
    if len(matches) != 1:
        raise ValueError(f"CFETS response must contain exactly one {instrument_code} record")
    record = matches[0]
    value_text = record.get("wghtdAvgRepoRate")
    if value_text in (None, ""):
        raise ValueError(f"CFETS {instrument_code} record has no wghtdAvgRepoRate")
    try:
        value = float(value_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"CFETS {instrument_code} weighted-average rate is not numeric") from exc
    if not pd.notna(value):
        raise ValueError(f"CFETS {instrument_code} weighted-average rate is NaN")
    release_at = datetime.combine(
        datetime.strptime(requested_date, "%Y-%m-%d").date(), time(23, 59, 59), SHANGHAI
    )
    next_bar = next_strategy_trading_day(requested_date, strategy_trading_dates)
    return pd.DataFrame([
        _base_record(
            series_id=series_id,
            reference_period=requested_date,
            value=value,
            unit="percent_per_annum",
            seasonal_adjustment="not_applicable",
            source_id=snapshot.source_id,
            source_record_id=f"{requested_date}|{instrument_code}|wghtdAvgRepoRate",
            release_at=release_at,
            available_at=next_bar,
            tradable_at=next_bar,
            availability_evidence="W1_D5_conservative_next_trading_day_rule",
            snapshot=snapshot,
            parser_version=RATES_PARSER_VERSION,
        )
    ], columns=CANONICAL_COLUMNS)


@dataclass(frozen=True, slots=True)
class PbocPolicyParseResult:
    observations: pd.DataFrame
    omissions: tuple[dict[str, Any], ...]
    page_timestamp: datetime
    event_kind: str


def _date_from_text(text: str, *, marker: str | None = None, fallback: datetime) -> str:
    if marker and marker in text:
        marker_position = text.find(marker)
        search_text = text[max(0, marker_position - 80):marker_position]
    else:
        search_text = text
    match = re.search(r"(?<!\d)(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", search_text)
    if match is None:
        return fallback.date().isoformat()
    year, month, day = (int(value) for value in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _policy_rate_from_tables(text: str) -> float | None:
    parser = _TableParser()
    parser.feed(text)
    for table in parser.tables:
        for row in table:
            if not row or not any("7天" in re.sub(r"\s+", "", cell) for cell in row):
                continue
            for cell in row:
                match = re.search(r"(?<![\d.])(\d+(?:\s*\.\s*\d+)?)\s*%", cell)
                if match:
                    return float(re.sub(r"\s+", "", match.group(1)))
    visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
    normalized = re.sub(r"\s+", "", visible)
    match = re.search(r"7天.{0,120}?操作利率.{0,80}?(\d+(?:\.\d+)?)\s*%", normalized)
    if match:
        return float(match.group(1))
    match = re.search(r"操作利率.{0,80}?7天.{0,80}?(\d+(?:\.\d+)?)\s*%", normalized)
    return float(match.group(1)) if match else None


def _mlf_explicit_rate(text: str) -> float | None:
    visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
    normalized = " ".join(visible.split())
    match = re.search(r"(?:统一中标利率|中标利率|操作利率|利率)\D{0,40}(\d+(?:\.\d+)?)\s*%", normalized)
    return float(match.group(1)) if match else None


def parse_pboc_policy_release(
    payload: bytes,
    snapshot: RawSnapshot,
    *,
    source_file: str | None = None,
) -> PbocPolicyParseResult:
    """Parse a PBOC OMO/MLF release, retaining post-reform MLF omission evidence."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("PBOC release is not UTF-8 HTML") from exc
    visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
    normalized = " ".join(visible.split())
    page_timestamp = _publication_timestamp(text)
    is_mlf = snapshot.source_id == "pboc_mlf_release" or "中期借贷便利" in normalized
    is_omo = snapshot.source_id == "pboc_omo_release" or "逆回购" in normalized
    if is_mlf == is_omo:
        raise ValueError("PBOC release cannot be classified uniquely as OMO or MLF")
    if is_omo:
        compact = re.sub(r"\s+", "", normalized)
        zero_operation = bool(re.search(r"7天期?逆回购操作量为零", compact) or re.search(r"7天0亿元0亿元", compact))
        if "7天" not in compact or ("操作利率" not in compact and not zero_operation):
            raise ValueError("PBOC OMO release lacks 7-day operation-rate context")
        value = _policy_rate_from_tables(text)
        if value is None:
            if re.search(r"7\s*天期?逆回购操作量为零", normalized) or re.search(r"7\s*天\s*0\s*亿元\s*0\s*亿元", normalized):
                omission = {
                    "series_id": "CN.PBOC.OMO.REVERSE_REPO.7D.RATE",
                    "reference_period": _date_from_text(normalized, fallback=page_timestamp),
                    "state": "RATE_NOT_PUBLISHED_ZERO_OPERATION",
                    "reason": "official notice reports zero 7-day reverse-repo operation and publishes no rate",
                    "source_file": source_file or snapshot.raw_path,
                    "raw_sha256": snapshot.sha256,
                }
                return PbocPolicyParseResult(_empty_rates_frame(), (omission,), page_timestamp, "OMO_7D_ZERO_OPERATION")
            raise ValueError("PBOC OMO release lacks an explicit 7-day percentage rate")
        reference_period = _date_from_text(normalized, fallback=page_timestamp)
        tradable_at = max(page_timestamp, datetime.combine(page_timestamp.date(), time(9, 30), SHANGHAI))
        frame = pd.DataFrame([
            _base_record(
                series_id="CN.PBOC.OMO.REVERSE_REPO.7D.RATE",
                reference_period=reference_period,
                value=value,
                unit="percent_per_annum",
                seasonal_adjustment="not_applicable",
                source_id=snapshot.source_id,
                source_record_id=f"{reference_period}|reverse_repo|7D",
                release_at=page_timestamp,
                available_at=page_timestamp,
                tradable_at=tradable_at,
                availability_evidence="observed_official_release_page_timestamp",
                snapshot=snapshot,
                parser_version=RATES_PARSER_VERSION,
            )
        ], columns=CANONICAL_COLUMNS)
        return PbocPolicyParseResult(frame, (), page_timestamp, "OMO_7D")

    if "1年期" not in normalized:
        raise ValueError("PBOC MLF release lacks 1-year context")
    reference_period = _date_from_text(normalized, marker="中国人民银行将", fallback=page_timestamp)
    explicit_rate = _mlf_explicit_rate(text)
    if reference_period >= "2025-03-01":
        if explicit_rate is not None:
            raise ValueError("post-reform MLF unified rate must never be emitted")
        omission = {
            "series_id": "CN.PBOC.MLF.1Y.RATE",
            "reference_period": reference_period,
            "state": "UNIFIED_RATE_STRUCTURALLY_UNDEFINED",
            "reason": "official notice states multiple-price winning and does not publish a unified MLF rate",
            "source_file": source_file or snapshot.raw_path,
            "raw_sha256": snapshot.sha256,
        }
        return PbocPolicyParseResult(_empty_rates_frame(), (omission,), page_timestamp, "MLF_POST_REFORM")
    if explicit_rate is None:
        raise ValueError("pre-reform MLF release lacks an explicit unified 1-year rate")
    tradable_at = max(page_timestamp, datetime.combine(page_timestamp.date(), time(9, 30), SHANGHAI))
    frame = pd.DataFrame([
        _base_record(
            series_id="CN.PBOC.MLF.1Y.RATE",
            reference_period=reference_period,
            value=explicit_rate,
            unit="percent_per_annum",
            seasonal_adjustment="not_applicable",
            source_id=snapshot.source_id,
            source_record_id=f"{reference_period}|MLF|1Y|unified_rate",
            release_at=page_timestamp,
            available_at=page_timestamp,
            tradable_at=tradable_at,
            availability_evidence="observed_official_release_page_timestamp",
            snapshot=snapshot,
            parser_version=RATES_PARSER_VERSION,
        )
    ], columns=CANONICAL_COLUMNS)
    return PbocPolicyParseResult(frame, (), page_timestamp, "MLF_PRE_REFORM")


parse_cfets_repo_rate = parse_cfets_repo_json
parse_pboc_release_html = parse_pboc_policy_release


def _publication_timestamp(text: str) -> datetime:
    metadata = re.search(
        r"""name=["']PubDate["'][^>]+content=["'](\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)["']""",
        text,
        re.IGNORECASE,
    )
    if metadata:
        year, month, day, clock = metadata.groups()
        clock_format = "%H:%M:%S" if clock.count(":") == 2 else "%H:%M"
        return datetime.strptime(f"{year}-{month}-{day} {clock}", f"%Y-%m-%d {clock_format}").replace(tzinfo=SHANGHAI)
    visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
    normalized = " ".join(visible.split())
    prefixed = re.search(
        r"发布时间[：:]?\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)",
        normalized,
    )
    match = prefixed or re.search(
        r"(?<![\d/-])(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)",
        normalized,
    )
    if not match:
        raise ValueError("PMI release page is missing an observed publication timestamp")
    year, month, day, clock = match.groups()
    clock_format = "%H:%M:%S" if clock.count(":") == 2 else "%H:%M"
    return datetime.strptime(f"{year}-{month}-{day} {clock}", f"%Y-%m-%d {clock_format}").replace(tzinfo=SHANGHAI)


def _period(cell: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{4})\D{1,8}(\d{1,2})(?!\d)", cell)
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None


def _rolling_rows(tables: list[list[list[str]]]) -> list[tuple[str, list[float]]]:
    for table in tables:
        dated = [row for row in table if row and _period(row[0]) is not None and len(row) >= 7]
        has_pmi_header = any(cell.strip().upper() == "PMI" for row in table[:3] for cell in row)
        if dated and has_pmi_header:
            result: list[tuple[str, list[float]]] = []
            for row in dated:
                period = _period(row[0])
                assert period is not None
                result.append((period, [float(value) for value in row[1:7]]))
            return result
    return []


def _legacy_rows(tables: list[list[list[str]]]) -> list[tuple[str, list[float]]]:
    for table in tables:
        for pmi_index, row in enumerate(table):
            if not row or row[0].strip().upper() != "PMI" or pmi_index == 0:
                continue
            header = table[pmi_index - 1]
            periods = [_period(cell) for cell in header[1:]]
            periods = [period for period in periods if period is not None]
            series_rows = table[pmi_index:pmi_index + 6]
            if not periods or len(series_rows) != 6:
                continue
            try:
                return [
                    (period, [float(series_row[column + 1]) for series_row in series_rows])
                    for column, period in enumerate(periods)
                ]
            except (IndexError, ValueError):
                continue
    return []


def parse_pmi_release(payload: bytes, snapshot: RawSnapshot) -> pd.DataFrame:
    text = payload.decode("utf-8", errors="strict")
    published_at = _publication_timestamp(text)
    parser = _TableParser()
    parser.feed(text)
    observations = _rolling_rows(parser.tables)
    layout = "rolling"
    if not observations:
        observations = _legacy_rows(parser.tables)
        layout = "legacy_horizontal"
    if not observations:
        raise ValueError("PMI manufacturing table was not found")
    records: list[dict[str, Any]] = []
    for reference_period, values in observations:
        for (series_id, field, position), value in zip(PMI_FIELDS, values, strict=True):
            assert position < len(values)
            records.append(
                _base_record(
                    series_id=series_id,
                    reference_period=reference_period,
                    value=value,
                    unit="diffusion_index_percent",
                    seasonal_adjustment="seasonally_adjusted",
                    source_id=snapshot.source_id,
                    source_record_id=f"{layout}|{reference_period}|{field}",
                    release_at=published_at,
                    available_at=published_at,
                    tradable_at=published_at,
                    availability_evidence="observed_release_page_timestamp",
                    snapshot=snapshot,
                )
            )
    return pd.DataFrame(records).sort_values(["reference_period", "series_id"]).reset_index(drop=True)
