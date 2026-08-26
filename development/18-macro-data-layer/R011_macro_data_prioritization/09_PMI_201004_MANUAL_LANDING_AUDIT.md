# R011 PMI 2010-04 人工确认落盘审计

状态：`NUMERIC_GAP_FILLED / HISTORICAL_PIT_GAP_RETAINED`

审计时点：2026-08-26（Asia/Shanghai）

## 技术结论

用户提供并人工复核的国家统计局国家数据导出已补齐 2010-04 六项制造业 PMI。PMI curated 表现在 2009-05—2026-07 数值连续，范围内缺月为 0，全部 canonical 校验通过。由于导出发生在 2026 年，它不能证明六项数据在 2010 年的精确历史可见时点；因此 `numerically_complete=true`、`historical_pit_complete=false`、全历史 `research_ready=false` 同时成立。

按用户决定，Excel、PDF、手工投递目录和本次 Raw 复制目录均已删除；仅保留规范化 Parquet、输入内容哈希和“用户人工复核”接收标记。

## 1. 补齐值

| series_id | 2010-04 |
|---|---:|
| `CN.PMI.MFG.HEADLINE` | 55.7 |
| `CN.PMI.MFG.PRODUCTION` | 59.1 |
| `CN.PMI.MFG.NEW_ORDERS` | 59.3 |
| `CN.PMI.MFG.RAW_MATERIAL_INVENTORY` | 51.5 |
| `CN.PMI.MFG.EMPLOYMENT` | 53.2 |
| `CN.PMI.MFG.SUPPLIER_DELIVERY_TIME` | 51.1 |

输入内容 SHA-256 为 `7ef3bff92ddb79f7338af9d3930f3a1a14f06ec462078dd963b7b0d6b65d8197`；它只用于 lineage，不代表原件仍被保留。Headline 55.7 与 2010-05-01 09:06 联合发布方存档一致。[CFLP 2010-04 PMI](https://old.chinawuliu.com.cn/lhhkx/201005/01/128367.shtml)

## 2. 时点处理

| 字段 | 值/规则 | 含义 |
|---|---|---|
| `reference_period` | `2010-04` | 经济数据所属月 |
| `release_at` | `2010-05-01 09:06 +08:00` | 联合发布方 headline 页面时间 |
| `available_at` | `2026-08-26 15:12:11.741776 +08:00` | 本项目人工接收时间 |
| `tradable_at` | 同 `available_at` | 不允许回写成 2010 年可交易数据 |
| `availability_evidence` | `current_nbs_database_export_not_historical_pit` | 明示 PIT 限制 |

## 3. 最终审计

| 项目 | 结果 |
|---|---:|
| 官方发布页 catalog | 204/204 完成 |
| 合并 vintage | 205 |
| canonical rows | 13,536 |
| 覆盖 | 2009-05—2026-07 |
| 数值缺月 | 0 |
| 非历史 PIT 月 | 2010-04 |
| canonical 10 项校验 | 全部通过 |
| 数值连续性 | 通过 |
| 历史 PIT 完整性 | 不通过 |
| 全历史 Research Ready | 否 |

## 4. 落盘哈希

| 产物 | SHA-256 |
|---|---|
| 2010-04 normalized shard | `060306f08c569b1e7b12829bdbc5c72d6b0243a3e272d8a2eed2d6b5efd73aef` |
| PMI curated table | `618982ddf1e01bbe1ff890d428fd824bd4069499d616e5afb4fa87261181e1a7` |
| PMI audit JSON | `d1fe64274ee2db47648500fec3f5e61a4bbe6991e960c9f13c4727de5fc1d632` |

## 5. 使用限制

- 2016-01—2026-07 已批准研究窗口不受影响。
- 需要 2009-05 起长样本的描述性研究可使用数值，但必须标记 2010-04 为 2026 年后见导出。
- 任何严格历史 PIT 回测不得让 2010-04 六项在 2026-08-26 之前可见。
- 不得因为缺月已消失就把全表自动提升为 Research Ready。

