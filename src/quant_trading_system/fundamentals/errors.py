class FundamentalsError(Exception): pass
class InvalidFundamental(FundamentalsError): pass
class IngestionRejected(FundamentalsError): pass
class FilingConflict(FundamentalsError): pass
class FactNotFound(FundamentalsError): pass
class DerivationUnavailable(FundamentalsError): pass
class RepositoryConflict(FundamentalsError): pass
