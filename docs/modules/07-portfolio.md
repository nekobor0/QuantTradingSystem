# 07 组合构建模块

## 目标与边界

把策略候选转为满足现金、集中度、市场、行业、流动性和纯多头约束的目标组合，并给出约束调整解释。

本模块不假定目标一定成交，不写实际持仓，不处理订单状态；实际账户快照来自 execution_ledger。

## 所有数据

- `portfolio_policy`：持仓数、单标的/行业/市场上限、现金下限、换手和缓冲规则版本。
- `portfolio_sleeve_policy`：`ETF_TIMING` 与 `EQUITY_DAILY_SELECTION` 的预算、现金归属、再平衡优先级和跨 sleeve 约束。
- `account_snapshot_ref`：构建时使用的实际持仓/现金快照引用，不复制事实。
- `target_portfolio`：`strategy_run_ids`、目标证券权重、现金权重、构建时间和内容哈希。
- `target_contribution`：每个 sleeve 对证券目标权重和现金的贡献，供解释与归因；不形成独立可下单组合。
- `constraint_result`：规则、调整前后值、是否 binding、原因和严重级别。
- `rebalance_delta`：当前权重到目标权重的理论差异，不是订单。

目标权重唯一键为 `(target_portfolio_id, instrument_id)`；证券权重加现金权重在容差内等于 1。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `BuildTargetPortfolio(strategy_run_ids, account_snapshot_id, policy_version)` | 幂等键含有序 run 集合、账户、总策略和 sleeve policy 哈希 |
| Query | `GetTargetPortfolio(id)` | 返回目标、现金、约束结果与未满足原因 |
| Query | `ExplainWeight(id, instrument_id)` | 返回策略原始权重和每步调整 |
| Query | `GetSleeveContributions(id)` | 返回 ETF/个股预算、目标贡献、被约束差额和现金贡献 |
| Event | `TargetPortfolioBuilt` / `TargetPortfolioRejected` | rejected 不得进入信号发布 |

## 主流程

读取冻结的 ETF 与个股 strategy run 和账户快照 → 分别在 sleeve 内应用资格与预算 → 合并同一 `instrument_id` 的连续目标贡献 → 对合并组合施加集中度/市场/行业/现金/换手约束 → 确定性归一化 → 输出唯一目标与逐 sleeve 解释。若任一必需 run 缺失或约束不可同时满足，拒绝而不是忽略某条策略或偷偷放宽。

## 业务规则

- 权重不得为负；SELL 仅表示从当前多头降至较低或零目标。
- 空仓是显式 `cash_weight=1` 的有效组合。
- 不可交易标的默认保持当前仓位并标 `FROZEN_POSITION`，不能假定按目标清零。
- 周频 ETF 在非调仓日保留目标；日频风险退出可按独立 policy 覆盖并留原因。
- 个股 sleeve 每日读取 `SELECT/KEEP/EXIT`，但只由目标权重变化产生调仓；`KEEP` 不重复加仓，`EXIT` 在不可交易时转为冻结持仓。
- sleeve 预算之和不得超过 1；两条策略对同一证券的贡献先合并成一个目标，再由 signals 生成一笔净建议，禁止各自下单。
- 整手和金额舍入属于 signals 的订单建议计算，组合层保留连续权重。
- 约束执行顺序固定并版本化，避免相同输入产生不同解。

## 失败、幂等与并发

账户快照过期、不可行约束、权重非有限数或策略 run 非 completed 均拒绝。相同输入输出哈希一致；新成交导致账户快照变化时必须新建目标组合。

## 可观测与安全

监控约束拒绝率、现金权重、预计换手、集中度、冻结持仓和目标偏移；策略原始意图与最终目标差异必须可解释。

## 测试与验收

- 纯多头、权重和、单标的/行业/市场上限的属性测试通过。
- 不可行约束返回 rejected，不调整阈值；相同输入顺序打乱后输出仍相同。
- 不可交易已有持仓被保留并产生冻结原因。
- 100% 现金、单一 ETF、满仓多资产和资金极小案例均有黄金结果。
- ETF 周度目标不变而个股日频候选变化时，只改变个股 sleeve；两策略对同一证券给出相反变化时，最终只有一个可解释净目标。
- 缺少任一声明为 required 的 strategy run 时构建必须 rejected，不能退化为单策略并标成功。

## 不做事项

不做券商成交模拟，不以整数股修改连续目标，不在这里批准风险例外。
