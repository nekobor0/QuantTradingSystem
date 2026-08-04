from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from quant_trading_system.strategies import *
from quant_trading_system.strategies.errors import InvalidStrategy

NOW=datetime(2024,1,8,tzinfo=timezone.utc)


@pytest.mark.parametrize("field",["name","purpose","asset_scope","decision_frequency","rebalance_frequency","owner"])
def test_definition_requires_text(field):
    values=dict(name="x",kind=StrategyKind.ETF_TIMING,purpose="p",asset_scope="a",decision_frequency="d",rebalance_frequency="w",benchmark="",owner="o",invalidation_conditions=())
    values[field]=""
    with pytest.raises(InvalidStrategy):StrategyDefinition(**values)


@pytest.mark.parametrize("field",["version","code_version"])
def test_version_requires_identity(field):
    values=dict(definition_id=uuid4(),version="1",code_version="c",required_features=("x",),default_parameters={});values[field]=""
    with pytest.raises(InvalidStrategy):StrategyVersion(**values)


def test_version_requires_features():
    with pytest.raises(InvalidStrategy):StrategyVersion(uuid4(),"1","c",(),{})


@pytest.mark.parametrize("weight",["-0.1","1.1"])
def test_candidate_weight_bounds(weight):
    with pytest.raises(InvalidStrategy):StrategyCandidate(uuid4(),uuid4(),CandidateAction.SELECT,Decimal(1),1,Decimal(weight),())


def make_run(status=RunStatus.CREATED):return StrategyRun(StrategyKind.ETF_TIMING,uuid4(),NOW,uuid4(),uuid4(),uuid4(),"p","i","r",status,False)


@pytest.mark.parametrize("start,next_status",[(RunStatus.CREATED,RunStatus.INPUTS_FROZEN),(RunStatus.CREATED,RunStatus.REJECTED),(RunStatus.INPUTS_FROZEN,RunStatus.RUNNING),(RunStatus.INPUTS_FROZEN,RunStatus.FAILED),(RunStatus.RUNNING,RunStatus.COMPLETED),(RunStatus.RUNNING,RunStatus.FAILED)])
def test_valid_state_transitions(start,next_status):assert make_run(start).transition(next_status).status is next_status


@pytest.mark.parametrize("start,next_status",[(RunStatus.CREATED,RunStatus.COMPLETED),(RunStatus.COMPLETED,RunStatus.RUNNING),(RunStatus.FAILED,RunStatus.RUNNING),(RunStatus.REJECTED,RunStatus.CREATED)])
def test_invalid_state_transitions(start,next_status):
    with pytest.raises(InvalidStrategy):make_run(start).transition(next_status)


@pytest.mark.parametrize("kind",list(StrategyKind))
def test_kind_roundtrip(kind):assert StrategyKind(kind.value) is kind


@pytest.mark.parametrize("status",list(RunStatus))
def test_status_roundtrip(status):assert RunStatus(status.value) is status


@pytest.mark.parametrize("action",list(CandidateAction))
def test_action_roundtrip(action):assert CandidateAction(action.value) is action


DDL=Path(__file__).parents[2]/"migrations"/"006_strategies.sql"


def test_all_owned_tables_present():
    sql=DDL.read_text(encoding="utf-8")
    for table in ("strategy_definitions","strategy_versions","strategy_runs","strategy_scores","strategy_candidates","strategy_contributions","research_evidence","strategy_events"):assert f"CREATE TABLE {table}" in sql


def test_run_input_hash_unique():assert "input_hash char(64) UNIQUE NOT NULL" in DDL.read_text(encoding="utf-8")
def test_candidate_weight_constraint():assert "CHECK(proposed_weight BETWEEN 0 AND 1)" in DDL.read_text(encoding="utf-8")
def test_run_status_constraint():assert "CHECK(status IN('CREATED','INPUTS_FROZEN','RUNNING','COMPLETED','FAILED','REJECTED'))" in DDL.read_text(encoding="utf-8")
def test_score_unique_per_instrument():assert "UNIQUE(run_id,instrument_id)" in DDL.read_text(encoding="utf-8")
