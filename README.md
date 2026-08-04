# Quant Trading System

面向单账户、纯多头、最高日频的半自动量化交易系统。覆盖 A 股、港股通和境内场内 ETF；系统生成信号与净交易建议，用户手工执行并回填订单、成交和券商日结。

## 当前实现

系统采用 Python 模块化单体与 PostgreSQL/TimescaleDB 目标架构，已经实现 14 个模块：证券主数据、行情、基本面、证券池、特征、ETF 择时与个股日选、组合构建、信号、执行台账、事件驱动回测、风控、报告、API/UI 和平台运行。

关键边界：

- 两条策略独立冻结输入和运行，在组合层合并后，每个证券只生成一条净建议。
- 实际持仓只由成交和资金事件派生；建议和审批不等于成交。
- 基本面、成分、特征与回测均执行 point-in-time 约束；模拟成交最早为下一可交易 bar。
- 平台使用 PostgreSQL transactional outbox、任务租约和 fencing token；首期不引入 Kafka、RabbitMQ、Redis 或 ClickHouse。

## 验证

```powershell
python -m pytest -q
python -m mypy src\quant_trading_system
python -m compileall -q src\quant_trading_system
python tools\validate_docs.py
docker compose -f deploy\compose.yaml config --quiet
```

本地最终证据：1486 项测试通过、0 skipped，mypy 检查 125 个源码文件成功，文档与 Compose 配置校验通过。真实 PostgreSQL、容器启动、备份恢复以及生产适配器仍需在外部环境完成，详见 [BLOCKED.md](BLOCKED.md)。

## 入口

- [对齐后的系统目标](docs/00-aligned-goal.md)
- [模块开发索引](docs/modules/README.md)
- [模块实现验收](docs/modules/COMPLETION-AUDIT.md)
- [部署与运维说明](deploy/OPERATIONS.md)
- [当前进度](PROGRESS.md)
