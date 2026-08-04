from dataclasses import replace
from typing import Sequence
from uuid import UUID
from .domain import *
from .errors import RepositoryConflict
class InMemoryFundamentalRepository:
    def __init__(self):
        self.metrics={}; self.mappings={}; self.filings={}; self.facts=[]; self.quality={}; self.events=[]; self.shares=[]
    def save_definition(self, metric, mappings):
        if metric.metric_id in self.metrics: raise RepositoryConflict("metric exists")
        self.metrics[metric.metric_id]=metric
        for x in mappings:
            key=(x.source,x.source_field)
            if key in self.mappings: raise RepositoryConflict("mapping exists")
            self.mappings[key]=x
    def get_mapping(self,source,field): return self.mappings.get((source.strip().lower(),field))
    def get_metric(self,metric_id): return self.metrics.get(metric_id)
    def find_filing(self,source,source_filing_id,revision): return self.filings.get((source.strip().lower(),source_filing_id,revision))
    def filing_revisions(self,source,source_filing_id): return tuple(x for k,x in self.filings.items() if k[:2]==(source.strip().lower(),source_filing_id))
    def save_rejected(self,filing,identity,results):
        self.quality[identity]=tuple(results)
        if filing: self.filings[identity]=replace(filing,status=FilingStatus.REJECTED)
    def publish(self,filing,facts,event):
        key=(filing.source,filing.source_filing_id,filing.revision)
        if key in self.filings: raise RepositoryConflict("filing exists")
        self.filings[key]=replace(filing,status=FilingStatus.PUBLISHED); self.facts.extend(facts); self.events.append(event)
    def published_facts(self):
        return tuple((x,self.filings[(x.source,next(f.source_filing_id for f in self.filings.values() if f.filing_id==x.filing_id),x.revision)]) for x in self.facts)
    def quality_results(self,identity): return self.quality.get(identity,())
    def latest_event(self): return self.events[-1] if self.events else None
    def save_share_change(self,change): self.shares.append(change)
    def share_changes(self,instrument_id): return tuple(x for x in self.shares if x.instrument_id==instrument_id)
