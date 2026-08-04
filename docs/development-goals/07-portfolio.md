你是执行者，本文件是 portfolio 模块唯一任务来源；换会话先读 `development/07-portfolio/PROGRESS.md`。目标是把已完成的 ETF_TIMING 与 EQUITY_DAILY_SELECTION run 合成纯多头、现金明确、约束可解释的连续目标组合；它不是实际持仓也不是订单。冲突按“实际快照引用/冻结仓位 > 纯多头与权重守恒 > required 双策略 > 硬约束 > 策略原始意图”处理。

## 冻结口径

- 输入 StrategyRunTarget 只接 COMPLETED run，含 kind/run_id/decision_at/cash_gate/候选连续权重；AccountSnapshotInput 来自 execution_ledger，含 snapshot_id/as_of/current weights/cash/tradable/market/industry，不在本模块修改或复制账本事实。
- Policy 固定 ETF/equity sleeve budget、required kinds、min_cash、max_instrument、market/industry caps、max_turnover、account_max_age 和容差。预算和≤1；未分配预算归总现金。缺 required run、过期账户、非法权重、不可行约束一律 rejected。
- 固定求解顺序：校验/归一 sleeve → 按 budget 形成贡献 → 同 instrument 合并 → 不可交易持仓固定为 current weight → 单标的 cap → 市场 cap → 行业 cap → turnover blend → 为 min_cash 等比例缩放可交易风险资产 → residual 现金。每步写 ConstraintResult；不得静默调阈值。
- 冻结持仓不可被策略 EXIT 清零，写 FROZEN_POSITION；若冻结权重自身令现金/总权重不可行则拒绝。证券权重非负，证券+现金在 Decimal 容差内=1。
- sleeve contribution 保留原始 budget 权重、最终归因差额和现金贡献；同证券跨 sleeve 只生成一个 TargetWeight/RebalanceDelta。delta=current→target 只是理论差异，不做整手/金额舍入。
- 同一有序 run 集、账户 snapshot、policy+sleeve hash 幂等；输入顺序先 canonical 排序，乱序不改变 ID/hash。账户 snapshot 改变必须新建目标。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/portfolio/**`、`migrations/007_portfolio.sql`、`tests/portfolio/**`、本文件、`development/07-portfolio/**`。
- 01–06、MvpSelect、模块规格、pyproject 只读；禁止联网/装依赖/容器。
- 开工：上游 `468 passed`，portfolio 0；07 文档 SHA256 `DB6C816956F75DD8E416723A20814CE0F07C8CA7874820A138899B4CF24A540B`，其余保护指纹复核既有值。
- 实测旧 MvpSelect 仅有策略内简单等权/裁剪与回测 portfolio，未见双 sleeve、冻结实盘仓位或约束证据，禁止复用为生产组合器。

## 任务 1：输入、sleeve 与现金

- 实现 PortfolioPolicy/SleevePolicy/StrategyRunTarget/AccountSnapshotInput/TargetPortfolio/TargetWeight/TargetContribution/ConstraintResult/RebalanceDelta/Event。
- 双策略黄金案例覆盖预算贡献、重叠证券合并、一个 sleeve cash_gate、100% 现金、单 ETF、满仓多资产、极小账户权重语义；缺任一 required run 必须拒绝。

## 任务 2：约束与解释

- 覆盖单标的、市场、行业、min cash、turnover 的固定顺序；每步记录 before/after/binding/reason/severity。输入乱序结果 hash 相同。
- 不可交易已有持仓保持并写 FROZEN_POSITION；KEEP 不重复加仓，EXIT 只通过目标差额体现。ExplainWeight/GetSleeveContributions 返回原始贡献、每步调整和最终 delta。
- 约束不可行返回 TargetPortfolioRejected 事件，不保存可发布 target。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `007_portfolio.sql` 覆盖 policy/sleeve/target/weight/contribution/constraint/delta/event 的唯一、外键、范围、事务约束。
- portfolio ≥85 passed、0 skipped；上游 468 项仍绿；compileall、mypy 七模块、文档校验均 0。
- 反向验证临时允许负权重或移除 required 双 run 门禁，既有测试必须非 0，恢复后全绿。

## 纪律与完成条件

- 禁止写实际持仓/订单、整数股舍入、单策略降级成功、负权重、忽略冻结仓位、放宽阈值、删/skip/todo 测试、白名单外修改或 `|| true`。测试数只增不减。
- PostgreSQL live 缺口如实记录。每项完成更新 PROGRESS；全量验收最多 3 轮，首轮全绿即停并贴证据。

