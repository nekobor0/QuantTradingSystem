from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable
from uuid import UUID

from quant_trading_system.signals import RiskDecision as SignalRiskDecision

from .domain import *
from .errors import *
from .ports import RiskRepository

Evaluator = Callable[[RiskRuleVersion, object, RiskCheckInput], bool]


class RiskService:
    def __init__(self, repository: RiskRepository):
        self.repository = repository
        self.evaluators: dict[str, Evaluator] = {"metric": self._metric_evaluator}
        self._ensure_system_rules()

    def _ensure_system_rules(self) -> None:
        names = ("ACCOUNT_RECONCILED", "ACCOUNT_SOURCE", "NONNEGATIVE_CASH", "NONNEGATIVE_POSITION", "INPUT_FRESHNESS")
        for index, name in enumerate(names, 1):
            version_id = UUID(int=index)
            if self.repository.get_rule_version(version_id) is not None:
                continue
            rule = RiskRule(name, name, "system", "mandatory fail-closed invariant", UUID(int=100 + index))
            version = RiskRuleVersion(rule.rule_id, "system-v1", RiskStage.PRE_TRADE, RiskScope.COMBINED_ACCOUNT, name, ComparisonOperator.EQ, True, RiskSeverity.HARD_BLOCK, datetime.min.date(), None, "system", False, "metric", version_id)
            self.repository.save_rule(rule)
            self.repository.save_rule_version(version)

    def register_rule(self, rule: RiskRule, version: RiskRuleVersion) -> None:
        if version.rule_id != rule.rule_id:
            raise InvalidRiskInput("rule/version identity mismatch")
        self.repository.save_rule(rule)
        self.repository.save_rule_version(version)

    def register_policy(self, policy: RiskPolicyVersion) -> None:
        versions = [self.repository.get_rule_version(value) for value in policy.rule_version_ids]
        if any(value is None for value in versions):
            raise RuleNotFound("policy references unknown rule version")
        scopes = {value.scope for value in versions if value is not None}
        if not set(policy.required_scopes).issubset(scopes):
            raise InvalidRiskInput("policy has no rule for a required scope")
        self.repository.save_policy(policy)

    def register_evaluator(self, key: str, evaluator: Evaluator) -> None:
        if not key.strip() or key == "metric":
            raise InvalidRiskInput("invalid evaluator key")
        self.evaluators[key] = evaluator

    def run_pre_trade_checks(self, value: RiskCheckInput, policy_version_id: UUID) -> RiskRunResult:
        return self._run(value, policy_version_id, RiskStage.PRE_TRADE)

    def run_in_flight_checks(self, value: RiskCheckInput, policy_version_id: UUID) -> RiskRunResult:
        return self._run(value, policy_version_id, RiskStage.IN_FLIGHT)

    def run_post_trade_checks(self, value: RiskCheckInput, policy_version_id: UUID) -> RiskRunResult:
        return self._run(value, policy_version_id, RiskStage.POST_TRADE)

    def _run(self, value: RiskCheckInput, policy_version_id: UUID, stage: RiskStage) -> RiskRunResult:
        if value.stage is not stage:
            raise InvalidRiskInput("risk input stage mismatch")
        policy = self.repository.get_policy(policy_version_id)
        if policy is None:
            raise PolicyNotFound(str(policy_version_id))
        if policy.account_id != value.account_id or not policy.active_on(value.decision_at.date()):
            raise InvalidRiskInput("policy is not applicable")
        input_hash = self._hash({"policy": str(policy_version_id), "input": value})
        existing = self.repository.find_run(input_hash)
        if existing is not None:
            result = self.repository.get_run_result(existing.run_id)
            if result is None:
                raise RiskRunNotFound(str(existing.run_id))
            return replace(result, effective_decision=self.effective_decision(existing.run_id, value.decision_at))
        started = datetime.now(timezone.utc)
        run = RiskCheckRun(value.account_id, value.object_id, policy_version_id, stage, value.decision_at, input_hash, RiskRunStatus.RUNNING, RiskDecision.PASS, started)
        results: list[RiskCheckResult] = []
        results.extend(self._system_results(run, value, policy))
        for scope in policy.required_scopes:
            scoped_rules = []
            for version_id in policy.rule_version_ids:
                version = self.repository.get_rule_version(version_id)
                if version is None:
                    raise RuleNotFound(str(version_id))
                if version.scope is scope and version.stage is stage and version.active_on(value.decision_at.date()):
                    scoped_rules.append(version)
            if not scoped_rules:
                results.append(self._engine_error(run, value, scope, "required scope has no active rule"))
                continue
            for version in scoped_rules:
                results.append(self._evaluate(run, value, version))
        decision = self._aggregate(results)
        completed = replace(run, status=RiskRunStatus.COMPLETED, decision=decision, completed_at=datetime.now(timezone.utc))
        alerts = self._new_alerts(completed, results)
        output = RiskRunResult(completed, tuple(results), decision)
        self.repository.save_run_result(output, alerts, RiskEvent("RiskCheckCompleted", value.account_id, value.object_id, completed.completed_at or started, {"decision": decision.value}))
        return output

    def _system_results(self, run: RiskCheckRun, value: RiskCheckInput, policy: RiskPolicyVersion) -> list[RiskCheckResult]:
        now = value.decision_at
        results = []
        checks = [
            ("ACCOUNT_RECONCILED", value.reconciled, True, ComparisonOperator.EQ, value.reconciled, "account must be reconciled"),
            ("ACCOUNT_SOURCE", value.account_source, "execution_ledger" if value.stage is RiskStage.POST_TRADE else value.account_source, ComparisonOperator.EQ, value.stage is not RiskStage.POST_TRADE or value.account_source == "execution_ledger", "post-trade source must be execution_ledger"),
        ]
        combined = value.scoped_values[RiskScope.COMBINED_ACCOUNT]
        cash = combined.get("cash", Decimal())
        checks.append(("NONNEGATIVE_CASH", cash, Decimal(), ComparisonOperator.GE, self._number(cash) >= 0, "cash must be nonnegative"))
        negative_position = bool(combined.get("negative_position", False))
        checks.append(("NONNEGATIVE_POSITION", negative_position, False, ComparisonOperator.FALSE, not negative_position, "position must be nonnegative"))
        ages = {"account": value.account_as_of, "market": value.market_as_of, "data": value.data_as_of, "task": value.task_as_of}
        age_values = [(now-point).total_seconds() for point in ages.values()]
        max_age = max(age_values)
        checks.append(("INPUT_FRESHNESS", Decimal(str(max_age)), Decimal(policy.max_input_age_seconds), ComparisonOperator.LE, min(age_values) >= 0 and max_age <= policy.max_input_age_seconds, "all input snapshots must be visible and fresh"))
        expires_at = combined.get("signal_expires_at")
        if expires_at is not None:
            valid = isinstance(expires_at, datetime) and aware(expires_at, "signal_expires_at") > now
            checks.append(("SIGNAL_NOT_EXPIRED", expires_at, now, ComparisonOperator.GT, valid, "signal must not be expired"))
        for index,(metric,observed,threshold,operator,passed,explanation) in enumerate(checks,1):
            results.append(RiskCheckResult(run.run_id, UUID(int=index), value.object_id, RiskScope.COMBINED_ACCOUNT, metric, observed, threshold, operator, RiskSeverity.HARD_BLOCK, RuleOutcome.PASS if passed else RuleOutcome.BLOCK, explanation, now))
        return results

    def _evaluate(self, run: RiskCheckRun, value: RiskCheckInput, version: RiskRuleVersion) -> RiskCheckResult:
        try:
            observed = value.scoped_values[version.scope][version.metric]
            evaluator = self.evaluators[version.evaluator_key]
            passed = evaluator(version, observed, value)
            outcome = RuleOutcome.PASS if passed else {RiskSeverity.HARD_BLOCK:RuleOutcome.BLOCK,RiskSeverity.APPROVAL_REQUIRED:RuleOutcome.APPROVAL_REQUIRED,RiskSeverity.WARNING:RuleOutcome.WARNING}[version.severity]
            explanation = f"{version.metric} {version.operator.value} {version.threshold}: observed={observed}"
            return RiskCheckResult(run.run_id, version.version_id, value.object_id, version.scope, version.metric, observed, version.threshold, version.operator, version.severity, outcome, explanation, value.decision_at)
        except Exception as error:
            return self._engine_error(run, value, version.scope, f"{version.version_id}: {type(error).__name__}: {error}", version.version_id)

    def _engine_error(self, run, value, scope, message, version_id=UUID(int=0)):
        return RiskCheckResult(run.run_id, version_id, value.object_id, scope, "RISK_ENGINE_ERROR", message, "NO_ERROR", ComparisonOperator.EQ, RiskSeverity.HARD_BLOCK, RuleOutcome.BLOCK, "risk evaluator failed closed", value.decision_at)

    @staticmethod
    def _metric_evaluator(version: RiskRuleVersion, observed: object, value: RiskCheckInput) -> bool:
        operator = version.operator; threshold = version.threshold
        if operator is ComparisonOperator.TRUE:return observed is True
        if operator is ComparisonOperator.FALSE:return observed is False
        if operator is ComparisonOperator.IN:
            if not isinstance(threshold, (tuple, list, set, frozenset)):
                raise InvalidRiskInput("IN threshold must be a collection")
            return observed in threshold
        if operator is ComparisonOperator.EQ:return observed == threshold
        left,right=RiskService._number(observed),RiskService._number(threshold)
        return {ComparisonOperator.LT:left<right,ComparisonOperator.LE:left<=right,ComparisonOperator.GT:left>right,ComparisonOperator.GE:left>=right}[operator]

    @staticmethod
    def convert(amount: Decimal, currency: str, base_currency: str, value: RiskCheckInput) -> Decimal:
        if currency == base_currency:return dec(amount)
        key=f"{currency}/{base_currency}"
        if value.fx_snapshot_id is None or key not in value.fx_rates:raise InvalidRiskInput("explicit FX snapshot/rate required")
        return dec(amount)*value.fx_rates[key]

    def approve_exception(self, result_id: UUID, requested_by: str, approved_by: str, reason: str, approved_at: datetime, expires_at: datetime, expected_version: int=0) -> RiskException:
        result=self.repository.get_result(result_id)
        if result is None:raise RiskRunNotFound(str(result_id))
        rule=self.repository.get_rule_version(result.rule_version_id)
        if rule is None or not rule.exception_allowed:raise ExceptionRejected("rule does not allow exceptions")
        if expected_version!=0:raise VersionConflict("new exception expected_version must be zero")
        approved=aware(approved_at,"approved_at");expires=aware(expires_at,"expires_at")
        if expires-approved>timedelta(days=365):raise ExceptionRejected("exception duration exceeds one year")
        value=RiskException(result_id,result.rule_version_id,result.scope,requested_by,approved_by,reason,approved,expires)
        run=self.repository.get_run_result(result.run_id)
        if run is None:raise RiskRunNotFound(str(result.run_id))
        self.repository.save_exception(value,RiskEvent("RiskExceptionApproved",run.run.account_id,result.object_id,approved,{"exception_id":str(value.exception_id)}));return value

    def revoke_exception(self, exception_id: UUID, expected_version: int, actor: str, reason: str, at: datetime) -> RiskException:
        current=self.repository.get_exception(exception_id)
        if current is None:raise RiskRunNotFound(str(exception_id))
        if current.version!=expected_version or current.status is not ExceptionStatus.APPROVED:raise VersionConflict("exception version/status conflict")
        if not actor.strip() or not reason.strip():raise ExceptionRejected("revocation audit required")
        updated=replace(current,status=ExceptionStatus.REVOKED,version=current.version+1)
        result=self.repository.get_result(current.result_id);run=self.repository.get_run_result(result.run_id) if result else None
        if result is None or run is None:raise RiskRunNotFound(str(current.result_id))
        self.repository.save_exception(updated,RiskEvent("RiskExceptionRevoked",run.run.account_id,result.object_id,aware(at,"at"),{"reason":reason}));return updated

    def effective_decision(self, run_id: UUID, as_of: datetime) -> RiskDecision:
        output=self.repository.get_run_result(run_id)
        if output is None:raise RiskRunNotFound(str(run_id))
        point=aware(as_of,"as_of");remaining=[]
        for result in output.results:
            active=any(item.status is ExceptionStatus.APPROVED and item.approved_at<=point<item.expires_at for item in self.repository.exceptions_for(result.result_id))
            if not active:remaining.append(result)
        return self._aggregate(remaining)

    def to_signal_decision(self, run_id: UUID, as_of: datetime) -> SignalRiskDecision:
        return SignalRiskDecision.PASS if self.effective_decision(run_id,as_of) is RiskDecision.PASS else SignalRiskDecision.HARD_FAIL

    def acknowledge_alert(self, alert_id: UUID, actor: str, at: datetime, expected_version: int) -> RiskAlert:
        return self._alert_transition(alert_id,expected_version,AlertStatus.ACKNOWLEDGED,at,actor=actor)
    def escalate_alert(self, alert_id: UUID, target: str, at: datetime, expected_version: int) -> RiskAlert:
        return self._alert_transition(alert_id,expected_version,AlertStatus.ESCALATED,at,target=target)
    def resolve_alert(self, alert_id: UUID, pass_result_id: UUID, evidence: str, at: datetime, expected_version: int) -> RiskAlert:
        alert=self._alert(alert_id);result=self.repository.get_result(pass_result_id)
        if result is None or result.outcome is not RuleOutcome.PASS or result.rule_version_id!=alert.rule_version_id or result.object_id!=alert.object_id or result.scope is not alert.scope:raise AlertConflict("resolution requires matching later PASS")
        if result.evaluated_at<=alert.opened_at or not evidence.strip():raise AlertConflict("resolution needs later evidence")
        return self._alert_transition(alert_id,expected_version,AlertStatus.RESOLVED,at,evidence=evidence)

    def _alert_transition(self,alert_id,expected_version,status,at,actor=None,target=None,evidence=None):
        current=self._alert(alert_id)
        if current.version!=expected_version or current.status is AlertStatus.RESOLVED:raise VersionConflict("alert version/status conflict")
        point=aware(at,"at")
        updated=replace(current,status=status,version=current.version+1,acknowledged_by=actor or current.acknowledged_by,acknowledged_at=point if actor else current.acknowledged_at,escalated_to=target or current.escalated_to,resolved_at=point if status is AlertStatus.RESOLVED else current.resolved_at,resolution_evidence=evidence or current.resolution_evidence)
        self.repository.update_alert(updated,RiskEvent("RiskAlert"+status.value.title(),current.account_id,current.object_id,point,{}));return updated

    def get_risk_state(self,account_id:UUID,as_of:datetime,max_check_age_seconds:int)->RiskState:
        point=aware(as_of,"as_of");runs=sorted((x for x in self.repository.runs_for_account(account_id) if x.decision_at<=point),key=lambda x:x.decision_at)
        latest=runs[-1] if runs else None;stale=latest is None or (point-latest.decision_at).total_seconds()>max_check_age_seconds
        alerts=tuple(x for x in self.repository.alerts_for_account(account_id) if x.opened_at<=point and x.status is not AlertStatus.RESOLVED)
        reason_values=[]
        for alert in alerts:
            result=self.repository.get_result(alert.result_id)
            if result is not None:reason_values.append(result.explanation)
        reasons=tuple(reason_values)
        return RiskState(account_id,point,alerts,reasons,stale,None if latest is None else latest.run_id)

    def get_sleeve_risk(self,target_id:UUID)->tuple[RiskRunResult,...]:return tuple(self.repository.runs_for_target(target_id))

    def _new_alerts(self,run,results):
        values=[]
        for result in results:
            if result.outcome is RuleOutcome.PASS:continue
            window=run.decision_at.date().isoformat();key=self._hash((str(result.rule_version_id),str(result.object_id),result.scope.value,window))
            existing=self.repository.find_alert(key)
            if existing is None:values.append(RiskAlert(run.account_id,result.object_id,result.result_id,result.rule_version_id,result.scope,window,key,AlertStatus.OPEN,run.decision_at))
        return tuple(values)
    def _alert(self,i):
        value=self.repository.get_alert(i)
        if value is None:raise RiskRunNotFound(str(i))
        return value
    @staticmethod
    def _aggregate(results):
        outcomes={x.outcome for x in results}
        if RuleOutcome.BLOCK in outcomes:return RiskDecision.BLOCK
        if RuleOutcome.APPROVAL_REQUIRED in outcomes:return RiskDecision.APPROVAL_REQUIRED
        if RuleOutcome.WARNING in outcomes:return RiskDecision.WARNING
        return RiskDecision.PASS
    @staticmethod
    def _number(value):return dec(value)
    @staticmethod
    def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
