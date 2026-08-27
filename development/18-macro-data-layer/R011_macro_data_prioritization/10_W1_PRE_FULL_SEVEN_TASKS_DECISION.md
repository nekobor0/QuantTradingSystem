# R011 W1：进入全量前七项任务决议

日期：2026-08-27  
状态：七项任务已执行；W1 全量入口保持关闭；`research_ready=false`

## 结论

已完成 canonical v2、34 条库存对账、五包契约、两期 Gold、统一 runner/日历/审计、三包小窗口 shadow，以及逐包 full-history 入口评审。当前不能把 34 条作为一个整体交给执行模型全量抓取。

| 包 | Gold | Shadow | Full-history 决议 |
|---|---|---|---|
| rates_liquidity | 4/11，部分覆盖 | 阻塞 | 阻塞：7 条缺两期 Gold；CFETS 历史路径仍未验证 |
| pmi_state | 8/8，两期 | Sol gate 通过 | 阻塞：8 字段历史发布页发现与全月期望期审计未实现 |
| prices | 5/5，两期 | Sol gate 通过 | 阻塞：CPI/PPI 历史配对发现未实现；基期制度提取仅 Gold 验证 |
| money_credit | 5/7，两期 | 阻塞 | 阻塞：两条贷款流量缺官方直接月值；附件 vintage 历史发现未实现 |
| growth_output | 3/3，两期 | Sol gate 通过 | 阻塞：GDP/工业历史发现未实现；1—2 月联合期 gate 未实现 |

## 已消除的前序陷阱

- canonical v1 不被重写；v2 通过显式升级函数扩展。
- “有部分官方数据”不等同于“整包 Gold ready”。
- `blocked`、`blockers`、`research_ready` 语义由统一 audit schema 机器校验。
- 测试不再依赖 Windows 系统 `%TEMP%/pytest-*`，输出固定到 Git 忽略的仓库 `artifacts`。
- NBS 页面出现字符集异常时，PMI、CPI/PPI、GDP、工业增加值以表结构和 Gold 值双重门禁解析，不用乱码关键词猜测。
- full-history runner 不允许跳过 Gold 与 Sol shadow gate；五包均已生成本地 ignored 阻塞审计。

## 可复现入口

- Gold：`python scripts/data_lake/validate_macro_w1_gold.py`
- Shadow：`python scripts/data_lake/run_macro_w1_nbs_shadow.py --package <pmi_state|prices|growth_output>`
- Full gate：`python scripts/data_lake/validate_macro_w1_full_entry.py`

下一阶段应逐包补历史发现器与完整 expected-period 审计；只有对应包的 blocker 清零，才将该包单独提升为 `FULL_HISTORY_ALLOWED`。禁止一次性放开 34 条。
