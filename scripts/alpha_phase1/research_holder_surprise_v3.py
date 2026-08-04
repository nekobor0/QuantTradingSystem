"""Build and evaluate the frozen V3 abnormal holder-concentration hypothesis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_trading_system.research.alpha_phase1.classified_evaluation import evaluate_tail_factor, tail_analysis
from quant_trading_system.research.alpha_phase1.long_only_evaluation import prepare_universe, neutralize


FACTOR = "holder_surprise_60d"
HYPOTHESIS = (
    "A股散户持有人占比较高且股东户数离散披露；公告后60日内，无法由价格、换手、规模、"
    "股本变化、回购和行业解释的户数下降代表静默筹码集中，最高5%下一月收益更高。"
)


def _zscore(values: pd.Series) -> pd.Series:
    clipped = values.clip(*values.quantile([0.01, 0.99]))
    std = clipped.std(ddof=0)
    return (clipped - clipped.mean()) / std if std and np.isfinite(std) else clipped * 0.0


def residualize_holder_surprise(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    controls = ["ret20", "turnover20", "log_circ_mv", "equity_supply_3m", "repurchase_execution_60"]
    for _, group in frame.groupby("signal_date", sort=False):
        valid = group["recent_holder_event"] & group[["holder_decay_change", *controls, "l1_code"]].notna().all(axis=1)
        sample = group.loc[valid]
        if len(sample) < 50:
            continue
        y = _zscore(sample["holder_decay_change"]).to_numpy()
        numeric = np.column_stack([_zscore(sample[column]).to_numpy() for column in controls])
        industries = pd.get_dummies(sample["l1_code"], drop_first=True, dtype=float).to_numpy()
        x = np.column_stack([np.ones(len(sample)), numeric, industries])
        result.loc[sample.index] = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
    known = frame["holder_num"].notna()
    result.loc[known & ~frame["recent_holder_event"]] = 0.0
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--tushare-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--panel-output", type=Path, required=True)
    parser.add_argument("--base-panel", default="factor_panel_raw.parquet")
    parser.add_argument("--version", type=int, default=3)
    args = parser.parse_args()

    base = pd.read_parquet(args.artifact_dir / args.base_panel)
    frame = prepare_universe(base, args.tushare_dir)
    frame["ret20"] = -frame["reversal_1m"]

    basic = pd.read_parquet(
        args.tushare_dir / "daily_basic_full.parquet",
        columns=["ts_code", "trade_date", "turnover_rate_f"],
    )
    basic["signal_date"] = pd.to_datetime(basic.pop("trade_date").astype(str))
    basic = basic.sort_values(["ts_code", "signal_date"])
    basic["turnover20"] = basic.groupby("ts_code", sort=False)["turnover_rate_f"].transform(
        lambda values: values.rolling(20, min_periods=12).mean()
    )
    wanted = set(frame["signal_date"].unique())
    frame = frame.merge(
        basic.loc[basic["signal_date"].isin(wanted), ["ts_code", "signal_date", "turnover20"]],
        on=["ts_code", "signal_date"], how="left", validate="one_to_one",
    )

    holder = pd.read_parquet(args.tushare_dir / "stk_holdernumber.parquet")
    holder["announcement_date"] = pd.to_datetime(holder.pop("ann_date").astype(str), errors="coerce")
    holder["report_date"] = pd.to_datetime(holder.pop("end_date").astype(str), errors="coerce")
    holder["holder_num"] = pd.to_numeric(holder["holder_num"], errors="coerce")
    holder = holder.dropna(subset=["ts_code", "announcement_date", "report_date", "holder_num"])
    holder = holder.sort_values(["ts_code", "report_date", "announcement_date"]).drop_duplicates(
        ["ts_code", "report_date"], keep="last"
    )
    prior = holder.groupby("ts_code", sort=False)["holder_num"].shift(1)
    holder["holder_change"] = -np.log(holder["holder_num"].where(holder["holder_num"] > 0) / prior.where(prior > 0))
    frame = pd.merge_asof(
        frame.sort_values(["signal_date", "ts_code"]),
        holder[["ts_code", "announcement_date", "holder_num", "holder_change"]].sort_values(["announcement_date", "ts_code"]),
        left_on="signal_date", right_on="announcement_date", by="ts_code", direction="backward",
    )
    frame["holder_age_days"] = (frame["signal_date"] - frame["announcement_date"]).dt.days
    frame["recent_holder_event"] = frame["holder_age_days"].between(0, 60) & frame["holder_change"].notna()
    frame["holder_decay_change"] = frame["holder_change"] * np.exp(-frame["holder_age_days"] / 30.0)

    supplemental = pd.read_parquet(
        args.artifact_dir / "factor_panel_supplemental.parquet",
        columns=["ts_code", "signal_date", "equity_supply_3m"],
    )
    corporate = pd.read_parquet(
        args.artifact_dir / "factor_panel_corporate_actions.parquet",
        columns=["ts_code", "signal_date", "repurchase_execution_60"],
    )
    for auxiliary in (supplemental, corporate):
        auxiliary["signal_date"] = pd.to_datetime(auxiliary["signal_date"])
        frame = frame.merge(auxiliary, on=["ts_code", "signal_date"], how="left", validate="one_to_one")
    frame[["equity_supply_3m", "repurchase_execution_60"]] = frame[
        ["equity_supply_3m", "repurchase_execution_60"]
    ].fillna(0.0)
    frame[FACTOR] = residualize_holder_surprise(frame)
    pure_name = f"pure_{FACTOR}"
    frame[pure_name] = neutralize(frame, FACTOR)

    unconditional = evaluate_tail_factor(frame, FACTOR, pure_name, HYPOTHESIS)
    flat_state = frame["ret20"].abs().le(0.10)
    conditional_frame = frame.copy()
    conditional_frame["eligible_quality"] &= flat_state
    conditional_frame["eligible_evaluation"] &= flat_state
    conditional = evaluate_tail_factor(
        conditional_frame,
        FACTOR,
        pure_name,
        HYPOTHESIS + " 条件状态事前冻结为绝对20日收益不超过10%。",
    )
    conditional["condition"] = "abs(ret20) <= 0.10"
    conditional["condition_row_share"] = float(flat_state.mean())
    cutoff = pd.Timestamp("2023-07-01")
    conditional["training_end"] = "2023-06-30"
    conditional["oos_start"] = str(cutoff.date())
    conditional["training_pure_tail"] = tail_analysis(
        conditional_frame.loc[conditional_frame["signal_date"] < cutoff], pure_name
    )[0]["excess"]
    conditional["fixed_oos_pure_tail"] = tail_analysis(
        conditional_frame.loc[conditional_frame["signal_date"] >= cutoff], pure_name
    )[0]["excess"]

    output_panel = frame[["ts_code", "signal_date", FACTOR, pure_name, "recent_holder_event", "holder_age_days", "ret20"]]
    output_panel.to_parquet(args.panel_output, index=False, compression="zstd")
    payload = {
        "version": args.version,
        "entry_price": "T+1 open" if args.version >= 4 else "T+1 close",
        "factor": FACTOR,
        "hypothesis": HYPOTHESIS,
        "construction": {
            "event_window_days": 60, "decay_days": 30,
            "controls": ["ret20", "turnover20", "log_circ_mv", "equity_supply_3m", "repurchase_execution_60", "SW_L1"],
            "conditional_state": "abs(ret20) <= 0.10",
        },
        "unconditional_tail": unconditional,
        "flat_price_conditional_tail": conditional,
        "admissions": [
            name for name, result in (("unconditional", unconditional), ("flat_price", conditional))
            if result["passes_all_gates"]
        ],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"admissions": payload["admissions"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
