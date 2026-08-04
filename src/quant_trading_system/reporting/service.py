from __future__ import annotations
import csv,hashlib,html,io,json,re
from decimal import Decimal
from uuid import UUID
from .domain import *
from .errors import *
from .ports import ReportingRepository

class ReportingService:
 def __init__(self,repository:ReportingRepository):self.repository=repository
 def build_report(self,command:BuildReport)->ReportResult:
  d=command.definition;self.repository.save_definition(d);input_hash=self._hash({"definition":d,"period":command.period,"inputs":sorted((str(x.source_id),x.content_hash) for x in command.inputs),"curve":command.curve,"trades":command.trades,"attributions":command.attributions,"summaries":command.strategy_summaries,"fx":command.fx_rates,"template":command.template_fields})
  existing=self.repository.find_run(input_hash)
  if existing:
   result=self.repository.get_result(existing.run_id)
   if result is None:raise ReportConflict("report input is already building")
   return result
  run_id=UUID(bytes=hashlib.sha256(input_hash.encode()).digest()[:16]);metrics=self._metrics(run_id,command);attributions=tuple(SleeveAttribution(run_id,x.component,x.dimension,x.value,x.source_run_id,x.source_reference,x.instrument_id) for x in command.attributions);summaries=tuple(ReportStrategySummary(run_id,x.kind,x.strategy_run_id,x.select_count,x.keep_count,x.exit_count,x.candidate_stability,x.turnover,x.daily_gate,x.rebalance_days,x.cash_state) for x in command.strategy_summaries)
  quality=self._quality(run_id,command,metrics,attributions,summaries);passed=all(x.outcome is QualityOutcome.PASS for x in quality);status=ReportRunStatus.COMPLETED if passed else ReportRunStatus.INCOMPLETE
  canonical={"metrics":[(x.name,str(x.value),x.unit,x.formula) for x in metrics],"attribution":[(x.component,x.dimension.value,str(x.value),str(x.source_run_id)) for x in attributions],"summaries":[(x.kind.value,x.select_count,x.keep_count,x.exit_count,str(x.candidate_stability),str(x.turnover),x.daily_gate,[str(v) for v in x.rebalance_days],x.cash_state) for x in summaries],"quality":[(x.check_name,x.outcome.value,x.observed,x.expected) for x in quality]};content_hash=self._hash(canonical)
  run=ReportRun(d.definition_id,command.period,input_hash,content_hash,status,d.mode,d.template_version,d.code_version,d.benchmark,d.risk_free_rate,d.annualization_days,command.fx_snapshot_id,command.generated_at,run_id)
  artifacts=self._artifacts(run,command,metrics,attributions,summaries,passed);result=ReportResult(run,command.inputs,metrics,attributions,summaries,artifacts,quality);event_type="ReportSnapshotBuilt" if passed else "ReportBuildIncomplete";self.repository.save_result(result,ReportEvent(event_type,run_id,command.generated_at,{"status":status.value}));return result
 def get_report(self,run_id:UUID)->ReportResult:
  value=self.repository.get_result(run_id)
  if value is None:raise ReportNotFound(str(run_id))
  return value
 def explain_metric(self,run_id:UUID,name:str)->MetricExplanation:
  result=self.get_report(run_id);metric=next((x for x in result.metrics if x.name==name),None)
  if metric is None:raise ReportNotFound(name)
  inputs=tuple(x for x in result.inputs if x.source_id in metric.source_snapshot_ids)
  if len(inputs)!=len(set(metric.source_snapshot_ids)):raise ReportConflict("metric source reference is broken")
  return MetricExplanation(metric,inputs)
 def get_sleeve_attribution(self,run_id:UUID)->tuple[SleeveAttribution,...]:return self.get_report(run_id).attributions
 def verify_artifact(self,artifact:ReportArtifact)->bool:
  if self._hash_text(artifact.content)!=artifact.content_hash:raise ArtifactIntegrityError("artifact content hash mismatch")
  return True
 def _metrics(self,run_id,command):
  curve=tuple(sorted((x for x in command.curve if x.mode is command.definition.mode),key=lambda x:x.at));trades=tuple(x for x in command.trades if x.mode is command.definition.mode and x.filled)
  refs=tuple(dict.fromkeys(x.source_reference for x in (*curve,*trades)));ids=tuple(dict.fromkeys(x.source_snapshot_id for x in (*curve,*trades)))
  if curve and all(x.nav.is_finite() for x in curve):
   total_return=curve[-1].nav/curve[0].nav-1;peak=curve[0].nav;max_dd=Decimal()
   for point in curve:peak=max(peak,point.nav);max_dd=min(max_dd,point.nav/peak-1)
   average_nav=sum((x.nav for x in curve),Decimal())/len(curve)
  elif curve:total_return=max_dd=Decimal("NaN");average_nav=Decimal()
  else:total_return=max_dd=Decimal();average_nav=Decimal()
  gross=sum((self._convert(x.gross,x.currency,command) for x in trades),Decimal());fees=sum((self._convert(x.fee,x.currency,command) for x in trades),Decimal());turnover=gross/average_nav if average_nav else Decimal()
  rows=(("total_return",total_return,"ratio","Ending NAV / Starting NAV - 1","nav_end/nav_start-1"),("max_drawdown",max_dd,"ratio","Minimum NAV / prior peak - 1","min(nav/running_peak-1)"),("turnover",turnover,"ratio","Filled gross notional / average NAV","sum(abs(filled_gross_base))/avg_nav"),("fees",fees,command.definition.base_currency,"Actual/simulated fill fees converted by frozen FX","sum(fill_fee*fx_rate)"))
  return tuple(ReportMetric(run_id,n,v.quantize(Decimal("0.0000000001")),u,definition,formula,ids,refs,f"report://{run_id}/metric/{n}/detail") for n,v,u,definition,formula in rows)
 def _convert(self,amount,currency,command):
  if currency==command.definition.base_currency:return amount
  key=f"{currency}/{command.definition.base_currency}"
  if command.fx_snapshot_id is None or key not in command.fx_rates:raise InvalidReportInput("explicit FX snapshot and rate required")
  return amount*command.fx_rates[key]
 def _quality(self,run_id,command,metrics,attributions,summaries):
  values=[]
  def add(name,passed,observed,expected,explanation):values.append(ReportQualityResult(run_id,name,QualityOutcome.PASS if passed else QualityOutcome.FAIL,str(observed),str(expected),explanation))
  d=command.definition;source_types={x.source_type for x in command.inputs};add("REQUIRED_SOURCES",set(d.required_source_types).issubset(source_types),source_types,d.required_source_types,"all required source types must be frozen")
  add("INPUT_QUALITY",all(x.quality is InputQuality.PASS for x in command.inputs),[x.quality.value for x in command.inputs],"PASS","upstream quality must pass")
  add("MODE_ISOLATION",all(x.source_mode is d.mode for x in command.inputs) and all(x.mode is d.mode for x in command.curve) and all(x.mode is d.mode for x in command.trades),"modes",d.mode.value,"curves and facts cannot mix LIVE/PAPER/BACKTEST")
  live_sources=[x for x in command.inputs if x.source_type=="execution_ledger"]
  live_ok=d.mode is not ReportMode.LIVE or (bool(live_sources) and all(x.reconciled for x in live_sources))
  add("LIVE_RECONCILIATION",live_ok,[x.reconciled for x in live_sources],True,"LIVE reports require reconciled execution_ledger")
  add("FILLED_TRADES_ONLY",all(x.filled for x in command.trades),[x.filled for x in command.trades],True,"unfilled recommendations cannot enter performance")
  refs={x.source_id for x in command.inputs};used={x.source_snapshot_id for x in (*command.curve,*command.trades)};add("SOURCE_REFERENCES",used.issubset(refs),used,refs,"every curve/trade point must link to an input snapshot")
  add("CURVE_PRESENT",bool(command.curve),len(command.curve),">0","performance reports require a frozen curve")
  dates_ok=all(command.period.start<=x.at.date()<=command.period.end for x in command.curve) and all(command.period.start<=x.occurred_at.date()<=command.period.end for x in command.trades)
  add("PERIOD_BOUNDS",dates_ok,"curve/trade dates",f"{command.period.start}..{command.period.end}","all displayed facts must fall inside the report period")
  missing_days=sum(int(x.facts.get("missing_trading_days",0)) for x in command.inputs);add("TRADING_DAYS_COMPLETE",missing_days==0,missing_days,0,"missing trading days make report incomplete")
  diffs=[]
  for x in live_sources:
   if all(k in x.facts for k in ("account_cash","account_position_value","account_total")):diffs.append(dec(x.facts["account_cash"])+dec(x.facts["account_position_value"])-dec(x.facts["account_total"]))
  add("ACCOUNT_RECONCILIATION",all(v==0 for v in diffs),diffs,0,"cash plus positions must equal source account total exactly")
  add("FINITE_METRICS",all(x.value.is_finite() for x in metrics),[str(x.value) for x in metrics],"finite","display metrics must be finite")
  missing_fields=[x for x in d.required_template_fields if not command.template_fields.get(x,"").strip()];add("TEMPLATE_FIELDS",not missing_fields,missing_fields,(),"required template fields cannot default silently")
  summary_kinds={x.kind for x in summaries};add("DUAL_STRATEGY_SUMMARY",summary_kinds=={StrategyKind.ETF_TIMING,StrategyKind.EQUITY_DAILY_SELECTION},[x.value for x in summary_kinds],[x.value for x in (StrategyKind.ETF_TIMING,StrategyKind.EQUITY_DAILY_SELECTION)],"both first strategy summaries are required")
  metric_map={AttributionDimension.RETURN:"total_return",AttributionDimension.RISK:"max_drawdown",AttributionDimension.TURNOVER:"turnover",AttributionDimension.COST:"fees"};metric_values={x.name:x.value for x in metrics};required_components={"ETF_TIMING","EQUITY_DAILY_SELECTION","CROSS_CONSTRAINT","CASH"}
  for dimension,name in metric_map.items():
   rows=[x for x in attributions if x.dimension is dimension];components={x.component for x in rows};total=sum((x.value for x in rows),Decimal());expected=metric_values[name];add("ATTRIBUTION_"+dimension.value,components==required_components and total.is_finite() and expected.is_finite() and abs(total-expected)<=Decimal("0.0000000001"),f"components={components},sum={total}",expected,"four attribution components must reconcile to portfolio metric")
  return tuple(values)
 def _artifacts(self,run,command,metrics,attributions,summaries,publishable):
  title=self._mask(command.template_fields.get("title",command.definition.name));audience=self._mask(command.definition.audience);metric_rows="".join(f"<tr><td>{html.escape(x.name)}</td><td>{html.escape(str(x.value))}</td><td>{html.escape(x.unit)}</td></tr>" for x in metrics);body=f"<!doctype html><html><head><title>{html.escape(title)}</title></head><body><h1>{html.escape(title)}</h1><p>mode={run.mode.value}; audience={html.escape(audience)}</p><table>{metric_rows}</table></body></html>"
  stream=io.StringIO(newline="");writer=csv.writer(stream,lineterminator="\n");writer.writerow(("metric","value","unit","formula"));[writer.writerow((x.name,str(x.value),x.unit,x.formula)) for x in metrics];csv_text=stream.getvalue();chart=json.dumps({x.name:str(x.value) for x in metrics},sort_keys=True,separators=(",",":"))
  rows=((ArtifactFormat.HTML,"report.html",body),(ArtifactFormat.CSV,"metrics.csv",csv_text),(ArtifactFormat.CHART_DATA,"chart.json",chart));return tuple(ReportArtifact(run.run_id,f,ref,content,self._hash_text(content),run.generated_at,command.definition.sensitivity,publishable) for f,ref,content in rows)
 @staticmethod
 def _mask(value):return re.sub(r"(?<!\d)\d{8,}(?!\d)",lambda m:"*"*(len(m.group())-4)+m.group()[-4:],value)
 @staticmethod
 def _hash(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,separators=(",",":")).encode()).hexdigest()
 @staticmethod
 def _hash_text(x):return hashlib.sha256(x.encode()).hexdigest()
