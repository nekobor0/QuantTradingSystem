"""Evaluate the five preregistered abnormal-margin candidates with the V3 tail channel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_trading_system.research.alpha_phase1.classified_evaluation import evaluate_tail_factor
from quant_trading_system.research.alpha_phase1.long_only_evaluation import neutralize, prepare_universe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pure-panel", type=Path, required=True)
    parser.add_argument("--base-panel", default="factor_panel_raw.parquet")
    parser.add_argument("--version", type=int, default=3)
    args = parser.parse_args()

    metadata = json.loads(
        (args.artifact_dir / "factor_panel_margin_metadata.json").read_text(encoding="utf-8")
    )
    hypotheses: dict[str, str] = metadata["factor_hypotheses"]
    factors = list(hypotheses)

    base = pd.read_parquet(args.artifact_dir / args.base_panel)
    frame = prepare_universe(base, args.tushare_dir)
    signals = pd.read_parquet(
        args.artifact_dir / "factor_panel_margin.parquet",
        columns=["ts_code", "signal_date", *factors],
    )
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])
    frame = frame.merge(signals, on=["ts_code", "signal_date"], how="left", validate="one_to_one")

    pure = frame[["ts_code", "signal_date"]].copy()
    results: dict[str, object] = {}
    for factor in factors:
        pure_factor = f"pure_{factor}"
        frame[pure_factor] = neutralize(frame, factor)
        pure[pure_factor] = frame[pure_factor].astype("float32")
        result = evaluate_tail_factor(frame, factor, pure_factor, hypotheses[factor])
        result["registered_channel"] = "tail"
        result["research_status"] = "ADMIT" if result["passes_all_gates"] else "REJECTED"
        results[factor] = result
        print(
            json.dumps(
                {
                    "factor": factor,
                    "pure_tail_mean": result["pure_tail"]["excess"]["mean"],
                    "pure_tail_t": result["pure_tail"]["excess"]["t_stat"],
                    "pass": result["passes_all_gates"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    payload = {
        "version": args.version,
        "spec": f"development/16-alpha-factor-phase1/EVALUATOR_V{args.version}_SPEC.md",
        "entry_price": "T+1 open" if args.version >= 4 else "T+1 close",
        "family": "abnormal_margin_demand",
        "candidates": len(results),
        "results": results,
        "new_alpha_admissions": [name for name, value in results.items() if value["passes_all_gates"]],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pure.to_parquet(args.pure_panel, index=False, compression="zstd")
    print(json.dumps({"new_alpha_admissions": payload["new_alpha_admissions"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
