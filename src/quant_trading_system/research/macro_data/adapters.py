"""Deterministic parsers for official Shibor and PMI releases."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, time, timedelta
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import RawSnapshot, SeriesSpec


PARSER_VERSION = "r011.2"
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
        "parser_version": PARSER_VERSION,
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


def _publication_timestamp(text: str) -> datetime:
    metadata = re.search(
        r"""name=["']PubDate["'][^>]+content=["'](\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2})["']""",
        text,
        re.IGNORECASE,
    )
    if metadata:
        year, month, day, clock = metadata.groups()
        return datetime.strptime(f"{year}-{month}-{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI)
    visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
    normalized = " ".join(visible.split())
    prefixed = re.search(
        r"发布时间[：:]?\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2})",
        normalized,
    )
    match = prefixed or re.search(
        r"(?<![\d/-])(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}:\d{2})(?!\d)",
        normalized,
    )
    if not match:
        raise ValueError("PMI release page is missing an observed publication timestamp")
    year, month, day, clock = match.groups()
    return datetime.strptime(f"{year}-{month}-{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI)


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
