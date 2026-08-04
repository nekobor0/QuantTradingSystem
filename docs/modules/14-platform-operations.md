# 14 平台运行模块

## 目标与边界

提供模块化单体的配置、批次、任务调度、事务 Outbox、审计、健康检查、备份和运行可观测能力，让任一失败都可发现、可重试且不产生重复业务事实。

本模块支撑业务模块但不拥有证券、行情、信号、订单或风险规则。

## 所有数据

- `dataset_batch`：来源、数据集、checksum、窗口、状态、质量摘要和发布时间。
- `task_run`：任务类型、业务日期、尝试次数、租约、开始/结束、状态和错误分类。
- `outbox_event`：事件 payload、schema version、提交时间、投递状态和尝试次数。
- `consumer_checkpoint`：消费者、event_id/offset 和处理状态。
- `audit_log`：操作者/服务、命令、对象、结果、correlation_id 和时间。
- `configuration_version`：非秘密配置、环境、生效区间和哈希；秘密只保存引用。
- 首批调度任务至少区分 `RUN_ETF_DAILY_GATE`、`RUN_ETF_SCHEDULED_REBALANCE`、`RUN_EQUITY_DAILY_SELECTION` 与 `BUILD_COMBINED_PORTFOLIO`，共享 `business_date`/`correlation_id` 但各有幂等键。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `StartTask(task_type, business_date, input_hash)` | 幂等键固定；返回既有或新 task_run |
| Command | `PublishOutbox(limit, lease_owner)` | 事务提交后投递；至少一次交付，消费者幂等 |
| Query | `GetOperationalReadiness(as_of)` | 聚合数据新鲜、任务、Outbox、备份和对账状态 |
| Query | `GetStrategyBundleReadiness(business_date)` | 两策略 required run、输入快照和组合构建必须全部成功 |
| Command | `RetryTask(task_run_id, expected_status)` | 只允许可重试错误且保留旧 attempt |
| Event | `TaskFailed` / `DataStaleDetected` / `BackupFailed` | 告警不得依赖已失败的同一通道作为唯一出口 |

## 主流程与状态

任务：`PENDING → RUNNING → SUCCEEDED | FAILED_RETRYABLE | FAILED_FINAL | CANCELLED`。调度器按交易日创建任务，获取有期限租约，调用应用服务；业务事务同时写事实与 Outbox；dispatcher 投递；消费者用 event_id 去重后更新 checkpoint。

第一阶段可用受控 worker；是否接 Prefect 由适配器决定。ETF 日频门控与个股日频选股可并行，但 `BUILD_COMBINED_PORTFOLIO` 必须等待两个 required run；ETF 周度调仓任务只在日历命中时运行。只有跨进程路由、确认和重试的实测需求出现才引入 RabbitMQ；Tick 高吞吐经基准证明后才评估 Kafka/Redpanda。

## 业务规则

- 配置按环境与版本加载，启动时校验；密钥仅来自环境/密钥服务，禁止入库和日志。
- 每日正式信号前必须通过 readiness：数据 published、质量 PASS、策略/风险成功、账户已对账、Outbox 无超龄积压。
- 重试复用业务幂等键，不用新 ID 掩盖重复；超过次数转 final 并告警。
- PostgreSQL 为生产事实库；Parquet raw 不可覆盖；备份必须定期做恢复演练。
- 结构化日志统一 correlation/causation，UTC 存储、界面按市场时区显示。
- 双策略中任一 required run 失败或陈旧时 bundle readiness 为失败，不能沿用上一日个股结果或省略一个 sleeve 后宣布成功。

## 失败、幂等与并发

租约超时可由新 worker 接管，但旧 worker 提交时须检查 fencing token。Outbox 至少一次投递，消费者重复事件无副作用。数据库不可用、备份失败、数据陈旧和事件积压都 fail closed，不宣布 readiness。

## 可观测与安全

指标覆盖任务成功率/延迟、数据新鲜度、Outbox age、数据库连接/容量、API 错误、备份年龄和告警投递。告警至少有独立备用路径或本地持久失败记录，避免“报警器坏了无人知道”。

## 测试与验收

- worker 在提交前/后崩溃两种案例均不丢事实、不重复业务效果，Outbox 最终投递。
- 重复事件消费两次结果不变；租约过期接管后旧 worker 无法覆盖新结果。
- 故意制造数据陈旧、Outbox 积压和备份失败，readiness 均非 PASS 且告警可见。
- 备份恢复到隔离环境后关键表计数/哈希和 schema 版本一致。
- 模拟 ETF run 成功、个股 run 失败和反向失败两种情况，组合任务均不启动且告警能指出具体 strategy_kind；两者成功时只启动一次组合任务。

## 不做事项

第一阶段不建 Kubernetes、高可用集群、Kafka、Redis 或 ClickHouse；无基准证据不新增基础设施。
