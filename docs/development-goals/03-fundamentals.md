你是执行者，本文件是 fundamentals 模块唯一任务来源；换会话先读 `development/03-fundamentals/PROGRESS.md`。目标是把来源公告转成可审计、可按 `decision_at` 重放的财务事实与股本变动，任何修订不得覆盖旧事实。冲突按“PIT 正确 > 原始事实与修订留存 > fail-closed > 查询便利 > 功能数量”处理。不确定项记 `BLOCKED.md` 后继续无关工作。

## 我替负责人冻结的口径

- 只实现已披露事实，不做预测、估值、因子评分或联网数据客户端；入口接收已解析公告和不可变 raw URI。
- `announced_at` 是市场披露时刻，`available_at` 是系统首次可用时刻，均为 aware UTC，且 `available_at >= announced_at`；缺任一时间的公告隔离，不能发布。
- period_type 只取 `INSTANT/QUARTER/YTD/TTM`。来源 YTD 可用同一 instrument/metric/年度相邻累计事实派生单季；TTM 仅在四个连续季度齐全时派生，派生事实保留 lineage，不猜缺失期。
- 金额统一存基础货币单位，百分比统一存小数；`scale` 显式转换，空值保持空值。metric_definition 固定 canonical unit、value_kind 与 source mapping。
- 查询 policy 只提供 `LATEST_AVAILABLE` 和显式 `SOURCE_PRIORITY`；两者都先过滤 `available_at <= decision_at`，再选修订，绝不按当前入库最新版回填历史。
- 使用 dataclass/Decimal/SQLAlchemy Core；内存与 SQLite 跑相同仓储契约，PostgreSQL DDL 单列。真实 PostgreSQL 留给 platform_operations 补验。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/fundamentals/**`、`migrations/003_fundamentals.sql`、`tests/fundamentals/**`、本文件和 `development/03-fundamentals/**`。
- `instruments`、`market_data`、既有 migrations/tests、MvpSelect、模块规格及 `pyproject.toml` 只读；禁止联网、装依赖、启动容器。
- 开工指纹：03 文档 `F42B97017B6AD362BCA469BAD9F06D421373BAE720D0247DEC735FC470D24315`；索引 `5E316...F35`；validator `BA66E...8A3`；pyproject `59AFF...AA7`。
- 实测 MvpSelect `fundamentals_baostock` 有 7 个 parquet、19,310 行，7 类 schema、8–12 列，公告字段名不统一；它只能作为迁移样本，不能直接 union 成生产事实。
- 基线为 instruments+market_data `135 passed`；fundamentals 0。复跑基线、指纹与只读树；不一致置顶写 BLOCKED。

## 任务 1：领域与发布门禁

- 实现 MetricDefinition/SourceMapping、Filing、FundamentalFact、ShareCapitalChange、QualityResult、RevisionEvent；所有证券只用 canonical `instrument_id`。
- `IngestFiling` 幂等键 `(source, source_filing_id, revision)`；相同键同内容返回原 filing，不同内容冲突。UNKNOWN_METRIC、INVALID_AVAILABILITY、UNIT_MISMATCH 必须留质量证据且不发布事实/事件。
- 新 revision 与旧 revision 并存，发布 `FundamentalRevisionPublished`，载明受影响 period/metric 和旧新 revision。

## 任务 2：PIT 查询与派生

- 实现 GetFacts/GetLatestKnownFact，必须显式 decision_at/policy；先过滤可见时间，再按 policy 和 revision 选择。
- 覆盖公告日前不可见、公告后可见；5 月修订不改变 4 月查询，6 月按 policy 可取修订。
- 黄金案例覆盖亿元/万元 scale、百分比、NULL、YTD→单季、连续四季→TTM、缺期拒绝和 lineage。

## 任务 3：存储与验收

- 内存/SQLAlchemy 仓储与 `003_fundamentals.sql` 覆盖 definition/mapping/filing/fact/share change/quality/event 的唯一、外键、检查和事务约束。
- fundamentals ≥60 passed、0 skipped；135 项上游仍绿；compileall、mypy 三模块、文档校验均 exit 0。
- 反向验证：临时破坏 `available_at <= decision_at` 或 revision 隔离，既有测试必须非 0，恢复后全绿。

## 纪律与完成条件

- 禁止 mock instruments 核心解析、覆盖旧 revision、用 period_end 代替可见时间、NULL→0、删/skip/todo 测试、改白名单外文件或用 `|| true`。测试数只增不减。
- PostgreSQL 不可用要如实记缺口，不得冒充通过。每完成一项立即更新 PROGRESS；全量验收最多 3 轮，首轮全绿即停并贴命令证据。

