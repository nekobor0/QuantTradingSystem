# /goal — 14 platform_operations

你是执行者。本任务书是 `platform_operations` 的唯一任务来源；断点续跑先读 `development/14-platform-operations/PROGRESS.md`。目标是交付单机日频模块化单体的运行底座：配置、数据批次、任务租约/fencing、双策略调度门、transactional outbox、幂等消费、审计、readiness、告警与备份恢复校验。平台只编排业务服务，不拥有证券、行情、信号、订单或风险事实。

## 冻结口径

- 首期采用 Python worker + PostgreSQL/TimescaleDB；不引入 Redis/RabbitMQ/Kafka/ClickHouse/InfluxDB/Kubernetes/Prefect。ETF daily gate 与个股日选可并行；ETF scheduled rebalance 仅日历到期运行；`BUILD_COMBINED_PORTFOLIO` 必须等待当日两个 required strategy run 成功，任一失败/陈旧即 fail closed。
- 任务幂等键=`task_type+business_date+input_hash`。状态为 PENDING→RUNNING→SUCCEEDED|FAILED_RETRYABLE|FAILED_FINAL|CANCELLED；有限租约可接管，但完成写入必须校验 fencing token，旧 worker 不得覆盖新结果。重试保留同一业务幂等身份和旧 attempt；超限转 final。
- 业务事实与 outbox 同事务写入。投递至少一次，发布租约可恢复；消费者以 consumer+event_id 去重，重复事件无副作用。事件含 event_id/type/occurred_at/recorded_at/correlation_id/causation_id/schema_version。
- readiness 同时检查：数据库、数据批次 PUBLISHED+PASS+新鲜、required tasks/bundle、风险成功、账户已对账、outbox 无超龄积压、备份最近成功且恢复演练未过期。数据库不可用、告警路径失败、备份失败均 fail closed，并保留本地持久失败记录。
- 配置按 environment/version/effective interval/hash 加载；秘密只保存环境变量名引用，配置/日志/审计不得存秘密。UTC 存储，市场时区只用于显示/日历决策。
- 修复发布依赖清单：声明 FastAPI/Pydantic/Streamlit 及 PostgreSQL driver；提供 `.env.example`、单机 compose、启动/迁移/健康/备份/恢复演练说明，但不得填真实密钥或将数据库暴露公网。

## 地界与任务

- 可修改：`src/quant_trading_system/platform_operations/**`、`migrations/014_platform_operations.sql`、`tests/platform_operations/**`、`deploy/**`、`scripts/ops/**`、`pyproject.toml`、本文件、`development/14-platform-operations/**`、根 `README.md/PROGRESS.md/BLOCKED.md`、`docs/modules/COMPLETION-AUDIT.md`。
- 01–13 模块代码/迁移/测试及 MvpSelect 只读；禁止联网安装依赖、直连券商、构建 HA/K8s、用 mock 冒充 PostgreSQL 恢复成功、`skip/todo`、`|| true`。
- 实现 domain/ports/service/in-memory/SQLAlchemy 双仓储与 014 DDL；实现任务开始、租约获取/续租、fenced 完成/失败/重试，双策略 bundle gate，outbox claim/publish/失败重试，幂等 consumer checkpoint，dataset/config/backup/alert 登记，readiness 聚合与结构化脱敏日志。
- 提供可注入 TaskHandler/EventTransport/HealthProbe/BackupRunner/AlertSink；业务调用仅走 ports。提供受控单次 worker/dispatcher 入口，崩溃前后重跑不得重复业务效果。
- 提供 PostgreSQL 生产配置与 SQLite 契约测试；Docker daemon/5432 当前不可用，真实容器、live PostgreSQL、pg_dump/restore 证据必须在 `BLOCKED.md` 标记为未完成，不得伪报。

## 防作弊验收

- 开工基线：`1346 passed`、115 源码文件；规范 SHA256 `5F14AA8324D2C5932421D373A64380C80AFACD58BEC8C0068B80F542F6B058B9`，验收后不漂移。
- `tests/platform_operations` 至少 120 passed、0 skipped；覆盖提交前/后崩溃、同 key 启动、租约过期接管和旧 token 拒写、可重试/最终失败、重复消费、outbox 最终投递、数据陈旧/积压/备份/数据库/告警失败、双策略正反失败与只建一次组合、配置秘密拒存、审计脱敏、SQLite 全契约、部署文件静态安全。
- 全量 pytest 仍绿；mypy、compileall、文档校验均为 0；依赖清单能生成 wheel，且 import smoke 覆盖 FastAPI/Streamlit/SQLAlchemy/PostgreSQL driver（若 driver 当前缺失，记录 BLOCKED，不能联网补装）。
- 反向验证：临时跳过 fencing token 或允许缺失 equity run 构建组合，既有测试必须非 0；恢复后全绿。
- 收尾更新模块 PROGRESS/BLOCKED、根 PROGRESS/BLOCKED 和 COMPLETION-AUDIT；最多三轮全量验收，首轮全绿即停止。
