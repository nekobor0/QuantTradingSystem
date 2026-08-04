class InMemoryApiUiRepository:
 def __init__(self):self.sessions={};self.token_sessions={};self.commands={};self.audits={};self.imports={};self.preferences={};self.events=[]
 def save_session(self,x):self.sessions[x.session_id]=x;self.token_sessions[x.token_hash]=x
 def find_session_by_token_hash(self,x):return self.token_sessions.get(x)
 def update_session(self,x):self.sessions[x.session_id]=x;self.token_sessions[x.token_hash]=x
 def find_command(self,u,a,k):return self.commands.get((u,a,k))
 def save_command_and_audit(self,c,a,e):self.commands[(c.user_id,c.action,c.idempotency_key)]=c;self.audits[a.audit_id]=a;self.events.append(e)
 def save_audit(self,a,e):self.audits[a.audit_id]=a;self.events.append(e)
 def save_import(self,x):self.imports[x.import_session_id]=x
 def find_import(self,a,h,v):return next((x for x in self.imports.values() if x.account_id==a and x.file_hash==h and x.format_version==v),None)
 def get_import(self,i):return self.imports.get(i)
 def save_import_and_command(self,x,c,a,e):self.imports[x.import_session_id]=x;self.save_command_and_audit(c,a,e)
 def update_import_and_command(self,x,c,a,e):self.imports[x.import_session_id]=x;self.save_command_and_audit(c,a,e)
 def save_preference(self,x):self.preferences[x.user_id]=x
 def save_preference_and_command(self,x,c,a,e):self.preferences[x.user_id]=x;self.save_command_and_audit(c,a,e)
 def get_preference(self,u):return self.preferences.get(u)
