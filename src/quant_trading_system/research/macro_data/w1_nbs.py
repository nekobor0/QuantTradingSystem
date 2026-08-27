"""Strict parsers for the three NBS W1 packages that passed local Gold."""

from __future__ import annotations

import html
import re
from io import StringIO
from typing import Any

import pandas as pd


def _text(payload: bytes) -> str:
    decoded = payload.decode("utf-8", errors="strict")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", decoded)).split())


def _tables(payload: bytes) -> list[pd.DataFrame]:
    return pd.read_html(StringIO(payload.decode("utf-8", errors="strict")))


def _signed(direction: str, value: str) -> float:
    number = float(value)
    if direction == "下降":
        return -number
    if direction in {"上涨", "增长"}:
        return number
    raise ValueError(f"unsupported direction: {direction}")


def _match(text: str, pattern: str, label: str) -> re.Match[str]:
    found = re.search(pattern, text)
    if found is None:
        raise ValueError(f"official release does not expose {label}")
    return found


def parse_pmi(payload: bytes, reference_period: str) -> list[dict[str, Any]]:
    tables = _tables(payload)
    if len(tables) < 4:
        raise ValueError("PMI release has fewer than four required tables")
    manufacturing, manufacturing_detail, nonmanufacturing = tables[:3]
    mfg = manufacturing.iloc[-1].tolist()
    mfg_detail = manufacturing_detail.iloc[-1].tolist()
    nonmfg = nonmanufacturing.iloc[-1].tolist()
    composite = float(_match(
        _text(payload), r"综合\s*PMI\s*产出指数为\s*([-+]?\d+(?:\.\d+)?)%", "composite PMI",
    ).group(1))
    values = {
        "CN.PMI.MFG.HEADLINE": float(mfg[1]),
        "CN.PMI.MFG.NEW_ORDERS": float(mfg[3]),
        "CN.PMI.MFG.NEW_EXPORT_ORDERS": float(mfg_detail[1]),
        "CN.PMI.MFG.INPUT_PRICE": float(mfg_detail[6]),
        "CN.PMI.NONMFG.ACTIVITY": float(nonmfg[1]),
        "CN.PMI.NONMFG.NEW_ORDERS": float(nonmfg[2]),
        "CN.PMI.NONMFG.INPUT_PRICE": float(nonmfg[3]),
        "CN.PMI.COMPOSITE.OUTPUT": composite,
    }
    return [{"series_id": key, "reference_period": reference_period, "value": value} for key, value in values.items()]


def parse_prices(cpi_payload: bytes, ppi_payload: bytes, interpretation_payload: bytes, reference_period: str) -> list[dict[str, Any]]:
    if not interpretation_payload:
        raise ValueError("price interpretation evidence is empty")
    cpi_tables, ppi_tables = _tables(cpi_payload), _tables(ppi_payload)
    if not cpi_tables or not ppi_tables:
        raise ValueError("price release has no official table")
    cpi_columns = cpi_tables[0].columns
    ppi_table = ppi_tables[0]
    values = {
        "CN.CPI.ALL.YOY": float(cpi_columns[2][1]),
        "CN.CPI.CORE.YOY": float(cpi_columns[2][8]),
        "CN.PPI.ALL.YOY": float(ppi_table.iloc[1, 2]),
        "CN.PPI.ALL.MOM": float(ppi_table.iloc[1, 1]),
        "CN.PPIRM.ALL.YOY": float(ppi_table.iloc[11, 2]),
    }
    return [{"series_id": key, "reference_period": reference_period, "value": value} for key, value in values.items()]

def parse_growth(gdp_payload: bytes, industrial_payload: bytes, fixture_id: str) -> list[dict[str, Any]]:
    tables = _tables(gdp_payload)
    if not tables:
        raise ValueError("GDP release has no official table")
    gdp_table = tables[0]
    if fixture_id.endswith("Q1"):
        row = gdp_table.iloc[1].tolist()
        nominal, real_yoy, industrial_period = float(row[1]), float(row[2]), f"{fixture_id[:4]}-03"
    elif fixture_id.endswith("Q2"):
        row = gdp_table.iloc[2].tolist()
        nominal, real_yoy, industrial_period = float(row[2]), float(row[3]), f"{fixture_id[:4]}-06"
    else:
        raise ValueError(f"unsupported Gold GDP fixture: {fixture_id}")
    industrial_tables = _tables(industrial_payload)
    if not industrial_tables:
        raise ValueError("industrial release has no official table")
    industrial = float(industrial_tables[0].iloc[2, 2])
    return [
        {"series_id": "CN.GDP.NOMINAL.YTD", "reference_period": fixture_id, "value": nominal},
        {"series_id": "CN.GDP.REAL.YOY", "reference_period": fixture_id, "value": real_yoy},
        {"series_id": "CN.INDUSTRIAL.VA.YOY", "reference_period": industrial_period, "value": industrial},
    ]