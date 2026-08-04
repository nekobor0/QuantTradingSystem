class RiskError(Exception): pass
class InvalidRiskInput(RiskError): pass
class RuleNotFound(RiskError): pass
class PolicyNotFound(RiskError): pass
class RiskRunNotFound(RiskError): pass
class ExceptionRejected(RiskError): pass
class VersionConflict(RiskError): pass
class AlertConflict(RiskError): pass
class RepositoryConflict(RiskError): pass

