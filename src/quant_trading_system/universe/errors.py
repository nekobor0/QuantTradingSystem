class UniverseError(Exception): pass
class InvalidUniverse(UniverseError): pass
class BatchRejected(UniverseError): pass
class BatchConflict(UniverseError): pass
class UniverseNotFound(UniverseError): pass
class StaleUniverse(UniverseError): pass
class RepositoryConflict(UniverseError): pass
