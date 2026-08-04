# 阶段一续跑检查点（2026-07-30）

## 结论先行

- 电脑重启前未完成的 `margin_detail` 已补齐：2018-07-02 至 2026-07-29 共 1,939 个交易日、5,376,724 行、5,079 只股票，`trade_date + ts_code` 重复数为 0。
- 59 因子冻结复跑已建立完整“因子动物园”：`development/16-alpha-factor-phase1/FACTOR_ZOO_59.md`。实际构成为 51 个既有候选 + 8 个新候选，并非口头描述中的 35 + 24；报告以落盘快照为准。
- 在 59 因子冻结快照之后，新增 5 个事前冻结方向的融资因子。64 因子总评估仍无候选通过全部 V2 硬门槛，因此当前不能宣称已有入库因子，更不能提前进入阶段二。

## 可审计产物

| 产物 | 路径 | 状态 |
|---|---|---|
| 59 因子动物园 | `development/16-alpha-factor-phase1/FACTOR_ZOO_59.md` | 59/59 唯一因子完整，SHA256 `783A9615FDE14993096DE2E7018CED2E18DD6F1A0B26C14D5FEF7A3F81412FC6` |
| 59 因子冻结结果 | `artifacts/alpha_phase1/factor_evaluation_long_only_v2_59_snapshot.json` | 后续新增因子不会污染 |
| 64 因子当前结果 | `artifacts/alpha_phase1/factor_evaluation_long_only_v2.json` | 59 旧 + 5 融资，`passing_factors=[]` |
| 融资明细 | `artifacts/alpha_phase1/tushare/margin_detail.parquet` | 完整、零主键重复 |
| 融资获取清单 | `artifacts/alpha_phase1/tushare/margin_detail_manifest.json` | 1937 日缓存命中，仅补取 2 日 |
| 融资因子面板 | `artifacts/alpha_phase1/factor_panel_margin.parquet` | 554,400 行，5 因子 |
| 融资假设与口径 | `artifacts/alpha_phase1/factor_panel_margin_metadata.json` | 方向在看结果前冻结 |
| Pure 因子面板 | `artifacts/alpha_phase1/factor_panel_pure_long_only_v2.parquet` | 已包含 64 因子中性化结果 |

## 融资数据断点与修复

重启审计发现 1,939 个目标交易日中有 1,937 个分片，缺少 `2022-04-01` 与 `2023-09-08`。两日历史错误均为 `ChunkedEncodingError: Response ended prematurely`，属于传输中断而非积分权限不足。重新执行断点脚本后仅请求这两日，其余 1,937 日均复用缓存，随后成功聚合。

`margin_detail_errors.json` 仍是历史失败日志，不代表当前缺口；是否完成应以新 manifest 的 `days=1939`、`duplicates=0` 和目标交易日差集为空为准。

原始明细还发现少量明显异常：负数融资字段，以及融资偿还额 `rzche` 高于 `max(rzye, rzmre)` 十倍的记录。清洗规则在因子评估前冻结：异常点的净融资流设为缺失，滚动窗口忽略异常点；不删除整只股票，也不根据回测结果调整阈值。已增加回归测试，保证单个坏点不会污染 5 日滚动和。

## 五个新增融资因子与盲测结果

所有流量以自由流通市值归一化；非融资标的定义为“观测到零融资需求”，因此正式可交易池内缺失率 0、股票及流通市值覆盖均为 100%。信号方向没有在看到结果后翻转。

| 因子 | 事前逻辑与方向 | Pure Rank IC / IC_IR | Pure D1月超额 / t | 最终判断 |
|---|---|---:|---:|---|
| `margin_demand_continuation_5` | A股散户和杠杆盘分批建仓，5日异常净需求预示延续 | 0.0024 / 0.070 | -0.14% / -0.72 | 预测力、D1、单调性和主板域等失败 |
| `margin_demand_continuation_10` | 政策/主题信息渐进加仓，10日净需求预示延续 | 0.0026 / 0.075 | -0.22% / -1.27 | 全部核心预测门槛及各稳健域失败 |
| `margin_flow_acceleration_5_20` | 5日相对20日融资需求加速包含新信息 | -0.0054 / -0.174 | -0.25% / -1.25 | 方向、显著性、单调性及多个域失败 |
| `margin_crowding_reversal_20` | 杠杆追涨和强平约束导致20日拥挤后反转 | -0.0072 / -0.206 | -0.18% / -1.14 | 原始IC正比例61.1%，但中性化后变负，属于风格污染 |
| `margin_balance_crowding_20` | 融资余额快速堆积提高踩踏风险 | -0.0062 / -0.184 | -0.14% / -0.92 | 原始IC正比例61.1%，纯净后变负且OOS/主板为负 |

这批结果不支持把简单融资需求或余额变化作为独立月频纯多头 Alpha。后续若继续研究，应采用事前明确的“条件事件”设计，例如融资需求与政策/主题状态、估值状态或急跌后的强平约束交互，而不是简单把上述五个因子翻号。

## 59 因子动物园摘要

59 个候选全部未通过。失败数最多的门槛为：Pure IC_IR（59/59）、原始 D1 月超额大于 1.5%（59/59）、Pure IC 绝对值（58/59）、原始 D1 t 值（57/59）和十组单调性（57/59）。最接近但仍不达标的候选包括 `holder_concentration_level`、`conservative_equity_growth`、`formulaic_012`、`cash_revenue_confirmation_yoy` 和 `price_volume_divergence`；详细构造逻辑及每项失败门槛见动物园正文。

## 数据扩充遗留与不可作弊边界

- `share_float`：按日期拉取时单日记录量超过接口可稳定分页/偏移的边界，已有月度分片只能作为接口失败证据，不能作为正式全市场解禁因子数据。不得把不完整样本当作零解禁。
- 财务现金确认：本地财务表覆盖不足，三个候选的数据门槛和预测门槛均失败。继续前应优先补全公告日可见的利润表、资产负债表和现金流量表，再做 PIT TTM 变化量。
- 动物园只描述冻结的 59 因子；融资五因子属于下一批研究，保留在本检查点和 64 因子 JSON 中，避免改写历史样本。
- 当前 0 个入库因子是有效研究结论。禁止降低阈值、结果后翻向、删除失败月份或把不完整事件数据填零来凑足 5 个。

## 踩坑与下一次续跑顺序

1. 当前评估器对每个因子重复构造中性化设计矩阵，64 因子全跑耗时较长。优化时必须先写等价性测试，再缓存每月相同的行业/风格设计矩阵，确保结果逐项一致。
2. PowerShell 默认显示 UTF-8 中文时可能出现乱码；文件本身为 UTF-8，读取时应显式使用 `Get-Content -Encoding utf8`。
3. `margin_detail_errors.json` 是历史日志，不能仅因它存在就判断任务未完成；用 manifest 和交易日差集审计。
4. 下一批优先级：先评估 Tushare 3000 权限下可完整取得的 `pledge_stat`/`stk_holdernumber` 增量事件覆盖，再决定是否构造质押压力变化或更严格的股东户数异常残差；任何新方向必须在看收益前写入 metadata。

## 本轮继续扩充：质押明细（进行中）

- 权限窄探针已成功：`pledge_stat` 对 `000001.SZ` 返回 637 行；`pledge_detail` 返回完整字段但该股票为真实空集。证据为 `artifacts/alpha_phase1/tushare/permission_smoke_pledge.json`。
- `pledge_stat` 只有 `end_date`、没有 `ann_date`，不满足本项目严格 PIT 要求；因此不直接拿它回测。`pledge_detail` 包含 `ann_date`、质押开始/结束/解押日期，可用于事件面板。
- 已新增断点脚本 `scripts/alpha_phase1/fetch_tushare_pledge_detail.py`，按 5,872 只历史证券逐股保存分片，真实空集也写零行 Parquet，避免重启后重复调用。
- 截至本检查点写入时已完成 176 个股票分片、34,735 行；全量抓取仍在运行。只有最终分片数等于 5,872 且 manifest 完成公告日缺失与重复审计后，才允许构造质押因子。
- 沙箱内首次权限探针被 Windows 网络策略阻断，表现为所有已知可用接口同时 `WinError 10013`；沙箱外窄探针成功，证明这不是 Tushare 权限失败。失败的全接口探针文件是诊断证据，不能作为权限结论。

## 最小复现命令

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/research/alpha_phase1 -q
python -m scripts.alpha_phase1.evaluate_factors_long_only --artifact-dir artifacts/alpha_phase1 --tushare-dir artifacts/alpha_phase1/tushare --output artifacts/alpha_phase1/factor_evaluation_long_only_v2.json --pure-panel artifacts/alpha_phase1/factor_panel_pure_long_only_v2.parquet
```
