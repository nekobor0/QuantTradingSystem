你是执行者，本文件是 strategies 模块唯一任务来源；换会话先读 `development/06-strategies/PROGRESS.md`。目标是在固定 PIT 快照上同时运行 ETF_TIMING 与 EQUITY_DAILY_SELECTION，输出隔离、不可变、可解释的候选目标，不下单、不读取账户。冲突按“快照/用途正确 > 明确现金门控与状态 > 可复现评分 > fail-closed > 候选数量”处理。

## 冻结口径

- 两类策略共享 RunStrategy 接口但 definition/version/run 状态完全分域。输入必须含 strategy kind、显式 decision_at、universe/feature/data snapshot ID+purpose+content hash、参数和可选前一 run；任何用途/成员/时点不一致即失败。
- ETF 首版：逐 ETF 通过 `momentum >= trend_min`、`volatility <= vol_max`、`max_drawdown >= drawdown_floor`、`liquidity >= liquidity_min`；按版本化 feature_weights 总分降序。周度调仓日取 top_n 等权；非调仓日仅保留前一 run 候选，风险门禁失败者 EXIT；无合格标的显式 `cash_gate=true`，不能用空列表暗示。
- 个股首版：对冻结特征值按 version feature_weights（权重和必须为 1）加权，资格标签必须全真；取 top_n 等权。相对前一交易日输出新入 SELECT、仍在 KEEP、退出 EXIT(weight=0)；KEEP 不代表买入。
- tie-break 固定 canonical instrument_id 字符串升序；所有权重 Decimal，候选原始权重和为 1 或 cash_gate 下为 0。策略层不做 sleeve 合并、账户差额或订单。
- 同一输入哈希幂等；参数、kind、任一 snapshot、前一 run 改变产生新 run。相同 kind+decision_at 已有不同 active run 必须显式 supersede，不静默覆盖。
- 失败写 FAILED/REJECTED 事件，绝不沿用旧结果并标 COMPLETED。ResearchEvidence 只保存 walk-forward/敏感性/成本翻倍/延迟一 bar/paper 引用，不参与生产评分。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/strategies/**`、`migrations/006_strategies.sql`、`tests/strategies/**`、本文件、`development/06-strategies/**`。
- 01–05、MvpSelect、模块规格、pyproject 只读；禁止联网/装依赖/容器。
- 开工基线前五模块 `375 passed`；strategies 0。06 文档指纹以开工实测为准并写 PROGRESS；索引/validator/pyproject 复核既有指纹。
- MvpSelect strategy_layer 有 17 个 Python 文件；存在缺值填 0、空结果成功和 IC 权重入口，不符合生产冻结要求，只参考显式排名/权重思想，不搬迁默认行为。
- 复跑测试、指纹和只读 manifest；不一致置顶写 BLOCKED。

## 任务 1：定义、状态与 ETF 策略

- 实现 StrategyDefinition/Version/Run/Score/Candidate/Contribution/ResearchEvidence/Event，状态机 `CREATED→INPUTS_FROZEN→RUNNING→COMPLETED|FAILED|REJECTED`，终态不可变。
- ETF 黄金案例覆盖日频门控、周度排名、非调仓保持、风险退出、全部现金、reason_codes、并列排序与等权；非调仓无前序 run 必须失败。

## 任务 2：个股策略与解释

- 个股黄金案例覆盖两日 SELECT/KEEP/EXIT、排名、逐因子贡献、等权、资格排除和空池失败。即使候选不变也生成当日独立 run。
- GetStrategyResult/ExplainCandidate/GetDailySelection 返回冻结证据；解释不得包含未来收益。ETF 与个股交换 snapshot/purpose 必须拒绝。
- 参数 schema 校验 top_n>0、权重和=1、阈值类型、rebalance_weekday 0–4、最低覆盖率；快照矩阵缺行/列不得缩小截面成功。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `006_strategies.sql` 覆盖 definition/version/run/score/candidate/contribution/evidence/event 的唯一、外键、状态和事务约束。
- strategies ≥85 passed、0 skipped；上游 375 项仍绿；compileall、mypy 六模块、文档校验均 0。
- 反向验证临时移除 kind/purpose 隔离或 cash_gate 明示保护，既有测试必须非 0，恢复后全绿。

## 纪律与完成条件

- 禁止下单/读账户、未来收益生产输入、动态 IC 权重、NULL→0、异常后成功、ETF/个股共用 run、删/skip/todo 测试、白名单外修改或 `|| true`。测试数只增不减。
- PostgreSQL live 缺口如实记录。每项完成即更新 PROGRESS；全量验收最多 3 轮，首轮全绿即停并贴证据。

