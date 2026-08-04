# 05 特征与因子模块

## 目标与边界

把时点正确的行情、基本面和证券池快照转换为有定义、有版本、可复现的特征值，并提供横截面处理、有效性诊断和血缘。

本模块不决定买卖、不自动选择表现最好的参数，也不允许 Notebook 中的临时代码直接成为生产因子。

## 所有数据

- `feature_definition`：名称、经济含义、公式、输入、方向、频率、窗口、缺失策略和 owner。
- `feature_version`：代码版本、参数、依赖版本、最小历史长度和生效状态。
- `feature_value`：证券、`as_of_date`, 数值、版本、数据快照、计算时间和质量标记。
- `feature_set_snapshot`：一次策略运行使用的特征集合、截面成员和内容哈希。
- `feature_set_purpose`：`ETF_TIMING` 或 `EQUITY_DAILY_SELECTION`，决定允许的特征定义、频率和质量门禁。
- `feature_diagnostic`：覆盖率、分布、极值、换手、IC/ICIR 等研究结果；不作为源事实。

唯一键为 `(instrument_id, as_of_date, feature_version, data_snapshot_id)`。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `CalculateFeatureSet(feature_versions, as_of, universe_snapshot_id, data_snapshot_id)` | 幂等键为全部输入哈希 |
| Query | `GetRequiredFeatureSet(strategy_kind, decision_at)` | 返回该策略用途绑定的版本列表，禁止临时挑选当日表现最佳因子 |
| Query | `GetFeatureMatrix(feature_set_id)` | 返回固定行列、值、质量标记和血缘 |
| Query | `ExplainFeatureValue(instrument_id, feature_version, as_of)` | 返回输入切片与计算步骤，不返回未来数据 |
| Event | `FeatureSetCalculated` / `FeatureSetRejected` | 失败事件含质量门禁原因 |

## 主流程

冻结 universe 与数据 snapshot → 校验最小历史和输入可用时间 → 计算原始特征 → winsorize/标准化/行业或市值中性化（均显式版本）→ 质量检查 → 写不可变 feature set → 发布事件。局部失败不得悄悄缩小截面，必须记录缺失和排除原因。

首批 `ETF_TIMING` 特征集以趋势、动量、波动、回撤和流动性为主，按日计算供风险门控，周度调仓读取当日已冻结值。`EQUITY_DAILY_SELECTION` 特征集按日计算价值、质量、成长、动量、波动和流动性，并在 point-in-time 行业/市值截面上执行版本化处理。

## 业务规则

- 任一输入满足 `available_at <= decision_at`；滚动窗口只含 `as_of` 当日及以前。
- 后复权价只通过 market_data 的版本化查询取得，因子代码不能自行拼复权。
- 横截面处理的 universe snapshot 是输入的一部分，变更成员必须改变内容哈希。
- 缺失值策略按特征定义执行；禁止为了覆盖率无条件填 0。
- 诊断使用的未来收益只存在研究域，不得进入生产特征表。
- ETF 与个股特征不能写入同一个无用途标记的 feature set；个股横截面处理不得把 ETF 样本混入基准分布。

## 失败、幂等与并发

输入快照缺失返回 `SNAPSHOT_NOT_READY`，历史不足标记 `INSUFFICIENT_HISTORY`，门禁失败为 `FEATURE_QUALITY_FAILED`。相同输入哈希重跑复用结果；版本或数据修订改变时生成新 feature set，不覆盖旧值。

## 可观测与安全

监控覆盖率、空值、极值、分布漂移、计算耗时和输入陈旧度；因子失效告警只提示复核，不自动改权重或停用版本。

## 测试与验收

- 在输入尾部追加未来数据，历史日期特征哈希保持不变。
- 手算动量/估值黄金样本一致；窗口边界和不足历史标记正确。
- 相同快照重跑不新增值；换 universe/参数/代码版本一定改变 feature_set_id。
- 故意混入公告后才可见的财务值，计算必须拒绝。
- ETF 风险门控日频值与个股日频因子矩阵各有手算黄金样本；交换两者 universe snapshot 时计算必须拒绝。

## 不做事项

不做自动因子挖掘上线，不在计算层执行组合约束，不把 IC 最优等同于可交易策略。
