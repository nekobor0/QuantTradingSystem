from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.risk import *
from quant_trading_system.risk.errors import *

from .conftest import NOW, make_input


def failing_market_result(service,policy,account_id,object_id=None,at=NOW,hash_value="1"):
    output=service.run_pre_trade_checks(make_input(account_id,object_id=object_id,at=at,market_weight=Decimal("0.9"),hashes={"h":hash_value}),policy.policy_version_id)
    return output,next(item for item in output.results if item.metric=="market_weight")


def test_exception_changes_effective_not_original_decision(service,policy,account_id):
    output,result=failing_market_result(service,policy,account_id)
    exception=service.approve_exception(result.result_id,"requester","approver","temporary market concentration",NOW,NOW+timedelta(days=1))
    assert output.run.decision is RiskDecision.APPROVAL_REQUIRED
    assert result.outcome is RuleOutcome.APPROVAL_REQUIRED
    assert service.effective_decision(output.run.run_id,NOW+timedelta(hours=1)) is RiskDecision.PASS
    assert exception.status is ExceptionStatus.APPROVED


def test_exception_expiry_restores_original_decision(service,policy,account_id):
    output,result=failing_market_result(service,policy,account_id)
    service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(hours=1))
    assert service.effective_decision(output.run.run_id,NOW+timedelta(hours=1)) is RiskDecision.APPROVAL_REQUIRED


def test_nonwaivable_hard_block_rejects_exception(service,policy,account_id):
    output=service.run_pre_trade_checks(make_input(account_id,stock_weight=Decimal("1")),policy.policy_version_id)
    result=next(item for item in output.results if item.metric=="max_weight")
    with pytest.raises(ExceptionRejected):service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(days=1))


def test_system_hard_block_rejects_exception(service,policy,account_id):
    output=service.run_pre_trade_checks(make_input(account_id,reconciled=False),policy.policy_version_id)
    result=next(item for item in output.results if item.metric=="ACCOUNT_RECONCILED")
    with pytest.raises(ExceptionRejected):service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(days=1))


@pytest.mark.parametrize("requested,approved", [("same","same"),("","b"),("a","")])
def test_exception_requires_auditable_two_person_approval(service,policy,account_id,requested,approved):
    _,result=failing_market_result(service,policy,account_id)
    with pytest.raises(InvalidRiskInput):service.approve_exception(result.result_id,requested,approved,"reason",NOW,NOW+timedelta(days=1))


def test_exception_rejects_more_than_one_year(service,policy,account_id):
    _,result=failing_market_result(service,policy,account_id)
    with pytest.raises(ExceptionRejected):service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(days=366))


def test_exception_new_version_must_start_zero(service,policy,account_id):
    _,result=failing_market_result(service,policy,account_id)
    with pytest.raises(VersionConflict):service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(days=1),1)


def test_revoke_exception_is_versioned_and_preserved(service,repo,policy,account_id):
    output,result=failing_market_result(service,policy,account_id)
    value=service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(days=1))
    revoked=service.revoke_exception(value.exception_id,0,"operator","no longer needed",NOW+timedelta(hours=1))
    assert revoked.status is ExceptionStatus.REVOKED and revoked.version==1
    assert service.effective_decision(output.run.run_id,NOW+timedelta(hours=2)) is RiskDecision.APPROVAL_REQUIRED
    assert repo.get_exception(value.exception_id)==revoked


def test_revoke_exception_version_conflict(service,policy,account_id):
    _,result=failing_market_result(service,policy,account_id)
    value=service.approve_exception(result.result_id,"a","b","reason",NOW,NOW+timedelta(days=1))
    with pytest.raises(VersionConflict):service.revoke_exception(value.exception_id,1,"operator","reason",NOW)


def test_breach_creates_open_alert(service,repo,policy,account_id):
    _,result=failing_market_result(service,policy,account_id)
    alert=next(item for item in repo.alerts.values() if item.result_id==result.result_id)
    assert alert.status is AlertStatus.OPEN and len(alert.dedupe_key)==64


def test_same_breach_window_dedupes_alert(service,repo,policy,account_id):
    object_id=uuid4();failing_market_result(service,policy,account_id,object_id,NOW,"1");first_count=len(repo.alerts)
    failing_market_result(service,policy,account_id,object_id,NOW+timedelta(minutes=1),"2")
    assert len(repo.alerts)==first_count


def test_new_observation_window_creates_new_alert(service,repo,policy,account_id):
    object_id=uuid4();failing_market_result(service,policy,account_id,object_id,NOW,"1");first_count=len(repo.alerts)
    failing_market_result(service,policy,account_id,object_id,NOW+timedelta(days=1),"2")
    assert len(repo.alerts)>first_count


def test_acknowledge_and_escalate_are_versioned(service,repo,policy,account_id):
    _,result=failing_market_result(service,policy,account_id);alert=next(item for item in repo.alerts.values() if item.result_id==result.result_id)
    ack=service.acknowledge_alert(alert.alert_id,"operator",NOW,0)
    escalated=service.escalate_alert(alert.alert_id,"risk-head",NOW+timedelta(minutes=1),1)
    assert ack.status is AlertStatus.ACKNOWLEDGED and ack.acknowledged_by=="operator"
    assert escalated.status is AlertStatus.ESCALATED and escalated.escalated_to=="risk-head" and escalated.version==2


def test_alert_version_conflict(service,repo,policy,account_id):
    _,result=failing_market_result(service,policy,account_id);alert=next(item for item in repo.alerts.values() if item.result_id==result.result_id)
    with pytest.raises(VersionConflict):service.acknowledge_alert(alert.alert_id,"operator",NOW,1)


def test_alert_resolution_requires_matching_later_pass(service,repo,policy,account_id):
    object_id=uuid4();_,failed=failing_market_result(service,policy,account_id,object_id);alert=next(item for item in repo.alerts.values() if item.result_id==failed.result_id)
    passed=service.run_pre_trade_checks(make_input(account_id,object_id=object_id,at=NOW+timedelta(days=1),market_weight=Decimal("0.5"),hashes={"h":"pass"}),policy.policy_version_id)
    pass_result=next(item for item in passed.results if item.metric=="market_weight")
    resolved=service.resolve_alert(alert.alert_id,pass_result.result_id,"new snapshot within limit",NOW+timedelta(days=1),0)
    assert resolved.status is AlertStatus.RESOLVED and resolved.resolution_evidence


def test_alert_cannot_resolve_with_old_fail(service,repo,policy,account_id):
    _,failed=failing_market_result(service,policy,account_id);alert=next(item for item in repo.alerts.values() if item.result_id==failed.result_id)
    with pytest.raises(AlertConflict):service.resolve_alert(alert.alert_id,failed.result_id,"evidence",NOW,0)


def test_risk_state_reports_active_alerts_and_staleness(service,repo,policy,account_id):
    output,_=failing_market_result(service,policy,account_id)
    state=service.get_risk_state(account_id,NOW+timedelta(minutes=1),3600)
    assert state.active_alerts and state.blocking_reasons and not state.stale and state.latest_run_id==output.run.run_id
    assert service.get_risk_state(account_id,NOW+timedelta(hours=2),3600).stale


def test_resolved_alert_not_active_in_state(service,repo,policy,account_id):
    object_id=uuid4();_,failed=failing_market_result(service,policy,account_id,object_id);alert=next(item for item in repo.alerts.values() if item.result_id==failed.result_id)
    passed=service.run_pre_trade_checks(make_input(account_id,object_id=object_id,at=NOW+timedelta(days=1),hashes={"h":"p"}),policy.policy_version_id)
    pass_result=next(item for item in passed.results if item.metric=="market_weight")
    service.resolve_alert(alert.alert_id,pass_result.result_id,"resolved",NOW+timedelta(days=1),0)
    assert alert.alert_id not in {item.alert_id for item in service.get_risk_state(account_id,NOW+timedelta(days=1),3600).active_alerts}


def test_get_sleeve_risk_by_target(service,policy,account_id):
    value=make_input(account_id);output=service.run_pre_trade_checks(value,policy.policy_version_id)
    assert service.get_sleeve_risk(value.object_id)==(output,)
