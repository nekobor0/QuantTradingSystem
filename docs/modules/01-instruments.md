# 01 证券主数据模块

## 目标与边界

为每个可研究或交易的标的分配稳定的 `instrument_id`，管理代码别名、交易所、板块、币种、上市生命周期和交易规格。所有模块必须先解析到该 ID 再存事实。

本模块不持有行情、停牌、港股通资格、行业成员或持仓；这些是带日期变化的其他领域事实。

## 所有数据

- `instrument`：`instrument_id`, `asset_type`, `exchange`, `board`, `currency`, `list_date`, `delist_date`, `lifecycle_status`。
- `instrument_alias`：来源代码及 `[valid_from, valid_to)` 生效区间。
- `trading_spec`：整手、价格最小变动、申报数量边界及生效区间。
- `instrument_source_record`：来源记录、批次、映射状态和人工裁决。

唯一约束：同一来源的同一代码在任一时点只能映射一个证券；同一证券可有多个来源别名。代码变更不得创建新证券，除非经济实体和交易合约确实变化。

## 接口契约

| 类型 | 契约 | 关键语义 |
|---|---|---|
| Command | `RegisterInstrument(source_record, batch_id)` | 幂等键 `(source, source_record_id, revision)`；歧义不自动猜测 |
| Command | `ChangeLifecycle(instrument_id, status, effective_from, reason)` | 不得形成重叠区间 |
| Query | `ResolveInstrument(source, code, as_of)` | 必须传 `as_of`；返回唯一 ID、未找到或歧义错误 |
| Query | `GetTradingSpec(instrument_id, as_of)` | 返回当日有效交易单位与币种 |
| Event | `InstrumentRegistered` / `InstrumentStatusChanged` | 带生效时间和来源批次 |

## 主流程与状态

`CANDIDATE → LISTED → DELISTED`；错误源记录进入 `QUARANTINED`，不进入可交易证券池。重新上市是否复用原 ID 必须由明确市场标识和人工裁决决定。

批次导入先规范交易所代码格式，再按强标识匹配；一对多、多对一或日期区间冲突进入隔离清单。任何人工合并或拆分都写审计记录。

## 业务规则

- `asset_type` 至少支持 A_SHARE、HK_STOCK_CONNECT_ELIGIBLE_SECURITY、ETF_DOMESTIC、ETF_OVERSEAS_LINKED；港股通“资格”仍由 universe 模块按日判断。
- 上市前和退市后的日期查询可解析身份，但不得标记为可交易。
- 北交所、科创板和创业板由交易所/板块字段明确表达，禁止从当前代码前缀永久推断。
- 名称可重复、可变化，永不作为键。

## 失败、幂等与并发

未知代码返回 `INSTRUMENT_NOT_FOUND`；多重匹配返回 `ALIAS_AMBIGUOUS`；区间冲突返回 `VALIDITY_OVERLAP`。批次重跑不得新增重复证券。写操作按来源记录或证券 ID 加事务锁，失败批次整体不发布。

## 可观测与安全

监控未映射率、歧义数、生命周期冲突和新证券增量；异常突增阻断数据批次。人工裁决记录操作者、前后值、原因和时间。

## 测试与验收

- 同一证券用 `600000.SH`、`sh.600000`、`600000` 在有效日期解析为同一 ID。
- 代码生效区间边界前后解析正确，重叠区间写入失败。
- 批次重跑两次后证券、别名计数和内容哈希不变。
- 上市前/退市后可识别但 `tradable=false`；名称变化不改变 ID。

## 不做事项

不依据实时行情判断停牌/涨跌停，不维护组合证券池，不提供模糊名称搜索作为业务关联方式。
