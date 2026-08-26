"""Validate the W1 rates contract and the ignored local gold fixtures."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


EXPECTED_SERIES = {
    "CN.REPO.DR007",
    "CN.REPO.R007",
    "CN.PBOC.OMO.REVERSE_REPO.7D.RATE",
    "CN.PBOC.MLF.1Y.RATE",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _visible_text(path: Path) -> str:
    payload = path.read_text(encoding="utf-8")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", payload)).split())


def validate_contract(contract_path: Path) -> dict[str, object]:
    contract = _load(contract_path)
    mlf = contract["series"]["CN.PBOC.MLF.1Y.RATE"]
    regimes = {item["state"]: item for item in mlf["regimes"]}
    checks = {
        "status_is_gold_ready_shadow_only": contract["status"] == "GOLD_READY_SHADOW_ONLY",
        "all_nine_decisions_confirmed": contract["confirmation"]["accepted_decisions"]
        == [f"W1_D{number}" for number in range(1, 10)],
        "exact_four_series": set(contract["scope"]["series_ids"]) == EXPECTED_SERIES,
        "series_contracts_exact": set(contract["series"]) == EXPECTED_SERIES,
        "canonical_no_forward_fill": contract["canonical"]["no_forward_fill"] is True,
        "shadow_only_before_sol_review": set(contract["scope"]["forbidden_until_sol_review"])
        == {"full_history_backfill", "strategy_integration", "research_ready_promotion"},
        "mlf_pre_reform_regime_present": regimes["UNIFIED_RATE_DEFINED"]["end"] == "2025-02-28",
        "mlf_post_reform_is_structurally_undefined": regimes["UNIFIED_RATE_STRUCTURALLY_UNDEFINED"]["start"]
        == "2025-03-01",
        "post_reform_mlf_emits_no_rate": regimes["UNIFIED_RATE_STRUCTURALLY_UNDEFINED"]["parser_action"]
        == "emit_no_rate_row_and_write_structural_omission_audit",
        "repo_uses_weighted_average_not_fixing": contract["sources"]["cfets_repo_daily"]["value_field"]
        == "wghtdAvgRepoRate",
        "repo_historical_visibility_is_next_day": all(
            contract["series"][series_id]["historical_tradable_at"]
            == "next_strategy_trading_day_09:30+08:00"
            for series_id in ("CN.REPO.DR007", "CN.REPO.R007")
        ),
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {"passed": not failures, "checks": checks, "failures": failures}


def _validate_period(contract: dict[str, Any], period_root: Path, period: str) -> dict[str, bool]:
    required = set(contract["gold_fixtures"]["required_files_per_period"])
    required.update(contract["gold_fixtures"]["additional_files"].get(period, []))
    checks: dict[str, bool] = {"required_files_present": all((period_root / item).is_file() for item in required)}
    if not checks["required_files_present"]:
        return checks

    checksums = _load(period_root / "checksums.json")["files"]
    checks["raw_checksums_match"] = all(
        (period_root / filename).is_file() and _sha256(period_root / filename) == digest
        for filename, digest in checksums.items()
    )
    expected = _load(period_root / "expected.json")
    rows = expected["rows"]
    canonical_columns = set(contract["canonical"]["columns"])
    checks["fixture_period_matches_directory"] = expected["reference_period"] == period
    checks["three_expected_rows"] = len(rows) == 3
    checks["canonical_columns_exact"] = all(set(row) == canonical_columns for row in rows)
    keys = [(row["series_id"], row["reference_period"], row["vintage_id"]) for row in rows]
    checks["unique_primary_key"] = len(keys) == len(set(keys))
    checks["only_contract_series"] = set(row["series_id"] for row in rows).issubset(EXPECTED_SERIES)
    checks["no_mlf_rate_row_post_reform"] = not any(
        row["series_id"] == "CN.PBOC.MLF.1Y.RATE" for row in rows
    )
    checks["timestamp_order"] = all(
        datetime.fromisoformat(row["release_at"])
        <= datetime.fromisoformat(row["available_at"])
        <= datetime.fromisoformat(row["tradable_at"])
        <= datetime.fromisoformat(row["retrieved_at"])
        for row in rows
    )
    checks["values_in_bounds"] = all(
        contract["series"][row["series_id"]]["value_bounds"][0]
        <= row["value"]
        <= contract["series"][row["series_id"]]["value_bounds"][1]
        for row in rows
    )
    raw_by_series = {
        "CN.REPO.R007": period_root / "cfets_r007.json",
        "CN.REPO.DR007": period_root / "cfets_dr007.json",
        "CN.PBOC.OMO.REVERSE_REPO.7D.RATE": period_root / "pboc_omo.html",
    }
    checks["row_raw_hashes_match"] = all(row["raw_sha256"] == _sha256(raw_by_series[row["series_id"]]) for row in rows)

    repo_ok = True
    for series_id, filename in (("CN.REPO.R007", "cfets_r007.json"), ("CN.REPO.DR007", "cfets_dr007.json")):
        payload = _load(period_root / filename)
        match = [item for item in payload["records"] if item["instrmntCd"] == contract["series"][series_id]["instrument_code"]]
        expected_row = next(row for row in rows if row["series_id"] == series_id)
        repo_ok = repo_ok and payload["head"]["rep_code"] == "200" and payload["data"]["lastDate"] == period
        repo_ok = repo_ok and len(match) == 1 and float(match[0]["wghtdAvgRepoRate"]) == expected_row["value"]
    checks["repo_payloads_match_gold"] = repo_ok

    omo_text = _visible_text(period_root / "pboc_omo.html")
    omo_row = next(row for row in rows if row["series_id"] == "CN.PBOC.OMO.REVERSE_REPO.7D.RATE")
    checks["omo_payload_matches_gold"] = (
        period in omo_text and "7天" in omo_text and f"{omo_row['value']:.2f}%" in omo_text
        and omo_row["release_at"].replace("T", " ").replace("+08:00", "") in omo_text
    )

    if (period_root / "pboc_mlf_notice.html").exists():
        mlf_text = _visible_text(period_root / "pboc_mlf_notice.html")
        omissions = expected["expected_omissions"]
        checks["mlf_structural_omission_recorded"] = (
            len(omissions) == 1
            and omissions[0]["series_id"] == "CN.PBOC.MLF.1Y.RATE"
            and omissions[0]["state"] == "UNIFIED_RATE_STRUCTURALLY_UNDEFINED"
            and omissions[0]["raw_sha256"] == _sha256(period_root / omissions[0]["source_file"])
            and "多重价位中标" in mlf_text
            and "1年期" in mlf_text
        )
    else:
        checks["no_unexplained_omissions"] = expected["expected_omissions"] == []
    return checks


def validate_gold(contract_path: Path, fixture_root: Path | None = None) -> dict[str, object]:
    contract = _load(contract_path)
    root = fixture_root or Path(contract["gold_fixtures"]["root"])
    period_results = {
        period: _validate_period(contract, root / period, period)
        for period in contract["gold_fixtures"]["periods"]
    }
    failures = sorted(
        f"{period}:{name}"
        for period, checks in period_results.items()
        for name, passed in checks.items()
        if not passed
    )
    return {"passed": not failures, "periods": period_results, "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=Path("config/macro_w1_rates_contract.json"))
    parser.add_argument("--fixtures-root", type=Path)
    args = parser.parse_args()
    contract_result = validate_contract(args.contract)
    gold_result = validate_gold(args.contract, args.fixtures_root)
    result = {"passed": contract_result["passed"] and gold_result["passed"], "contract": contract_result, "gold": gold_result}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
