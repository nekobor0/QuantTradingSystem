你是执行者，本文件是当前 V6 执行切片的唯一任务来源；最高约束仍是`GOAL_V6.md`。中断先读`PROGRESS_V6.md`续跑，每完成一项立刻更新；拿不准写`BLOCKED_V6.md`并继续不受影响部分。目标是先把 V5 证据固化成不会漂移的 V6 平台，再登记并研究首个 Downside Beta 防御机制；同时只在版本化暂存区补 Tushare 历史。冲突时：无未来信息与数据完整性 > 冻结证据 > 可交易性 > 收益 > 速度。只有“只允许/禁止”是硬法，其余建议可替换但须记录原因。

## 我替领导拍的板

- 本轮主线范围是 V6 Phase 1 的五项基础设施和 Phase 2 首个 Downside Beta 家族；不同时开启基本面、反转、动量、行业轮动（GOAL 已拍板）。
- “完整风险模型”先定义为现有12项风格控制+申万一级行业+金融分组+覆盖/PIT/组合暴露接口，不冒充完整 Barra 协方差模型（按现有数据能力拍板）。
- Tushare“最早年份”按接口分别核实，不强行取一个共同年份；官网未写明时用当前账户轻量查询确认并标证据（猜错会造成假覆盖）。
- 补历史只写`artifacts/data_backfill_v6/**`，验收前不覆盖`artifacts/alpha_phase1/tushare/**`；V6 主线继续读取冻结 V5 快照，因此两线可并行。
- 同一 token 只允许一个下载进程，默认≤120次/分钟、2 workers（保守拍板）；磁盘当前可用约327GB。

## 界限

只允许新增/修改`src/quant_trading_system/research/v6/**`、`tests/research/v6/**`、`scripts/v6/**`、`development/16-alpha-factor-phase1/*V6*`、`artifacts/registrations/**`、`artifacts/data_audits/**`、`artifacts/evaluations/**`、`artifacts/live_shadow/**`、`artifacts/data_backfill_v6/**`。V5代码、既有Tushare文件和冻结产物只读。`GOAL_V6.md` SHA256必须保持`4030CA236BDC3931A380D6C8C91577827C9087326C4E666C19AB97136B68F48F`；无Git，所有冻结输入记录SHA256。禁止删数据、改权限、装依赖、写生产库。

## 现状与任务0

2026-07-31实测：研究测试57 passed/0 skipped，全仓1562 tests collected；三基线产物齐但无统一registry；27列V5风格面板含12控制，风险审计只覆盖9项；无增量评价器、研究层净额合并、实时影子。Python3.12、tushare已安装，本机配置有token。先复跑：
`python -m pytest tests/research/alpha_phase1 -q -p no:cacheprovider`
`python -m pytest --collect-only -q -p no:cacheprovider`
不符就写BLOCKED并停受影响项；一致后在PROGRESS写≤10行开工回执。

## 任务1：固化 V5 三基线

建立只读registry，登记P0/ICIR/24月回归的evaluation、monthly、holdings、capacity、双基准指标、2018-07/2023-07切分、T+1开盘、5bp及文件SHA256；`--check`遇文件、schema、行数、重复键、指标或hash漂移必须非0退出。故意篡改临时副本验证会变红，再还原全绿。不得重跑或改写V5结果。

## 任务2：Tushare历史审计与暂存补齐

复用本机skill及现有分片/限流/原子写入逻辑，生成接口级表：官网声明起点、API实测起点、本地起止、缺口、权限、预计请求/体量、主键。只对当前data层已有接口补齐；基础表/低成本数据优先，大表按接口独立断点。空响应必须区分无数据、非交易日、权限和失败；每个数据集有manifest、失败分片、重复/日期审计。发布到现有data层另立后续裁决，本轮禁止覆盖。

## 任务3：V6 Phase 1基础设施

按依赖顺序实现：12控制风险schema与暴露审计→统一增量评价（含Δ净超额/IR/TE/回撤/换手/DownsideBeta/相关性/重叠）→任意策略目标交易净额合并纯函数→append-only影子记录（重复拒绝、更正追加、代码/配置/数据hash）。每项先写失败测试；不得mock核心计算。

## 任务4：首轮 Downside Beta

结果前在`artifacts/registrations/`冻结机制、252日窗口/至少120日且仅市场负收益日、方向、股票池、成本、切分、最多1主候选+2稳健性变体和晋级门槛。保留raw/winsorized/standardized/neutralized信号；用防御评价器及加入24月回归后的边际评价，更新多重检验账本。不得同时研究其他防御家族或结果后改窗口。

## 规矩与完成条件

禁止skip/todo、删测试、放宽断言、mock核心、改V5阈值/切分/方向、覆盖影子历史或用`|| true`。同一验收连败3次换项；结果变差如实保留。完成本切片需：①三基线registry、四项Phase1接口和Downside Beta正式决策均可由固定命令复算；②Tushare现有接口历史审计完整且补齐任务可断点续跑、未覆盖旧数据。最终研究测试≥57、全仓tests collected≥1562、skipped=0；每条贴实际命令输出，`BLOCKED_V6.md`空也写“无”。
