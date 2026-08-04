from __future__ import annotations
import hashlib,json
from dataclasses import replace
from datetime import date, datetime,timezone
from decimal import Decimal,InvalidOperation
from typing import Sequence
from uuid import UUID
from quant_trading_system.instruments import InstrumentService
from .domain import *
from .errors import *
from .ports import FundamentalRepository

class FundamentalService:
    def __init__(self,repository: FundamentalRepository,instruments: InstrumentService): self.repository=repository; self.instruments=instruments
    def define_metric(self,metric: MetricDefinition,mappings: Sequence[SourceMapping]): self.repository.save_definition(metric,mappings)
    def ingest(self,command: IngestFilingCommand) -> Filing:
        identity=(command.source.strip().lower(),command.source_filing_id,command.revision)
        payload_hash=hashlib.sha256(json.dumps({"command":repr(command)},sort_keys=True).encode()).hexdigest()
        existing=self.repository.find_filing(*identity)
        if existing:
            if existing.payload_hash!=payload_hash: raise FilingConflict("same filing revision has different content")
            return existing
        failures=[]
        if command.announced_at is None or command.available_at is None:
            failures.append(QualityResult("INVALID_AVAILABILITY","announcement and availability are required"))
            self.repository.save_rejected(None,identity,failures); raise IngestionRejected(failures[0].code)
        instrument=self.instruments.resolve(command.source,command.source_code,command.announced_at.date()).instrument
        try:
            filing=Filing(instrument.instrument_id,command.source,command.source_filing_id,command.revision,command.report_type,command.period_end,command.announced_at,command.available_at,command.ingested_at,command.raw_uri,payload_hash)
        except InvalidFundamental as exc:
            self.repository.save_rejected(None,identity,[QualityResult("INVALID_AVAILABILITY",str(exc))]); raise IngestionRejected(str(exc)) from exc
        facts=[]
        for item in command.facts:
            mapping=self.repository.get_mapping(command.source,item.source_field)
            if mapping is None: failures.append(QualityResult("UNKNOWN_METRIC",item.source_field,item.source_field)); continue
            metric=self.repository.get_metric(mapping.metric_id)
            if metric is None or mapping.source_unit != item.source_unit: failures.append(QualityResult("UNIT_MISMATCH",item.source_unit,item.source_field)); continue
            try: value=None if item.raw_value is None else Decimal(str(item.raw_value))*mapping.scale
            except InvalidOperation: failures.append(QualityResult("INVALID_VALUE",str(item.raw_value),item.source_field)); continue
            if metric.value_kind is ValueKind.PERCENT and value is not None: value/=Decimal("100")
            facts.append(FundamentalFact(filing.filing_id,instrument.instrument_id,metric.metric_id,item.period_end,item.period_type,filing.source,filing.revision,value,metric.unit,item.currency,None if item.raw_value is None else str(item.raw_value)))
        if failures:
            self.repository.save_rejected(filing,identity,failures); raise IngestionRejected(",".join(x.code for x in failures))
        old=max(self.repository.filing_revisions(filing.source,filing.source_filing_id),key=lambda x:x.available_at,default=None)
        event=FundamentalRevisionEvent(filing.filing_id,instrument.instrument_id,None if old is None else old.revision,filing.revision,tuple((x.period_end,x.metric_id) for x in facts),datetime.now(timezone.utc))
        self.repository.publish(filing,facts,event)
        return replace(filing,status=FilingStatus.PUBLISHED)
    def get_facts(self,ids: Sequence[UUID],metrics: Sequence[UUID],decision_at: datetime,policy: QueryPolicy=QueryPolicy.LATEST_AVAILABLE,source_priority: SourcePriorityPolicy|None=None):
        decision_at=aware(decision_at,"decision_at")
        candidates=[(x,f) for x,f in self.repository.published_facts() if x.instrument_id in ids and x.metric_id in metrics and f.available_at<=decision_at]
        groups: dict[tuple[UUID, UUID, object, object], list[tuple[FundamentalFact, Filing]]] = {}
        for x,f in candidates: groups.setdefault((x.instrument_id,x.metric_id,x.period_end,x.period_type),[]).append((x,f))
        out=[]
        for values in groups.values():
            if policy is QueryPolicy.SOURCE_PRIORITY:
                if source_priority is None: raise InvalidFundamental("source priority policy requires sources")
                ranks={s.lower():i for i,s in enumerate(source_priority.sources)}
                values.sort(key=lambda pair:(-ranks.get(pair[0].source,999),pair[1].available_at,pair[0].revision))
            else: values.sort(key=lambda pair:(pair[1].available_at,pair[0].revision))
            out.append(values[-1][0])
        return tuple(sorted(out,key=lambda x:(str(x.instrument_id),str(x.metric_id),x.period_end)))
    def get_latest_known_fact(self,instrument_id,metric_id,decision_at):
        values=self.get_facts([instrument_id],[metric_id],decision_at)
        if not values: raise FactNotFound("no visible fact")
        return max(values,key=lambda x:x.period_end)
    def record_share_change(self,change: ShareCapitalChange) -> None:
        self.repository.save_share_change(change)
    def get_share_capital(self,instrument_id: UUID,effective_at: date,decision_at: datetime) -> ShareCapitalChange:
        decision_at=aware(decision_at,"decision_at")
        values=[x for x in self.repository.share_changes(instrument_id) if x.effective_date<=effective_at and x.available_at<=decision_at]
        if not values: raise FactNotFound("no visible share capital")
        return max(values,key=lambda x:(x.effective_date,x.available_at))

def ytd_to_quarter(current: FundamentalFact,previous: FundamentalFact|None) -> FundamentalFact:
    if current.period_type is not PeriodType.YTD or current.value is None: raise DerivationUnavailable("current YTD value required")
    lineage: tuple[UUID, ...]
    if current.period_end.month==3: value=current.value; lineage=(current.fact_id,)
    else:
        if previous is None or previous.value is None or previous.period_type is not PeriodType.YTD or previous.instrument_id!=current.instrument_id or previous.metric_id!=current.metric_id or previous.period_end.year!=current.period_end.year: raise DerivationUnavailable("previous same-year YTD required")
        value=current.value-previous.value; lineage=(previous.fact_id,current.fact_id)
    return replace(current,period_type=PeriodType.QUARTER,value=value,lineage=lineage,fact_id=UUID(int=(current.fact_id.int+1)%(1<<128)))

def quarters_to_ttm(values: Sequence[FundamentalFact]) -> FundamentalFact:
    ordered=sorted(values,key=lambda x:x.period_end)
    if len(ordered)!=4 or any(x.period_type is not PeriodType.QUARTER or x.value is None for x in ordered): raise DerivationUnavailable("four complete quarters required")
    months=[]
    for a,b in zip(ordered,ordered[1:]): months.append((b.period_end.year-a.period_end.year)*12+b.period_end.month-a.period_end.month)
    if months != [3,3,3] or len({(x.instrument_id,x.metric_id) for x in ordered})!=1: raise DerivationUnavailable("quarters must be consecutive and homogeneous")
    return replace(ordered[-1],period_type=PeriodType.TTM,value=sum((x.value for x in ordered if x.value is not None),Decimal()),lineage=tuple(x.fact_id for x in ordered),fact_id=UUID(int=(ordered[-1].fact_id.int+1)%(1<<128)))
