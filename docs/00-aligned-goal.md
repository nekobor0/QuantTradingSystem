你是执行者，这份文档是唯一任务来源；中途没人可问，拿不准的写进 `BLOCKED.md`，跳过继续做别的，最后一并提交。
断了或换会话先读 `PROGRESS.md` 接着做；每完成一项立刻更新，禁止重做已完成项。
这活要把顶层设计变成可直接指导编码和测试的模块规格，使不同模块不会重复持有事实、错用未来数据或在人工执行处断链。
冲突时按“时点正确与账户安全 > 契约一致 > 覆盖完整 > 文档篇幅”让步。
“只允许/不许”是硬约束；“建议”可替换，但须在 `PROGRESS.md` 记原因。

## 我替领导拍的板

- 首条闭环 → ETF 择时和个股日频选股信号；两条策略共享账户、组合、风控与执行闭环，但分别保留运行、贡献和验收证据。
- 本轮产物 → 只写开发规格，不写业务代码/数据库迁移。
- 模块范围 → 架构中的 12 个业务模块 + API/前端 + 平台运行，共 14 份。
- 调度 → 文档定义抽象任务接口，暂不替 Prefect/自有 worker 二选一。
- 文风验收只能半自动：机器检查结构与链接，领导抽查契约是否够开发者落地。

## 界限

- 只允许新建/修改 `QuantTradingSystem/docs/00-aligned-goal.md`、`docs/modules/**`、`tools/validate_docs.py`、`README.md`、`PROGRESS.md`、`BLOCKED.md`；其他路径只读。
- `docs/01` 至 `05` 是上位判卷规格，不许修改。开工 SHA256 依次为 `F023BAB4BC20674C880B120A042339C377B376A26128035BAF29A62A677D64AD`、`2DAB6CA2F3F5A4A7908069D2FA9F6CA9A1CCCD6153EC4CAB1EC2E96D8A113537`、`355398E2E50F49A195A980AA82DDDFE6A732646739EE516586113AB3E40A195D`、`72EE57113CD2253CA891C892551D73DE91FFF938EF5A6718798B0322121FD85D`、`071FF400C125D4C2D0CEC9B8AE7040565A6CD1EE435F193DC0886F5C931A625E`，交付须一致。
- 不许改 `MvpSelect`、安装依赖、联网取数、创建数据库、补业务代码；发现顺手可修问题写入 `BLOCKED.md`。
- 删除数据、改权限等不可逆操作必须停下记录，继续不受影响部分。

## 现状与任务 0

- 2026-07-28 实测：5 份上位文档；架构表列 12 个业务模块；当前模块开发文档为 0。
- 数据审计实测：2,916 文件、37,275,041,547 bytes、79 种 Parquet schema；这些数字只能引用，不能扩大解释。
- 先运行 `python tools/audit_mvpselect.py --help` 和 `rg -n "^## 4. 模块边界" docs/02-architecture.md`。命令不存在或数字不符，证据置顶写入 `BLOCKED.md`，只做不受影响部分。
- 核对后把目标、顺序、最大风险写入不超过 10 行的 `PROGRESS.md`。

## 任务 1：冻结模块地图和统一规格

- 新建 `docs/modules/README.md`，列全 14 个模块、唯一事实所有者、依赖方向和跨模块事件。
- 每份模块文档必须有：目标与边界、所有数据、接口契约、主流程/状态机、业务规则、失败与幂等、可观测与安全、测试与验收、不做事项。
- 接口必须写输入、输出、时间语义、幂等键或唯一键；否则无法据此实现，算未完成。

## 任务 2：完成 14 份模块开发文档

- 依次写 instruments、market_data、fundamentals、universe、features、strategies、portfolio、signals、execution_ledger、backtest、risk、reporting、api_ui、platform_operations。
- 所有证券引用 canonical `instrument_id`；财务/成分按 `available_at <= decision_at`；实际持仓只由 fill/资金事件派生；回测订单最早下一可交易 bar 成交。
- 首批策略同时覆盖 ETF 择时/轮动与个股日频多因子选股；ETF 可按周调仓但风险门控日频运行，个股每日生成 SELECT/KEEP/EXIT 候选。两者先按 sleeve 独立产出，再由组合层合并，禁止直接叠加订单。

## 任务 3：让规格可机器检查

- 写 `tools/validate_docs.py`，检查 14 文件齐全、必需标题齐全、Markdown 相对链接存在、上位规格指纹不变。
- 验收：`python tools/validate_docs.py` 退出码 0 且输出 `14 module docs: PASS`、`baseline hashes: PASS`、`links: PASS`。
- 反向验证：在临时目录删除一个必需标题，运行同一验证器必须非 0；贴红色输出，删除临时目录后重跑全绿。

## 规矩

- 不许删检查、放宽必需标题/文件数、伪造输出、`|| true`、把上位文档复制成 14 份凑数。
- 不新增依赖、流程或权限；必须加的写 `BLOCKED.md`。
- 同一验收连败 3 次先换项；结果比开工差就还原自己改动并如实记录。

## 完成条件

- 14 个模块均有可实现的责任边界、数据所有权、契约、状态规则和机器可判验收，验证器三项全部 PASS。
- 5 份上位规格 SHA256 与开工一致，`MvpSelect` 零修改，越界改动为 0。
- 每条完成声明都须贴实际命令输出；只说完成不算。`BLOCKED.md` 空也写“无”。
- 最多 3 轮全量验收；满轮即停，如实报告卡点与剩余项。
