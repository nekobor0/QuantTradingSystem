你是执行者，本文件是 market_data 模块唯一任务来源；不确定项写 `development/02-market-data/BLOCKED.md` 后继续，换会话先读模块 PROGRESS，每完成一项立即更新。
这活要把来源文件变成时点正确、质量过门、可按固定 snapshot 重放的 RAW/复权行情；新修订不能静默改变旧回测。
冲突按“原始事实不变 > 时点/快照正确 > 质量 fail-closed > 查询速度 > 功能数量”让步。
“只允许/不许”是硬约束；“建议”可替换但记 PROGRESS。

## 我替领导拍的板

- 本轮不联网写数据源客户端；入口接收不可变 raw 文件引用和源记录（猜的）｜避免免费源不稳定掩盖数据内核错误。
- 频率只实现 1d/1m；bar_end_at/available_at 存 UTC，trading_date 为交易所本地日（规格已定）。
- RAW 永不覆盖；factor 定义固定为累计后复权乘数：HFQ=RAW×factor，QFQ=RAW×factor/查询 snapshot 内最新 factor（猜的）｜口径变更需新 factor_version。
- 用 zoneinfo、Decimal、dataclass + SQLAlchemy Core；SQLite 跑仓储契约，PostgreSQL DDL验证专属唯一/事务约束（猜的）。真实 PostgreSQL 仍由 platform_operations 补验。
- snapshot 是已发布 batch 集合的不可变内容哈希；查询必须显式传 snapshot_id（猜的）。

## 界限

- 只允许改 `pyproject.toml`、`src/quant_trading_system/market_data/**`、`migrations/002_market_data.sql`、`tests/market_data/**`、`docs/development-goals/02-market-data.md`、`development/02-market-data/**`。
- 判卷标准不许改：`docs/modules/02-market-data.md`、`docs/modules/README.md`、`tools/validate_docs.py`、`pyproject.toml` 开工 SHA256 为 `7B5579D29C46BBD8E21D148C78EFEBE27624CB9DB24D3A3CB6253C65946AA27C`、`5E3163873281659EF20881488CAC22833C5FBB05B23324D1E51A6D4A2B837F35`、`BA66E2B81190E071698FDEAC20957AFF8BE72F34592C2563C3856E801F64B8A3`、`59AFF9743B20F7F00C193C1398D358F8B7BEDA89F1EC7589EADCF7E0219EA7AA`。
- instruments 实现/测试/DDL 全部只读，开工 manifest `7b1a05f3476dbb5c03019a8836419e7c9a35ac0cfb7ef04fade960fc3d02fd7e`。
- 不许改 MvpSelect、安装依赖、联网、启动容器、实现因子/策略、把缺量填 0、把调整价写回 RAW；相邻问题写 BLOCKED。

## 现状与任务 0

- 2026-07-28 实测：market_data 代码/测试 0；instruments `65 passed`；Python/pytest/SQLAlchemy 可用；PostgreSQL/Docker daemon 不可用；文档验证 PASS。
- 复跑 `python -B -m pytest tests/instruments -q -p no:cacheprovider`、`python tools/validate_docs.py` 与上述指纹/manifest；不符就置顶 BLOCKED，只做无关部分。
- 核对后把目标、顺序、最大风险写进 ≤10 行模块 PROGRESS。

## 任务 1：时间、事实与复权领域

- 实现交易 session（SSE/SZSE/BSE 用 Asia/Shanghai，HKEX 用 Asia/Hong_Kong）、1d/1m RAW Bar、公司行动、factor、市场状态、batch/snapshot/质量结果；Decimal 和半开时间区间。
- OHLC>0、high/low 包络、量额非负且缺失不等于 0；时间必须 aware UTC；证券只用 instrument_id。
- 复权查询不得改变 RAW 对象/哈希；factor 缺失、版本混用或 snapshot 外数据必须明确失败。

## 任务 2：采集门禁与固定快照

- 原始文件按 checksum 不可变登记；源 code 通过 instruments 在 trading_date 解析，手数按当日 TradingSpec 换股。
- 同批重复键、未来 bar、非交易日、错误 OHLC、未知代码是 hard fail：保存 batch+质量证据但不发布事实/事件；相同 `(source, checksum)` 重跑返回同一 batch。
- 通过门禁后事务写事实和 DatasetBatchPublished，生成不可变 snapshot；新 revision 发布后旧 snapshot 查询哈希不变。

## 任务 3：存储与验收

- 实现内存/SQLAlchemy 仓储和 `002_market_data.sql`：批次、session、bar、行动、factor、状态、质量、snapshot、事件及唯一/外键/检查约束。
- `python -B -m pytest tests/market_data -q -p no:cacheprovider` 必须 ≥50 passed、0 skipped；instruments 65 项仍绿；compileall、mypy 两模块、文档验证均 0。
- 反向验证：临时副本破坏 OHLC 或 snapshot 隔离保护，对应测试必须非 0；恢复后全绿。

## 规矩

- 不许 skip/todo、放宽判断、mock instruments 核心对象、删测试、改判卷文件、`|| true`；测试数只许增。
- 不新增依赖/权限；必须加写 BLOCKED。同一验收连败 3 次换项；变差则还原并如实记录。

## 完成条件

- ≥50 项无跳过测试证明时区、1d/1m、质量拒绝、幂等发布、RAW/QFQ/HFQ、旧 snapshot 不漂移和两仓储契约，mutation 变红。
- 判卷指纹与 instruments manifest 不变，MvpSelect/白名单外改动 0；真实 PostgreSQL 缺口不得冒充通过。
- 所有完成声明贴命令输出；BLOCKED 空也写“无”。最多 3 轮全量验收，满轮即停并报告剩余。
