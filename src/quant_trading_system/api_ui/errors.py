class ApiUiError(Exception):
 def __init__(self,code,message,status_code,field_errors=None,retryable=False):super().__init__(message);self.code=code;self.message=message;self.status_code=status_code;self.field_errors=field_errors or {};self.retryable=retryable
class AuthenticationError(ApiUiError):
 def __init__(self,message="authentication required"):super().__init__("AUTH_REQUIRED",message,401)
class AuthorizationError(ApiUiError):
 def __init__(self,message="account access denied"):super().__init__("FORBIDDEN",message,403)
class CsrfError(ApiUiError):
 def __init__(self):super().__init__("CSRF_INVALID","invalid CSRF token",403)
class ValidationError(ApiUiError):
 def __init__(self,message,fields=None):super().__init__("VALIDATION_ERROR",message,422,fields)
class VersionConflict(ApiUiError):
 def __init__(self,message="version conflict; refresh required"):super().__init__("REFRESH_REQUIRED",message,409,retryable=False)
class BusinessBlock(ApiUiError):
 def __init__(self,message="operation blocked by risk"):super().__init__("BUSINESS_BLOCK",message,409)
class IdempotencyConflict(ApiUiError):
 def __init__(self):super().__init__("IDEMPOTENCY_CONFLICT","idempotency key reused with different payload",409)
class NotFound(ApiUiError):
 def __init__(self,message="not found"):super().__init__("NOT_FOUND",message,404)

