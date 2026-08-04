"""Generate the auditable Markdown factor-zoo report from frozen V2 results."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


FAMILIES = (
    ("行情与微观结构", "factor_panel_metadata.json"),
    ("资金流与股东户数", "factor_panel_flow_holder_metadata.json"),
    ("公式型价量因子", "factor_panel_formulaic_metadata.json"),
    ("供给与财务质量", "factor_panel_supplemental_metadata.json"),
    ("估值与基本面变化", "factor_panel_valuation_metadata.json"),
    ("回购与重要股东交易", "factor_panel_corporate_actions_metadata.json"),
    ("现金流确认", "factor_panel_cash_confirmation_metadata.json"),
)

FAMILY_METHOD = {
    "行情与微观结构": "由前复权日线OHLCV构造20/60/120/252日价量、波动、振幅、隔夜与日内统计，月末采样。",
    "资金流与股东户数": "资金流先按5/20日滚动并按分类成交活跃度归一；股东户数只在ann_date后可见并向后携带。",
    "公式型价量因子": "复现公开101 Formulaic Alphas中的15个公式，使用A股字段适配后的日频值20日均值作为月末信号。",
    "供给与财务质量": "股本/自由流通股本按3或12个月变化；财务字段只取公告日后可见的年报值与同比变化。",
    "估值与基本面变化": "由月末估值、分红及年度利润/净资产/收入变化相对市值构造，负盈利按冻结规则处理。",
    "回购与重要股东交易": "回购仅计实施/完成金额且同一计划取最新累计值；股东实际IN/DE按方向和60/120日窗口聚合。",
    "现金流确认": "按公告日PIT合并季度CFO/净利润与CFO/收入比率，做四季度同比变化及其加速度。",
}

GATE_LABELS = {
    "missing_rate_lt_5pct": "缺失率<5%",
    "float_mv_coverage_ge_80pct": "流通市值覆盖>=80%",
    "pure_ic_abs_gt_004": "Pure IC绝对值>0.04",
    "pure_ic_ir_gt_06": "Pure IC_IR>0.6",
    "pure_ic_positive_ratio_gt_60pct": "正IC月份>60%",
    "raw_d1_mean_gt_15pct": "原始D1月超额>1.5%",
    "raw_d1_t_gt_2": "原始D1 t>2",
    "pure_d1_positive": "Pure D1超额>0",
    "pure_d1_t_gt_2": "Pure D1 t>2",
    "pure_d1_decay_lt_40pct": "Pure D1衰减<40%",
    "monotonic_pairs_ge_8": "十组至少8对递增",
    "d1_gt_d10": "D1>D10",
    "oos_3y_pure_d1_positive": "近3年Pure D1>0",
    "hs300_pure_d1_positive": "沪深300域Pure D1>0",
    "csi500_csi1000_pure_d1_positive": "中证500+1000域Pure D1>0",
    "main_board_pure_d1_positive": "主板域Pure D1>0",
}


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{value * 100:.2f}%"


def num(value: float | None, digits: int = 3) -> str:
    return "NA" if value is None else f"{value:.{digits}f}"


def escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def failure_text(result: dict) -> str:
    failed = [GATE_LABELS.get(key, key) for key, passed in result["gate_checks"].items() if not passed]
    return "；".join(failed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evaluation = json.loads(args.evaluation.read_text(encoding="utf-8"))
    results = evaluation["results"]
    if evaluation["factors_tested"] != 59 or len(results) != 59:
        raise ValueError("factor zoo requires the frozen 59-factor snapshot")
    family_factors: list[tuple[str, dict[str, str]]] = []
    ordered_names: list[str] = []
    for family, metadata_name in FAMILIES:
        metadata = json.loads((args.artifact_dir / metadata_name).read_text(encoding="utf-8"))
        hypotheses = metadata["factor_hypotheses"]
        family_factors.append((family, hypotheses))
        ordered_names.extend(hypotheses)
    if len(ordered_names) != 59 or set(ordered_names) != set(results):
        raise ValueError("metadata families do not match the 59 evaluated factors")

    failures = Counter(
        key for result in results.values() for key, passed in result["gate_checks"].items() if not passed
    )
    top_d1 = sorted(
        results.items(),
        key=lambda item: item[1]["pure_deciles"]["d1_excess"]["mean"] or -99,
        reverse=True,
    )[:5]
    lines = [
        "# 阶段一因子动物园：59个候选的构建思路与失败档案",
        "",
        "## 技术摘要",
        "",
        "本轮冻结快照包含 **59个候选（51个既有候选 + 8个新增候选）**、96个信号月，严格通过数为 **0**。所有因子均保持事前方向，没有因结果翻号；收益标签为月末T信号、T+1可交易收盘入场，并排除零成交及明显一字涨跌停入退场。",
        "",
        "失败不是主要由数据覆盖造成："
        f"{failures['pure_ic_ir_gt_06']}个未通过Pure IC_IR，"
        f"{failures['pure_ic_abs_gt_004']}个未通过Pure IC绝对值，"
        f"{failures['raw_d1_mean_gt_15pct']}个未达到原始D1月超额1.5%；"
        f"{failures['raw_d1_t_gt_2']}个原始D1 t值不足2，"
        f"{failures['monotonic_pairs_ge_8']}个十组单调性不足8对。"
        "最接近的Pure D1仍不足1%，不能作为500万元以内纯多头策略的入库砖石。",
        "",
        "Pure D1月超额最高的5个为："
        + "、".join(
            f"`{name}` {pct(result['pure_deciles']['d1_excess']['mean'])}"
            for name, result in top_d1
        )
        + "。",
        "",
        "## 口径与判定",
        "",
        "- 研究域：全A（研究阶段纳入ST并标记）；风格中性控制为流通市值、申万一级行业、60日波动率、自由流通换手率和12-1动量。",
        "- D1：因子值最高十分位；基准为同月合格全A等权收益。Pure因子是每月截面风格回归残差并重新分组。",
        "- 稳健性域：近3年样本外、沪深300、中证500+中证1000、主板；各域内部重新分组并用域内等权基准。",
        "- 下表“失败门槛”列出该因子未满足的全部冻结硬门槛；任何一项失败即不入库。",
        "",
        "## 全局失败分布",
        "",
        "| 未通过门槛 | 因子数/59 |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {GATE_LABELS.get(key, key)} | {count}/59 |" for key, count in failures.most_common()
    )

    for family, hypotheses in family_factors:
        lines.extend(
            [
                "",
                f"## {family}：{len(hypotheses)}个",
                "",
                FAMILY_METHOD[family],
                "",
                "| 因子 | 构建思路/可证伪逻辑 | 关键实测 | 最终失败门槛 |",
                "|---|---|---|---|",
            ]
        )
        for factor, hypothesis in hypotheses.items():
            result = results[factor]
            quality = result["quality"]
            pure_ic = result["pure_ic"]
            raw_d1 = result["raw_deciles"]["d1_excess"]
            pure_d1 = result["pure_deciles"]["d1_excess"]
            metrics = (
                f"缺失{pct(quality['missing_rate'])}；市值覆盖{pct(quality['float_mv_coverage'])}；"
                f"Pure IC {num(pure_ic['mean'], 4)} / IR {num(pure_ic['ir'])}；"
                f"原始D1 {pct(raw_d1['mean'])} (t={num(raw_d1['t_stat'], 2)})；"
                f"Pure D1 {pct(pure_d1['mean'])} (t={num(pure_d1['t_stat'], 2)})"
            )
            lines.append(
                f"| `{factor}` | {escape(hypothesis)} | {escape(metrics)} | {escape(failure_text(result))} |"
            )

    lines.extend(
        [
            "",
            "## 失败模式与研究含义",
            "",
            "1. **高IC不等于纯多头可赚。** `formulaic_012`是旧评估中最接近者之一，但V2 Pure IC约0.030，原始D1月超额仅约0.46%，说明信息更多分布在排序全局或空头端，无法满足纯多头D1要求。",
            "2. **风格剥离会改变尾部收益。** `conservative_equity_growth`原始D1约1.39%且t>3，是最接近1.5%门槛的候选；中性后Pure D1约0.89%，仍未达到入库标准，表明部分收益来自风格暴露。",
            "3. **事件因子稀疏但不能把无事件当缺失。** 回购和实际增减持按无事件=0实现，覆盖达标，但Pure IC和D1均失败；本轮证据不支持把管理层行动直接视为月频可交易Alpha。",
            "4. **现金流数据源不够全。** 本地现金流比率只覆盖约2%–24%的流通市值，三个候选先死于数据质量，任何收益统计都不能外推到全A。",
            "",
            "## 下一步",
            "",
            "- 优先完成异常融资需求数据与5个事前冻结窗口的盲评；其经济来源与现有价量、财务和管理层行动不同。",
            "- 解禁接口因持有人明细在单日超过Tushare约10万offset上限而无法证明完整，本轮不进入正式因子面板；后续应获取按股票-解禁日聚合的数据源。",
            "- 若新增因子继续无法达到D1 1.5%与Pure IC 0.04，应把“至少5个全门槛入库”判为当前数据与固定月频框架下未实现，而不是放宽阈值或事后翻号。",
            "",
            "## 证据与复算",
            "",
            f"- 冻结评价：`{args.evaluation.as_posix()}`",
            "- 评价器：`scripts/alpha_phase1/evaluate_factors_long_only.py`",
            "- 因子构建脚本：`scripts/alpha_phase1/build_*factor_panel.py`",
            "- 本报告生成器：`scripts/alpha_phase1/generate_factor_zoo.py`",
            "",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"path": str(args.output), "factors": len(ordered_names)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
