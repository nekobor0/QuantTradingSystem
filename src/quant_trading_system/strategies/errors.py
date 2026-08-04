class StrategyError(Exception): pass
class InvalidStrategy(StrategyError): pass
class StrategyRunRejected(StrategyError): pass
class SnapshotMismatch(StrategyError): pass
class StrategyRunNotFound(StrategyError): pass
class RepositoryConflict(StrategyError): pass
