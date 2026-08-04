# 12 报告模块

## 目标与边界

从有版本的账户、信号、回测、风险和数据质量事实生成可追溯的绩效、归因、运营与研究报告，确保展示数字能回到来源快照。

报告是派生快照，不是订单、成交、持仓、指标或风险事实的所有者；修正源事实后生成新报告版本，不覆盖旧报告。

## 所有数据

- `report_definition`：报告类型、受众、指标版本、数据需求和模板版本。
- `report_run`：报告期、输入 snapshot、生成状态、代码/模板版本和内容哈希。
- `report_metric`：指标名、值、单位、口径和来源查询引用。
- `sleeve_attribution`：`ETF_TIMING`、`EQUITY_DAILY_SELECTION` 与交叉约束/现金对组合收益、风险、换手和成本的贡献；证券下钻用 `instrument_id`，名称/代码按报告时点展示。
- `report_artifact`：HTML/CSV/图表等路径、哈希、生成时间和敏感级别。
- `report_quality_result`：对账、完整性、数值和引用检查。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `BuildReport(definition, period, input_snapshots)` | 幂等键为定义、期间、输入与模板哈希 |
| Query | `GetReport(report_run_id)` | 返回 artifact、口径、来源和质量状态 |
| Query | `ExplainMetric(report_run_id, metric_name)` | 返回公式、输入快照与明细下钻引用 |
| Query | `GetSleeveAttribution(report_run_id)` | 返回两策略独立 run、目标贡献、净交易与组合归因 |
| Event | `ReportSnapshotBuilt` / `ReportBuildFailed` | 仅 quality PASS 的 artifact 可发布 |

## 主流程

冻结输入快照 → 对账检查 → 计算组合和两个 sleeve 的版本化指标/归因 → 生成表格/图表 → 校验合计、单位、日期和敏感字段 → 固化 artifact 哈希 → 发布。账户与策略报告必须明确区分建议、模拟和实际绩效。

## 业务规则

- 实际绩效只使用 execution_ledger 的成交、现金事件和估值；未成交建议不计收益。
- 回测、论文交易和实盘使用不同标签和数据源，禁止拼成一条无标记曲线。
- 基准、无风险利率、汇率、年化天数和费用口径随报告版本保存。
- 交易日缺失、账户未对账或输入 quality fail 时报告标 `DRAFT/INCOMPLETE`，不得作为正式决策材料。
- 图表数据与表格指标来自同一查询结果，不能各算一遍。
- 个股日频报告至少展示 SELECT/KEEP/EXIT 数量、候选稳定性和换手；ETF 报告展示日频门控、实际调仓日和现金状态。sleeve 贡献加交叉约束/现金项必须对账到组合结果。

## 失败、幂等与并发

输入未冻结、对账失败、指标非有限数或模板字段缺失均失败。相同输入生成相同指标和内容哈希；并发构建同一报告只保留一个有效 run。

## 可观测与安全

监控构建失败、陈旧报告、指标异常跳变、下钻断链和 artifact 哈希不符。账户号、成交明细和持仓按敏感级别脱敏或限制下载。

## 测试与验收

- 手算收益、最大回撤、换手、费用和汇率折算案例一致。
- 报告总持仓/现金与输入账户 snapshot 对账；差 1 元即 quality fail。
- 同一输入重跑指标和 artifact 哈希一致；源修订产生新 report_run。
- 任一展示指标均能通过 `ExplainMetric` 找到公式和输入引用。
- 双策略报告中 sleeve 收益、交易成本和换手贡献与组合总数可对账；禁止把两个独立回测收益简单相加冒充组合收益。

## 不做事项

不在模板中重算业务指标，不把报告值回写源模块，不对未对账数据标正式，不隐去模拟/实盘差异。
