你是执行者，本文件是 instruments 模块唯一任务来源；中途没人可问，拿不准写 `development/01-instruments/BLOCKED.md`，跳过继续，最后一并提交。
换会话先读 `development/01-instruments/PROGRESS.md`，每完成一项立即更新，禁止重做。
这活要建立全系统唯一证券身份底座：代码会变、名称会重，但任何下游事实都能按时点稳定解析到 canonical `instrument_id`。
冲突时按“身份不串 > 时点正确 > 事务幂等 > 功能数量 > 速度”让步。
“只允许/不许”是硬约束；“建议”可替换但在 PROGRESS 记原因。

## 我替领导拍的板

- 领域模型用 dataclass + Enum，持久化用 SQLAlchemy Core（猜的）｜换框架只影响适配器，不改领域契约。
- `instrument_id` 用 UUID，日期区间统一 `[valid_from, valid_to)`，`valid_to=None` 表示开放（猜的）｜若口径不同需重做全部边界测试。
- 当前无 psql/驱动且 Docker daemon 不可用：SQLite 实跑仓储契约，PostgreSQL 专属排他约束用 DDL/编译测试；真实 PostgreSQL 连接验收由 platform_operations 补做（环境实测，不是假绿）。
- 本模块不引入 Web/API；对外只交付 Python 应用服务和仓储端口（猜的）。

## 界限

- 只允许改 `pyproject.toml`、`src/quant_trading_system/__init__.py`、`src/quant_trading_system/instruments/**`、`migrations/001_instruments.sql`、`tests/instruments/**`、`docs/development-goals/01-instruments.md`、`development/01-instruments/**`。
- `docs/modules/01-instruments.md`、`docs/modules/README.md`、`tools/validate_docs.py` 为判卷标准，SHA256 分别为 `9C4F7C2A461EB48FD46CB4A05D2A277A3E9C5A751C55B5BFAC645CDCBB3E1B42`、`5E3163873281659EF20881488CAC22833C5FBB05B23324D1E51A6D4A2B837F35`、`BA66E2B81190E071698FDEAC20957AFF8BE72F34592C2563C3856E801F64B8A3`，不许改。
- 不许改 MvpSelect、安装依赖、启动/拉取容器、实现行情/证券池/持仓、根据代码前缀猜板块；发现相邻问题写 BLOCKED。
- 不可逆删除或权限变更必须停下记录，继续其他项。

## 现状与任务 0

- 2026-07-28 实测：业务 Python/SQL/测试文件 0；Python 3.12.7、pytest 9.1.1、SQLAlchemy 2.0.34 可用；`pytest tests/instruments -q` 因目录不存在退出；文档验证三项 PASS。
- 先复跑 `python --version`、`python -m pytest --version`、`python tools/validate_docs.py`，并核对三份指纹。任一不符置顶写 BLOCKED，只做不受影响部分。
- 核对后把理解、顺序、最大风险写进不超过 10 行的模块 PROGRESS。

## 任务 1：领域契约和规则

- 实现 Instrument、Alias、TradingSpec、LifecyclePeriod、SourceRecord、错误码和仓储 Protocol；所有写入先验证再改变状态。
- 明确 CANDIDATE→LISTED→DELISTED、上市前/退市后不可交易、半开区间、Decimal 价格步长/正整数整手。
- 验收纳入最终 pytest；非法状态、重叠区间、无效数量/日期必须抛稳定领域错误。

## 任务 2：应用服务与幂等

- 实现 register、resolve、get_trading_spec、change_lifecycle；来源键 `(source, source_record_id, revision)` 重跑返回同一结果。
- 同一来源代码同一时点只解到一个 ID；显式登记 `600000.SH`、`sh.600000`、`600000` 可解到同一 ID；歧义/未知返回指定错误，禁止模糊猜测。

## 任务 3：持久化与验收

- 实现内存仓储和 SQLAlchemy 仓储，写 PostgreSQL DDL：唯一键、外键、审计字段、alias/spec 日期区间排他约束；数据库写操作事务化。
- `python -m pytest tests/instruments -q` 必须 ≥24 passed、0 failed、0 skipped；`python -m compileall -q src` 和 `python tools/validate_docs.py` 均退出 0。
- 反向验证：临时副本中移除一个状态/区间保护，跑对应测试必须非 0；恢复后全绿并贴红→绿输出。

## 规矩

- 不许 skip/todo、放宽断言、mock 被测领域对象、删测试、改文档判卷标准、`|| true`；测试数只许增加。
- 不新增依赖/流程/权限；必须加写 BLOCKED。同一验收连败 3 次换项；变差则还原自己改动并如实记录。

## 完成条件

- ≥24 个不跳过测试证明身份解析、生命周期、交易规格、幂等和两个仓储实现符合规格，反向 mutation 确实变红。
- 三份判卷指纹不变，MvpSelect 与白名单外改动为 0；真实 PostgreSQL 未跑必须在 BLOCKED 精确列环境缺口，不能声称已验证。
- 每条完成声明贴实际命令输出；BLOCKED 空也写“无”。最多 3 轮全量验收，满轮即停并报告剩余项。
