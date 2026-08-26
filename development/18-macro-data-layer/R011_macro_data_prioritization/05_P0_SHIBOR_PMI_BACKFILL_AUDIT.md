# R011 P0 Shibor / PMI 正式回填与数据质量审计

> 2026-08-26 后续更新：2010-04 六项 PMI 已由用户复核的国家数据导出补齐，当前数值缺月为 0；由于导出不提供历史可见时点，全历史 PIT 门禁仍关闭。下文保留补齐前审计快照，最终结论见 [09_PMI_201004_MANUAL_LANDING_AUDIT.md](09_PMI_201004_MANUAL_LANDING_AUDIT.md)。

状态：`COMPLETED_WITH_RESTRICTIONS`

审计时点：2026-08-26（Asia/Shanghai）

范围：D1—D5 确认后的正式实现、官方源历史回填、不可变落盘、自动质量检查及既有 Tushare Bronze 独立对账。未进行宏观特征研究、策略回测、定时调度或生产接入。

## 1. 技术结论

1. **PMI 2016-01—2026-07 可作为首个获批研究窗口。** 国家统计局发布页与 Tushare Bronze 在 127 个月、6 个制造业指标、共 762 个重叠单元格上全部精确一致；每个官方页面保留独立发布时间和 vintage。
2. **PMI 全历史表不能无条件标记 Research Ready。** 官方归档可解析范围为 2009-05—2026-07，但 2010-04 没有在国家统计局公开搜索目录中发现对应页面或观测值。全表门禁保持关闭；研究消费者必须显式限定到已批准连续窗口或处理缺口。
3. **Shibor 数值层完整，但历史 PIT 使用仍受限。** CFETS 官方回填覆盖 2006-10-08—2026-08-25，共 4,966 个发布日期、8 个期限、39,728 条记录；每个日期均有完整 8 期限，自动契约通过。由于历史抓取不是当时的实时可见延迟观测，必须执行 D1 的 `tradable_at=max(采集完成时点, 11:05)`，不得把回填时点伪装成历史实时可得时点。
4. **既有 Tushare Shibor Bronze 存在高严重度局部列互换。** 2016-01-04—2026-08-19 共 21,040 个重叠单元格中 20,998 个一致；42 个差异全部来自 2022-04-18—2022-05-17 的 21 个日期，且每天都可精确证明 O/N 与 3M 两列互换。原 Bronze 未修改，差异已进入 quarantine。
5. **整体状态不是全绿。** PMI 获批窗口可用于后续 Regime / Conditional Alpha / Exposure Control 研究；Shibor 可用于数值研究和当前开始的 forward observation，但历史交易时点回测门禁仍关闭。

## 2. 数据集、粒度与主键

| 数据集 | 官方源 | 规范化粒度 | 规范化主键 | 值域/单位 |
|---|---|---|---|---|
| Shibor | CFETS/Shibor 页面后端 | 发布日 × 8 期限 × vintage | `series_id, reference_period, vintage_id` | 年化百分数，0—20 |
| 制造业 PMI | 国家统计局逐月发布页 | 指标 × 参考月 × 页面 vintage | `series_id, reference_period, vintage_id` | 季调扩散指数百分数，0—100 |

统一 schema 包含：`series_id`、`reference_period`、`value`、`unit`、`source_id`、`source_record_id`、`release_at`、`available_at`、`tradable_at`、`retrieved_at`、`vintage_id`、`raw_sha256` 和 `parser_version`。

## 3. 正式落盘结果

### 3.1 Shibor

| 项目 | 结果 |
|---|---:|
| 年度分片 | 21/21 成功（2006—2026） |
| 日期 | 4,966 |
| 期限 | 8 |
| 规范化记录 | 39,728 |
| 覆盖 | 2006-10-08—2026-08-25 |
| 每日期 8 期限完整 | 通过 |
| 规范化文件 SHA-256 | `791aa746a37c6109515053ab104c9fcd86512064bcbd4bbdd2c14a0fc5c2af93` |
| Research Ready | 否；历史采集时点限制 |

### 3.2 PMI

| 项目 | 结果 |
|---|---:|
| 官方候选发布页 | 204 |
| 完成页面 | 204 |
| 页面 vintage | 204 |
| 规范化记录 | 13,530 |
| 覆盖 | 2009-05—2026-07 |
| 范围内缺月 | 2010-04 |
| 规范化文件 SHA-256 | `21d8f21e1f582565fb15483355b46221ff5587ac1a9e022891358bc43bf9191e` |
| 全表 Research Ready | 否；存在已知缺月 |
| 获批研究窗口 | 2016-01—2026-07 |

PMI 解析器支持三类官方页面：早期双月横表、较短的纵向累计表、现代 13 个月滚动表。正文时间和 `<meta name="PubDate">` 时间均按页面证据解析，不用搜索索引日期替代发布时间。

## 4. 质量检查与结果

| 维度 | Shibor | PMI |
|---|---|---|
| 非空 | 通过 | 通过 |
| 主键唯一 | 通过 | 通过 |
| 契约字段非空 | 通过 | 通过 |
| 时间戳可解析 | 通过 | 通过 |
| `available_at >= release_at` | 通过 | 通过 |
| `tradable_at >= available_at` | 通过 | 通过 |
| `retrieved_at >= available_at` | 通过 | 通过 |
| 注册表覆盖 | 通过 | 通过 |
| 值域 | 通过 | 通过 |
| Raw 哈希格式 | 通过 | 通过 |
| 时间覆盖完整性 | 通过官方返回日 × 8 期限 | 失败：2010-04 缺失 |
| 独立对账 | 失败：42 个 Bronze 差异 | 通过：762/762 |

没有使用图表：本轮目标是二元门禁、精确计数和异常日期审计，表格比趋势图更能保留主键、分母和失败范围。

## 5. 对账异常、严重度与影响

### F1 — Tushare Shibor O/N 与 3M 局部互换

- 严重度：**High**。
- 置信度：**High**；21 个异常日期全部满足 `official_ON == tushare_3M` 且 `official_3M == tushare_ON`。
- 影响窗口：2022-04-18—2022-05-17。
- 影响：使用既有 Bronze 计算期限利差、流动性压力或 Regime 时会反转 O/N 与 3M 关系，可能制造虚假信号。
- 处置：官方源优先；差异文件留在 `artifacts/macro_r011/quarantine/shibor_tushare_mismatches.parquet`；本轮不覆盖或修复原 Bronze。
- 自动化建议：对 O/N、3M 加入跨列互换检测；任何整段精确互换直接阻断下游研究发布。

### F2 — PMI 2010-04 官方归档缺口

- 严重度：**Medium**。
- 置信度：**High**；204 页全部成功解析，定向查询 `PMI`、`4月份制造业`、`5月份制造业` 等仍未找到对应官方发布页。
- 影响：2009-05 起的全范围不是连续月频序列，不能无提示做滚动、差分或状态转移估计。
- 处置：全表 `research_ready=false`；2016-01—2026-07 作为首个连续且已独立对账的研究窗口。
- 后续补救：仅可从国家数据正式导出、获得授权的数据服务或另一份可审计官方附件补齐；不得从相邻月份插值后冒充官方值。

### F3 — Shibor 历史采集延迟不可观测

- 严重度：**High（针对 PIT 回测）**，Low（针对描述性数值研究）。
- 置信度：**High**；此次为 2026-08-26 的历史回填，不是逐日 11:00 附近观测。
- 影响：若把 `release_at=11:00` 直接当作历史稳定可交易时点，会产生前视风险。
- 处置：保留 D1 `tradable_at=max(实际采集完成, 11:05)`；从当前开始积累 forward latency evidence；历史策略只能在另行批准的保守下一交易日规则下评估。

## 6. 可复现产物与命令

正式数据位于 Git 忽略目录：

```text
artifacts/macro_r011/
  raw/
  normalized/
  curated/shibor_observations.parquet
  curated/pmi_observation_vintages.parquet
  catalogs/pmi_release_pages.json
  state/shibor_backfill.json
  state/pmi_backfill.json
  audits/shibor_backfill.json
  audits/pmi_backfill.json
  audits/tushare_reconciliation.json
  quarantine/shibor_tushare_mismatches.parquet
  quarantine/pmi_tushare_mismatches.parquet
```

断点续跑：

```powershell
$env:PYTHONPATH = "src"
python scripts/data_lake/run_macro_samples.py `
  --mode backfill --source all `
  --output-root artifacts/macro_r011 `
  --shibor-start 2006-10-08
```

独立对账：

```powershell
python scripts/data_lake/run_macro_samples.py `
  --mode reconcile `
  --output-root artifacts/macro_r011 `
  --tushare-macro-root <existing-tushare-bronze-macro-directory>
```

## 7. 下一步

1. 用 PMI 2016-01—2026-07 启动第一轮 Regime / Conditional Alpha / Exposure Control 研究，优先 `HEADLINE` 与 `NEW_ORDERS`；其余四项作为条件变量。
2. Shibor 从当前开始按低频内部研究规则积累实际采集完成时间；在形成足够 latency 证据前，不开放历史盘中 PIT 回测。
3. 为既有 Tushare Shibor Bronze 单开修复轮次：保留原文件，生成更正派生层和 lineage，不原地覆盖。
4. 2010-04 PMI 仅在获得可审计官方值时补齐；否则长期保留显式 gap。
5. 本轮不开始策略回测或特征生产；下一轮必须先注册研究假设、使用窗口和停止规则。

## 8. 开放问题

- CFETS 正式机构接口或授权数据服务是否能提供历史可得时点/修订证据？
- 国家数据查询端点的 403 是否可通过正常浏览器导出或正式授权渠道解决？
- 2010-04 是否存在未被当前国家统计局搜索索引收录的官方附件？
- Tushare Shibor 2022 年列互换是上游接口历史问题，还是本地 Bronze 构建时字段顺序问题？修复前必须追溯原始抓取 manifest。
