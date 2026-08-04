from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.strategies import *
from quant_trading_system.strategies.errors import *

MONDAY = datetime(2024, 1, 8, 8, tzinfo=timezone.utc)


def frozen(kind, when, members, rows, *, universe_purpose=None, feature_purpose=None):
    purposes = {
        StrategyKind.ETF_TIMING: ("ETF_TIMING_POOL", "ETF_TIMING"),
        StrategyKind.EQUITY_DAILY_SELECTION: ("EQUITY_DAILY_POOL", "EQUITY_DAILY_SELECTION"),
    }
    up, fp = purposes[kind]
    return FrozenStrategyInputs(kind, when, uuid4(), universe_purpose or up, "uh", uuid4(), feature_purpose or fp, "fh", uuid4(), tuple(members), tuple(rows))


def etf_inputs(when=MONDAY, values=None):
    members=(uuid4(),uuid4(),uuid4())
    values=values or (("0.3","0.1","-0.1","0.5"),("0.2","0.2","-0.2","0.4"),("-0.1","0.1","-0.1","0.5"))
    rows=[]
    for iid,xs in zip(members,values):
        rows.extend(StrategyFeatureValue(iid,name,Decimal(value)) for name,value in zip(("momentum","volatility","max_drawdown","liquidity"),xs))
    return frozen(StrategyKind.ETF_TIMING,when,members,rows),members


def equity_inputs(when=MONDAY, members=None, values=None, eligibility=None):
    members=members or (uuid4(),uuid4(),uuid4(),uuid4());values=values or ((4,1,1),(3,2,1),(2,3,1),(1,4,1));rows=[]
    for iid,xs in zip(members,values):rows.extend(StrategyFeatureValue(iid,n,Decimal(v)) for n,v in zip(("value","quality","momentum"),xs))
    result=frozen(StrategyKind.EQUITY_DAILY_SELECTION,when,members,rows)
    if eligibility:result=replace(result,eligibility=eligibility)
    return result,members


def run_command(version,kind,inputs,**changes):
    values=dict(version_id=version.version_id,kind=kind,decision_at=inputs.decision_at,inputs=inputs,parameters={});values.update(changes);return RunStrategy(**values)


def test_etf_rebalance_golden(strategy_setup):
    service,_,version,_=strategy_setup;inputs,members=etf_inputs();result=service.run(run_command(version,StrategyKind.ETF_TIMING,inputs))
    selected=[x for x in result.candidates if x.proposed_weight>0]
    assert result.run.status is RunStatus.COMPLETED and not result.run.cash_gate and len(selected)==2 and all(x.proposed_weight==Decimal("0.5") for x in selected)


def test_etf_gate_reason_and_cash_is_explicit(strategy_setup):
    service,_,version,_=strategy_setup;inputs,_=etf_inputs(values=(("-1","0.1","-0.1","1"),)*3);result=service.run(run_command(version,StrategyKind.ETF_TIMING,inputs))
    assert result.run.cash_gate is True and sum((x.proposed_weight for x in result.candidates),Decimal())==0 and any("TREND_MIN_FAILED" in x.reason_codes for x in result.candidates)


def test_etf_tie_breaks_by_instrument_id(strategy_setup):
    service,_,version,_=strategy_setup;inputs,members=etf_inputs(values=((".2",".1","-.1",".5"),)*3);result=service.run(run_command(version,StrategyKind.ETF_TIMING,inputs));assert [x.instrument_id for x in result.scores]==sorted(members,key=str)


def test_etf_non_rebalance_requires_previous(strategy_setup):
    service,_,version,_=strategy_setup;inputs,_=etf_inputs(MONDAY+timedelta(days=1))
    with pytest.raises(StrategyRunRejected):service.run(run_command(version,StrategyKind.ETF_TIMING,inputs))


def test_etf_non_rebalance_keeps_prior_candidates(strategy_setup):
    service,_,version,_=strategy_setup;first,members=etf_inputs();one=service.run(run_command(version,StrategyKind.ETF_TIMING,first));second=replace(first,decision_at=MONDAY+timedelta(days=1),universe_snapshot_id=uuid4(),feature_set_id=uuid4());two=service.run(run_command(version,StrategyKind.ETF_TIMING,second,previous_run_id=one.run.run_id));assert {x.instrument_id for x in two.candidates if x.action is CandidateAction.KEEP}=={x.instrument_id for x in one.candidates if x.proposed_weight>0}


def test_etf_non_rebalance_risk_exit(strategy_setup):
    service,_,version,_=strategy_setup;first,members=etf_inputs();one=service.run(run_command(version,StrategyKind.ETF_TIMING,first));rows=tuple(replace(x,value=Decimal("-1")) if x.instrument_id==members[0] and x.feature_name=="momentum" else x for x in first.feature_values);second=replace(first,decision_at=MONDAY+timedelta(days=1),universe_snapshot_id=uuid4(),feature_set_id=uuid4(),feature_hash="fh2",feature_values=rows);two=service.run(run_command(version,StrategyKind.ETF_TIMING,second,previous_run_id=one.run.run_id));assert any(x.instrument_id==members[0] and x.action is CandidateAction.EXIT for x in two.candidates)


def test_equity_first_day_selects_top_n(strategy_setup):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs();result=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs));assert [x.action for x in result.candidates]==[CandidateAction.SELECT,CandidateAction.SELECT]


def test_equity_second_day_select_keep_exit(strategy_setup):
    service,_,_,version=strategy_setup;first,members=equity_inputs();one=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,first));second,_=equity_inputs(MONDAY+timedelta(days=1),members,((1,1,1),(3,2,1),(5,3,1),(0,0,0)));two=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,second,previous_run_id=one.run.run_id));assert {x.action for x in two.candidates}=={CandidateAction.SELECT,CandidateAction.KEEP,CandidateAction.EXIT}


def test_equity_contributions_sum_to_score(strategy_setup):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs();result=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs));first=result.scores[0];assert sum((x.contribution for x in result.contributions if x.instrument_id==first.instrument_id),Decimal())==first.raw_score


def test_equity_eligibility_excludes_member(strategy_setup):
    service,_,_,version=strategy_setup;inputs,members=equity_inputs();inputs=replace(inputs,eligibility={members[0]:("NOT_ELIGIBLE",)});result=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs));assert members[0] not in {x.instrument_id for x in result.scores}


def test_identical_run_is_idempotent(strategy_setup):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs();command=run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs);assert service.run(command).run.run_id==service.run(command).run.run_id


@pytest.mark.parametrize("field,value",[("universe_purpose","EQUITY_DAILY_POOL"),("feature_purpose","EQUITY_DAILY_SELECTION")])
def test_etf_snapshot_purpose_isolated(strategy_setup,field,value):
    service,_,version,_=strategy_setup;inputs,_=etf_inputs();inputs=replace(inputs,**{field:value})
    with pytest.raises(SnapshotMismatch):service.run(run_command(version,StrategyKind.ETF_TIMING,inputs))


def test_strategy_kind_version_isolated(strategy_setup):
    service,_,etf_version,_=strategy_setup;inputs,_=equity_inputs()
    with pytest.raises(SnapshotMismatch):service.run(run_command(etf_version,StrategyKind.EQUITY_DAILY_SELECTION,inputs))


def test_decision_time_must_match_frozen_input(strategy_setup):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs()
    with pytest.raises(SnapshotMismatch):service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs,decision_at=MONDAY+timedelta(seconds=1)))


@pytest.mark.parametrize("mutation",["missing","null","quality","extra"])
def test_incomplete_matrix_fails(strategy_setup,mutation):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs();rows=list(inputs.feature_values)
    if mutation=="missing":rows.pop()
    elif mutation=="null":rows[0]=replace(rows[0],value=None)
    elif mutation=="quality":rows[0]=replace(rows[0],quality="MISSING")
    else:rows.append(StrategyFeatureValue(inputs.member_ids[0],"extra",Decimal(1)))
    with pytest.raises(StrategyRunRejected):service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,replace(inputs,feature_values=tuple(rows))))


@pytest.mark.parametrize("parameters",[{"top_n":0},{"feature_weights":{"value":".5","quality":".5","momentum":".5"}},{"feature_weights":{"value":".5","quality":".5"}},{"feature_weights":{"value":"-1","quality":"1","momentum":"1"}}])
def test_parameter_validation(strategy_setup,parameters):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs()
    with pytest.raises(InvalidStrategy):service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs,parameters=parameters))


def test_same_kind_time_requires_explicit_supersede(strategy_setup):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs();one=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs));changed=replace(inputs,feature_hash="changed")
    with pytest.raises(StrategyRunRejected):service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,changed))
    two=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,changed,supersede_run_id=one.run.run_id));assert two.run.supersedes_run_id==one.run.run_id


def test_failed_run_emits_failure_event(strategy_setup):
    service,repository,_,version=strategy_setup;inputs,_=equity_inputs();inputs=replace(inputs,member_ids=())
    with pytest.raises(StrategyRunRejected):service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs))
    assert repository.latest_event().event_type=="StrategyRunFailed"


def test_explain_candidate_has_contributions(strategy_setup):
    service,_,_,version=strategy_setup;inputs,_=equity_inputs();result=service.run(run_command(version,StrategyKind.EQUITY_DAILY_SELECTION,inputs));candidate,parts=service.explain_candidate(result.run.run_id,result.candidates[0].instrument_id);assert candidate and len(parts)==3


def test_daily_selection_rejects_etf_run(strategy_setup):
    service,_,version,_=strategy_setup;inputs,_=etf_inputs();result=service.run(run_command(version,StrategyKind.ETF_TIMING,inputs))
    with pytest.raises(SnapshotMismatch):service.get_daily_selection(result.run.run_id)


def test_research_evidence_is_separate(strategy_setup):
    service,repository,version,_=strategy_setup;e=ResearchEvidence(version.version_id,"latency_one_bar","2020","2024","file:///e","h");service.add_research_evidence(e);assert repository.evidence(version.version_id)==(e,)
