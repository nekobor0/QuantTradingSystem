你是执行者，本文是 backtest 模块唯一任务来源；换会话先读 `development/10-backtest/PROGRESS.md`。目标是交付可复现、无前视、纯多头的事件驱动正式回测，必须同时运行 ETF_TIMING 与 EQUITY_DAILY_SELECTION 两条独立策略，经 sleeve 合并后的净订单才可成交。冲突按“时点正确 > 事件/资金守恒 > 市场规则 > 可复现 > 指标完整 > 便利”处理。

## 冻结口径

- Run 状态 `CREATED→VALIDATING→RUNNING→COMPLETED|FAILED|CANCELLED`；事件按 `(market_time, priority, sequence)` 严格排序，priority 固定为公司行动/结算、市场状态/Bar、两策略决策、组合净额、订单、撮合、账户、估值。
- 输入固定 definition、双策略版本/参数、sleeve budget、数据/universe/rule/cost snapshot、起止时点、随机种子、代码版本；内容哈希相同则结果/事件/交易/NAV 哈希相同。各 run 不共享策略可变状态。
- StrategyContext 只能读取 `available_at<=decision_at` 的对象；任何未来 Bar/公告/universe/feature 访问立即 `LOOKAHEAD` 失败。追加未来数据不改变历史 run。
- 决策产生目标候选，不直接成交；两个 sleeve 先独立留痕，再按预算合并，同 instrument 买卖净额后生成订单。T 收盘信号最早 T+1 下一可交易 Bar；禁止当根成交。
- 撮合支持 canonical instrument_id、买卖、限价/市价、整手/价格步长、停牌、无量、涨停不可买/跌停不可卖、限价未触达、按 `max_participation*volume` 部分成交及剩余单；不模拟 Tick 排队。
- 规则按 market/date/version：T+1 可卖与 ETF/港股独立 settlement_days；费用含佣金/最低佣金/卖出税/平台费；滑点只进入成交价一次。现金、持仓、可卖量不得为负；每次 fill 后守恒。
- 日终 snapshot 含现金、持仓、可卖、NAV、sleeve 暴露；退市证券保留历史并按显式 policy 处置。指标至少 total/annual return、volatility、Sharpe、Sortino、max drawdown、Calmar、turnover、win rate、profit-loss ratio、cost；支持成本倍增和延迟敏感性重跑、互斥 walk-forward 窗口。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/backtest/**`、`migrations/010_backtest.sql`、`tests/backtest/**`、本文、`development/10-backtest/**`。
- 01–09、MvpSelect、模块规格、pyproject 只读；禁止联网、安装依赖、自动实盘下单。
- 开工实测：上游 `801 passed`、76 源码文件；10 规范 SHA256 `60214A0C9F4F27C63875BD4A6E153920A3244348F3F4042B0291A1C517935553`，完成时复核。
- MvpSelect 为向量化主引擎，订单原地 fill/reject，日志还记录滑点重复计算；仅可参考公式，禁止迁移其执行/组合状态。

## 任务 1：事件、时点与双策略

- 实现 Definition/Run/Event/Bar/MarketRule/CostRule/Target/Order/Fill/Ledger/Snapshot/Metric/Artifact 领域对象，InMemory 与 SQLAlchemy 仓储。
- 实现只读 StrategyContext；注册恰好两种 strategy callback，分别产生独立 run/candidate/event；ETF 支持周度目标+日频 EXIT，个股支持每日 SELECT/KEEP/EXIT；合并器输出 sleeve contribution 与净目标。
- 黄金序列证明 T 日决策、T+1 资格、公司行动/结算优先、双策略→合并→订单→fill→估值因果顺序。

## 任务 2：撮合、账户与结果

- BrokerSimulator 逐 Bar 处理 eligibility、市场状态、限价触达、lot/tick、容量、部分成交；显式 rejection/unfilled reason。BUY/SELL 费用与滑点手算一致，卖出受 settled_sellable 限制。
- 回测账户只由模拟 fill/公司行动/现金事件更新；日终估值和逐事件守恒校验失败即 run FAILED，保留最后序号与错误。
- GetBacktestResult 返回完整血缘、事件/交易/快照/指标/贡献和稳定 hash；实现 walk-forward 窗口校验与成本/延迟 sensitivity 派生 definition。

## 任务 3：存储与验收

- `010_backtest.sql` 与 SQLAlchemy 覆盖 definition/run/event/order/fill/ledger/snapshot/metric/artifact/sleeve contribution，含 run+sequence、输入 hash、外键、状态、版本约束和事务写。
- `tests/backtest` ≥120 passed、0 skipped；上游 801 仍绿；compileall、mypy 十模块、文档校验均 0。
- 正向必须覆盖：次 Bar、最低佣金、卖出税、滑点一次、整手/tick、部分成交、停牌/无量/涨跌停、T+1、限价、公司行动、双策略净额、指标、walk-forward、确定性、future append 稳定、并行隔离、SQLite 契约。
- 反向验证临时允许同 Bar 成交或未来读取，既有测试必须非 0；恢复后全绿。

## 纪律与完成条件

- 禁止向量化结果冒充正式结果、代码/名称作外键、捕获异常沿用旧目标、两个单策略成交相加、共享 run 状态、短仓/融资/衍生品、删改/skip/todo 测试、白名单外修改或 `|| true`。测试数只增不减。
- PostgreSQL live 缺口如实写 BLOCKED；每任务更新 PROGRESS。全量验收最多 3 轮，首轮全绿即停并贴证据。
