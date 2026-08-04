你是执行者，本文件是 signals 模块唯一任务来源；换会话先读 `development/08-signals/PROGRESS.md`。目标是把唯一目标组合与 execution_ledger 账户证明冻结成可过期、可风控、可审批的人工订单建议；建议永远不是成交或实际持仓。冲突按“账本实际/可卖数量 > hard risk/对账/时效 > 方向和现金安全 > 目标逼近 > 订单数量”处理。

## 冻结口径

- CreateSignal 输入 TargetPortfolioInput、AccountExecutionInput、PricingSnapshot、双策略 SignalComponent、FeePolicy、decision_at/valid_for_date/expires_at。账户输入必须声明 `source=execution_ledger` 且含 snapshot_id/reconciled/nav/cash/实际与 settled_sellable 数量；禁止从旧建议推导。
- 每 instrument 只按合并目标与实际市值的净差额生成一条 recommendation。绝对差额低于 min_trade_value 或整手后为 0 不生成；SELL 先计算且不超过 settled_sellable，BUY 总成本不得超过 `cash + estimated sell proceeds - cash_buffer`。
- lot_size/tick_size 通过真实 InstrumentService 在 valid_for_date 获取；数量向下整手，限价 BUY 按 tick 向上、SELL 向下。费用固定 commission_rate/min_commission，SELL 加 stamp_duty；所有 Decimal。
- 信号默认 `DRAFT→RISK_CHECKED→PUBLISHED→EXPIRED|SUPERSEDED|CLOSED`。AttachRiskResult 只接不可变 risk_result_id+PASS/HARD_FAIL；Publish 要求 risk PASS、账户 reconciled、价格/数据未超 max_age、当前未过 expires_at。失败不能发布。
- 建议 `PENDING→APPROVED|PARTIALLY_APPROVED|REJECTED→HANDED_OFF`。审批追加不可变 ApprovalDecision；expected_version 乐观锁。部分接受必须 0<quantity<建议量且有理由；接受不可改方向/超过量；decision_id 重试幂等。
- 信号内容发布后不可编辑；价格偏离超过 reprice_threshold 标记 REPRICE_REQUIRED/过期。supersede 明确旧信号失效，新信号独立。
- ETF/个股 component 仅解释，贡献和需对账到 portfolio delta；同证券冲突先净额，只出一条建议。DailyDecisionBoard 同屏展示两个 run 的门控/SELECT/KEEP/EXIT 与净建议。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/signals/**`、`migrations/008_signals.sql`、`tests/signals/**`、本文件、`development/08-signals/**`。
- 01–07、MvpSelect、模块规格、pyproject 只读；禁止联网/装依赖/容器。
- 开工上游 `554 passed`、signals 0；08 文档 SHA256 `9220108D1259DBA5C17029D3D7E8A3050629AA00E4165C329492B4298D6D77E7`，其余保护指纹复核。
- 旧 MvpSelect 只有回测 execution/order，以 symbol、固定 lot_size 和自动成交为中心，不满足人工审批、canonical ID、账本引用和不可变建议，禁止搬迁。

## 任务 1：建议生成

- 实现 Signal/Component/Recommendation/RiskRef/Approval/Supersession/FeePolicy/Event 及输入 DTO；明确状态机、内容哈希和输入幂等。
- 黄金案例覆盖 BUY/SELL、整手、tick、佣金/印花税、卖出释放现金、现金不足拒绝、可卖上限、零意义订单消除、双 sleeve 净额与原始贡献对账。

## 任务 2：发布、审批与行动板

- AttachRiskResult/Publish/Expire/Supersede/Approve/HandOff 全部验证状态；hard risk、未对账、stale、过期均不可发布/行动。
- 审批覆盖接受/部分/拒绝、重复 decision_id、expected_version 冲突、方向边界和成交并发后的 remaining quantity。成交引用只能减少 remaining，不回写原建议。
- GetActionableRecommendations 只返 published、未过期/替代、已批准且 remaining>0；DecisionBoard 保留 ETF 与个股解释。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `008_signals.sql` 覆盖 signal/component/recommendation/risk/approval/supersession/event 的唯一、外键、状态、版本与事务约束。
- signals ≥95 passed、0 skipped；上游 554 项仍绿；compileall、mypy 八模块、文档校验均 0。
- 反向验证临时允许 SELL 超过 settled_sellable 或绕过 hard risk，既有测试必须非 0，恢复后全绿。

## 纪律与完成条件

- 禁止券商连接/自动下单、建议计入持仓绩效、用建议重建账户、反向审批、发布 hard risk、零股建议、删/skip/todo 测试、白名单外修改或 `|| true`。测试数只增不减。
- PostgreSQL live 缺口如实记录。每项完成更新 PROGRESS；全量验收最多 3 轮，首轮全绿即停并贴证据。

