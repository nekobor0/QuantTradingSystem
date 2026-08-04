class SignalError(Exception): pass
class InvalidSignal(SignalError): pass
class SignalCreationRejected(SignalError): pass
class PublishRejected(SignalError): pass
class ApprovalConflict(SignalError): pass
class SignalNotFound(SignalError): pass
class RepositoryConflict(SignalError): pass
