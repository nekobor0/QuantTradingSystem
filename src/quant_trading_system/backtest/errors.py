class BacktestError(Exception): pass
class InvalidBacktest(BacktestError): pass
class LookaheadAccess(BacktestError): pass
class MissingRule(BacktestError): pass
class SimulationInvariantError(BacktestError): pass
class RunNotFound(BacktestError): pass
class RunConflict(BacktestError): pass

