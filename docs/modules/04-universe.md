# 04 证券池模块

## 目标与边界

管理港股通、指数、行业、板块和策略基础池的 point-in-time 成员关系，回答“在某个决策时点哪些证券有资格参与”。

本模块不判断账户是否应买入，不保存证券身份，不因今天已退市而从历史池删除。

## 所有数据

- `universe_definition`：证券池类型、来源、用途、版本和规则描述。
- `universe_membership`：`universe_id`, `instrument_id`, `[valid_from, valid_to)`, `announced_at`, `available_at`, 来源。
- `classification_membership`：行业分类体系、层级、代码和生效区间。
- `universe_snapshot`：决策时点、成员哈希、来源批次和排除原因。
- 首批生产池分别登记为 `ETF_TIMING_POOL` 与 `EQUITY_DAILY_POOL`；两者不可复用同一个 snapshot ID，即使成员偶然相同。

同一证券在同一 universe 的有效区间不得重叠；不同分类体系可以并存，查询必须指定体系版本。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `ApplyMembershipBatch(universe_id, source_batch)` | 幂等键 `(universe_id, source_batch_id)`；差分后生效 |
| Query | `GetMembers(universe_id, decision_at)` | 同时满足有效区间与 `available_at <= decision_at` |
| Query | `ExplainMembership(universe_id, instrument_id, decision_at)` | 返回纳入/排除依据和来源 |
| Command | `FreezeUniverseSnapshot(universe_id, decision_at, data_snapshot_id)` | 返回不可变成员哈希 |
| Query | `GetStrategyUniverse(strategy_kind, decision_at)` | ETF 与个股策略返回各自 snapshot、资格口径和陈旧度 |
| Event | `UniverseMembershipChanged` | 列出加入/移除、生效与可用时间 |

## 主流程

接收来源全量或差分名单 → 解析证券 ID → 对比上一已发布版本 → 生成带生效区间的加入/移除 → 检查未知证券、区间重叠和异常大幅变化 → 发布成员事件。策略运行前冻结 snapshot，之后来源修订不改变该次运行。

首批双策略在同一 `decision_at` 分别冻结：`ETF_TIMING_POOL` 仅含允许交易的境内行业/海外相关场内 ETF；`EQUITY_DAILY_POOL` 覆盖 A 股四类板块及当日有效港股通资格证券，并保留上市时间、ST/退市整理等资格标签供策略和风控解释。

## 业务规则

- 港股通资格必须按交易日保存，不得用当前名单回测历史。
- 行业分类必须指明供应方、层级和版本；跨体系名称相同不代表同一分类。
- 上市/退市生命周期由 instruments 提供；本模块只给成员资格，两者共同决定基础可研究池。
- 停牌、涨跌停和流动性是策略/风险过滤，不改写历史成员关系。
- 来源未到不能默认“沿用”或“全清空”；沿用策略必须显式配置最大陈旧天数。
- ETF 池的周度调仓节奏不改变成员事实；个股池每日冻结，某日名单缺失不得退回使用今天的全量名单。

## 失败、幂等与并发

未知证券进入 `UNRESOLVED_MEMBER` 隔离；重叠区间和异常成员变化阻断发布。重复批次返回原 snapshot。每个 universe 同一生效日只允许一个已发布版本，修订生成新 revision。

## 可观测与安全

监控成员数、日变化率、未知映射、来源陈旧度和无有效行业分类比例；港股通名单逾期必须产生 hard alert。

## 测试与验收

- 已退市证券在退市前历史 snapshot 中仍存在，退市后由生命周期过滤。
- 港股通调入公告与生效时间不同的案例，在正确 decision_at 才可见。
- 同一日期重复导入成员哈希不变；异常清空名单被门禁拒绝。
- 两套行业体系可并存且查询不串值。
- 同一交易日能生成两个不同用途的 snapshot；把 ETF 放入 `EQUITY_DAILY_POOL` 或把普通个股放入 `ETF_TIMING_POOL` 时门禁失败。

## 不做事项

不做信号评分，不用当前成分替代历史成分，不把临时风险过滤永久写成成员移除。
