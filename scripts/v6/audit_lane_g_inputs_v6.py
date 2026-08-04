"""Audit Lane G allocator inputs and stop before portfolio construction when blocked."""

from __future__ import annotations

import json
from pathlib import Path

from quant_trading_system.research.v6.strategy_allocator import audit_allocator_inputs


def evaluation(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    evaluation_dir = Path("artifacts/evaluations")
    artifact_dir = Path("artifacts/alpha_phase1")
    candidates = [
        {
            "research_id": "rolling_regression_24m_v5_frozen_shadow",
            "lane": "A",
            "role": "index_enhancement",
            "decision": "SHADOW_BASELINE",
            "monthly_path": str(artifact_dir / "style_rolling_regression_24m_portfolio_v5_monthly.parquet"),
            "holdings_path": str(artifact_dir / "style_rolling_regression_24m_portfolio_v5_holdings.parquet"),
        }
    ]
    definitions = [
        ("shrunken_icir_v6", "A", "index_enhancement"),
        ("downside_beta_v6", "B", "defensive"),
        ("quality_adjusted_value_v6", "C", "independent_alpha"),
        ("limit_down_reopen_survival_v6", "D", "independent_alpha"),
        ("industry_residual_momentum_v6", "E", "independent_alpha"),
        ("industry_relative_momentum_v6", "F", "independent_alpha"),
    ]
    for research_id, lane, role in definitions:
        result = evaluation(evaluation_dir / f"{research_id}_evaluation.json")
        candidates.append(
            {
                "research_id": research_id,
                "lane": lane,
                "role": role,
                "decision": result["decision"],
                "monthly_path": str(evaluation_dir / f"{research_id}_monthly.parquet"),
                "holdings_path": str(evaluation_dir / f"{research_id}_holdings.parquet"),
            }
        )
    audit = audit_allocator_inputs(candidates)
    audit.update(
        {
            "version": 6,
            "research_id": "fixed_weight_allocator_v6",
            "frozen_weights": {
                "index_enhancement": 0.60,
                "defensive": 0.20,
                "independent_alpha": 0.20,
            },
            "portfolio_computed": audit["status"] == "PASS",
            "decision": "READY_FOR_FIXED_WEIGHT_BACKTEST" if audit["status"] == "PASS" else "DATA_BLOCKED",
        }
    )
    output = Path("artifacts/evaluations/fixed_weight_allocator_v6_input_audit.json")
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if audit["status"] != "PASS":
        raise SystemExit("DATA_BLOCKED: Lane G requires eligible defensive and independent-alpha engines")


if __name__ == "__main__":
    main()
