# 10 事件驱动回测模块

## 目标与边界

用与生产策略相同的输入契约和市场规则，按事件顺序模拟信号、订单、成交、公司行动、现金与持仓，给出可复现且不含前视的正式回测结果。

向量化计算只可作为研究筛选器；正式策略评审不得以其替代事件驱动结果。

## 所有数据

- `backtest_definition`：`strategy_bundle`（ETF 择时 + 个股日频选股）、各自版本/参数/sleeve 预算、市场规则、成本/滑点、基准与评估方案。
- `backtest_run`：数据/universe 快照、代码版本、随机种子、窗口和状态。
- `simulation_event`：序号、市场时间、接收时间、类型、payload 版本和因果链。
- `sim_order` / `sim_fill` / `sim_ledger`：全部以 canonical `instrument_id` 关联的模拟订单、成交和账户流水。
- `backtest_snapshot`：每日现金、持仓、可卖量、净值、暴露。
- `backtest_metric` / `backtest_artifact`：指标、交易明细和报告引用。

同一 run 的事件序号严格递增；结果由输入内容哈希唯一标识。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `RunBacktest(definition, strategy_bundle, snapshots)` | 固定两策略、sleeve policy、数据/成分/规则/成本版本与随机种子 |
| Interface | `Strategy.on_market_event(context) -> target_candidates` | context 只暴露事件时点已知数据 |
| Interface | `BrokerSimulator.submit(order, submitted_at) -> order_id` | 最早下一可交易 bar 才有成交资格 |
| Query | `GetBacktestResult(run_id)` | 返回指标、事件/交易/快照引用和完整血缘 |
| Event | `BacktestCompleted` / `BacktestFailed` | 仅内部运营事件，不触发实盘信号 |

## 主流程与状态

`CREATED → VALIDATING → RUNNING → COMPLETED | FAILED | CANCELLED`。按 `(market_time, priority, sequence)` 排序：公司行动/结算 → 市场状态与 Bar → ETF 日频门控和个股日频选择分别运行 → 组合按 sleeve 合并 → 风控/净订单 → 撮合成交 → 账户更新 → 日终估值。优先级固定并版本化。

## 业务规则

- T 收盘后信号不能按 T 收盘成交；默认 T+1 下一可交易 bar。
- 撮合处理停牌、无量、涨跌停/一字板、限价触达、部分成交、整手、价格步长和容量上限。
- 费用按市场/日期版本化，覆盖佣金、最低佣金、印花税、平台费和滑点。
- A 股可卖数量按 T+1，港股通/ETF 规则独立配置；不以一个市场规则套全部资产。
- universe、财务和特征均按 decision_at 可见快照；退市证券保留在历史中并模拟处置政策。
- `strategy_bundle` 中两条首批策略都必须有独立 run、输入快照和绩效贡献；组合成交只能来自合并后的净订单，禁止把两个单策略成交序列简单相加。
- 绩效至少含收益、波动、Sharpe、Sortino、最大回撤、Calmar、换手、胜率、盈亏比、成本和容量敏感性。

## 失败、幂等与并发

输入快照不完整、未来数据访问、无市场规则或数值不守恒立即失败。相同输入和随机种子结果哈希一致；并行 run 隔离账户与事件流，不共享可变策略状态。

## 可观测与安全

监控事件吞吐、拒单原因、未成交率、现金/证券守恒、异常价格和运行资源；失败保留最后事件序号与可复现输入。

## 测试与验收

- 手算黄金场景覆盖次 bar 成交、最低佣金、卖出税、整手、部分成交、停牌、涨跌停和 T+1。
- 尝试读取未来 bar/公告必须抛错；历史结果在追加未来数据后不变。
- 同一 run 两次结果、交易和净值哈希一致；现金 + 证券 + 费用逐事件守恒。
- walk-forward 区间互斥，测试集只用于最终评估；成本翻倍和延迟敏感性可复跑。
- 双策略黄金回测证明 ETF 周度目标、ETF 日频退出、个股每日 SELECT/KEEP/EXIT、sleeve 合并和净订单事件顺序正确；报告能同时给出各 sleeve 与组合结果。

## 不做事项

第一阶段不模拟 Tick 队列位置，不支持卖空/融资/衍生品，不用捕获异常后沿用旧权重伪装成功。
