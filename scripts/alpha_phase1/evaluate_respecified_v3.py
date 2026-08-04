"""Re-evaluate the four frozen RESPECIFY candidates with V3 monthly channels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1.classified_evaluation import (
    evaluate_dense_factor_v3,
    evaluate_tail_factor,
)
from quant_trading_system.research.alpha_phase1.long_only_evaluation import prepare_universe


CANDIDATES = {
    "holder_concentration_level": {
        "panel": "factor_panel_flow_holder.parquet",
        "channel": "tail",
        "status": "RESPECIFY",
        "hypothesis": "散户占比较高的A股中，公告后可见的极端筹码集中代表持有人结构变化，最高5%而非全截面线性排序在下一月获得正超额。",
    },
    "formulaic_012": {
        "panel": "factor_panel_formulaic.parquet",
        "channel": "tail_diagnostic",
        "status": "RESPECIFY_SHORT_PRIMARY",
        "hypothesis": "价格与成交量变化方向极端背离代表短期冲击缺乏确认，极端尾部可能均值回归；月频尾部只作诊断，主检验应为5日。",
    },
    "price_volume_divergence": {
        "panel": "factor_panel_raw.parquet",
        "channel": "tail_diagnostic",
        "status": "RESPECIFY_SHORT_CONDITIONAL_PRIMARY",
        "hypothesis": "价格上涨而量能未确认的极端股票在散户注意力冲击后更易反转；月频尾部只作诊断，主检验应为5日和事前状态。",
    },
    "conservative_equity_growth": {
        "panel": "factor_panel_supplemental.parquet",
        "channel": "dense_style_baseline",
        "status": "STYLE_BASELINE",
        "hypothesis": "低权益扩张补偿投资风格风险并可能预测收益，但必须先作为传统Investment风格基线，不能直接计入新Alpha。",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-panel", default="factor_panel_raw.parquet")
    parser.add_argument("--version", type=int, default=3)
    args = parser.parse_args()

    base = pd.read_parquet(args.artifact_dir / args.base_panel)
    frame = prepare_universe(base, args.tushare_dir)
    pure = pd.read_parquet(args.artifact_dir / "factor_panel_pure_long_only_v2.parquet")
    pure["signal_date"] = pd.to_datetime(pure["signal_date"])
    pure_columns = [f"pure_{name}" for name in CANDIDATES]
    frame = frame.merge(
        pure[["ts_code", "signal_date", *pure_columns]],
        on=["ts_code", "signal_date"],
        how="left",
        validate="one_to_one",
    )

    results = {}
    for factor, registration in CANDIDATES.items():
        if factor not in frame:
            signal = pd.read_parquet(
                args.artifact_dir / registration["panel"],
                columns=["ts_code", "signal_date", factor],
            )
            signal["signal_date"] = pd.to_datetime(signal["signal_date"])
            frame = frame.merge(signal, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
        pure_factor = f"pure_{factor}"
        if registration["channel"].startswith("tail"):
            result = evaluate_tail_factor(frame, factor, pure_factor, registration["hypothesis"])
        else:
            result = evaluate_dense_factor_v3(frame, factor, pure_factor, registration["hypothesis"])
        result["registered_channel"] = registration["channel"]
        result["research_status"] = registration["status"]
        result["eligible_for_new_alpha_admission"] = bool(
            result["passes_all_gates"] and registration["status"] == "RESPECIFY"
        )
        results[factor] = result
        print(json.dumps({"factor": factor, "channel": result["channel"], "pass": result["passes_all_gates"]}, ensure_ascii=False), flush=True)

    payload = {
        "version": args.version,
        "spec": f"development/16-alpha-factor-phase1/EVALUATOR_V{args.version}_SPEC.md",
        "entry_price": "T+1 open" if args.version >= 4 else "T+1 close",
        "candidates": len(results),
        "results": results,
        "new_alpha_admissions": [name for name, value in results.items() if value["eligible_for_new_alpha_admission"]],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"new_alpha_admissions": payload["new_alpha_admissions"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
