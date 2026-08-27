from pathlib import Path

from scripts.data_lake.validate_macro_w1_full_entry import validate_full_entry


ROOT = Path(__file__).resolve().parents[2]


def test_w1_full_entry_is_closed_package_by_package_with_specific_reasons():
    result = validate_full_entry(ROOT / "config" / "macro_w1_execution_manifest.json")
    assert result["passed"], result
    assert result["full_entry_ready"] is False
    assert result["decision"] == "BLOCKED_PACKAGE_BY_PACKAGE"
