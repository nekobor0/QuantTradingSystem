class PortfolioError(Exception): pass
class InvalidPortfolio(PortfolioError): pass
class PortfolioRejected(PortfolioError): pass
class PortfolioNotFound(PortfolioError): pass
class RepositoryConflict(PortfolioError): pass
