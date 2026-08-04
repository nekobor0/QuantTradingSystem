# 03 基本面模块

## 目标与边界

保存可按历史时点查询的财务事实、估值原料和股本变动，使策略只能看到决策时已经公开的信息，并能重现当时使用的修订版本。

本模块不直接计算选股分数，不持有行情收盘价，也不以今天下载到的最新版替换历史可见版本。

## 所有数据

- `metric_definition`：标准字段、含义、单位、累计/单季口径和来源映射。
- `filing`：证券、报告期、报告类型、公告时间、实际可用时间、修订号、来源。
- `fundamental_fact`：`filing_id`, `metric_id`, 数值、单位、币种、原始值。
- `share_capital_change`：生效日期、总股本/流通股本及来源。
- `fundamental_quality_result`：平衡关系、单位、累计/单季转换和跨源差异。

事实唯一键为 `(instrument_id, metric_id, period_end, period_type, source, revision)`；不同公告修订并存。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `IngestFiling(source, source_filing_id, batch_id)` | 幂等键含来源公告 ID 与 revision |
| Query | `GetFacts(ids, metrics, periods, decision_at, policy)` | 只返回 `available_at <= decision_at`；policy 指定来源/修订选择 |
| Query | `GetLatestKnownFact(id, metric, decision_at)` | “最新”相对 decision_at，不是系统当前时间 |
| Event | `FundamentalRevisionPublished` | 包含受影响期间、指标和旧/新修订 |

## 主流程

保存原始公告/响应 → 解析报告期和公告时间 → 映射字段与单位 → 分离累计值、单季值和 TTM → 运行会计关系与跨源检查 → 发布可查询修订。无法确定公告时间的数据进入隔离区，不得用于 point-in-time 回测。

## 业务规则

- `announced_at` 是市场公告时刻，`available_at` 是系统可使用时刻；后者不得早于前者。
- 报告期、公告日和入库日必须分列；禁止用报告期作为可用时间。
- 百分比存小数，金额保留币种和单位缩放；空值不转换成 0。
- 估值比率优先由同一时点可见财务事实和市场价格派生，外部现成比率须标来源口径。
- restatement 不覆盖旧 revision；历史回测按当时可见 revision，当前报告可选最新修订。

## 失败、幂等与并发

字段无法映射为 `UNKNOWN_METRIC`，时间倒置为 `INVALID_AVAILABILITY`，单位冲突为 `UNIT_MISMATCH`。同一公告重跑不新增事实；新修订以新 revision 写入并触发受影响特征重算请求。

## 可观测与安全

监控公告延迟、映射覆盖率、未知字段、修订率、空值率、单位异常和跨源偏差。原始财报保持不可变并记录许可。

## 测试与验收

- 某报告 4 月 30 日公告：4 月 29 日查询不可见，4 月 30 日可见。
- 5 月修订后，4 月历史快照仍返回旧值，6 月查询按策略返回新值。
- 累计/单季/TTM 黄金案例与手算一致；百分比和亿元单位转换正确。
- 缺 announcement/available 时间的记录不能进入 published 快照。

## 不做事项

不做财务预测，不猜测缺失公告时间，不在本模块做行业中性化或因子打分。
