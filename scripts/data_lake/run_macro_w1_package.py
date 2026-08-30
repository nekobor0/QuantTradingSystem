"""Unified W1 package entry point with explicit no-skip execution gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from quant_trading_system.research.macro_data.w1_execution import build_audit, validate_audit
from scripts.data_lake.validate_macro_w1_gold import validate_registry
from scripts.data_lake.run_macro_w1_pmi_state_enablement import run_shadow as run_pmi_shadow
from scripts.data_lake.run_macro_w1_pmi_state_full import check_full_gate as check_pmi_full_gate
from scripts.data_lake.run_macro_w1_pmi_state_full import run_full as run_pmi_full
from scripts.data_lake.run_macro_w1_prices_enablement import run_shadow as run_prices_shadow
from scripts.data_lake.run_macro_w1_prices_full import check_full_gate as check_prices_full_gate
from scripts.data_lake.run_macro_w1_prices_full import run_full as run_prices_full
from scripts.data_lake.run_macro_w1_growth_output_enablement import run_bounded_candidate
from scripts.data_lake.run_macro_w1_growth_output_full import check_full_gate as check_growth_full_gate
from scripts.data_lake.run_macro_w1_growth_output_full import run_full as run_growth_full
from scripts.data_lake.run_macro_w1_money_credit_afre_full import check_full_gate as check_money_afre_full_gate
from scripts.data_lake.run_macro_w1_money_credit_afre_full import run_full as run_money_afre_full
from scripts.data_lake.validate_macro_w1_full_entry import MONEY_AFRE_SERIES_ID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--series")
    parser.add_argument("--mode", choices=("gold", "shadow", "full"), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--discovery", choices=("combined", "index", "direct-search"), default="combined")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "macro_r011")
    parser.add_argument("--authorize-formal-write", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((ROOT / "config" / "macro_w1_execution_manifest.json").read_text(encoding="utf-8"))
    package = next((item for item in manifest["packages"] if item["package_id"] == args.package), None)
    if package is None:
        raise SystemExit(f"unknown package: {args.package}")
    gold = validate_registry(ROOT / "config" / "macro_w1_gold_registry.json")["packages"][args.package]
    blockers: list[dict[str, str]] = []
    money_afre_full = args.package == "money_credit" and args.mode == "full" and args.series == MONEY_AFRE_SERIES_ID
    if args.series is not None and not money_afre_full:
        blockers.append({"code": "SERIES_DISPATCH_NOT_ALLOWED", "detail": args.series})
    if args.mode != "gold" and not gold["package_ready"] and not money_afre_full:
        blockers.append({"code": "GOLD_NOT_READY", "detail": package["gold_state"]})
    if args.mode == "shadow" and not package["shadow_allowed"]:
        blockers.append({"code": "SHADOW_NOT_ALLOWED", "detail": "execution manifest gate"})
    if args.mode == "full" and not package["full_history_allowed"] and not money_afre_full:
        blockers.extend(
            {"code": "FULL_HISTORY_NOT_ALLOWED", "detail": detail}
            for detail in package["full_blockers"]
        )
    if args.package == "prices" and args.mode == "full" and not blockers:
        blockers.extend(check_prices_full_gate(ROOT / "config" / "macro_w1_execution_manifest.json", args.start, args.end))
    if args.package == "pmi_state" and args.mode == "full" and not blockers:
        blockers.extend(check_pmi_full_gate(ROOT / "config" / "macro_w1_execution_manifest.json", args.start, args.end))
    if args.package == "growth_output" and args.mode == "full" and not blockers:
        blockers.extend(check_growth_full_gate(ROOT / "config" / "macro_w1_execution_manifest.json", args.start, args.end))
    if money_afre_full and not blockers:
        blockers.extend(check_money_afre_full_gate(ROOT / "config" / "macro_w1_execution_manifest.json", args.start, args.end))
    if money_afre_full and not blockers:
        result = run_money_afre_full(
            args.output_root,
            args.start,
            args.end,
            "execute",
            authorize_execute=args.authorize_formal_write,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(2 if result.get("blocked") else 0)
    if args.package == "pmi_state" and args.mode == "full" and not blockers:
        result = run_pmi_full(args.output_root, args.start, args.end, "execute")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(2 if result.get("blocked") else 0)
    if args.package == "pmi_state" and args.mode == "shadow" and not blockers:
        result = run_pmi_shadow(args.output_root, args.start, args.end)
        output = args.output_root / "audits" / "w1_pmi_state_shadow.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"audit": result["audit"], "validation": result["validation"], "gold": gold}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "blocked": result["audit"]["blocked"], "validation": result["validation"]}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["validation"]["passed"] else 1)
    if args.package == "prices" and args.mode == "shadow" and not blockers:
        result = run_prices_shadow(args.output_root, args.start, args.end)
        output = args.output_root / "audits" / "w1_prices_shadow.json"
        print(json.dumps({"output": str(output), "blocked": result["audit"]["blocked"], "validation": result["validation"], "research_ready": False}, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if result["validation"]["passed"] and not result["audit"]["blocked"] else 1)
    if args.package == "prices" and args.mode == "full" and not blockers:
        result = run_prices_full(args.output_root, args.start, args.end, "execute")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(2 if result.get("blocked") else 0)
    if args.package == "growth_output" and args.mode == "full" and not blockers:
        result = run_growth_full(
            args.output_root,
            args.start,
            args.end,
            "execute",
            authorize_execute=args.authorize_formal_write,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(2 if result.get("blocked") else 0)
    if args.package == "growth_output" and args.mode == "shadow" and not blockers:
        result = run_bounded_candidate(args.output_root, args.start, args.end, discovery=args.discovery)
        print(json.dumps({
            "output": str(args.output_root / "audits" / "w1_growth_output_bounded_candidate.json"),
            "candidate": result["candidate"], "blocked": result["audit"]["blocked"],
            "validation": result["validation"], "research_ready": False,
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if result["validation"]["passed"] and not result["audit"]["blocked"] else 1)
    if args.mode != "gold" and not blockers:
        blockers.append({"code": "PACKAGE_RUNNER_NOT_DISPATCHED", "detail": "use the package-specific shadow implementation"})
    audit = build_audit(
        package_id=args.package,
        run_mode=args.mode,
        start=args.start,
        end=args.end,
        expected=[],
        observed=[],
        sources=[],
        blockers=blockers,
    )
    validation = validate_audit(audit)
    output = args.output_root / "audits" / f"w1_{args.package}_{args.mode}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"audit": audit, "validation": validation, "gold": gold}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "blocked": audit["blocked"], "blocker_codes": [item["code"] for item in blockers], "validation": validation}, ensure_ascii=False, indent=2))
    raise SystemExit(2 if audit["blocked"] else 0)


if __name__ == "__main__":
    main()
