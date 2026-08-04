# 15 · TdxQuant 历史行情桥接任务书

你是执行者，本文件是本功能唯一任务来源；中途拿不准的事项写入 `development/15-tdx-bridge/BLOCKED.md`，继续做不受影响的部分。断线后先读 `development/15-tdx-bridge/PROGRESS.md`，不要重做。目标是让通达信历史日线可追溯、幂等地进入现有市场数据层。冲突时按“数据正确 > 失败可见 > 功能完整 > 速度”排序。“只允许/不许”是硬约束，其余建议可调整并在进度记录原因。

## 我替领导拍的板

- 验收证券 → `600000.SH`（猜的）｜若领导想验全市场，运行量会显著扩大。
- 接入方式 → 官方本机 HTTP `127.0.0.1:17709`（猜的）｜隔离专有 DLL，桥接脚本可独立运行。
- 入库价格 → `dividend_type=none`、`fill_data=false`（猜的）｜不把查询窗口相关的复权价或填充值写成事实。
- 成交量 → 默认按股；成交额从通达信“万元”乘 10000 转为元（猜的）｜正式扩面前须交叉验证单位。
- 增量口径 → 每次显式传一个交易日；缺数硬失败（猜的）｜不将休市/接口故障静默记为成功。
- 不自动创建证券主数据或执行数据库迁移（猜的）｜缺别名/表结构时明确失败，避免污染生产主数据。

## 界限

只允许新增或修改：`src/quant_trading_system/tdx_bridge/**`、`scripts/tdx_bridge.py`、`tests/tdx_bridge/**`、`docs/integrations/tdx-bridge.md`、本文件、`development/15-tdx-bridge/**`、根 `PROGRESS.md` 与 `BLOCKED.md` 中本功能条目。现有迁移、市场数据/证券主数据实现和既有测试为冻结区，不许修改。不接实时行情、交易函数，不安装数据库或通达信客户端，不用本地 `.day` 二进制文件绕过 TQ 接口。

## 现状与任务 0

2026-07-28 实测：基线 `1486 passed in 9.21s`、0 skipped；`TdxW.exe` 已运行于 `D:\TDX`，但没有 `PYPlugins`/`tqcenter.py`，17709 未监听；5432 未监听，Python 3.12.7 无 `psycopg`，无 `QTS_DATABASE_URL`。先复核这些数字并把目标、顺序、最大风险用不超过 10 行写入进度；关键数字不符时记录证据，继续不受影响的实现。

## 任务

1. 实现仅负责历史/增量日线的 HTTP 客户端：请求必须固定 `period=1d`、`count=-1`、`dividend_type=none`、`fill_data=false`；网络、协议、空响应必须非零退出且不得发布空批次。
2. 将响应规范化为现有 `RawBarInput`，原始 JSON 先进入 `RawFileStore`，再经 `MarketDataService` 质量门禁和 `SqlAlchemyMarketDataRepository` 发布；复用 `(source, checksum)` 幂等语义，数据库 URL 只从参数或 `QTS_DATABASE_URL` 获取且不打印。
3. 提供独立 CLI：`backfill` 接起止日，`incremental` 接单日，`verify` 查询实际落库日期数；数据库表或 `tdx` 证券别名缺失必须明确失败。
4. 单测覆盖官方 HTTP 形状、单位/时区转换、幂等重跑、坏 OHLC、空响应和增量单日；故意把 `fill_data` 变成 true，测试必须红，恢复后全绿。
5. 运行 `python scripts/tdx_bridge.py backfill --symbols 600000.SH --start 2024-01-01 --end 2024-01-31`，随后 `verify` 应得到 22 个交易日。真实前提缺失时必须贴原始失败输出并写 `BLOCKED.md`，不得以 fake/mock/手工 SQL 冒充。

## 规矩

不许 skip/todo、删测试、放宽断言、mock 真实验收、修改既有判卷文件或用 `|| true`。测试总数不得低于 1486，skipped 必须为 0。同一验收连续失败 3 次就停并换项；结果比基线差则撤回本功能改动并如实记录。外部前提不具备不是假成功的理由，也不是破坏边界的授权。

## 完成条件

- 新增测试与原 1486 项全部通过、0 skipped；mypy、compileall、文档校验保持通过，并提供 `fill_data=true` 红→恢复绿证据。
- 真实 TQ + PostgreSQL 环境中，独立脚本发布 `600000.SH` 的 2024-01 日线，`verify` 返回 22 个不同交易日且重跑不增行；或已完成实现并以原始输出证明外部前提阻塞，绝不声称已落库。

每条都要保留实际命令输出。`BLOCKED.md` 随交付提交，空也写“无”。
