class ReportingError(Exception): pass
class InvalidReportInput(ReportingError): pass
class ReportNotFound(ReportingError): pass
class ReportConflict(ReportingError): pass
class ArtifactIntegrityError(ReportingError): pass
class RepositoryConflict(ReportingError): pass

