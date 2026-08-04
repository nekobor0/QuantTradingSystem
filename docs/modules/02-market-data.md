# 02 市场数据模块

## 目标与边界

采集、标准化和发布交易日历、未复权 Bar、公司行动与复权因子，为研究、回测和每日决策提供可追溯的时间序列快照。

本模块不计算策略因子，不决定证券池，不用后复权价格覆盖原始行情，也不把免费源的“最新值”静默回填历史。

## 所有数据

- `exchange_calendar` / `trading_session`：交易所本地交易日、开闭市和特殊时段。
- `bar`：`instrument_id`, `frequency`, `bar_end_at`, 未复权 OHLC、股数成交量、成交额、币种、来源、批次。
- `corporate_action`：事件类型、公告/除权/支付日期、现金或比例、`available_at`。
- `adjustment_factor`：因子值、方向、基准日、算法版本和来源。
- `market_status`：停牌、复牌及可验证的特殊交易状态。
- `data_quality_result`：批次规则、严重级别、观测值与判定。

事实唯一键为 `(instrument_id, frequency, bar_end_at, source, revision)`；“首选源视图”是派生结果，不能删除其他来源。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `IngestMarketBatch(source, dataset_ref, checksum)` | 幂等键 `(source, checksum)`；先原始落盘后标准化 |
| Query | `GetBars(ids, start, end, frequency, price_mode, snapshot_id)` | `price_mode` 为 RAW/QFQ/HFQ；必须固定快照 |
| Query | `GetTradableSession(exchange, local_date)` | 返回交易所本地时段及 UTC 边界 |
| Query | `GetMarketStatus(instrument_id, as_of)` | 不把缺失记录自动解释为可交易 |
| Event | `DatasetBatchPublished` / `CorporateActionPublished` | 仅质量门禁通过后发布 |

## 主流程

源响应不可变落 Parquet raw 区 → 登记哈希与许可 → 标准化代码/单位/时区 → 暂存表 → 唯一性、完整性、OHLC、范围、跨源和时效检查 → 事务合并 → 发布快照与 Outbox 事件。Hard fail 批次保留证据但不进入 published 视图。

复权序列按未复权 Bar + 指定版本因子即时或物化生成。HFQ 的基准、方向和版本必须进入响应元数据，防止不同源同名不同义。

## 业务规则

- `bar_end_at` 存 UTC，`trading_date` 按交易所本地日派生；A 股与港股日历不能互相代替。
- 成交量统一为股，源为手时显式换算并保留原单位。
- 缺失量/额先分类停牌、未上市、休市或源缺失；禁止无条件填 0。
- 日线策略默认 T 收盘后可用，信号不得在 T 收盘价回填成交。
- 源优先级版本化；跨源冲突保留双方值和裁决理由。

## 失败、幂等与并发

校验失败返回批次状态 `REJECTED`；部分源超时可标 `INCOMPLETE`，但不得发布。相同 checksum 重跑复用原批次；不同修订生成新版本。每个来源/交易日只允许一个活动采集租约。

## 可观测与安全

监控最新交易日、覆盖证券数、缺口、重复键、跨源偏差、复权跳变和任务耗时；源许可与凭证不写日志。

## 测试与验收

- 故意注入 `high < close`、重复键和未来时间，批次必须拒绝并产生质量记录。
- 拆分/分红黄金案例能由 RAW + 因子重建预期 HFQ，且 RAW 哈希不变。
- 同一批次重跑行数不增加；同一查询固定 snapshot 结果不随新修订变化。
- A 股与港股节假日、时区边界和 1d/1m 唯一键测试通过。

## 不做事项

第一阶段不接 Tick 流，不承诺免费源 SLA，不实现 Kafka，也不把 Parquet 目录直接暴露给生产策略。
