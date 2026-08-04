from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime,timezone
from enum import StrEnum
from typing import Mapping
from uuid import UUID,uuid4
from .errors import ValidationError
def aware(x:datetime,name:str)->datetime:
 if x.tzinfo is None or x.utcoffset() is None:raise ValidationError(f"{name} must be timezone-aware",{name:"timezone required"})
 return x.astimezone(timezone.utc)
class ImportStatus(StrEnum):PREVIEWED="PREVIEWED";COMMITTED="COMMITTED";EXPIRED="EXPIRED";FAILED="FAILED"
class CommandState(StrEnum):IDLE="IDLE";SUBMITTING="SUBMITTING";SUCCEEDED="SUCCEEDED";FAILED="FAILED"
@dataclass(frozen=True,slots=True)
class AuthSession:
 user_id:str;account_id:UUID;token_hash:str;csrf_hash:str;created_at:datetime;expires_at:datetime;revoked_at:datetime|None=None;session_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"created_at",aware(self.created_at,"created_at"));object.__setattr__(self,"expires_at",aware(self.expires_at,"expires_at"))
  if self.revoked_at is not None:object.__setattr__(self,"revoked_at",aware(self.revoked_at,"revoked_at"))
  if not self.user_id.strip() or not self.token_hash or not self.csrf_hash or self.expires_at<=self.created_at:raise ValidationError("invalid session")
@dataclass(frozen=True,slots=True)
class UserActionAudit:
 user_id:str;account_id:UUID;action:str;object_id:UUID|None;before_version:int|None;after_version:int|None;result:str;occurred_at:datetime;correlation_id:str;details:Mapping[str,str];audit_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))
@dataclass(frozen=True,slots=True)
class UiPreference:
 user_id:str;theme:str;timezone_name:str;page_size:int;updated_at:datetime;version:int=0;preference_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"updated_at",aware(self.updated_at,"updated_at"))
  if self.page_size<10 or self.page_size>200 or not self.theme.strip() or not self.timezone_name.strip():raise ValidationError("invalid UI preference")
@dataclass(frozen=True,slots=True)
class ImportSession:
 account_id:UUID;user_id:str;file_hash:str;format_version:str;columns:tuple[str,...];row_count:int;preview_passed:bool;summary:Mapping[str,str];created_at:datetime;expires_at:datetime;status:ImportStatus=ImportStatus.PREVIEWED;committed_result_id:UUID|None=None;version:int=0;import_session_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):
  object.__setattr__(self,"created_at",aware(self.created_at,"created_at"));object.__setattr__(self,"expires_at",aware(self.expires_at,"expires_at"))
  if not self.file_hash.strip() or not self.format_version.strip() or self.row_count<0 or self.expires_at<=self.created_at:raise ValidationError("invalid import session")
@dataclass(frozen=True,slots=True)
class IdempotentCommand:
 user_id:str;action:str;idempotency_key:str;payload_hash:str;status_code:int;response:Mapping[str,object];created_at:datetime;command_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"created_at",aware(self.created_at,"created_at"))
@dataclass(frozen=True,slots=True)
class ApiUiEvent:
 event_type:str;account_id:UUID;occurred_at:datetime;correlation_id:str;payload:Mapping[str,str];event_id:UUID=field(default_factory=uuid4)
 def __post_init__(self):object.__setattr__(self,"occurred_at",aware(self.occurred_at,"occurred_at"))
@dataclass(frozen=True,slots=True)
class CommandResult:
 object_id:UUID;version:int;payload:Mapping[str,object];event_type:str
@dataclass(frozen=True,slots=True)
class SessionCredentials:
 session_token:str;csrf_token:str;session_id:UUID;expires_at:datetime;account_id:UUID
