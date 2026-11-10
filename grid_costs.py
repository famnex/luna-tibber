"""Persistent measured grid-import ledger. No device IO or inferred missing usage."""
import hashlib
import math
import sqlite3
import threading
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo


def finite(v):return type(v) in (int,float) and math.isfinite(v)

class GridCosts:
    def __init__(self,folder):
        self.path=folder/'grid-costs.sqlite3';self.lock=threading.Lock()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS samples(device TEXT PRIMARY KEY,t REAL,kwh REAL);
            CREATE TABLE IF NOT EXISTS costs(device TEXT,a REAL,b REAL,kwh REAL,eur REAL, PRIMARY KEY(device,a,b));
            CREATE INDEX IF NOT EXISTS cost_time ON costs(device,a,b);''')
        self.path.chmod(0o600)
    def connect(self):return sqlite3.connect(self.path,timeout=5)
    def device(self,c):return hashlib.sha256(c.get('expected_serial','').encode()).hexdigest()
    def record(self,c,event,prices):
        m=event.get('meter') or {}
        if not c.get('expected_serial') or not m.get('valid') or not finite(m.get('import_kwh')) or m['import_kwh']<0:return
        try:t=datetime.fromisoformat(m['measured_at']).timestamp()
        except (KeyError,ValueError,TypeError):return
        key=self.device(c);value=m['import_kwh']
        with self.lock,self.connect() as db:
            prev=db.execute('SELECT t,kwh FROM samples WHERE device=?',(key,)).fetchone()
            if prev and t<=prev[0]:return
            db.execute('INSERT OR REPLACE INTO samples VALUES(?,?,?)',(key,t,value))
            if not prev:return
            a,old=prev;duration=t-a;delta=value-old
            # No interpolation over outages, resets or implausible house loads.
            if duration>600 or delta<0 or delta/duration*3600>100:return
            pieces=[];cursor=a
            for p in sorted(prices,key=lambda p:p['start']):
                left=max(a,p['start'].timestamp());right=min(t,p['end'].timestamp())
                if right<=left:continue
                if left>cursor+.001 or left<cursor-.001 or not finite(p.get('ct')):return
                energy=delta*(right-left)/duration
                pieces.append((key,left,right,energy,energy*p['ct']/100));cursor=right
            if cursor<t-.001:return
            db.executemany('INSERT OR IGNORE INTO costs VALUES(?,?,?,?,?)',pieces)
    def summary(self,c,now=None):
        now=now or datetime.now(timezone.utc);local=now.astimezone(ZoneInfo(c['timezone']))
        today=local.replace(hour=0,minute=0,second=0,microsecond=0)
        starts={'today':today,'yesterday':today-timedelta(days=1),'week':today-timedelta(days=today.weekday()),'month':today.replace(day=1),'year':today.replace(month=1,day=1)}
        with self.connect() as db:
            rows=db.execute('SELECT a,b,kwh,eur FROM costs WHERE device=? AND b>? ORDER BY a',(self.device(c),min(x.timestamp() for x in starts.values()))).fetchall()
        result={}
        for name,start in starts.items():
            a=start.timestamp();b=(today if name=='yesterday' else now).timestamp();energy=cost=seconds=0.
            for left,right,kwh,eur in rows:
                overlap=max(0,min(b,right)-max(a,left))
                if overlap:
                    fraction=overlap/(right-left);energy+=kwh*fraction;cost+=eur*fraction;seconds+=overlap
            result[name]={'kwh':energy,'eur':cost,'ct_kwh':100*cost/energy if energy>1e-9 else None,'coverage_pct':min(100,100*seconds/(b-a)) if b>a else 0,'hours':seconds/3600,'start':start.isoformat(),'end':datetime.fromtimestamp(b,timezone.utc).isoformat()}
        return {'periods':result}
