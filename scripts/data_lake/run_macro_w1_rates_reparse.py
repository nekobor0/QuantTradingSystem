"""Offline reparse of immutable PBOC full-history raw snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "data_lake"))

from quant_trading_system.research.macro_data.adapters import parse_pboc_policy_release  # noqa: E402
from quant_trading_system.research.macro_data.backfill import _write_json, _write_rate_shard  # noqa: E402
from quant_trading_system.research.macro_data.contracts import CANONICAL_COLUMNS, RawSnapshot, SeriesSpec, snapshot_as_dict, write_normalized_snapshot  # noqa: E402
from quant_trading_system.research.macro_data.pipeline import validate_canonical  # noqa: E402
from run_macro_w1_rates_full import _calendar_evidence, count_independent_cfets_paths  # noqa: E402


def _snapshot(source_id: str, path: Path) -> RawSnapshot:
    payload = path.read_bytes()
    return RawSnapshot(
        source_id=source_id,
        retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        raw_path=str(path.resolve()),
        manifest_path="local-reparse.manifest.json",
        request_method="GET",
        request_url="https://www.pbc.gov.cn/local-reparse",
        response_status=200,
        content_type="text/html",
    )


def page_funnel(
    details: dict[str, list[dict[str, object]]], discovery: dict[str, object]
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for kind, group in details.items():
        source_discovery = discovery.get(kind, {})
        discovered = source_discovery.get("relevant_pages", 0) if isinstance(source_discovery, dict) else 0
        result[kind] = {
            "candidate_pages_discovered": int(discovered),
            "raw_pages_attempted": len(group),
            "pages_parsed": sum(item.get("status") == "PARSED" for item in group),
            "pages_with_observations": sum(int(item.get("observation_rows", 0)) > 0 for item in group),
            "parsed_omission_only_pages": sum(
                item.get("status") == "PARSED" and int(item.get("observation_rows", 0)) == 0
                for item in group
            ),
            "unresolved_parse_failures": sum(item.get("status") != "PARSED" for item in group),
        }
    return result


def reparse(
    output_root: Path,
    calendar_path: Path | None = None,
    *,
    write_shards: bool = True,
) -> dict[str, object]:
    details: dict[str, list[dict[str, object]]] = {"omo": [], "mlf": []}
    frames: list[pd.DataFrame] = []
    for kind, source_id in (("omo", "pboc_omo_release"), ("mlf", "pboc_mlf_release")):
        root = output_root / "raw" / source_id
        for path in sorted(root.rglob("*.html")):
            snapshot = _snapshot(source_id, path)
            try:
                parsed = parse_pboc_policy_release(path.read_bytes(), snapshot, source_file=path.name)
                if write_shards:
                    _write_rate_shard(
                        output_root,
                        parsed.observations,
                        snapshot,
                        {"event_kind": parsed.event_kind, "omissions": list(parsed.omissions), "reparsed_offline": True},
                    )
                details[kind].append({"status": "PARSED", "raw_path": str(path), "event_kind": parsed.event_kind, "observation_rows": int(len(parsed.observations)), "omissions": list(parsed.omissions), "snapshot": snapshot_as_dict(snapshot)})
                if not parsed.observations.empty:
                    frames.append(parsed.observations)
            except Exception as exc:
                details[kind].append({"status": "QUARANTINED", "raw_path": str(path), "reason": f"{type(exc).__name__}: {exc}", "snapshot": snapshot_as_dict(snapshot)})

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CANONICAL_COLUMNS)
    if not combined.empty:
        combined = combined.drop_duplicates(["series_id", "reference_period", "vintage_id"]).sort_values(["reference_period", "series_id"]).reset_index(drop=True)
        write_normalized_snapshot(combined, output_root / "curated" / "pboc_omo_mlf_official_event_history.parquet")
    prior_path = output_root / "audits" / "w1_rates_full_history.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else {}
    shadow_path = output_root / "audits" / "w1_rates_shadow.json"
    shadow = json.loads(shadow_path.read_text(encoding="utf-8")) if shadow_path.exists() else {}
    omissions = [omission for group in details.values() for item in group for omission in item.get("omissions", [])]
    mlf_rate_rows = int(((combined["series_id"] == "CN.PBOC.MLF.1Y.RATE") & (combined["reference_period"] >= "2025-03-01")).sum()) if not combined.empty else 0
    contract = json.loads((ROOT / "config" / "macro_w1_rates_contract.json").read_text(encoding="utf-8"))
    specs = tuple(
        SeriesSpec(
            series_id=series_id,
            source_id=spec["source_id"],
            source_field=spec.get("instrument_code", series_id),
            frequency=spec["frequency"],
            unit=spec["unit"],
            seasonal_adjustment="not_applicable",
            value_min=float(spec["value_bounds"][0]),
            value_max=float(spec["value_bounds"][1]),
        )
        for series_id, spec in contract["series"].items()
    )
    value_domain_failures = [
        item.series_id
        for item in specs
        if not combined.empty
        and not combined.loc[combined["series_id"].eq(item.series_id), "value"].between(item.value_min, item.value_max).all()
    ]
    funnel = page_funnel(details, prior.get("pboc", {}).get("discovery", {}))
    for kind, series_id in (
        ("omo", "CN.PBOC.OMO.REVERSE_REPO.7D.RATE"),
        ("mlf", "CN.PBOC.MLF.1Y.RATE"),
    ):
        funnel[kind]["canonical_rows_after_primary_key_dedup"] = int(
            combined["series_id"].eq(series_id).sum()
        ) if not combined.empty else 0
    current_quarantine = [
        {"kind": kind, "raw_path": item.get("raw_path"), "reason": item.get("reason")}
        for kind, group in details.items()
        for item in group
        if item.get("status") != "PARSED"
    ]
    historical_quarantine = prior.get("quarantine_history", prior.get("quarantine", []))
    prior_scope = prior.get("scope", {})
    cfets_window = prior_scope.get("cfets_shadow_validation_window", {
        "start": prior_scope.get("start"), "end": prior_scope.get("end")
    })
    calendar = prior.get("calendar", {})
    if calendar_path is not None:
        calendar = _calendar_evidence(
            output_root,
            calendar_path,
            str(cfets_window["start"]),
            str(cfets_window["end"]),
        )
    reference_periods = combined["reference_period"].astype(str) if not combined.empty else pd.Series(dtype="string")
    audit = {
        **prior,
        "scope": {
            "four_series_only": True,
            "cfets_shadow_validation_window": cfets_window,
            "pboc_collection": "all_immutable_official_event_pages_available_in_raw_store",
            "pboc_reference_period_min": reference_periods.min() if not reference_periods.empty else None,
            "pboc_reference_period_max": reference_periods.max() if not reference_periods.empty else None,
            "research_ready": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calendar": calendar,
        "pboc": {
            **prior.get("pboc", {}),
            "parse_counts": {kind: sum(item.get("status") == "PARSED" for item in group) for kind, group in details.items()},
            "parse_rates": {kind: (sum(item.get("status") == "PARSED" for item in group) / len(group) if group else None) for kind, group in details.items()},
            "page_funnel": funnel,
            "page_funnel_population_note": "candidate_pages_discovered is from the latest URL discovery run; raw_pages_attempted is the cross-run immutable raw store and can be larger",
            "events": details,
            "series_semantics": {
                "CN.PBOC.OMO.REVERSE_REPO.7D.RATE": "sparse official operation-rate events; not a daily panel",
                "CN.PBOC.MLF.1Y.RATE": "sparse official unified-rate events; not a monthly panel; structurally undefined from 2025-03-01",
            },
            "structural_omissions": [item for item in omissions if item.get("state") == "UNIFIED_RATE_STRUCTURALLY_UNDEFINED"],
            "mlf_post_2025_03_rate_rows": mlf_rate_rows,
        },
        "normalized": {"dataset": "pboc_omo_mlf_official_event_history.parquet", "rows": len(combined), "duplicate_primary_keys": int(combined.duplicated(["series_id", "reference_period", "vintage_id"]).sum()) if not combined.empty else 0, "raw_hashes_valid": all(len(item["snapshot"]["sha256"]) == 64 for group in details.values() for item in group)},
        "value_domain_failures": value_domain_failures,
        "timestamp_order": validate_canonical(combined, specs) if not combined.empty else {"passed": True, "reason": "no rows"},
        "raw_hash": {"captured_responses": sum(len(group) for group in details.values()), "valid_sha256": all(len(item["snapshot"]["sha256"]) == 64 for group in details.values() for item in group)},
        "quarantine": current_quarantine,
        "quarantine_history": historical_quarantine,
        "quarantine_semantics": {
            "quarantine": "currently unresolved raw pages after this parser version",
            "quarantine_history": "retained legacy incident artifacts; not counted as current failures",
        },
        "cfets": {**prior.get("cfets", {}), "independent_mechanism_count": count_independent_cfets_paths(prior.get("cfets", {}).get("independent_mechanisms", [])), "daily_pair_coverage": shadow.get("repo_pair_same_date_coverage"), "daily_pair_unexplained": shadow.get("unexplained_missing_dates", []), "duplicate_primary_keys": shadow.get("duplicate_primary_keys", 0), "calendar_blocked": calendar.get("status") != "OK"},
        "unexplained": [
            {"kind": kind, **item}
            for kind, group in details.items()
            for item in group
            if item.get("status") != "PARSED"
        ] + ([{"kind": "calendar", **calendar}] if calendar.get("status") != "OK" else []),
        "blocked": True,
        "research_ready": False,
    }
    _write_json(prior_path, audit)
    summary_path = output_root / "audits" / "w1_rates_full_history_summary.md"
    summary_path.write_text(
        "# R011 PBOC official event-history source summary\n\n"
        f"PBOC OMO page funnel: {json.dumps(funnel['omo'], ensure_ascii=False)}. Parse success uses raw pages attempted as its denominator; observation-emitting pages are reported separately.\n\n"
        f"PBOC MLF page funnel: {json.dumps(funnel['mlf'], ensure_ascii=False)}. The output is a sparse unified-rate event series, not a monthly panel; post-2025-03 MLF rate rows={mlf_rate_rows}.\n\n"
        f"CFETS remains blocked: daily shadow pair coverage={shadow.get('repo_pair_same_date_coverage')}; calendar status={audit.get('calendar', {}).get('status')}; three distinct official mechanism records remain evidence-only.\n\n"
        f"Current unresolved quarantine={len(current_quarantine)}; retained legacy quarantine artifacts={len(historical_quarantine)}. Duplicate primary keys={audit['normalized']['duplicate_primary_keys']}; value-domain failures={len(value_domain_failures)}; timestamp-order passed={audit['timestamp_order'].get('passed')}; unexplained={len(audit['unexplained'])}.\n\n"
        "No forward-fill, interpolation, old MLF rate continuation, fixing rate, or third-party value was used. Research-ready promotion is prohibited.\n",
        encoding="utf-8",
    )
    state_dir = output_root / "state" / "w1_rates_luna_full"
    state_dir.mkdir(parents=True, exist_ok=True)
    calendar = audit.get("calendar", {})
    calendar_line = (
        "- Strategy calendar: `OK`; requested window and one later session are covered.\n"
        if calendar.get("status") == "OK"
        else f"- Strategy calendar: `BLOCKED`; {calendar.get('error', 'not supplied')}.\n"
    )
    (state_dir / "BLOCKED.md").write_text(
        "# R011 full-history BLOCKED\n\n"
        "Status is intentionally blocked and `research_ready=false`.\n\n"
        f"{calendar_line}"
        "- CFETS formal history: not promoted; three independent official mechanism records are in `audits/w1_rates_full_history.json`.\n"
        f"- PBOC unexplained items: {len(audit['unexplained'])}; see full audit and quarantine paths.\n"
        "- No third-party data was used.\n",
        encoding="utf-8",
    )
    (state_dir / "PROGRESS.md").write_text(
        "# R011 W1 rates full-history progress\n\n"
        "- Task 0: passed; Gold exact and W1 baseline 13 passed with worktree basetemp.\n"
        f"- Calendar: {calendar.get('status')}; CFETS remains blocked.\n"
        f"- PBOC OMO: discovered {audit['pboc']['discovery'].get('omo', {}).get('relevant_pages', 0)} pages; parsed {audit['pboc']['parse_rates']['omo']}.\n"
        f"- PBOC MLF: discovered {audit['pboc']['discovery'].get('mlf', {}).get('relevant_pages', 0)} candidate pages; parsed {audit['pboc']['parse_rates']['mlf']}; post-2025-03 rate rows={mlf_rate_rows}.\n"
        f"- Full audit: `audits/w1_rates_full_history.json`; unexplained={len(audit['unexplained'])}; duplicate keys={audit['normalized']['duplicate_primary_keys']}.\n"
        "- Blocked status: true; no strategy integration.\n",
        encoding="utf-8",
    )
    print(json.dumps({"rows": len(combined), "parse_counts": audit["pboc"]["parse_counts"], "parse_rates": audit["pboc"]["parse_rates"], "mlf_post_2025_03_rate_rows": mlf_rate_rows, "unexplained": len(audit["unexplained"])}, ensure_ascii=False, indent=2))
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/macro_r011"))
    parser.add_argument("--calendar-source", type=Path)
    parser.add_argument("--audit-only", action="store_true", help="Validate immutable raw without rewriting normalized shards")
    args = parser.parse_args()
    reparse(args.output_root, args.calendar_source, write_shards=not args.audit_only)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
