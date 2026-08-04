class OperationsError(Exception): pass
class ValidationError(OperationsError): pass
class LeaseConflict(OperationsError): pass
class FencingConflict(OperationsError): pass
class StateConflict(OperationsError): pass
class NotFound(OperationsError): pass

