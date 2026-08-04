# 06 策略模块

## 目标与边界

在固定数据与特征快照上执行版本化策略，输出评分、择时状态和候选目标，不直接生成券商订单或修改账户。

首批闭环同时运行 `ETF_TIMING`（ETF 择时/轮动）与 `EQUITY_DAILY_SELECTION`（个股日频多因子选股信号）；二者共享公共策略接口，但输入快照、运行记录、调度频率和结果证据必须隔离。

## 所有数据

- `strategy_definition`：`strategy_kind`、策略目的、适用资产、决策/调仓频率、基准、负责人和失效条件。
- `strategy_version`：代码、参数 schema、默认参数、所需特征/证券池及状态。
- `strategy_run`：决策时间、版本、参数哈希、数据/特征/universe snapshot、运行状态。
- `strategy_score` / `strategy_candidate`：证券评分、排序、择时门控、建议原始权重和原因码。
- `research_evidence`：样本划分、walk-forward、敏感性和论文交易引用。

策略运行结果不可变；参数变化必须形成新 run。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `RunStrategy(strategy_version, decision_at, snapshots, parameters)` | 幂等键为版本、时间、snapshot 与参数哈希 |
| Query | `GetStrategyResult(strategy_run_id)` | 返回现金门控、候选、评分、原因和排除项 |
| Query | `ExplainCandidate(run_id, instrument_id)` | 返回因子贡献与过滤链，不暴露未来绩效 |
| Query | `GetDailySelection(run_id)` | 个股策略返回 `SELECT/KEEP/EXIT`、排名、原因和相对上日变化 |
| Event | `StrategyRunCompleted` / `StrategyRunFailed` | completed 不代表通过组合/风险约束 |

输出至少含 `instrument_id`, `raw_score`, `rank`, `proposed_weight`, `reason_codes`；可空仓时明确 `cash_gate`，不得用空结果暗示 100% 现金。

## 主流程与状态

`CREATED → INPUTS_FROZEN → RUNNING → COMPLETED | FAILED | REJECTED`。冻结输入后执行 eligibility 过滤、择时门控、评分/排序和原始权重。结果交 portfolio 模块处理账户与约束。

`ETF_TIMING`：冻结 point-in-time ETF 池 → 每日趋势/风险门控 → 横向排名 → 在周度调仓日应用缓冲并输出候选；非调仓日仅在版本化风险退出条件触发时改变目标。

`EQUITY_DAILY_SELECTION`：冻结当日个股池和因子矩阵 → 流动性/上市状态等资格过滤 → 横截面标准化及行业/市值约束后的多因子评分 → 与前一交易日候选比较 → 输出 `SELECT/KEEP/EXIT` 及原始建议权重。两个 run 分别完成后交 portfolio 以 sleeve 预算合并；策略层不净额、不生成订单。

## 业务规则

- 决策时点之后的数据、未来收益和最终退市名单不得作为输入。
- 训练、验证、测试、论文交易窗口互斥且记录；进入论文交易后参数冻结。
- 异常捕获不能退回上一期结果并标成功；若允许 fallback，状态必须为 `DEGRADED` 且信号层默认不发布。
- benchmark 是评估参照，不进入目标持仓，除非策略显式把它列为可交易 ETF。
- `strategy_kind` 是幂等输入；ETF 与个股策略不得共用可变运行状态。行业/市值中性化只属于明确版本的个股特征或策略步骤，不能偷偷塞进 ETF 策略。
- 个股日频结果即使候选不变也要产生可审计 run；`KEEP` 不等于再次买入，`EXIT` 只表达候选退出，实际卖出由组合差额决定。

## 失败、幂等与并发

快照不完整、证券池为空、参数非法、覆盖率不足均失败并给原因。相同输入重跑结果哈希一致；同一策略/decision_at 只允许一个 active run，替代运行显式 supersede。

## 可观测与安全

监控运行时长、候选数、换手预估、门控状态、分数分布漂移和连续失败；参数审批和版本启停保留审计。

## 测试与验收

- ETF 黄金案例给定固定输入，日频风险门控、周度排名、现金门控和原因码逐项一致。
- 个股黄金案例给定连续两个交易日输入，`SELECT/KEEP/EXIT`、排名、因子贡献和原始权重逐项一致。
- 同一 `decision_at` 两种 `strategy_kind` 生成独立 run；交换 universe/feature snapshot 必须失败。
- 未来数据追加不改变历史 run；重复运行结果哈希一致。
- 参数敏感性、成本翻倍、延迟一 bar 和样本外结果能关联到同一策略版本。
- 异常输入不会返回 `COMPLETED` 或静默沿用旧信号。

## 不做事项

不在本模块取“最新”数据库状态，不下单，不用回测测试集反复选参数，不自动提升研究策略为生产版本。
