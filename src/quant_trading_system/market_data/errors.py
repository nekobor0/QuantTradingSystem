"""Market-data domain and application errors."""

class MarketDataError(Exception):
    """Base market-data error."""


class InvalidMarketData(MarketDataError):
    pass


class QualityGateRejected(MarketDataError):
    pass


class SnapshotNotFound(MarketDataError):
    pass


class FactorUnavailable(MarketDataError):
    pass


class RepositoryConflict(MarketDataError):
    pass

