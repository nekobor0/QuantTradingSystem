"""Validate the frozen ignored-local rates Gold candidate without promoting its gate."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "data_lake"))

from validate_macro_w1_chinabond_full_candidate import (  # noqa: E402
    SERIES as CHINABOND_READY_SERIES,
    validate_chinabond_full_candidate,
)


CANDIDATE_ROOT = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_rates_candidate_v2"
AUDIT_PATH = ROOT / "artifacts" / "macro_r011" / "audits" / "w1_rates_gold_candidate_v2.json"
FROZEN_HASHES = {
    "expected.json": "9DCA3BDFCCBF9BB0217DBE67EAE017E7505143FFB774F23DBB22DDA7748451B1",
    "source_map.json": "A623D95F2E2968180BFD907F1C07312122289F292426900A7DCFF9CB174FCA83",
    "manual_audit.json": "F15BCC18F458F6EA54535D64618CDFC36F8294FB1D546BA71AB63BA4F033A0D8",
    "candidate_audit": "A9C33119E0EE323DDF8CB449F19ECD7FEB1F37809448197E2264315F9067BEEE",
}
NEW_READY_SERIES = {
    "CN.SHIBOR.ON",
    "CN.SHIBOR.1W",
    "CN.SHIBOR.3M",
    "CN.LPR.1Y",
    "CN.LPR.5Y_PLUS",
}
EXISTING_READY_SERIES = {
    "CN.REPO.DR007",
    "CN.REPO.R007",
    "CN.PBOC.OMO.REVERSE_REPO.7D.RATE",
    "CN.PBOC.MLF.1Y.RATE",
}
LEGACY_GOLD_MISSING_SERIES = {
    "CN.CHINABOND.GOV.YTM.1Y",
    "CN.CHINABOND.GOV.YTM.10Y",
}
GOLD_MISSING_SERIES: set[str] = set()
GOLD_MISSING_ORDER: list[str] = []
FULL_HISTORY_BLOCKED_SERIES = {"CN.REPO.DR007", "CN.REPO.R007"}
LEGACY_FULL_HISTORY_BLOCKED_SERIES = LEGACY_GOLD_MISSING_SERIES | FULL_HISTORY_BLOCKED_SERIES
EXPECTED_PERIODS = {
    "CN.SHIBOR.ON": {"2026-08-24", "2026-08-25"},
    "CN.SHIBOR.1W": {"2026-08-24", "2026-08-25"},
    "CN.SHIBOR.3M": {"2026-08-24", "2026-08-25"},
    "CN.LPR.1Y": {"2026-07", "2026-08"},
    "CN.LPR.5Y_PLUS": {"2026-07", "2026-08"},
}
RAW_FILES = {
    "2c7d61d3f23bff443a5d5a833ffc72192a4103b638588c7f37000aa2cd968673": "raw/shibor_2026-01-01_2026-08-25.json",
    "40285435bd15e5e93edd0399301b52fa5b52aac3af4ad61d98477df13f22d2f4": "raw/chinamoney_lpr_2026-07-20.html",
    "5b4ddec501ddfe52bfec15d471c8c6d4548b643da9a61f35f9a978825bc04bd5": "raw/chinamoney_lpr_2026-08-20.html",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _visible_text(path: Path) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8"))).split())


def validate_rates_gold_candidate(
    candidate_root: Path = CANDIDATE_ROOT,
    audit_path: Path = AUDIT_PATH,
    frozen_hashes: dict[str, str] = FROZEN_HASHES,
) -> dict[str, Any]:
    paths = {
        "expected.json": candidate_root / "expected.json",
        "source_map.json": candidate_root / "source_map.json",
        "manual_audit.json": candidate_root / "manual_audit.json",
        "candidate_audit": audit_path,
    }
    checks: dict[str, bool] = {
        "frozen_files_present": all(path.is_file() for path in paths.values()),
        "frozen_hashes_exact": False,
    }
    try:
        checks["frozen_hashes_exact"] = checks["frozen_files_present"] and all(
            _sha256(paths[name]) == digest for name, digest in frozen_hashes.items()
        )
        expected = _load(paths["expected.json"])
        source_map = _load(paths["source_map.json"])
        manual = _load(paths["manual_audit.json"])
        audit = _load(paths["candidate_audit"])
        rows = expected.get("rows")
        rows = rows if isinstance(rows, list) else []
        row_series = {row.get("series_id") for row in rows if isinstance(row, dict)}
        keys = [(row.get("series_id"), row.get("reference_period"), row.get("vintage_id")) for row in rows]
        by_series = {
            series_id: {row.get("reference_period") for row in rows if row.get("series_id") == series_id}
            for series_id in NEW_READY_SERIES
        }
        columns = expected.get("canonical_columns")
        checks.update(
            {
                "candidate_identity_exact": expected.get("package_id") == "rates_liquidity" and expected.get("candidate_id") == "R011.W1.RATES_LIQUIDITY.GOLD_CANDIDATE_V2",
                "requested_window_exact": expected.get("requested_window") == {"daily": ["2026-08-24", "2026-08-25"], "monthly_events": ["2026-07", "2026-08"]},
                "ten_rows_five_by_two": len(rows) == 10 and row_series == NEW_READY_SERIES and all(sum(row.get("series_id") == series_id for row in rows) == 2 for series_id in NEW_READY_SERIES),
                "series_periods_exact": by_series == EXPECTED_PERIODS,
                "canonical_columns_exact": isinstance(columns, list) and all(set(row) == set(columns) for row in rows),
                "unique_primary_keys": len(keys) == len(set(keys)),
                "values_and_units_valid": all(type(row.get("value")) in {int, float} and math.isfinite(row["value"]) and 0.0 <= row["value"] <= 20.0 and row.get("unit") == "percent_per_annum" for row in rows),
                "timestamps_ordered": all(datetime.fromisoformat(row["release_at"]) <= datetime.fromisoformat(row["available_at"]) <= datetime.fromisoformat(row["tradable_at"]) <= datetime.fromisoformat(row["retrieved_at"]) for row in rows),
                "blocked_series_have_no_rows": not row_series & LEGACY_FULL_HISTORY_BLOCKED_SERIES,
                "raw_hashes_known": all(row.get("raw_sha256") in RAW_FILES for row in rows),
                "manual_audit_exact": set(manual.get("passed_series", [])) == NEW_READY_SERIES and set(manual.get("blocked_series", [])) == LEGACY_FULL_HISTORY_BLOCKED_SERIES and manual.get("failures") == [] and manual.get("checks", {}).get("cfets_repo_new_mechanism") is False,
                "source_map_fail_closed": source_map.get("package_id") == "rates_liquidity" and any(item.get("source_id") == "CHINABOND" and item.get("status") == "LICENSE_GATE" and item.get("data_files") == [] for item in source_map.get("sources", [])) and any(item.get("source_id") == "CFETS_REPO_HISTORY" and item.get("new_independent_mechanism_found") is False for item in source_map.get("sources", [])),
                "audit_fail_closed": set(audit.get("passed_series", [])) == NEW_READY_SERIES and set(audit.get("blocked_series", [])) == LEGACY_FULL_HISTORY_BLOCKED_SERIES and audit.get("full_history_allowed") is False and audit.get("formal_curated_written") is False and audit.get("research_ready") is False and audit.get("failures") == [],
            }
        )
        checks["raw_hashes_match"] = checks["raw_hashes_known"] and all(
            (candidate_root / relative).is_file() and _sha256(candidate_root / relative).lower() == digest
            for digest, relative in RAW_FILES.items()
        )
        shibor = _load(candidate_root / RAW_FILES[next(digest for digest, name in RAW_FILES.items() if "shibor" in name)])
        shibor_records = {item["showDateCN"]: item for item in shibor.get("records", [])}
        field_by_series = {"CN.SHIBOR.ON": "ON", "CN.SHIBOR.1W": "1W", "CN.SHIBOR.3M": "3M"}
        checks["shibor_values_match_raw"] = all(
            float(shibor_records[row["reference_period"]][field_by_series[row["series_id"]]]) == row["value"]
            for row in rows if row["series_id"] in field_by_series
        )
        lpr_text = {
            "2026-07": re.sub(r"\s+", "", _visible_text(candidate_root / RAW_FILES["40285435bd15e5e93edd0399301b52fa5b52aac3af4ad61d98477df13f22d2f4"])),
            "2026-08": re.sub(r"\s+", "", _visible_text(candidate_root / RAW_FILES["5b4ddec501ddfe52bfec15d471c8c6d4548b643da9a61f35f9a978825bc04bd5"])),
        }
        lpr_pattern = {
            "CN.LPR.1Y": "1年期LPR为{value:.1f}%",
            "CN.LPR.5Y_PLUS": "5年期以上LPR为{value:.1f}%",
        }
        checks["lpr_values_and_times_match_raw"] = all(
            lpr_pattern[row["series_id"]].format(value=row["value"]) in lpr_text[row["reference_period"]]
            and row["release_at"].replace("T", "").replace(":00+08:00", "") in lpr_text[row["reference_period"]]
            for row in rows if row["series_id"] in {"CN.LPR.1Y", "CN.LPR.5Y_PLUS"}
        )
        chinabond = validate_chinabond_full_candidate()
        checks["chinabond_candidate_evidence_valid"] = chinabond["passed"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError, StopIteration):
        checks["candidate_parse_and_crosscheck"] = False
    failures = sorted(name for name, passed in checks.items() if not passed)
    legacy_checks = {name: passed for name, passed in checks.items() if name != "chinabond_candidate_evidence_valid"}
    legacy_passed = all(legacy_checks.values())
    return {
        "passed": not failures,
        "gold_ready_count": 11 if not failures else 9 if legacy_passed else 4,
        "gold_required_count": 11,
        "gold_missing": GOLD_MISSING_ORDER if not failures else sorted(LEGACY_GOLD_MISSING_SERIES) if legacy_passed else sorted(NEW_READY_SERIES | CHINABOND_READY_SERIES),
        "full_history_blocked_series": sorted(FULL_HISTORY_BLOCKED_SERIES),
        "checks": checks,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, default=CANDIDATE_ROOT)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()
    result = validate_rates_gold_candidate(args.candidate_root, args.audit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
