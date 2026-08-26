# R011 P0 + Shibor / PMI 样板确认门

状态：`VALIDATED_PENDING_HUMAN_CONFIRMATION`

生成日期：2026-08-25（Asia/Shanghai）

范围：仅 P0 最小治理闭环、Shibor 与 PMI 样板；尚未进入全量回填、定时更新、研究特征或策略接入。

## 1. 已完成且不需要人工操作的部分

1. 建立机器可读 source / series registry，冻结频率、单位、季调状态、取值边界和官方入口。
2. 建立不可变 Raw 快照：原始响应按 SHA-256 内容寻址，伴随请求 URL、响应状态、抓取时点、内容类型及脱敏后的 manifest。
3. 建立统一的 observation-vintage schema：
   - `series_id`
   - `reference_period`
   - `value`
   - `release_at`
   - `available_at`
   - `retrieved_at`
   - `vintage_id`
   - `raw_sha256`
   - `availability_evidence`
4. 建立自动验证：主键唯一、必填字段、时间顺序、防前视、注册表覆盖、值域、哈希格式。
5. 两个样板均已真实从官方公开页面获取，保存 Raw、normalized Parquet 和 manifest；运行产物位于 Git 忽略的 `artifacts/macro_r011_samples/`。
6. 与现有 Tushare Bronze 逐单元格交叉核对，未覆盖或覆盖不一致的项目均不会静默通过。

## 2. 样板结果

### 2.1 Shibor

- 官方源：CFETS/Shibor 网站页面自身调用的公开后端。
- 请求区间：2026-08-18 至 2026-08-25。
- 覆盖：6 个交易日，8 个期限，共 48 条规范化 observation。
- 期限：O/N、1W、2W、1M、3M、6M、9M、1Y。
- 官方 Raw SHA-256：`f096f3d6e8e220ad1be01847d513a54fc3173d5482002e2805066f434be3d828`。
- 自动检查：全部通过。
- 与现有 Tushare Bronze：重叠 2 日 × 8 期限 = 16 个单元格，最大绝对差为 `0.0`。
- 当前 PIT 证据：官方规则说明每个交易日 11:00 发布；样板尚未做盘中轮询，因此这是“规则型发布时点”，不是对网页实际出现延迟的观测。

### 2.2 PMI

- 官方源：国家统计局《2026 年 7 月中国采购经理指数运行情况》发布页。
- 页面标示发布时间：2026-07-31 09:30（Asia/Shanghai）。
- 覆盖：2025-07 至 2026-07，13 个月，制造业 6 个指标，共 78 条规范化 observation。
- 指标：制造业 PMI、生产、新订单、原材料库存、从业人员、供应商配送时间。
- 单位：扩散指数百分数；页面明确为季节调整后数据。
- 官方 Raw SHA-256：`013fe0cd839e4b90d3af3dbba7ba2adf1c6a5ef082d2da76cf5928310ae3ab16`。
- 自动检查：全部通过。
- 与现有 Tushare Bronze：78 个单元格全部重叠，最大绝对差为 `0.0`。
- 当前 PIT 处理：发布页中的 13 个月滚动历史属于同一个 2026-07-31 页面 vintage。为避免前视，样板没有倒推旧月份的首次发布时间，全部保守记为本页面标示的 2026-07-31 09:30。完整 PIT 历史必须逐期抓取历史发布页后才能建立。

## 3. 推荐口径（请确认）

### D1 — Shibor 的策略可用时点

推荐：保留 `release_at=当日 11:00` 作为官方计划时点；新增研究/交易层 `tradable_at=max(实际采集完成时点, 11:05)`。日频策略只允许 11:05 之后的决策或下一交易日使用；在没有盘中延迟观测前，不允许假定 11:00:00 已可稳定读取。

请确认：接受 

### D2 — PMI 的主从源职责

推荐：国家统计局逐月发布页作为 PIT 主源，因为它有页面级发布时间；国家数据数据库作为数值补全和修订对账源，不把数据库更新时间冒充经济数据发布时间。当前环境访问国家数据查询端点返回 403，因此在下一阶段将其作为待解决的 reconciliation adapter，不影响发布页样板。

请确认：接受

### D3 — PMI 第一批落盘字段

推荐：六个制造业指标全部落盘，避免未来重复抓取；首轮研究优先使用 `HEADLINE` 和 `NEW_ORDERS`，其余四个先保留为候选条件变量，不直接进入策略。

请确认：接受 

### D4 — Shibor 自动化使用边界

推荐：当前仅限本项目内部研究、低频率、可审计抓取，不转载或对外分发原始数据；全量历史回填前，由你确认这是内部研究用途，并决定是否需要向 CFETS 申请学术/机构数据服务或正式接口授权。此项是数据授权与用途确认，不是数值口径问题。

请确认：内部研究低频抓取

### D5 — 既有 Tushare Bronze 的角色

推荐：不覆盖既有文件。官方源作为新 PIT 数据层主源；Tushare 保留为独立交叉验证源。只有在主键、单位和时点一致时才生成 reconciliation pass，差异进入 quarantine。

请确认：接受 

## 4. 当前 readiness 与硬门槛

| 数据集 | Raw | 规范化 | 自动验证 | 人工口径 | Research Ready |
|---|---:|---:|---:|---:|---:|
| Shibor 样板 | 通过 | 通过 | 通过 | 待确认 D1/D4/D5 | 否 |
| PMI 样板 | 通过 | 通过 | 通过 | 待确认 D2/D3/D5 | 否 |

在 D1—D5 未确认前：

- 不做全量历史回填；
- 不建定时任务；
- 不写入现有 Tushare Bronze；
- 不生成 Regime / Conditional Alpha / Exposure Control 特征；
- 不把状态提升为 `RESEARCH_READY`。

## 5. 你确认后的下一阶段

1. 将确认结果写回 registry 和 readiness manifest。
2. 建立逐期 PMI 发布页发现器与 archive crawl，形成真实 release vintage 历史。
3. 解决国家数据 403 或改用浏览器导出/授权渠道，仅用于数值对账与修订检测。
4. 为 Shibor 建立低频增量更新、实际可见延迟观测和官方/Tushare reconciliation。
5. 扩大回填前先给出请求数量、预计耗时、失败恢复点和授权边界。

## 6. 复现命令

PowerShell，在项目已安装为 editable package 时可直接运行；未安装时先只对当前进程设置 `PYTHONPATH`：

```powershell
$env:PYTHONPATH = "src"
python scripts/data_lake/run_macro_samples.py `
  --source all `
  --shibor-start 2026-08-18 `
  --shibor-end 2026-08-25
```

运行数据和 manifest 均在 `.gitignore` 覆盖的 `artifacts/` 下，不会进入提交。
