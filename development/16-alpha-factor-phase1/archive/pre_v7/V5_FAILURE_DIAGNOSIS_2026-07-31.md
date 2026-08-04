# V5三轮冻结构造失败诊断（2026-07-31）

## 可复算结论

三轮构造均使用同一T+1开盘执行、5bp成本、行业/Size/个股/换手约束和2023-07后固定验证：

1. 五风格等权P0固定验证通过，但全历史回撤为-30.35%/-29.38%。
2. 历史ICIR固定验证净超额只有2.846%/2.722%，且中证1000有2笔真实容量超限。
3. 24月滚动回归固定验证通过，但全历史回撤仍为-30.51%/-29.48%。

因此失败不是换手、成本或单股/行业/Size违规造成，而是绝对风险目标与指数增强相对风险预算之间的结构冲突。研究期基准自身回撤约-40.58%/-42.53%；全权益横截面增强已减少约10—13个百分点回撤，但还不足以达到-20%。

## 风险机制为何没有补上缺口

- MA200/70%把全期回撤降到约-26%—-27%，但固定验证TE升至7.49%/10.22%。
- 15%实现波动目标在趋势回撤中滞后，且现金仓位直接形成基准空头暴露；全期回撤仍-33.07%/-28.53%，中证1000固定验证TE达10.984%并产生负超额。

在不使用股指期货/期权、不增加独立横截面防御信号、又要求TE≤5%的范围内，继续搜索现金仓位参数很可能只是在“回撤”和“基准偏离”之间移动失败，不构成新证据。

## 固化复算命令

```powershell
$env:PYTHONPATH='src'
python scripts/alpha_phase1/run_style_baseline_portfolio_v5.py --variant historical_icir
python scripts/alpha_phase1/run_style_baseline_portfolio_v5.py --variant rolling_regression_24m
python scripts/alpha_phase1/evaluate_capacity_v5.py --stem style_historical_icir_portfolio_v5
python scripts/alpha_phase1/evaluate_capacity_v5.py --stem style_rolling_regression_24m_portfolio_v5
python scripts/alpha_phase1/build_multiple_testing_ledger_v5.py
python scripts/alpha_phase1/evaluate_volatility_target_v5.py
python -m pytest tests/research/alpha_phase1 -q
```

## 下一步边界

停止调MA、目标波动、窗口和仓位下限。24月滚动回归只作为实时影子候选。若发起下一轮历史研究，必须先冻结一个保持接近全权益、直接降低下行Beta的横截面机制，并提供独立数据或实时样本；否则按`GOAL.md`的“三轮冻结构造失败并提交可复算死因”路径结束本轮。
