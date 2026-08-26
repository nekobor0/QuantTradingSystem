"""Strict manual imports for official macro exports that cannot be fetched reliably."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import (
    load_registry,
    write_normalized_snapshot,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
NBS_PMI_QUERY_URL = "https://data.stats.gov.cn/easyquery.htm?cn=A01&zb=A0B01&sj=201004"
CFLP_RELEASE_URL = "https://old.chinawuliu.com.cn/lhhkx/201005/01/128367.shtml"
RELEASE_AT = datetime(2010, 5, 1, 9, 6, tzinfo=SHANGHAI)
PARSER_VERSION = "r011.3-manual"
TARGET_PERIOD = "2010-04"
TARGET_COLUMN = "2010年4月"
FIELD_MAP = {
    "制造业采购经理指数": "CN.PMI.MFG.HEADLINE",
    "生产指数": "CN.PMI.MFG.PRODUCTION",
    "新订单指数": "CN.PMI.MFG.NEW_ORDERS",
    "原材料库存指数": "CN.PMI.MFG.RAW_MATERIAL_INVENTORY",
    "从业人员指数": "CN.PMI.MFG.EMPLOYMENT",
    "供应商配送时间指数": "CN.PMI.MFG.SUPPLIER_DELIVERY_TIME",
}


def _column_number(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if letters is None:
        raise ValueError(f"invalid spreadsheet cell reference: {reference}")
    result = 0
    for letter in letters.group():
        result = result * 26 + ord(letter) - ord("A") + 1
    return result


def _read_first_sheet(path: Path) -> list[list[str]]:
    """Read the small NBS OOXML export without adding an Excel dependency."""
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as workbook:
        names = set(workbook.namelist())
        required = {"xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"}
        if not required.issubset(names):
            raise ValueError("NBS workbook must contain one shared-string worksheet")
        strings_root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
        shared_strings = ["".join(node.itertext()) for node in strings_root.findall(f"{namespace}si")]
        sheet_root = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        if sheet_root.findall(f".//{namespace}f"):
            raise ValueError("NBS workbook formulas are not accepted")
        rows: list[list[str]] = []
        for row_node in sheet_root.findall(f".//{namespace}row"):
            cells: dict[int, str] = {}
            for cell in row_node.findall(f"{namespace}c"):
                reference = cell.attrib.get("r", "")
                value_node = cell.find(f"{namespace}v")
                value = "" if value_node is None or value_node.text is None else value_node.text
                if cell.attrib.get("t") == "s" and value:
                    value = shared_strings[int(value)]
                cells[_column_number(reference)] = value
            width = max(cells, default=0)
            rows.append([cells.get(index, "") for index in range(1, width + 1)])
    return rows


def parse_nbs_pmi_workbook(path: Path) -> dict[str, float]:
    rows = _read_first_sheet(path)
    flattened = [cell.strip() for row in rows for cell in row]
    if "数据库：月度数据" not in flattened or "数据来源：国家统计局" not in flattened:
        raise ValueError("workbook is not an NBS monthly National Data export")
    header = next((row for row in rows if row and row[0].strip() == "指标"), None)
    if header is None or TARGET_COLUMN not in header:
        raise ValueError(f"workbook is missing target period {TARGET_COLUMN}")
    target_index = header.index(TARGET_COLUMN)
    values: dict[str, float] = {}
    for row in rows:
        if not row:
            continue
        label = re.sub(r"\s*\(%\)\s*$", "", row[0].strip())
        series_id = FIELD_MAP.get(label)
        if series_id is None:
            continue
        if target_index >= len(row) or not row[target_index].strip():
            raise ValueError(f"missing {TARGET_COLUMN} value for {label}")
        values[series_id] = float(row[target_index])
    if set(values) != set(FIELD_MAP.values()):
        raise ValueError(f"workbook PMI field mismatch: {sorted(set(FIELD_MAP.values()) - set(values))}")
    return values


def import_manual_nbs_pmi(
    *,
    registry_path: Path,
    output_root: Path,
    workbook_path: Path,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    if retrieved_at is None:
        retrieved_at = datetime.now(SHANGHAI)
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    workbook_payload = workbook_path.read_bytes()
    values = parse_nbs_pmi_workbook(workbook_path)
    workbook_sha256 = hashlib.sha256(workbook_payload).hexdigest()
    registry = load_registry(registry_path)
    specs = {item.series_id: item for item in registry.series_for_source("nbs_pmi_release_archive")}
    available_at = retrieved_at.astimezone(SHANGHAI)
    vintage_id = f"nbs_national_data_pmi:{workbook_sha256[:16]}"
    rows = []
    for series_id, value in values.items():
        spec = specs[series_id]
        rows.append({
            "series_id": series_id,
            "reference_period": TARGET_PERIOD,
            "value": value,
            "unit": spec.unit,
            "seasonal_adjustment": spec.seasonal_adjustment,
            "source_id": "nbs_national_data_pmi",
            "source_record_id": f"national_data_export|{TARGET_PERIOD}|{spec.source_field}",
            "release_at": RELEASE_AT.isoformat(),
            "available_at": available_at.isoformat(),
            "tradable_at": available_at.isoformat(),
            "availability_evidence": "current_nbs_database_export_not_historical_pit",
            "retrieved_at": available_at.isoformat(),
            "vintage_id": vintage_id,
            "raw_sha256": workbook_sha256,
            "parser_version": PARSER_VERSION,
        })
    frame = pd.DataFrame(rows).sort_values("series_id").reset_index(drop=True)
    normalized_path = output_root / "normalized" / "nbs_national_data_pmi" / f"{workbook_sha256}.parquet"
    write_normalized_snapshot(frame, normalized_path)
    manifest = {
        "schema_version": 1,
        "source_id": "nbs_national_data_pmi",
        "reference_period": TARGET_PERIOD,
        "rows": len(frame),
        "numeric_gap_filled": True,
        "historical_pit_supported": False,
        "release_time_evidence": {
            "timestamp": RELEASE_AT.isoformat(),
            "url": CFLP_RELEASE_URL,
            "scope": "headline_release_context",
        },
        "availability_evidence": "user-verified manual export; no historical database availability timestamp",
        "input_sha256": workbook_sha256,
        "source_file_retained": False,
        "normalized_path": str(normalized_path.resolve()),
        "values": values,
    }
    manifest_path = normalized_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {**manifest, "manifest_path": str(manifest_path.resolve())}
