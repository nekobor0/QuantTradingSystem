# 初版数据字典

以下是核心实体和不可妥协的时点字段。具体 SQL 类型与索引在数据库实施阶段冻结。

## 通用约定

- 内部关联只用稳定 UUID `instrument_id`；交易代码是有生效区间的别名。
- 事件时间 `event_at` 表示市场/业务发生时间；`available_at` 表示系统当时最早可知时间；`ingested_at` 表示入库时间。
- 所有带修订的数据包含 `source`、`source_record_id`、`dataset_batch_id` 和 `revision`。
- 时间戳存 UTC；交易日期保持交易所本地自然日。
- 金额带 `currency`，成交量明确股/手，比例统一存小数而非百分数。

## 核心实体

### instrument

`instrument_id`, `asset_type`, `exchange`, `board`, `currency`, `list_date`, `delist_date`, `lot_size`, `status_valid_from`, `status_valid_to`

`asset_type` 至少区分 A_SHARE、HK_STOCK_CONNECT、ETF_DOMESTIC、ETF_QDII/OVERSEAS_LINKED。

### instrument_alias

`instrument_id`, `source`, `source_code`, `valid_from`, `valid_to`

解决 `600000.SH`、`sh.600000`、`600000` 等格式，不在业务表重复猜测代码。

### universe_membership

`universe_id`, `instrument_id`, `valid_from`, `valid_to`, `announced_at`, `available_at`, `source`

用于港股通、指数成分、行业分类和策略池。禁止只存“当前成分”。

### bar

`instrument_id`, `frequency`, `trading_date`, `bar_end_at`, `open`, `high`, `low`, `close`, `volume_shares`, `turnover`, `currency`, `source`, `dataset_batch_id`

唯一键建议为 `(instrument_id, frequency, bar_end_at, source)`。保存未复权事实值。

### adjustment_factor / corporate_action

`instrument_id`, `ex_date`, `factor`, `factor_definition`, `action_type`, `announced_at`, `available_at`, `source`

后复权值由未复权行情和有版本的因子计算。必须写清因子方向与基准日。

### fundamental_fact

`instrument_id`, `metric_id`, `period_end`, `period_type`, `value`, `unit`, `currency`, `announced_at`, `available_at`, `revision`, `source`

策略按 `available_at <= decision_at` 查询，不能用今天看到的最新版回填历史。

### feature_value

`instrument_id`, `as_of_date`, `feature_id`, `value`, `feature_version`, `data_snapshot_id`, `calculated_at`

### strategy_run / target_position

`strategy_run_id`, `strategy_version`, `parameter_hash`, `data_snapshot_id`, `decision_at`, `valid_for_date`, `instrument_id`, `target_weight`, `score`, `reason_codes`

目标组合必须包含显式现金权重或保证权重和不超过 1。

### recommendation

`recommendation_id`, `strategy_run_id`, `instrument_id`, `side`, `quantity`, `limit_price`, `valid_from`, `expires_at`, `risk_status`, `approval_status`

纯多头不代表没有 SELL；SELL 只能减少已有多头仓位，不得形成负持仓。

### order / fill

`order_id`, `recommendation_id`, `broker_order_id`, `submitted_at`, `status`, `instrument_id`, `side`, `quantity`, `limit_price`

`fill_id`, `order_id`, `filled_at`, `quantity`, `price`, `commission`, `tax`, `other_fee`, `currency`, `source`

持仓和现金由 fill 与资金事件派生；人工调整必须作为单独 adjustment 事件留下原因和操作者。

### risk_check / reconciliation

`risk_check_id`, `subject_type`, `subject_id`, `rule_version`, `severity`, `result`, `observed_value`, `threshold`, `checked_at`

`reconciliation_id`, `as_of_date`, `source`, `status`, `difference_type`, `expected_value`, `actual_value`, `resolution`
