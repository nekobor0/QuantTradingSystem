from __future__ import annotations
import hashlib,hmac,json,secrets
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from typing import Mapping
from uuid import UUID, uuid4
from .domain import *
from .errors import *
from .ports import ApiUiRepository,CredentialVerifier,TradingBackend

class ApiUiService:
 REQUIRED_IMPORT_COLUMNS=("broker_fill_id","order_id","filled_at","quantity","price","commission","tax","currency")
 def __init__(self,repository:ApiUiRepository,backend:TradingBackend,verifier:CredentialVerifier,session_ttl:timedelta=timedelta(hours=8),import_ttl:timedelta=timedelta(minutes=30)):
  self.repository=repository;self.backend=backend;self.verifier=verifier;self.session_ttl=session_ttl;self.import_ttl=import_ttl
 def login(self,username:str,password:str,now:datetime)->SessionCredentials:
  point=aware(now,"now")
  if not username.strip() or not password:raise AuthenticationError("invalid credentials")
  identity=self.verifier.verify(username,password)
  if identity is None:raise AuthenticationError("invalid credentials")
  user_id,account_id=identity;token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);session=AuthSession(user_id,account_id,self._secret_hash(token),self._secret_hash(csrf),point,point+self.session_ttl);self.repository.save_session(session);return SessionCredentials(token,csrf,session.session_id,session.expires_at,account_id)
 def logout(self,token:str,csrf:str,now:datetime,correlation_id:str)->None:
  session=self.authenticate(token,now,csrf);updated=replace(session,revoked_at=aware(now,"now"));self.repository.update_session(updated);audit=self._audit(session,"LOGOUT",None,None,None,"SUCCEEDED",now,correlation_id);self.repository.save_audit(audit,ApiUiEvent("UserActionAudited",session.account_id,aware(now,"now"),correlation_id,{"action":"LOGOUT"}))
 def authenticate(self,token:str,now:datetime,csrf:str|None=None)->AuthSession:
  if not token:raise AuthenticationError()
  session=self.repository.find_session_by_token_hash(self._secret_hash(token));point=aware(now,"now")
  if session is None or session.revoked_at is not None or point>=session.expires_at:raise AuthenticationError("session expired or invalid")
  if csrf is not None and (not csrf or not hmac.compare_digest(session.csrf_hash,self._secret_hash(csrf))):raise CsrfError()
  return session
 def query(self,token:str,name:str,as_of:datetime|None,now:datetime,object_id:UUID|None=None,account_id:UUID|None=None)->Mapping[str,object]:
  session=self.authenticate(token,now)
  if account_id is not None and account_id!=session.account_id:raise AuthorizationError()
  if as_of is not None:as_of=aware(as_of,"as_of")
  return self._sanitize(self.backend.query(name,session.account_id,as_of,object_id))
 def execute(self,token:str,csrf:str,action:str,idempotency_key:str,expected_version:int,payload:Mapping[str,object],now:datetime,correlation_id:str,object_id:UUID|None=None)->Mapping[str,object]:
  session=self.authenticate(token,now,csrf);self._validate_command(action,idempotency_key,expected_version,correlation_id);clean_payload=dict(payload);clean_payload["expected_version"]=expected_version;payload_hash=self._hash(clean_payload);existing=self.repository.find_command(session.user_id,action,idempotency_key)
  if existing:
   if existing.payload_hash!=payload_hash:raise IdempotencyConflict()
   return existing.response
  if action=="APPROVE_RECOMMENDATION":
   state=self.backend.query("daily_status",session.account_id,aware(now,"now"),None)
   if bool(state.get("hard_block",False)):raise BusinessBlock(str(state.get("blocking_reason","approval blocked by risk")))
  if action=="SAVE_UI_PREFERENCE":
   current=self.repository.get_preference(session.user_id)
   if (current.version if current else 0)!=expected_version:raise VersionConflict()
   value=UiPreference(session.user_id,str(payload["theme"]),str(payload["timezone_name"]),int(str(payload["page_size"])),aware(now,"now"),expected_version+1,current.preference_id if current else uuid4())
   response={"preference_id":str(value.preference_id),"version":value.version,"theme":value.theme,"timezone_name":value.timezone_name,"page_size":value.page_size}
   command=IdempotentCommand(session.user_id,action,idempotency_key,payload_hash,200,response,aware(now,"now"));audit=self._audit(session,action,value.preference_id,expected_version,value.version,"SUCCEEDED",now,correlation_id);event=ApiUiEvent("UserActionAudited",session.account_id,aware(now,"now"),correlation_id,{"action":action});self.repository.save_preference_and_command(value,command,audit,event);return response
  result=self.backend.command(action,session.account_id,object_id,clean_payload);response=self._sanitize(dict(result.payload)|{"object_id":str(result.object_id),"version":result.version});command=IdempotentCommand(session.user_id,action,idempotency_key,payload_hash,200,response,aware(now,"now"));audit=self._audit(session,action,result.object_id,expected_version,result.version,"SUCCEEDED",now,correlation_id);event=ApiUiEvent(result.event_type,session.account_id,aware(now,"now"),correlation_id,{"object_id":str(result.object_id)});self.repository.save_command_and_audit(command,audit,event);return response
 def preview_import(self,token,csrf,idempotency_key,file_hash,format_version,columns,row_count,now,correlation_id):
  session=self.authenticate(token,now,csrf);self._validate_command("IMPORT_PREVIEW",idempotency_key,0,correlation_id);payload={"file_hash":file_hash,"format_version":format_version,"columns":list(columns),"row_count":row_count};payload_hash=self._hash(payload);cached=self.repository.find_command(session.user_id,"IMPORT_PREVIEW",idempotency_key)
  if cached:
   if cached.payload_hash!=payload_hash:raise IdempotencyConflict()
   return cached.response
  existing=self.repository.find_import(session.account_id,file_hash,format_version)
  if existing:return {"import_session_id":str(existing.import_session_id),"preview_passed":existing.preview_passed,"missing_columns":list(set(self.REQUIRED_IMPORT_COLUMNS)-set(existing.columns)),"version":existing.version}
  missing=tuple(sorted(set(self.REQUIRED_IMPORT_COLUMNS)-set(columns)));passed=not missing and row_count>0;value=ImportSession(session.account_id,session.user_id,file_hash,format_version,tuple(columns),row_count,passed,{"missing_columns":",".join(missing),"row_count":str(row_count)},aware(now,"now"),aware(now,"now")+self.import_ttl);response={"import_session_id":str(value.import_session_id),"preview_passed":passed,"missing_columns":list(missing),"version":0};command=IdempotentCommand(session.user_id,"IMPORT_PREVIEW",idempotency_key,payload_hash,200,response,aware(now,"now"));audit=self._audit(session,"IMPORT_PREVIEW",value.import_session_id,0,0,"SUCCEEDED",now,correlation_id);self.repository.save_import_and_command(value,command,audit,ApiUiEvent("UserActionAudited",session.account_id,aware(now,"now"),correlation_id,{"action":"IMPORT_PREVIEW"}));return response
 def commit_import(self,token,csrf,idempotency_key,import_session_id,file_hash,expected_version,now,correlation_id):
  session=self.authenticate(token,now,csrf);self._validate_command("IMPORT_COMMIT",idempotency_key,expected_version,correlation_id);value=self.repository.get_import(import_session_id)
  if value is None:raise NotFound("import preview not found")
  if value.account_id!=session.account_id:raise AuthorizationError()
  if value.version!=expected_version:raise VersionConflict()
  if value.status is ImportStatus.COMMITTED:
   existing=self.repository.find_command(session.user_id,"IMPORT_COMMIT",idempotency_key)
   if existing:return existing.response
   raise VersionConflict("import already committed")
  if aware(now,"now")>=value.expires_at:raise ValidationError("import preview expired")
  if not value.preview_passed or value.file_hash!=file_hash:raise ValidationError("file hash/schema does not match passed preview")
  payload={"import_session_id":import_session_id,"file_hash":file_hash,"expected_version":expected_version};payload_hash=self._hash(payload);cached=self.repository.find_command(session.user_id,"IMPORT_COMMIT",idempotency_key)
  if cached:
   if cached.payload_hash!=payload_hash:raise IdempotencyConflict()
   return cached.response
  result=self.backend.command("IMPORT_COMMIT",session.account_id,import_session_id,payload);updated=replace(value,status=ImportStatus.COMMITTED,committed_result_id=result.object_id,version=value.version+1);response=self._sanitize(dict(result.payload)|{"object_id":str(result.object_id),"version":updated.version});command=IdempotentCommand(session.user_id,"IMPORT_COMMIT",idempotency_key,payload_hash,200,response,aware(now,"now"));audit=self._audit(session,"IMPORT_COMMIT",import_session_id,expected_version,updated.version,"SUCCEEDED",now,correlation_id);self.repository.update_import_and_command(updated,command,audit,ApiUiEvent("BrokerImportCommitted",session.account_id,aware(now,"now"),correlation_id,{"import_session_id":str(import_session_id)}));return response
 def save_preference(self,token,csrf,theme,timezone_name,page_size,expected_version,now,correlation_id):
  session=self.authenticate(token,now,csrf);current=self.repository.get_preference(session.user_id)
  if (current.version if current else 0)!=expected_version:raise VersionConflict()
  value=UiPreference(session.user_id,theme,timezone_name,page_size,aware(now,"now"),expected_version+1,current.preference_id if current else uuid4());self.repository.save_preference(value);return value
 @staticmethod
 def _validate_command(action,key,version,correlation):
  fields={}
  if not action.strip():fields["action"]="required"
  if not key or len(key)>128:fields["Idempotency-Key"]="required and <=128 chars"
  if version<0:fields["expected_version"]="must be nonnegative"
  if not correlation:fields["correlation_id"]="required"
  if fields:raise ValidationError("invalid command",fields)
 @staticmethod
 def _audit(session,action,object_id,before,after,result,now,correlation):return UserActionAudit(session.user_id,session.account_id,action,object_id,before,after,result,aware(now,"now"),correlation,{"object_id":"" if object_id is None else str(object_id)})
 @staticmethod
 def _secret_hash(x):return hashlib.sha256(x.encode()).hexdigest()
 @staticmethod
 def _hash(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,separators=(",",":")).encode()).hexdigest()
 @classmethod
 def _sanitize(cls,value):
  def clean(x):
   if isinstance(x,str):return __import__("re").sub(r"(?<!\d)\d{8,}(?!\d)",lambda m:"*"*(len(m.group())-4)+m.group()[-4:],x)
   if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items() if str(k).lower() not in ("token","password","secret","raw_file")}
   if isinstance(x,(list,tuple)):return [clean(v) for v in x]
   return x
  return clean(dict(value))
