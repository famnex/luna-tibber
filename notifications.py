"""Opt-in Web Push, persistent subscriptions, bounded queue and event deduplication."""
import base64
import hashlib
import json
import os
import queue
import threading
import time
from urllib.parse import urlsplit
from luna import write_json


def read(path,default):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default


def validate_subscription(sub):
    endpoint=sub.get('endpoint','');u=urlsplit(endpoint);host=u.hostname or ''
    allowed=host in ('fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com') or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
    if u.scheme!='https' or not allowed or u.username or u.password or u.port not in (None,443) or len(endpoint)>4096:
        raise ValueError('Unbekannter Push-Dienst oder ungültige Push-Adresse')
    keys=sub.get('keys',{})
    for key,size in [('p256dh',65),('auth',16)]:
        value=keys.get(key,'')
        try:decoded=base64.urlsafe_b64decode(value+'='*(-len(value)%4))
        except Exception:raise ValueError('Ungültiger Push-Schlüssel') from None
        if len(decoded)!=size:raise ValueError('Ungültiger Push-Schlüssel')
    return {'endpoint':endpoint,'keys':{k:keys[k] for k in ('p256dh','auth')}}


class Notifications:
    def __init__(self,folder,start_worker=True):
        self.folder=folder;self.lock=threading.RLock();self.queue=queue.Queue(maxsize=20)
        self.closed=threading.Event();self.error='';self.last=read(folder/'push-events.json',{})
        self.available=False;self.public_key=None
        try:
            from pywebpush import webpush
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
            import requests
            class PushSession(requests.Session):
                def post(self,*args,**kwargs):
                    kwargs['allow_redirects']=False
                    return super().post(*args,**kwargs)
            self.session=PushSession()
            self.sender=webpush
            path=folder/'push-key.pem'
            if path.exists():private=serialization.load_pem_private_key(path.read_bytes(),password=None)
            else:
                private=ec.generate_private_key(ec.SECP256R1())
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as f:f.write(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            self.private_key=str(path)
            self.public_key=base64.urlsafe_b64encode(private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
            self.available=True
        except ImportError:
            self.error='Push-Paket noch nicht installiert'
        if start_worker and self.available:threading.Thread(target=self.worker,daemon=True).start()
    def status(self):
        return {'available':self.available,'public_key':self.public_key,'error':self.error}
    def subscribe(self,sub,contact):
        if not self.available:raise ValueError(self.error)
        if not contact.startswith('mailto:') or '@' not in contact or len(contact)>254:
            raise ValueError('Für Push eine Kontakt-E-Mail in den Einstellungen eintragen')
        clean=validate_subscription(sub)
        with self.lock:
            rows=read(self.folder/'push-subscriptions.json',{})
            key=hashlib.sha256(clean['endpoint'].encode()).hexdigest()
            if key not in rows and len(rows)>=20:raise ValueError('Maximal 20 Push-Geräte')
            rows[key]=clean;write_json(self.folder/'push-subscriptions.json',rows)
    def unsubscribe(self,endpoint):
        with self.lock:
            rows=read(self.folder/'push-subscriptions.json',{})
            rows.pop(hashlib.sha256(endpoint.encode()).hexdigest(),None)
            write_json(self.folder/'push-subscriptions.json',rows)
    def emit(self,key,title,body,contact,cooldown=1800):
        if not self.available or not contact:return False
        with self.lock:
            if not read(self.folder/'push-subscriptions.json',{}):return False
            now=time.time()
            if now-self.last.get(key,0)<cooldown:return False
            try:self.queue.put_nowait((key,title,body,contact))
            except queue.Full:return False
            self.last={k:v for k,v in self.last.items() if now-v<7*86400}
            self.last[key]=now;write_json(self.folder/'push-events.json',self.last)
        return True
    def worker(self):
        while not self.closed.is_set():
            try:key,title,body,contact=self.queue.get(timeout=1)
            except queue.Empty:continue
            with self.lock:rows=read(self.folder/'push-subscriptions.json',{})
            for sub in rows.values():
                try:
                    validate_subscription(sub)
                    response=self.sender(subscription_info=sub,data=json.dumps({'title':title,'body':body,'tag':key}),
                        vapid_private_key=self.private_key,vapid_claims={'sub':contact},ttl=3600,timeout=10,requests_session=self.session)
                    if getattr(response,'status_code',200)>=300:raise RuntimeError('Push abgelehnt')
                    self.error=''
                except Exception as exc:
                    code=getattr(getattr(exc,'response',None),'status_code',None)
                    if code in (404,410):self.unsubscribe(sub['endpoint'])
                    self.error='Push-Zustellung fehlgeschlagen; Internet und Abonnement prüfen'
            self.queue.task_done()
