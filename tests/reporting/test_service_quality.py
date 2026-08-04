from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import pytest
from quant_trading_system.reporting import *
from quant_trading_system.reporting.errors import *
from quant_trading_system.strategies import StrategyKind
from .conftest import NOW,make_command

def metric(result,name):return next(x for x in result.metrics if x.name==name)
def quality(result,name):return next(x for x in result.quality if x.check_name==name)

def test_golden_live_report_metrics(service,definition):
 result=service.build_report(make_command(definition));assert result.run.status is ReportRunStatus.COMPLETED
 assert metric(result,"total_return").value==Decimal("0.0500000000")
 assert metric(result,"max_drawdown").value==Decimal("-0.0454545455")
 assert metric(result,"turnover").value==Decimal("0.2857142857")
 assert metric(result,"fees").value==Decimal("3.0000000000")
 assert all(x.publishable for x in result.artifacts)

def test_idempotent_report_returns_same_run_and_hash(service,repo,definition):
 command=make_command(definition);first=service.build_report(command);second=service.build_report(command)
 assert first==second and len(repo.results)==1 and first.run.content_hash==second.run.content_hash

def test_source_revision_creates_new_run(service,definition):
 first=service.build_report(make_command(definition,content_hash="v1"));second=service.build_report(make_command(definition,content_hash="v2"))
 assert first.run.run_id!=second.run.run_id and first.run.input_hash!=second.run.input_hash

def test_unreconciled_live_is_incomplete_and_unpublishable(service,definition):
 result=service.build_report(make_command(definition,reconciled=False));assert result.run.status is ReportRunStatus.INCOMPLETE
 assert quality(result,"LIVE_RECONCILIATION").outcome is QualityOutcome.FAIL
 assert not any(x.publishable for x in result.artifacts)

@pytest.mark.parametrize("difference",["1","-1","0.01"])
def test_account_difference_any_nonzero_fails(service,definition,difference):
 result=service.build_report(make_command(definition,total_difference=Decimal(difference)));assert quality(result,"ACCOUNT_RECONCILIATION").outcome is QualityOutcome.FAIL

def test_exact_account_reconciliation_passes(service,definition):assert quality(service.build_report(make_command(definition)),"ACCOUNT_RECONCILIATION").outcome is QualityOutcome.PASS

@pytest.mark.parametrize("days",[1,2,10])
def test_missing_trading_days_incomplete(service,definition,days):
 result=service.build_report(make_command(definition,missing_days=days));assert quality(result,"TRADING_DAYS_COMPLETE").outcome is QualityOutcome.FAIL and result.run.status is ReportRunStatus.INCOMPLETE

def test_upstream_quality_fail_incomplete(service,definition):assert quality(service.build_report(make_command(definition,quality=InputQuality.FAIL)),"INPUT_QUALITY").outcome is QualityOutcome.FAIL

def test_unfilled_recommendation_fails_quality_and_does_not_enter_metrics(service,definition):
 normal=service.build_report(make_command(definition));bad=service.build_report(make_command(definition,include_unfilled=True,content_hash="with-unfilled"))
 assert metric(bad,"turnover").value==metric(normal,"turnover").value
 assert quality(bad,"FILLED_TRADES_ONLY").outcome is QualityOutcome.FAIL

@pytest.mark.parametrize("mode",[ReportMode.PAPER,ReportMode.BACKTEST,ReportMode.RESEARCH])
def test_mode_mixing_is_incomplete(service,definition,mode):
 result=service.build_report(make_command(definition,mode=mode));assert quality(result,"MODE_ISOLATION").outcome is QualityOutcome.FAIL

def test_missing_required_source_incomplete(service,definition):
 result=service.build_report(make_command(definition,source_type="other"));assert quality(result,"REQUIRED_SOURCES").outcome is QualityOutcome.FAIL

def test_broken_curve_reference_incomplete(service,definition):
 command=make_command(definition);curve=(replace(command.curve[0],source_snapshot_id=uuid4()),)+command.curve[1:];result=service.build_report(replace(command,curve=curve));assert quality(result,"SOURCE_REFERENCES").outcome is QualityOutcome.FAIL

def test_missing_template_field_incomplete(service,definition):
 command=make_command(definition);result=service.build_report(replace(command,template_fields={}));assert quality(result,"TEMPLATE_FIELDS").outcome is QualityOutcome.FAIL

def test_missing_strategy_summary_incomplete(service,definition):
 command=make_command(definition);result=service.build_report(replace(command,strategy_summaries=command.strategy_summaries[:1]));assert quality(result,"DUAL_STRATEGY_SUMMARY").outcome is QualityOutcome.FAIL

@pytest.mark.parametrize("dimension",list(AttributionDimension))
def test_each_attribution_dimension_reconciles(service,definition,dimension):assert quality(service.build_report(make_command(definition)),"ATTRIBUTION_"+dimension.value).outcome is QualityOutcome.PASS

def test_attribution_one_cent_mismatch_incomplete(service,definition):
 command=make_command(definition);row=command.attributions[0];attrs=(replace(row,value=row.value+Decimal("0.01")),)+command.attributions[1:];result=service.build_report(replace(command,attributions=attrs));assert quality(result,"ATTRIBUTION_RETURN").outcome is QualityOutcome.FAIL

def test_missing_cross_constraint_component_incomplete(service,definition):
 command=make_command(definition);attrs=tuple(x for x in command.attributions if not (x.dimension is AttributionDimension.COST and x.component=="CROSS_CONSTRAINT"));result=service.build_report(replace(command,attributions=attrs));assert quality(result,"ATTRIBUTION_COST").outcome is QualityOutcome.FAIL

def test_independent_strategy_run_ids_preserved(service,definition):
 result=service.build_report(make_command(definition));rows=[x for x in result.attributions if x.component in ("ETF_TIMING","EQUITY_DAILY_SELECTION")];assert all(x.source_run_id for x in rows)
 assert {x.kind for x in result.strategy_summaries}=={StrategyKind.ETF_TIMING,StrategyKind.EQUITY_DAILY_SELECTION}

def test_explain_metric_returns_formula_and_inputs(service,definition):
 result=service.build_report(make_command(definition));explanation=service.explain_metric(result.run.run_id,"total_return");assert explanation.metric.formula and explanation.input_snapshots

def test_unknown_report_and_metric(service,definition):
 with pytest.raises(ReportNotFound):service.get_report(uuid4())
 result=service.build_report(make_command(definition))
 with pytest.raises(ReportNotFound):service.explain_metric(result.run.run_id,"unknown")

def test_explain_detects_broken_source(service,repo,definition):
 result=service.build_report(make_command(definition));broken=replace(result,inputs=result.inputs[1:]);repo.results[result.run.run_id]=broken
 with pytest.raises(ReportConflict):service.explain_metric(result.run.run_id,"total_return")

def test_html_csv_chart_consume_same_metric_rows(service,definition):
 result=service.build_report(make_command(definition));contents={x.format:x.content for x in result.artifacts}
 for row in result.metrics:
  assert str(row.value) in contents[ArtifactFormat.HTML]
  assert str(row.value) in contents[ArtifactFormat.CSV]
  assert str(row.value) in contents[ArtifactFormat.CHART_DATA]

def test_sensitive_account_number_masked(service,definition):
 result=service.build_report(make_command(definition,account_label="account 123456789012"));html_artifact=next(x for x in result.artifacts if x.format is ArtifactFormat.HTML)
 assert "123456789012" not in html_artifact.content and "********9012" in html_artifact.content

@pytest.mark.parametrize("text",["<script>alert(1)</script>","A&B",'\"quoted\"'])
def test_html_escapes_template_text(service,definition,text):
 command=make_command(definition);result=service.build_report(replace(command,template_fields={"title":text}));content=next(x.content for x in result.artifacts if x.format is ArtifactFormat.HTML);assert text not in content

@pytest.mark.parametrize("format",list(ArtifactFormat))
def test_artifact_hash_verifies(service,definition,format):
 result=service.build_report(make_command(definition));artifact=next(x for x in result.artifacts if x.format is format);assert service.verify_artifact(artifact)

def test_artifact_tampering_detected(service,definition):
 artifact=service.build_report(make_command(definition)).artifacts[0]
 with pytest.raises(ArtifactIntegrityError):service.verify_artifact(replace(artifact,content=artifact.content+"tampered"))

def test_fx_conversion_is_explicit(service,definition):
 command=make_command(definition);trades=(replace(command.trades[0],currency="HKD",gross=Decimal("100"),fee=Decimal("2")),);command=replace(command,trades=trades,fx_snapshot_id=uuid4(),fx_rates={"HKD/CNY":Decimal("0.9")});result=service.build_report(command)
 assert metric(result,"fees").value==Decimal("1.8000000000")

def test_missing_fx_snapshot_rejected(service,definition):
 command=make_command(definition);command=replace(command,trades=(replace(command.trades[0],currency="HKD"),))
 with pytest.raises(InvalidReportInput):service.build_report(command)

def test_get_sleeve_attribution(service,definition):
 result=service.build_report(make_command(definition));assert service.get_sleeve_attribution(result.run.run_id)==result.attributions

def test_empty_curve_is_incomplete(service,definition):
 command=make_command(definition);result=service.build_report(replace(command,curve=()));assert quality(result,"CURVE_PRESENT").outcome is QualityOutcome.FAIL

def test_curve_outside_period_is_incomplete(service,definition):
 command=make_command(definition);curve=(replace(command.curve[0],at=NOW-timedelta(days=100)),)+command.curve[1:];result=service.build_report(replace(command,curve=curve));assert quality(result,"PERIOD_BOUNDS").outcome is QualityOutcome.FAIL

def test_nonfinite_metric_is_incomplete(service,definition):
 command=make_command(definition);curve=(replace(command.curve[0],nav=Decimal("NaN")),)+command.curve[1:];result=service.build_report(replace(command,curve=curve));assert quality(result,"FINITE_METRICS").outcome is QualityOutcome.FAIL

@pytest.mark.parametrize("mode,source",[(ReportMode.BACKTEST,"backtest"),(ReportMode.PAPER,"paper_ledger"),(ReportMode.RESEARCH,"research")])
def test_non_live_modes_remain_explicit(service,definition,mode,source):
 d=replace(definition,definition_id=uuid4(),mode=mode,required_source_types=(source,"risk"));command=make_command(d,mode=mode,source_type=source);result=service.build_report(command)
 assert result.run.mode is mode and quality(result,"MODE_ISOLATION").outcome is QualityOutcome.PASS

def test_independent_repositories_produce_same_hashes(definition):
 from quant_trading_system.reporting.in_memory import InMemoryReportingRepository
 command=make_command(definition);first=ReportingService(InMemoryReportingRepository()).build_report(command);second=ReportingService(InMemoryReportingRepository()).build_report(command)
 assert first.run.content_hash==second.run.content_hash
 assert [x.content_hash for x in first.artifacts]==[x.content_hash for x in second.artifacts]

def test_metric_rows_have_drilldown_references(service,definition):
 result=service.build_report(make_command(definition));assert all(x.formula and x.source_references and x.drilldown_reference for x in result.metrics)

def test_incomplete_event_is_explicit(service,repo,definition):
 result=service.build_report(make_command(definition,reconciled=False));assert result.run.status is ReportRunStatus.INCOMPLETE and repo.events[-1].event_type=="ReportBuildIncomplete"
