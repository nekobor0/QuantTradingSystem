你是执行者，本文件是 universe 模块唯一任务来源；换会话先读 `development/04-universe/PROGRESS.md`。目标是实现可按历史决策时点重放的证券池、行业分类与双策略独立快照，来源修订不能污染已冻结运行。冲突按“PIT/池用途隔离 > canonical identity > fail-closed > 可解释 > 便利”处理；不确定项记 BLOCKED 后继续无关工作。

## 冻结口径

- 只实现成员资格，不做信号、流动性/停牌过滤或账户决策；生命周期实时通过 InstrumentService 叠加，不删除历史成员事实。
- 成员区间统一 `[valid_from, valid_to)`；`announced_at/available_at` 为 aware UTC 且后者不早于前者。查询同时满足区间、`available_at <= decision_at` 和 instrument 当日生命周期。
- 批次为某生效日的完整名单；幂等键 `(universe_id, source_batch_id)`。空名单、未知证券、同日已发布不同内容、成员变化超过定义阈值均 fail-closed 并保留质量证据。
- `ETF_TIMING_POOL` 只接受 `ETF_DOMESTIC/ETF_OVERSEAS_LINKED`；`EQUITY_DAILY_POOL` 只接受 A_SHARE 与 HK_STOCK_CONNECT_ELIGIBLE_SECURITY。两个用途即使成员相同也必须产生不同 snapshot_id/hash 域。
- 行业分类键含 provider/system/version/level/code；不同体系不合并。staleness 以最新已发布批次 available_at 计算，超过 max_staleness_days 明确失败，不静默沿用。
- dataclass/SQLAlchemy Core；内存与 SQLite 跑相同契约，PostgreSQL DDL 单列；真实 PostgreSQL 留给 platform_operations。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/universe/**`、`migrations/004_universe.sql`、`tests/universe/**`、本文件、`development/04-universe/**`。
- 01–03 模块、既有 migrations/tests、MvpSelect、模块规格、pyproject 只读；禁止联网/装依赖/启动容器。
- 开工指纹：04 文档 `689E5F175B2616D5BB58D5C457039DEC553CBD1A9E174AF0BC383F21B6DB8686`；索引 `5E316...F35`；validator `BA66...8A3`；pyproject `59AFF...AA7`。
- 实测上游组合 `215 passed`；universe 0。MvpSelect 未发现可生产使用的历史成分名单，仅 1 个行业归因结果 parquet，不能反推成员历史。
- 复跑基线、指纹与上游只读 manifest；不一致置顶写 BLOCKED。

## 任务 1：定义、分类与批次

- 实现 UniverseDefinition、MembershipPeriod、ClassificationMembership、MembershipBatch、QualityResult、MembershipChangedEvent。
- ApplyMembershipBatch 必须用真实 InstrumentService 解析来源 code；全量名单差分为加入/移除，旧区间在新 effective_date 闭合，新成员开启；同一证券区间不得重叠。
- 公告与生效分离；未到 available_at 不可见，未到 valid_from 不生效。异常清空、超阈值变化和跨用途资产类型阻断发布。

## 任务 2：查询、解释与冻结

- GetMembers/ExplainMembership 必须显式 universe_id+decision_at；解释包含来源批次、区间、公告/可用时间、生命周期结果与排除理由。
- FreezeUniverseSnapshot 固化 universe_id、decision_at、data_snapshot_id、成员/标签、内容哈希和来源批次；后续批次不改变旧 snapshot。
- GetStrategyUniverse 分别冻结/读取 ETF_TIMING 与 EQUITY_DAILY；snapshot 身份与哈希加入 universe_id 域，严禁跨池复用。
- 分类查询必须指定 provider/system/version/level；同名 code 在两体系互不串值。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `004_universe.sql` 覆盖 definition/batch/membership/classification/quality/snapshot/event 的唯一、外键、半开区间和事务约束。
- universe ≥65 passed、0 skipped；上游 215 项仍绿；compileall、mypy 四模块、文档校验均 exit 0。
- 反向验证临时破坏 `available_at <= decision_at` 或池用途隔离，既有测试必须非 0，恢复后全绿。

## 纪律与完成条件

- 禁止当前名单回填历史、NULL/未到来源默认沿用、mock instruments 核心解析、ETF/个股池混用、删/skip/todo 测试、改白名单外文件或 `|| true`。测试数只增不减。
- PostgreSQL 缺口如实记录，不冒充 live 通过。每项完成即更新 PROGRESS；全量验收最多 3 轮，首轮全绿即停并贴证据。

