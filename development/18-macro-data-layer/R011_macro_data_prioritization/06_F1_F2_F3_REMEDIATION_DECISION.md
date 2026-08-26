# R011 F1—F3 修复与研究时点决策

状态：`F1_COMPLETED / F2_NUMERIC_GAP_FILLED_PIT_RESTRICTED / F3_PRIOR_TRADING_DAY_APPROVED`

> F2 已于 2026-08-26 完成数值补齐；用户决定人工复核后不保留 Excel/PDF 原件。最终数值、哈希、PIT 限制和清理记录见 [09_PMI_201004_MANUAL_LANDING_AUDIT.md](09_PMI_201004_MANUAL_LANDING_AUDIT.md)。本文件第 3 节保留为补齐前的获取路径记录。

审计时点：2026-08-26（Asia/Shanghai）

## 1. 决策摘要

- **F1 已修复并通过复核。** 既有 Tushare Shibor Bronze 在官方重叠区只有 2022-04-18—2022-05-17 的 21 个日期发生 O/N 与 3M 精确互换；除这 42 个单元格外，其他 20,998 个单元格全部一致。以 CFETS/全国银行间同业拆借中心为 Shibor 官方源，已修复总表及 2022 年分片，并保留字节级原件、前后 SHA-256 和恢复说明。
- **F2 的 headline 已找到联合官方证据，完整六字段仍需国家数据人工导出。** 中国物流与采购联合会 2010-05-01 09:06 发布页确认 2010 年 4 月制造业 PMI 为 55.7%，但页面没有给出本项目所需五个构成指数的精确值。国家数据端点在当前自动化环境被 WAF 以 `403 UrlACL` 拒绝，不能用脚本可靠获取。
- **F3 的历史主规则已确定为前一交易日可见。** 官方规则能证明计划 11:00 发布，但不能证明最近六个月每天都在 11:05 前实际可读；因此策略交易日 D 只使用 `reference_period < D` 的最新 Shibor。D1 同日规则保留给 forward observation，同日 11:05 历史规则不作为 PIT 主结果。

## 2. F1：Shibor 跨列互换检测与 Bronze 修复

### 2.1 修复前门禁

| 项目 | 结果 |
|---|---:|
| 官方/Tushare 重叠单元格 | 21,040 |
| 修复前一致 | 20,998 |
| 修复前差异 | 42 |
| 受影响日期 | 21 |
| 最早/最晚 | 2022-04-18 / 2022-05-17 |
| 每日差异列 | 仅 O/N、3M |
| 交叉相等 | `official_ON == bronze_3M` 且 `official_3M == bronze_ON` |
| 区间外或第三列差异 | 0 |

受影响日期：

```text
2022-04-18, 2022-04-19, 2022-04-20, 2022-04-21, 2022-04-22,
2022-04-24, 2022-04-25, 2022-04-26, 2022-04-27, 2022-04-28,
2022-04-29, 2022-05-05, 2022-05-06, 2022-05-07, 2022-05-09,
2022-05-10, 2022-05-11, 2022-05-12, 2022-05-13, 2022-05-16,
2022-05-17
```

### 2.2 修复对象与恢复证据

修复对象：

```text
D:/Claude_work_Territory/QuantTradingSystem/artifacts/data_expansion/bronze/macro/shibor.parquet
D:/Claude_work_Territory/QuantTradingSystem/artifacts/data_expansion/bronze/macro/shards/shibor/2022.parquet
```

原件及 manifest：

```text
D:/Claude_work_Territory/QuantTradingSystem/artifacts/data_expansion/repairs/r011_shibor_on_3m_swap/
  original/shibor.11591c1cc2ed03f934811f86f1c5854c448dc3824450690964920a31ea698cf9.parquet
  original/2022.94e06c78d9f2d93e5baa88980965dc67c3814c05e77f809b50c03b7cd25e0728.parquet
  repair_manifest.json
```

| 文件 | 修复前 SHA-256 | 修复后 SHA-256 |
|---|---|---|
| 总表 | `11591c1cc2ed03f934811f86f1c5854c448dc3824450690964920a31ea698cf9` | `97d823e77d131facda1a9de26ae3a207ae3ee74e9a0c5544dd0dce5b879ebef3` |
| 2022 分片 | `94e06c78d9f2d93e5baa88980965dc67c3814c05e77f809b50c03b7cd25e0728` | `bec9f83696e7ed4d436cf8d8d150c90e77030aa9c4dd310a2aaae52a71c54a90` |

修复后：官方/Tushare 21,040/21,040 精确一致；总表 2022 子集与年度分片按日期键排序后逐值一致。修复工具在异常日期数、差异单元格数、首末日期或跨列模式有任一变化时拒绝写入。

## 3. F2：2010-04 PMI 获取路径与人工交付规范

### 3.1 已找到的一手证据

- 中国物流与采购联合会官方存档页：[4月份中国制造业采购经理指数为55.7%](https://old.chinawuliu.com.cn/lhhkx/201005/01/128367.shtml)。页面标示 2010-05-01 09:06，确认 `2010-04 HEADLINE=55.7`。
- 国家统计局国家数据 PMI 直达页：[月度数据—采购经理指数](https://data.stats.gov.cn/easyquery.htm?cn=A01&zb=A0B01&sj=201004)。`A01` 为月度数据，`A0B01` 为 PMI 指标组，`201004` 为目标参考月。

仅用 headline 不能补齐本项目六字段 schema，也不能从加权公式反推出五个分类指数，因此暂不做局部伪补全。

### 3.2 需要用户人工完成的步骤

1. 用普通桌面浏览器打开上述国家数据直达页；若页面没有保留参数，依次选择“月度数据”→“采购经理指数”→制造业 PMI 指标组。
2. 时间至少选择 `2010-04`；推荐一次导出 `2009-05—2010-05` 或页面允许的完整历史，以便 Agent 检查口径、修订和邻月一致性。
3. 选择并保留以下六项，不要手工改值或改列名：
   - 制造业采购经理指数（PMI）
   - 生产指数
   - 新订单指数
   - 原材料库存指数
   - 从业人员指数
   - 供应商配送时间指数
4. 使用网页原生“下载/导出”功能保存原始 Excel（优先 `.xlsx`/`.xls`，其次 `.csv`）。不要复制粘贴到自建表格。
5. 将网页查询结果另存 PDF，或提供完整截图，必须能看见：国家数据域名、菜单路径、所选指标、时间范围、单位、季节调整说明（若页面显示）和查询日期。
6. 将未经编辑的导出文件和 PDF/截图放入：

```text
D:/Claude_work_Territory/QuantTradingSystem/temp/r011-macro-samples/artifacts/macro_r011/manual_drop/nbs_national_data_pmi/
```

建议文件名：

```text
nbs_national_data_pmi_200905_201005_original.xlsx
nbs_national_data_pmi_200905_201005_query_evidence.pdf
```

交付后由 Agent 完成：原文件 SHA-256、字段映射、2010-04 六字段提取、与 CFLP headline 55.7 交叉验证、vintage/来源标记、缺口重跑和审计更新。国家数据数据库更新时间不得冒充 2010 年实际发布时间；页面 09:06 证据只适用于已明确发布的 headline，其他字段的 PIT 时点需按来源证据单独处理。

## 4. F3：近六个月发布时间证据

审计窗口：2026-02-26—2026-08-25。

| 项目 | 结果 |
|---|---:|
| 官方发布日期 | 126 |
| 记录数 | 1,008 |
| 每日期限数 | 8/8 |
| 注册 release time | 11:00 Asia/Shanghai |
| 历史 API 实际发布时间字段 | 无 |
| 同期实时采集日志 | 无；本批只有 2026-08-26 回填时间 |

官方依据：[Shibor 简介及实施准则](https://www.shibor.org/chinese/llshibor/)明确指定发布人于每个交易日 11:00 对外发布；[实施准则 PDF](https://www.shibor.org/dqs/cm-s-notice-query/fileDownLoad.do?contentId=1004233&mode=save&priority=0)同时规定 10:55 前完成报价并建立应急机制。该证据证明计划时点，不提供逐日“首次成功读取”时点。

历史接口记录仅含 `showDateCN`、`showDateEN`、O/N、1W、2W、1M、3M、6M、9M、1Y；HTTP 响应时间是本次查询时间，不是历史发布时间。未发现异常/暂停公告也不能证明每一天都在 11:05 前可读。

### 4.1 策略测试规则

1. **Forward/生产观察：正式采用 D1。** `tradable_at=max(first_successful_capture_completed_at, 11:05)`；保存每次轮询时间、首次成功响应时间、响应 SHA-256、HTTP 状态和失败次数。
2. **历史主结果：采用用户批准的前一交易日规则。** 对任一策略交易日 D，只允许使用 `reference_period < D` 的最新 Shibor 观测；实现为严格滞后 as-of join，不按自然日机械减一天。该规则覆盖周末、节假日和策略市场与银行间市场日历差异。
3. **同日 11:05 不再是当前历史主规则。** 如单独做研究敏感性测试，可标记 `scheduled_release_proxy_unverified`，但不得用于 Research Ready、上线或资金配置结论。
4. **Forward 规则不变。** 当积累至少六个月实时日志后，检查覆盖率、11:05 违约次数、最大/分位延迟和节假日；只有真实观测满足批准阈值，才复审是否允许历史同日 11:05。
5. 历史规则的证据标签统一为 `prior_strategy_trading_day_observation`；策略数据装配必须断言所连接的 Shibor `reference_period` 严格早于决策交易日。

## 5. 实现与复现

新增：

```text
src/quant_trading_system/research/macro_data/repair.py
scripts/data_lake/repair_shibor_bronze.py
tests/research/test_macro_data_repair.py
```

修复工具执行前自动对全重叠区做跨列检测；修复前备份两个目标文件，写后重新对账并核对总表与分片。正式对账当前结果：Shibor 21,040/21,040、PMI 762/762，数值层全部通过；Shibor 唯一剩余限制为 historical capture timing。
