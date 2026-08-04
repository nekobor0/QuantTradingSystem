# V6 Phase 1验收矩阵 — 2026-08-01

## 结论

Phase 1五项基础设施均已有代码、机器artifact和自动化测试证据。M1所列六项已逐项证明；2026-08-01最终重跑V6测试为54 passed，全仓回归为1616 passed。

## Phase 1五项

| 要求 | 实现证据 | 机器证据 | 测试证据 | 状态 |
|---|---|---|---|---|
| 固化V5三个增强基线 | `src/quant_trading_system/research/v6/baseline_registry.py`、`scripts/v6/freeze_v5_baselines.py` | `artifacts/registrations/v5_baselines_v6.json`含`equal_style_p0`、`historical_icir`、`rolling_regression_24m`及输入SHA256 | `test_baseline_registry.py`重算三基线并验证漂移fail-closed | PASS |
| 完整风格风险模型 | `src/quant_trading_system/research/v6/style_risk.py`、`scripts/v6/audit_style_risk_model.py` | `artifacts/data_audits/style_risk_model_v6.json`：12项连续控制、PIT行业和金融子类，554,400行、5,775股、96月、重复0、PIT违规0 | schema、暴露覆盖、金融聚合阻断、券商/保险PIT区分测试 | PASS |
| 因子组合增量评价器 | `src/quant_trading_system/research/v6/incremental_evaluation.py` | `downside_beta_v6_evaluation.json`同时保存固定验证Δ净超额、ΔIR、ΔTE、Δ回撤、Δ换手、ΔDownside Beta、相关性、Partial IC、持仓重叠 | 指标计算和月份不一致fail-closed测试 | PASS |
| 策略级交易净额合并 | `src/quant_trading_system/research/v6/transaction_netting.py` | API输出净交易及未成交原因；先跨策略净额再执行 | 对手订单净额、不可交易报告、策略集合漂移、NaN/Inf阻断测试 | PASS |
| 实时影子流水线 | `src/quant_trading_system/research/v6/live_shadow.py`、`scripts/v6/record_live_shadow.py` | append-only记录带代码/数据/config hash；错误只追加correction | 不可覆盖、未来追加不改历史、缺hash、非有限数和不安全路径阻断测试 | PASS |

## M1六项

| M1要求 | 证据 | 状态 |
|---|---|---|
| 完整风险模型 | 上述12项风格/PIT行业暴露与覆盖模型；GOAL未要求Barra协方差预测，artifact明确限定为风格暴露和覆盖模型 | PASS |
| 因子和策略分级 | `src/quant_trading_system/research/v6/classification.py`严格实现GOAL第11节A/B/C必要门禁，缺失或非布尔证据fail-closed；研究状态与等级分离 | PASS |
| 增量组合评价 | 上述增量评价器及Downside Beta机器结果 | PASS |
| 多重检验账本 | `multiple_testing_ledger_v6.csv`与`multiple_testing_summary_v6.json`；第63项含HAC p、BH q和区块bootstrap | PASS |
| 实时影子框架 | 上述append-only框架；被拒候选未进入影子 | PASS |
| 全套测试通过 | 2026-08-01当前工作树V6范围54 passed；全仓回归1616 passed/0 skipped | PASS |

## 首轮研究

- 标准输出：`artifacts/evaluations/downside_beta_v6_report.md`。
- 数据审计：PASS；554,400行、5,775股、96月、未来信息违规0。
- 冻结配置完整复算：最终`REJECTED`，没有参数搜索或影子写入。
- 容量：机器结果现同时包含100万、500万、1000万元情景和5% ADV最低容量。
- 失败路径：本构造被证伪；不得继续搜索窗口、方向、20%权重、当前股票池和中性化口径。
