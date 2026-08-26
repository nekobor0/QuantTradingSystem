from datetime import datetime
from pathlib import Path
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import pandas as pd

from quant_trading_system.research.macro_data.contracts import load_registry
from quant_trading_system.research.macro_data.manual_import import (
    import_manual_nbs_pmi,
    parse_nbs_pmi_workbook,
)
from quant_trading_system.research.macro_data.pipeline import validate_canonical


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "macro_sample_registry.json"


def _fixture_workbook(path: Path) -> Path:
    strings = [
        "数据库：月度数据", "指标", "2010年4月", "制造业采购经理指数 (%) ",
        "生产指数 (%) ", "新订单指数 (%) ", "原材料库存指数 (%) ",
        "从业人员指数 (%) ", "供应商配送时间指数 (%) ", "数据来源：国家统计局",
        "55.7", "59.1", "59.3", "51.5", "53.2", "51.1",
    ]
    shared = "".join(f"<si><t>{value}</t></si>" for value in strings)
    rows = [
        [("A1", 0)], [("A2", 1), ("B2", 2)],
        [("A3", 3), ("B3", 10)], [("A4", 4), ("B4", 11)],
        [("A5", 5), ("B5", 12)], [("A6", 6), ("B6", 13)],
        [("A7", 7), ("B7", 14)], [("A8", 8), ("B8", 15)], [("A9", 9)],
    ]
    sheet = "".join(
        f'<row r="{index}">' + "".join(f'<c r="{ref}" t="s"><v>{value}</v></c>' for ref, value in cells) + "</row>"
        for index, cells in enumerate(rows, 1)
    )
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{namespace}">{shared}</sst>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{namespace}"><sheetData>{sheet}</sheetData></worksheet>')
    return path


def test_nbs_workbook_extracts_the_six_2010_04_values(tmp_path):
    values = parse_nbs_pmi_workbook(_fixture_workbook(tmp_path / "pmi.xlsx"))
    assert values == {
        "CN.PMI.MFG.HEADLINE": 55.7,
        "CN.PMI.MFG.PRODUCTION": 59.1,
        "CN.PMI.MFG.NEW_ORDERS": 59.3,
        "CN.PMI.MFG.RAW_MATERIAL_INVENTORY": 51.5,
        "CN.PMI.MFG.EMPLOYMENT": 53.2,
        "CN.PMI.MFG.SUPPLIER_DELIVERY_TIME": 51.1,
    }


def test_manual_import_preserves_numeric_continuity_without_claiming_historical_pit(tmp_path):
    workbook = _fixture_workbook(tmp_path / "pmi.xlsx")
    result = import_manual_nbs_pmi(
        registry_path=REGISTRY,
        output_root=tmp_path / "output",
        workbook_path=workbook,
        retrieved_at=datetime(2026, 8, 26, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    frame = pd.read_parquet(result["normalized_path"])
    registry = load_registry(REGISTRY)
    validation = validate_canonical(frame, registry.series_for_source("nbs_pmi_release_archive"))
    assert validation["passed"]
    assert len(frame) == 6
    assert set(frame["reference_period"]) == {"2010-04"}
    assert set(frame["availability_evidence"]) == {"current_nbs_database_export_not_historical_pit"}
    assert set(frame["available_at"]) == {"2026-08-26T15:00:00+08:00"}
    assert result["numeric_gap_filled"] is True
    assert result["historical_pit_supported"] is False
    assert result["source_file_retained"] is False
