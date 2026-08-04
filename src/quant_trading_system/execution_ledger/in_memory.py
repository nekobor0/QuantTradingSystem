class InMemoryLedgerRepository:
 def __init__(self):self.accounts={};self.orders={};self.order_keys={};self.fills={};self.fill_keys={};self.entry_values=[];self.cash_events={};self.snapshots={};self.reconciliations={};self.imports={};self.events=[]
 def save_account(self,a):self.accounts[a.account_id]=a
 def get_account(self,i):return self.accounts.get(i)
 def update_account(self,a):self.accounts[a.account_id]=a
 def find_order(self,a,k):return self.order_keys.get((a,k))
 def get_order(self,i):return self.orders.get(i)
 def save_order(self,o,event):self.orders[o.order_id]=o;self.order_keys[(o.account_id,o.idempotency_key)]=o;self.events.append(event)
 def update_order(self,o,event):self.orders[o.order_id]=o;self.order_keys[(o.account_id,o.idempotency_key)]=o;self.events.append(event)
 def find_fill(self,b,a,k):return self.fill_keys.get((b,a,k))
 def get_fill(self,i):return self.fills.get(i)
 def reversal_for(self,i):return next((x for x in self.fills.values() if x.reverses_fill_id==i),None)
 def record_fill(self,f,entries,order,event):self.fills[f.fill_id]=f;self.fill_keys[(f.broker,f.account_id,f.broker_fill_id)]=f;self.entry_values.extend(entries);self.orders[order.order_id]=order;self.order_keys[(order.account_id,order.idempotency_key)]=order;self.events.append(event)
 def entries(self,a):return tuple(x for x in self.entry_values if x.account_id==a)
 def find_cash_event(self,a,r):return self.cash_events.get((a,r))
 def record_cash(self,v,e,event):self.cash_events[(v.account_id,v.external_ref)]=v;self.entry_values.append(e);self.events.append(event)
 def save_snapshot(self,s):self.snapshots[s.snapshot_id]=s
 def save_reconciliation(self,r,a,event):self.reconciliations[r.reconciliation_id]=r;self.accounts[a.account_id]=a;self.events.append(event)
 def get_reconciliation(self,i):return self.reconciliations.get(i)
 def save_import(self,i):self.imports[(i.account_id,i.file_hash,i.format_version)]=i
 def find_import(self,a,h,v):return self.imports.get((a,h,v))
 def get_import(self,i):return next((x for x in self.imports.values() if x.import_id==i),None)
 def latest_event(self):return self.events[-1] if self.events else None
