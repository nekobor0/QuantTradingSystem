# V6阻塞与待裁决

以下均为外部数据源阻断，不影响V6 Phase 1与Downside Beta研究结论；禁止填零或发布到生产层：

- `stock_st`：607任务中453 valid、154个稳定源空日期。
- `financial`：6,555任务中6,521 valid、34个稳定源空证券/年代区间。
- `index`：259任务中256 valid；沪深300、中证500、中证1000的2016-01权重均源空。
- `event`：829任务中645 valid、184个稳定源空月份。质押明细有17个晚于2026-07-31的合同`end_date`，但其ann/start/release日期均未越过数据截止日；作为未来合同到期日保留，不得误判为未来信息可用日。

完整逐项身份、request hash与日期范围见`artifacts/data_audits/tushare_backfill_*_v6.json`。总体验收为`DATA_BLOCKED_PARTIAL`，生产发布门禁保持关闭。
