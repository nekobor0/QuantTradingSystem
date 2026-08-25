"""Deterministic parsers for the R011 Shibor and PMI samples."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, time
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import RawSnapshot, SeriesSpec


PARSER_VERSION = "r011.1"
SHANGHAI = ZoneInfo("Asia/Shanghai")
PMI_FIELDS = (
    ("CN.PMI.MFG.HEADLINE", "manufacturing_pmi", 1),
    ("CN.PMI.MFG.PRODUCTION", "production", 2),
    ("CN.PMI.MFG.NEW_ORDERS", "new_orders", 3),
    ("CN.PMI.MFG.RAW_MATERIAL_INVENTORY", "raw_material_inventory", 4),
    ("CN.PMI.MFG.EMPLOYMENT", "employment", 5),
    ("CN.PMI.MFG.SUPPLIER_DELIVERY_TIME", "supplier_delivery_time", 6),
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
    records: list[dict[str, Any]] = []
    for row in document.get("records", []):
        reference_date = datetime.strptime(row["showDateCN"], "%Y-%m-%d").date()
        release_at = datetime.combine(reference_date, time(11, 0), SHANGHAI)
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
                    availability_evidence="official_scheduled_publication_time_not_observed_latency",
                    snapshot=snapshot,
                )
            )
    if not records:
        raise ValueError("Shibor response contains no records")
    return pd.DataFrame(records).sort_values(["reference_period", "series_id"]).reset_index(drop=True)


def _publication_timestamp(text: str) -> datetime:
    visible = html.unescape(re.sub(r"<[^>]+>", " ", text))
    normalized = " ".join(visible.split())
    match = re.search(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", normalized)
    if not match:
        raise ValueError("PMI release page is missing an observed publication timestamp")
    return datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI)


def _manufacturing_rows(text: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(text)
    candidates: list[list[list[str]]] = []
    for table in parser.tables:
        dated = [row for row in table if row and re.fullmatch(r"\d{4}\s*年\s*\d{1,2}\s*月", row[0])]
        if len(dated) >= 10 and all(len(row) >= 7 for row in dated):
            candidates.append(dated)
    if not candidates:
        raise ValueError("PMI manufacturing table was not found")
    return candidates[0]


def parse_pmi_release(payload: bytes, snapshot: RawSnapshot) -> pd.DataFrame:
    text = payload.decode("utf-8", errors="strict")
    published_at = _publication_timestamp(text)
    records: list[dict[str, Any]] = []
    for row in _manufacturing_rows(text):
        match = re.fullmatch(r"(\d{4})\s*年\s*(\d{1,2})\s*月", row[0])
        assert match is not None
        reference_period = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
        for series_id, field, position in PMI_FIELDS:
            records.append(
                _base_record(
                    series_id=series_id,
                    reference_period=reference_period,
                    value=float(row[position]),
                    unit="diffusion_index_percent",
                    seasonal_adjustment="seasonally_adjusted",
                    source_id=snapshot.source_id,
                    source_record_id=f"table1|{reference_period}|{field}",
                    release_at=published_at,
                    available_at=published_at,
                    availability_evidence="observed_release_page_timestamp_conservative_for_rolling_history",
                    snapshot=snapshot,
                )
            )
    return pd.DataFrame(records).sort_values(["reference_period", "series_id"]).reset_index(drop=True)
