"""Opt-in CallMeBot delivery. Fixed HTTPS endpoint, secret-free public status."""
import hashlib
import json
import os
import queue
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request


def read(path,default):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default


def private_write(path,data):
    tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    os.chmod(tmp,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f)
    os.replace(tmp,path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def send_message(phone,key,text):
    query=urllib.parse.urlencode({'phone':phone,'apikey':key,'text':text[:1800]})
    request=urllib.request.Request('https://api.callmebot.com/whatsapp.php?'+query,headers={'User-Agent':'LUNA/1.0'})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=12) as response:
        body=response.read(32768).decode('utf-8',errors='replace').lower()
        # HTTP 200 can contain provider errors. Never expose echoed credentials/body.
        if response.status!=200 or any(word in body for word in ('error','invalid','not activated','not allowed','not sent','unable','failed')):
            raise ValueError('CallMeBot hat die Anfrage abgelehnt.')
        if not any(word in body for word in ('queued','sent','success')):
            raise ValueError('Antwort von CallMeBot nicht bestätigt.')


class WhatsApp:
    def __init__(self,folder,start_worker=True):
        self.path=folder/'whatsapp-private.json';self.events_path=folder/'whatsapp-events.json'
        self.lock=threading.RLock();self.closed=threading.Event();self.queue=queue.Queue(100);self.pending=set()
        self.data=read(self.path,{'recipients':[],'car_alerts':True,'system_alerts':False})
        self.events=read(self.events_path,{});self.delivery={};self.sender=send_message
        if start_worker:threading.Thread(target=self.worker,daemon=True).start()
    def status(self):
        with self.lock:
            return {'car_alerts':self.data['car_alerts'],'system_alerts':self.data['system_alerts'],
                    'recipients':[{k:v for k,v in r.items() if k!='key'}|{'has_key':bool(r['key']),'delivery':self.delivery.get(r['id'],{})} for r in self.data['recipients']]}
    def change(self,action,data):
        with self.lock:
            rows=self.data['recipients'];rid=data.get('id')
            if action=='settings':
                for key in ('car_alerts','system_alerts'):
                    if key in data:
                        if type(data[key]) is not bool:raise ValueError('Ungültige Benachrichtigungsauswahl')
                        self.data[key]=data[key]
            elif action=='delete':
                self.data['recipients']=[r for r in rows if r['id']!=rid];self.delivery.pop(rid,None)
            elif action=='save':
                old=next((r for r in rows if r['id']==rid),None)
                if rid and not old:raise ValueError('Empfänger wurde inzwischen gelöscht.')
                if not old and len(rows)>=10:raise ValueError('Maximal zehn Empfänger.')
                phone=re.sub(r'[\s()\-]','',str(data.get('phone','')))
                if phone.startswith('00'):phone='+'+phone[2:]
                if not re.fullmatch(r'\+[1-9][0-9]{7,14}',phone):raise ValueError('Telefonnummer mit Ländervorwahl eingeben, z. B. +491701234567.')
                key=str(data.get('key','')).strip()
                if not key and old and old['phone']==phone:key=old['key']
                if not re.fullmatch(r'[A-Za-z0-9_-]{4,200}',key):raise ValueError('Eigenen CallMeBot-API-Schlüssel für diese Nummer eingeben.')
                if any(r['phone']==phone and r['id']!=rid for r in rows):raise ValueError('Diese Nummer ist bereits eingerichtet.')
                if data.get('authorized') is not True and (not old or phone!=old['phone'] or key!=old['key']):raise ValueError('Freischaltung dieser Nummer bestätigen.')
                row={'id':rid or secrets.token_hex(8),'name':str(data.get('name','')).strip()[:60] or 'Empfänger','phone':phone,'key':key,'enabled':data.get('enabled',True) is True}
                self.data['recipients']=[r for r in rows if r['id']!=rid]+[row]
                if old and (phone!=old['phone'] or key!=old['key']):self.delivery.pop(rid,None)
            else:raise ValueError('Unbekannte Aktion')
            private_write(self.path,self.data)
            return self.status()
    def emit(self,event,title,body,category='car',cooldown=43200,recipient=None):
        now=time.time();count=0
        with self.lock:
            if category!='test' and not self.data.get(category+'_alerts',False):return 0
            for r in self.data['recipients']:
                if recipient and r['id']!=recipient:continue
                if not r['enabled'] and category!='test':continue
                key=hashlib.sha256((r['id']+'|'+event).encode()).hexdigest()
                last=self.events.get(key,{})
                if key in self.pending or now-last.get('success',0)<cooldown or now-last.get('attempt',0)<(60 if category=='test' else 900):continue
                if category!='test' and last.get('failures',0)>=3 and now-last.get('attempt',0)<86400:continue
                try:self.queue.put_nowait((r['id'],r['phone'],r['key'],key,title+'\n'+body,category,now))
                except queue.Full:continue
                self.pending.add(key);self.events[key]={**last,'attempt':now}
                self.delivery[r['id']]={'state':'queued','at':now,'message':'Wartet auf Versand'};count+=1
            if count:self.persist_events()
        return count
    def test(self,rid):
        if not any(r['id']==rid for r in self.data['recipients']):raise ValueError('Empfänger nicht gefunden.')
        if not self.emit('test','LUNA · WhatsApp-Test','Testnachricht: Die Einrichtung funktioniert, wenn diese Nachricht bei dir ankommt.','test',60,rid):raise ValueError('Test bereits angefordert. Bitte mindestens eine Minute warten.')
        return self.status()
    def persist_events(self):
        cutoff=time.time()-14*86400;self.events={k:v for k,v in self.events.items() if v.get('attempt',0)>cutoff}
        private_write(self.events_path,self.events)
    def process(self,item):
        rid,phone,secret,key,text,category,created=item
        with self.lock:
            r=next((r for r in self.data['recipients'] if r['id']==rid),None)
            valid=r and r['phone']==phone and r['key']==secret and (category=='test' or (r['enabled'] and self.data.get(category+'_alerts')))
        if not valid or time.time()-created>600:
            with self.lock:self.pending.discard(key)
            return
        try:
            self.sender(phone,secret,text)
            state='accepted';message='Von CallMeBot angenommen · Empfang am Handy prüfen'
            success=True
        except Exception:
            state='failed';message='Versand nicht bestätigt · Schlüssel, Freischaltung und Internet prüfen';success=False
        with self.lock:
            now=time.time();event=self.events.get(key,{})
            if success:event.update(success=now,failures=0)
            else:event['failures']=event.get('failures',0)+1
            self.events[key]=event;self.pending.discard(key);self.persist_events()
            if any(r['id']==rid for r in self.data['recipients']):self.delivery[rid]={'state':state,'at':now,'message':message}
    def worker(self):
        while not self.closed.is_set():
            try:item=self.queue.get(timeout=1)
            except queue.Empty:continue
            try:self.process(item)
            finally:self.queue.task_done()
            self.closed.wait(6) # Sequential, bounded delivery; no burst to the provider.
