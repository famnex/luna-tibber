"""ntfy.sh publishing using the bounded, persistent notification queue."""
import json
import re
import secrets
import threading
import urllib.request
from whatsapp import WhatsApp,NoRedirect,private_write


def send_message(topic,token,text):
    title,_,message=text.partition('\n')
    payload={'topic':topic,'title':title,'message':message or title,'tags':['electric_plug'],'priority':3}
    headers={'Content-Type':'application/json','User-Agent':'LUNA/1.0'}
    if token:headers['Authorization']='Bearer '+token
    request=urllib.request.Request('https://ntfy.sh/',data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers=headers,method='POST')
    with urllib.request.build_opener(NoRedirect).open(request,timeout=12) as response:
        result=json.loads(response.read(32768))
        if response.status!=200 or result.get('event')!='message' or result.get('topic')!=topic or not result.get('id'):
            raise ValueError('ntfy hat die Nachricht nicht bestätigt.')


class Ntfy(WhatsApp):
    prefix='ntfy'
    address_field='topic'
    provider='ntfy'
    test_title='ntfy'
    def __init__(self,folder,start_worker=True):
        super().__init__(folder,start_worker=False);self.sender=send_message
        if start_worker:threading.Thread(target=self.worker,daemon=True).start()
    def status(self):
        result=super().status();result['server']='https://ntfy.sh'
        return result
    def change(self,action,data):
        if action in ('settings','delete'):return super().change(action,data)
        if action!='save':raise ValueError('Unbekannte Aktion')
        with self.lock:
            rows=self.data['recipients'];rid=data.get('id');old=next((r for r in rows if r['id']==rid),None)
            if rid and not old:raise ValueError('Topic wurde inzwischen gelöscht.')
            if not old and len(rows)>=10:raise ValueError('Maximal zehn Topics.')
            topic=str(data.get('topic','')).strip() or ('luna-'+secrets.token_hex(16) if not old else old['topic'])
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',topic) or topic in ('app','docs','static','file','v1','account','settings'):
                raise ValueError('Topic: 1–64 Buchstaben, Ziffern, Bindestriche oder Unterstriche; kein reservierter Name.')
            if any(r['topic']==topic and r['id']!=rid for r in rows):raise ValueError('Dieses Topic ist bereits eingerichtet.')
            token=str(data.get('key','')).strip()
            if not token and old and old['topic']==topic and not data.get('clear_key'):token=old['key']
            if token and not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',token):raise ValueError('Ungültiger ntfy-Zugriffstoken.')
            row={'id':rid or secrets.token_hex(8),'name':str(data.get('name','')).strip()[:60] or 'Meine Geräte','topic':topic,'key':token,'enabled':data.get('enabled',True) is True}
            self.data['recipients']=[r for r in rows if r['id']!=rid]+[row]
            if old and (topic!=old['topic'] or token!=old['key']):self.delivery.pop(rid,None)
            private_write(self.path,self.data)
            return self.status()
