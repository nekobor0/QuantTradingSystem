# V6执行切片最终验收 — 2026-08-01

## 结论

`V6_LEADER_BRIEF.md`定义的本轮执行切片已完成。V6 Phase 1基础设施与首轮Downside Beta研究均可复算；Tushare历史审计和11阶段staging回填均已终止并有独立审计。数据源空洞按`DATA_BLOCKED`保留，未填零、未覆盖V5或生产数据。

## 逐条证据

| 要求 | 当前证据 | 结论 |
|---|---|---:|
| GOAL不可漂移 | `GOAL_V6.md` SHA256=`4030CA236BDC3931A380D6C8C91577827C9087326C4E666C19AB97136B68F48F` | PASS |
| Leader任务书 | `V6_LEADER_BRIEF.md`存在，范围、白名单、断点与反作弊门禁明确 | PASS |
| 冻结V5三基线 | `python -m scripts.v6.freeze_v5_baselines --check`输出3 baselines PASS | PASS |
| Phase 1基础设施 | baseline registry、12控制风险模型、增量评价、交易净额、append-only影子接口及分类器均有机器artifact和测试 | PASS |
| 首轮Downside Beta登记与数据审计 | 冻结registration存在；完整复算554,400行、5,775股、96月、重复0、未来信息违规0 | PASS |
| 首轮正式决策 | 两基准Downside Beta与主要回撤门槛均失败；复算决策仍为`REJECTED`，未调参、未写影子 | PASS |
| 多重检验 | 第63项已写入账本，方向不利但显著的结果未被翻号 | PASS |
| Tushare最早可用审计 | `tushare_history_v6.{json,md}`覆盖当前data层21个数据集、20个接口及质押分片 | PASS |
| 历史回填边界 | 仅写`artifacts/data_backfill_v6/v2` immutable shards；无生产发布 | PASS |
| 逐阶段数据验收 | 11/11阶段审计齐全；7 PASS，4 DATA_BLOCKED；无缺失或无效审计 | PASS WITH DATA BLOCKS |
| staging总量 | 43,222,321行、1,742,332,805字节；总体验收`DATA_BLOCKED_PARTIAL` | RECORDED |
| 源空处理 | stock_st 154、financial 34、index 3、event 184；两轮复验后仍空，未落零行分片 | PASS |
| 事件日期值域 | repurchase/holdertrade/holdernumber的ann_date均未越界；pledge_detail有17个未来合同end_date，但ann/start/release日期未越过截止日 | RECORDED |
| 断点与Windows原子写 | 全局锁、request hash、sidecar、批量checkpoint；瞬时`WinError 5`已有有限重试测试 | PASS |
| 临时状态 | 下载进程0、全局锁0、checkpoint `.tmp` 0；正式失败checkpoint全部保留 | PASS |
| 测试 | V6 54 passed；全仓1616 passed/0 skipped | PASS |
| 文档交接 | `PROGRESS_V6.md`、`CONTEXT_HANDOFF_V6.md`、`BLOCKED_V6.md`与本文件 | PASS |

## 决策边界

- 本轮Downside Beta为`REJECTED`，不得继续搜索同义窗口、方向或20%权重。
- Tushare staging可用于后续独立的数据治理，但当前生产发布被`PROHIBITED_WHILE_DATA_BLOCKED_OR_INCOMPLETE`门禁阻止。
- 生产data层映射、事件表canonical key/availability timestamp和缺口处置属于后续单独裁决，不属于本轮执行切片。

## 固定复算命令

```powershell
$env:PYTHONPATH='src'
python -m scripts.v6.freeze_v5_baselines --check
python -m scripts.v6.run_downside_beta_v6
python -m scripts.v6.summarize_tushare_backfill_v6
python -m pytest tests/research/v6 -q -p no:cacheprovider
python -m pytest -q -p no:cacheprovider
```

汇总器因预期的真实数据阻断返回非零，但必须同时生成`DATA_BLOCKED_PARTIAL`机器artifact；这不是PASS，也不得用shell吞掉退出码。
