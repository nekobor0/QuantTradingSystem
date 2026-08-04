# 阶段一 V4 断点记录（2026-07-30）

## 冻结口径

- 用户将所有新评价的买入价从T+1收盘改为T+1复权开盘；信号日、退出日、方向、核心窗口、门槛和样本切分不变。
- V4规范见`EVALUATOR_V4_SPEC.md`；旧V3面板和结果永久保留，V4使用独立文件名。
- 第二轮反馈后的优先级是先补完整风格风险模型，再研究季度基本面意外×反应不足及可证明完整的预定供给冲击；停止继续微调旧公式、简单订单流、回购完成、简单股东增持、静态户数和月频融资。

## 已完成

1. T+1开盘月频面板`factor_panel_raw_v4_t1_open.parquet`：554,400行、96个月、重复0。
2. T+1开盘日频面板`factor_panel_short_horizon_v4_t1_open.parquet`：9,009,889行、1,939日、重复0。
3. 旧候选V4复评无新增入库；完整数值已写入`FACTOR_ZOO_59.md`。
4. 新增风格工具`style_baseline.py`及5个测试；本地全A等权市场收益与252日Beta完成缓存。
5. 扩展风格面板`factor_panel_style_baseline_v4.parquet`：554,400行、96个月、重复0。活跃行Beta覆盖96.84%、Value 99.27%、Investment 93.80%。
6. 修复首版截面风格`groupby.apply`索引错位；修复前未运行任何新因子评价。
7. Tushare财务四接口非金融样本探测通过；全量`fina_indicator`逐股分片下载已启动。
8. Residual Volatility已从总波动代理升级为252日市场模型残差的60日波动；活跃行覆盖95.80%。
9. 慢变量1/3/6/12月T+1开盘标签完成，活跃行核心3个月覆盖94.37%、重复0。
10. 三个季度基本面意外候选已在结果前冻结，见`FUNDAMENTAL_SURPRISE_V4_SPEC.md`；PIT转换、公告反应收益、扩展中性化及3个月重叠收益HAC评价代码与测试已完成。
11. `fina_indicator`全量完成：5,872/5,872分片、聚合312,550行、缺分片0、最大单股81行、无100行截断，审计见`fina_indicator_audit.json`。
12. 三个季度候选已评价且全部拒绝：利润加速反应不足Pure 3个月+0.266%、HAC t=0.64；营收利润宽度-0.070%、t=-0.16；现金确认-0.502%、t=-1.33。无入库因子。

## 数据恢复方式

- 运行脚本：`scripts/alpha_phase1/fetch_tushare_financial_statements.py`
- 输出分片：`artifacts/alpha_phase1/tushare/shards/fina_indicator/*.parquet`
- 聚合目标：`artifacts/alpha_phase1/tushare/fina_indicator.parquet`
- manifest：`artifacts/alpha_phase1/tushare/financial_statements_manifest.json`
- 下载已经完成；重跑同一命令会验证并跳过5,872个现有分片。若未来扩展日期或字段，应使用新目录/版本，禁止静默覆盖当前冻结快照。

## 下一步（不得跳序）

1. 三个季度意外具体实现已经证伪，不因补三张报表而重跑或改窗口；保留失败日志。
2. 下一研究优先级转向可证明完整的预定供给冲击：先审计`share_float`权限、公告日/解禁日/股份类型/解禁股数与相对ADV20口径，再在结果前冻结事件定义。
3. 若预定供给数据不完整或接口权限不足，停止并报告缺失日期、代码、字段和替代方案；不得用当前自由流通股本月变化倒推公告前市场已知信息。
4. 完成下一物种机器评价、动物园记录与全测试后，再决定是否继续其他机制。
