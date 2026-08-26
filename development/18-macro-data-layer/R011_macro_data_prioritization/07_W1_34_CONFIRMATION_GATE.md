# R011 W1 34 条宏观脊柱确认门

状态：`PRE_CONFIRMATION_COMPLETE / FULL_BACKFILL_BLOCKED`

审计时点：2026-08-26（Asia/Shanghai）

范围：完成 W1 的现有资产盘点、官方源核验、字段映射、样例对照、PIT/修订风险设计和机器校验；尚未启动 W1 新增序列的正式全量回填。

## 1. 结论

W1 的 34 条已冻结为 5 个数据包并通过机器校验：利率与流动性 11、PMI 8、价格 5、货币信用 7、增长 3。现有资产可为 17 条提供字段级独立对照，其中 Shibor 3 条和 PMI 2 条已有正式官方实现；其余不是重复下载，而是官方来源、发布时间、历史 vintage 和口径版本的升级。

机器注册表：[macro_w1_confirmation_registry.json](../../../config/macro_w1_confirmation_registry.json)

复核命令：

```powershell
$env:PYTHONPATH = "src;."
python scripts/data_lake/validate_macro_w1_gate.py
```

## 2. 包级实施顺序

| 顺序 | 数据包 | 条数 | 当前基础 | 确认后首个工作单元 |
|---:|---|---:|---|---|
| 1 | 利率与流动性 | 11 | Shibor 3 条已实现；其余缺官方 adapter | DR007/R007 + OMO/MLF 两种来源样板 |
| 2 | PMI 状态 | 8 | 2 条已实现；另外 6 条已映射现有字段 | 扩展发布页 parser 并与 `cn_pmi` 对账 |
| 3 | CPI/PPI | 5 | 3 条有现有对照；核心 CPI、PPIRM 待建 | CPI/PPI 同一发布页样板 |
| 4 | 货币、贷款、社融 | 7 | M1/M2、社融总量/存量有现有对照 | 人行公告 + 附件双载体样板 |
| 5 | GDP/工业增加值 | 3 | GDP 2 条有现有对照 | 季度累计 GDP + 1—2 月跨期样板 |

## 3. 已核验样例与字段映射

以下数值来自现有 Tushare Bronze，只作为独立 cross-check，不决定官方发布时间或口径。

| 参考期 | W1 字段 | 现有字段 | 样例值 |
|---|---|---|---:|
| 2026Q2 | `gdp_nominal` / `gdp_real_yoy` | `cn_gdp.gdp` / `gdp_yoy` | 695704 / 4.7 |
| 2026-07 | `cpi_yoy` | `cn_cpi.nt_yoy` | 0.5 |
| 2026-07 | `ppi_yoy` / `ppi_mom` | `cn_ppi.ppi_yoy` / `ppi_mom` | 3.5 / -0.7 |
| 2026-07 | `m1_balance` / `m2_balance` | `cn_m.m1` / `m2` | 1154623 / 3555077.24 |
| 2026-07 | `tsf_flow` / `tsf_stock` | `sf_month.inc_month` / `stk_endval` | 14017 / 463.27 |
| 2026-07 | PMI 8 条 | `pmi010000, pmi010500, pmi010900, pmi011200, pmi020100, pmi020200, pmi020300, pmi030000` | 49.2, 48.5, 49.6, 53.2, 49.0, 44.4, 49.7, 49.3 |
| 2026-08-19 | Shibor O/N、1W、3M | `shibor.on, 1w, 3m` | 1.381, 1.385, 1.430 |

国家统计局 2026-07 发布页已直接验证制造业 PMI 49.2、新订单 48.5、非制造业商务活动 49.0、综合 PMI 49.3；核心 CPI 0.9、PPI 同比 3.5、环比 -0.7 也可从对应官方发布/解读页提取。现有样例因此足以确认字段方向，但不能替代全历史逐期对账。

## 4. 请确认 W1_D1—W1_D9

### W1_D1 — 金额单位

推荐：GDP、货币余额和流量在 canonical 层保存官方“亿元”，万亿元只作为展示/特征层派生；避免不同表自动缩放后静默错 10,000 倍。

### W1_D2 — 名义 GDP 粒度

推荐：canonical 保存官方季度累计值 `CN.GDP.NOMINAL.YTD`；单季值另行相减派生并保留 lineage，不把累计值标成单季值。

### W1_D3 — 工业增加值 1—2 月

推荐：把联合发布的 1—2 月值记在 `YYYY-02`，增加 `period_span=YYYY-01/02`；不虚构 1 月单月值。

### W1_D4 — 货币信用修订与累计值

推荐：以人行公告实际页面时间控制 `available_at`，附件按哈希形成 vintage；累计转单月只允许显式白名单，不做通用差分。

### W1_D5 — DR007/R007/中债历史可见时点

推荐：历史主规则为下一策略交易日可见；forward 采集只有在记录首次成功完成时间后才能提前到当日盘后。

### W1_D6 — OMO/MLF/LPR 事件序列

推荐：canonical 保持稀疏事件，不自动向前填充；持有期政策利率是带来源事件 lineage 的派生特征。

### W1_D7 — LPR 制度断点

推荐：2019-08-20 后改革 LPR 为主研究序列；改革前 1Y LPR 单独保存为不可比 regime，5Y+ 从 2019 年开始。

### W1_D8 — 历史 PIT 门槛

推荐：只有当前历史值、没有当期发布证据的区间统一 `exploratory_only`；Research Ready 窗口从可重建发布页 vintage 的时期开始。

### W1_D9 — 中债使用边界

推荐：仅限项目内部研究，保存条款/曲线说明版本，按官方最多一年查询窗口分片，不再分发 Raw。

## 5. 硬门禁

在 W1_D1—W1_D9 未确认前：

- 不启动 29 条尚未正式实现序列的全量回填；
- 不把现有非 PIT Bronze 提升为官方主源；
- 不做累计转单月、事件前填、LPR 跨制度拼接；
- 不生成可进入策略的 Regime / Conditional Alpha / Exposure Control 特征；
- 可继续做无状态变化的来源探测、fixture、parser skeleton 和质量测试。

## 6. 确认后的验收顺序

每个数据包依次通过：source terms → 两期真实样例 → Raw/或获批人工接收策略 → parser 重放 → canonical 校验 → 现有 Bronze 对账 → PIT 窗口分级 → 全量回填。任一步失败即停在 quarantine，不以“下载行数”代替验收。

