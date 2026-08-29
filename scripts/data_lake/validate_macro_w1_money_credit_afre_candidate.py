"""Validate the authorized AFRE RMB-loans Gold candidate without gate promotion."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_ROOT = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_money_credit_candidate_v3"
AUDIT_PATH = ROOT / "artifacts" / "macro_r011" / "audits" / "w1_money_credit_afre_gold_candidate_v1.json"
RAW_PATH = ROOT / "artifacts" / "macro_r011" / "gold_fixtures" / "w1_money_credit_candidate_v2" / "raw" / "pboc_afre_flow_2026-06_2026-07.htm"
RAW_MANIFEST_PATH = RAW_PATH.with_name(f"{RAW_PATH.name}.manifest.json")

SERIES_ID = "CN.TSF.RMB_LOANS.FLOW"
LEGACY_BLOCKED_SERIES = {"CN.LOANS.RMB.FLOW", "CN.LOANS.CORP.MEDIUM_LONG.FLOW"}
EXPECTED_VALUES = {"2026-06": 17650, "2026-07": -5896}
RAW_SHA256 = "D17359C92CE0F040C1B9C5355432A127D6CDA34FAB18285CB5F53D978D5C12A5"
PAGE_TIME = "2026-08-14T16:30:05+08:00"
SOURCE_URL = "https://www.pbc.gov.cn/diaochatongjisi/attachDir/2026/08/2026081417010772070.htm"
CANONICAL_COLUMNS = {
    "series_id", "reference_period", "value", "unit", "seasonal_adjustment",
    "source_id", "source_record_id", "release_at", "available_at", "tradable_at",
    "availability_evidence", "retrieved_at", "vintage_id", "raw_sha256", "parser_version",
}
SEMANTIC_SCOPE = "loans_to_the_real_economy_afre_component"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _cells(fragment: str) -> list[str]:
    values = re.findall(r"<td\b[^>]*>(.*?)</td>", fragment, flags=re.IGNORECASE | re.DOTALL)
    return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split()) for value in values]


def _raw_values(path: Path) -> dict[str, int]:
    text = path.read_bytes().decode("gb18030")
    rows = [_cells(fragment) for fragment in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.IGNORECASE | re.DOTALL)]
    if not any("AFRE(flow)" in row and "RMB loans" in row for row in rows):
        raise ValueError("AFRE/RMB-loans header missing")
    result: dict[str, int] = {}
    for row in rows:
        if len(row) >= 3 and row[0] in {"2026.06", "2026.07"}:
            result[row[0].replace(".", "-")] = int(row[2])
    return result


def validate_money_credit_afre_candidate(
    candidate_root: Path = CANDIDATE_ROOT,
    audit_path: Path = AUDIT_PATH,
    raw_path: Path = RAW_PATH,
    raw_manifest_path: Path = RAW_MANIFEST_PATH,
) -> dict[str, Any]:
    paths = {
        "expected": candidate_root / "expected.json",
        "source_map": candidate_root / "source_map.json",
        "manual_audit": candidate_root / "manual_audit.json",
        "candidate_audit": audit_path,
        "raw": raw_path,
        "raw_manifest": raw_manifest_path,
    }
    checks: dict[str, bool] = {"required_files_present": all(path.is_file() for path in paths.values())}
    try:
        expected = _load(paths["expected"])
        source_map = _load(paths["source_map"])
        manual = _load(paths["manual_audit"])
        audit = _load(paths["candidate_audit"])
        manifest = _load(paths["raw_manifest"])
        rows = expected.get("rows") if isinstance(expected.get("rows"), list) else []
        keys = [(row.get("series_id"), row.get("reference_period"), row.get("vintage_id")) for row in rows if isinstance(row, dict)]
        values = {row.get("reference_period"): row.get("value") for row in rows if isinstance(row, dict)}
        timestamps_ordered = all(
            datetime.fromisoformat(row["release_at"])
            <= datetime.fromisoformat(row["available_at"])
            <= datetime.fromisoformat(row["tradable_at"])
            <= datetime.fromisoformat(row["retrieved_at"])
            for row in rows
        )
        source_items = source_map.get("sources") if isinstance(source_map.get("sources"), list) else []
        accepted_sources = [item for item in source_items if isinstance(item, dict) and item.get("accepted") is True]
        checks.update(
            {
                "candidate_identity_exact": expected.get("schema_version") == 2
                and expected.get("package_id") == "money_credit"
                and expected.get("candidate_id") == "R011.W1.MONEY_CREDIT.AFRE.GOLD_CANDIDATE_V1",
                "requested_window_exact": expected.get("requested_window") == ["2026-06", "2026-07"],
                "two_rows_one_series": expected.get("row_count") == 2
                and len(rows) == 2
                and {row.get("series_id") for row in rows} == {SERIES_ID},
                "periods_and_values_exact": values == EXPECTED_VALUES,
                "canonical_columns_exact": set(expected.get("canonical_columns", [])) == CANONICAL_COLUMNS
                and all(isinstance(row, dict) and set(row) == CANONICAL_COLUMNS for row in rows),
                "unique_primary_keys": len(keys) == len(set(keys)) == 2,
                "units_and_values_valid": all(
                    type(row.get("value")) in {int, float}
                    and math.isfinite(row["value"])
                    and row.get("unit") == "100m_cny"
                    and row.get("seasonal_adjustment") == "not_seasonally_adjusted"
                    for row in rows
                ),
                "source_and_semantics_exact": all(
                    row.get("source_id") == "PBOC_STATS"
                    and row.get("source_record_id") == "AFRE(flow)|RMB loans"
                    and row.get("raw_sha256", "").upper() == RAW_SHA256
                    for row in rows
                ),
                "timestamps_ordered": timestamps_ordered,
                "official_release_time_exact": all(
                    row.get("release_at") == PAGE_TIME and row.get("available_at") == PAGE_TIME for row in rows
                ),
                "legacy_total_loan_ids_absent": not ({row.get("series_id") for row in rows} & LEGACY_BLOCKED_SERIES),
                "expected_state_exact": expected.get("passed_series") == [SERIES_ID]
                and set(expected.get("blocked_series", [])) == LEGACY_BLOCKED_SERIES,
                "source_map_exact": len(accepted_sources) == 1
                and accepted_sources[0].get("source_id") == "PBOC_STATS"
                and accepted_sources[0].get("official_table") == "AFRE(flow)"
                and accepted_sources[0].get("official_field") == "RMB loans"
                and accepted_sources[0].get("semantic_scope") == SEMANTIC_SCOPE
                and accepted_sources[0].get("not_equivalent_to") == ["CN.LOANS.RMB.FLOW"]
                and accepted_sources[0].get("raw_sha256", "").upper() == RAW_SHA256,
                "manual_audit_fail_closed": manual.get("status") == "GOLD_CANDIDATE_AWAITING_SOL_REVIEW"
                and manual.get("passed_series") == [SERIES_ID]
                and set(manual.get("blocked_series", [])) == LEGACY_BLOCKED_SERIES
                and manual.get("checks", {}).get("direct_monthly_afre_component") is True
                and manual.get("checks", {}).get("not_total_rmb_loan_flow") is True
                and manual.get("checks", {}).get("no_cumulative_or_balance_differencing") is True
                and manual.get("failures") == [],
                "candidate_audit_fail_closed": audit.get("status") == "GOLD_CANDIDATE_AWAITING_SOL_REVIEW"
                and audit.get("passed_series") == [SERIES_ID]
                and set(audit.get("blocked_series", [])) == LEGACY_BLOCKED_SERIES
                and audit.get("full_history_allowed") is False
                and audit.get("formal_curated_written") is False
                and audit.get("research_ready") is False
                and audit.get("failures") == [],
                "raw_sha_exact": _sha256(paths["raw"]) == RAW_SHA256,
                "raw_values_match": _raw_values(paths["raw"]) == EXPECTED_VALUES,
                "raw_manifest_exact": manifest.get("source_id") == "PBOC_STATS"
                and manifest.get("url") == SOURCE_URL
                and manifest.get("http_status") == 200
                and manifest.get("page_time") == PAGE_TIME
                and manifest.get("sha256", "").upper() == RAW_SHA256
                and manifest.get("bytes") == paths["raw"].stat().st_size,
            }
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        checks["candidate_parse_and_crosscheck"] = False
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "passed": not failures,
        "candidate_series": SERIES_ID,
        "candidate_rows": 2 if not failures else 0,
        "post_candidate_gold_ready_count": 6 if not failures else 5,
        "gold_required_count": 8,
        "remaining_gold_missing": sorted(LEGACY_BLOCKED_SERIES),
        "checks": checks,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, default=CANDIDATE_ROOT)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    parser.add_argument("--raw", type=Path, default=RAW_PATH)
    parser.add_argument("--raw-manifest", type=Path, default=RAW_MANIFEST_PATH)
    args = parser.parse_args()
    result = validate_money_credit_afre_candidate(args.candidate_root, args.audit, args.raw, args.raw_manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
