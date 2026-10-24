"""Local measured energy integration and explicitly modelled battery arbitrage savings."""
import json
import math
import os
import sqlite3
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo


class History:
    def __init__(self,folder):
        self.path=folder/'history.sqlite3'
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, charge REAL DEFAULT 0, discharge REAL DEFAULT 0,
              valued REAL DEFAULT 0, saving REAL DEFAULT 0, cost REAL DEFAULT 0, avoided REAL DEFAULT 0,
              seconds REAL DEFAULT 0, gaps REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS samples (time REAL PRIMARY KEY, soc REAL, power REAL);''')
        os.chmod(self.path,0o600)
    def connect(self):return sqlite3.connect(self.path,timeout=10)
    def record(self,c,t,prices):
        if not c.get('statistics_enabled') or c['battery_capacity_kwh']<=0:return
        try:
            now=datetime.fromisoformat(t['time']);power=float(t['battery_power_w']);soc=float(t['soc'])
            if now.tzinfo is None or not all(math.isfinite(x) for x in (power,soc)) or not 0<=soc<=100 or abs(power)>20000:return
        except (KeyError,ValueError,TypeError):return
        zone=ZoneInfo(c['timezone']);eta=math.sqrt(c['roundtrip_efficiency'])
        model=[c['expected_serial'],c['battery_capacity_kwh'],c['roundtrip_efficiency'],c['wear_ct_kwh'],c['timezone']]
        with self.connect() as db:
            row=db.execute('SELECT data FROM state WHERE id=1').fetchone()
            state=json.loads(row[0]) if row else {}
            prev=state.get('prev');pool=state.get('pool',0);book=state.get('book',0)
            if prev and now.timestamp()<=prev['stamp']:return
            if prev and now.timestamp()-prev['stamp']<45:return
            current={'stamp':now.timestamp(),'power':power,'soc':soc,'app':bool(t.get('app_charging')),'pv':t.get('pv_input_w')}
            if state.get('model')!=model:prev=None;pool=book=0
            if prev:
                start=datetime.fromtimestamp(prev['stamp'],timezone.utc);dt=(now-start).total_seconds()
                if dt>150:
                    pool=book=0
                    day=now.astimezone(zone).date().isoformat()
                    db.execute('INSERT OR IGNORE INTO daily(day) VALUES(?)',(day,))
                    db.execute('UPDATE daily SET gaps=gaps+? WHERE day=?',(dt,day))
                else:
                    cuts={start,now}
                    for p in prices:
                        for edge in (p['start'],p['end']):
                            if start<edge<now:cuts.add(edge)
                    midnight=(start.astimezone(zone).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).astimezone(timezone.utc)
                    if start<midnight<now:cuts.add(midnight)
                    total=max(0,prev['soc']/100*c['battery_capacity_kwh'])
                    if pool>total and pool>0:book*=total/pool;pool=total
                    edges=sorted(cuts)
                    for a,b in zip(edges,edges[1:]):
                        seconds=(b-a).total_seconds();mid=a+(b-a)/2
                        # Ambiguous direction changes are not turned into invented savings.
                        avg=(prev['power']+power)/2 if prev['power']*power>=0 else 0
                        dc=abs(avg)*seconds/3600000
                        price=next((p['ct'] for p in prices if p['start']<=mid<p['end']),None)
                        charge=dc if avg>0 else 0;discharge=dc if avg<0 else 0
                        saving=valued=cost=avoided=0
                        if charge:
                            if (prev['app'] and current['app'] and price is not None and
                                all(type(v) in (int,float) and 0<=v<=50 for v in (prev['pv'],current['pv']))):
                                pool+=dc;book+=dc/eta*price/100
                            total+=dc
                        if discharge:
                            portion=min(dc,total)*min(1,pool/total) if total>0 else 0
                            used_cost=book*portion/pool if pool>0 else 0
                            pool=max(0,pool-portion);book-=used_cost;total=max(0,total-dc)
                            if price is not None:
                                valued=portion*eta;cost=used_cost
                                avoided=valued*price/100
                                saving=avoided-cost-valued*c['wear_ct_kwh']/100
                        day=mid.astimezone(zone).date().isoformat()
                        db.execute('INSERT OR IGNORE INTO daily(day) VALUES(?)',(day,))
                        db.execute('UPDATE daily SET charge=charge+?,discharge=discharge+?,valued=valued+?,saving=saving+?,cost=cost+?,avoided=avoided+?,seconds=seconds+? WHERE day=?',
                                   (charge,discharge,valued,saving,cost,avoided,seconds,day))
            db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(json.dumps({'prev':current,'pool':pool,'book':book,'model':model}),))
            db.execute('INSERT OR REPLACE INTO samples VALUES(?,?,?)',(now.timestamp(),soc,power))
            db.execute('DELETE FROM samples WHERE time<?',(now.timestamp()-30*86400,))
    def summary(self,c,now=None):
        now=now or datetime.now(timezone.utc);today=now.astimezone(ZoneInfo(c['timezone'])).date()
        with self.connect() as db:
            db.row_factory=sqlite3.Row
            rows=[dict(r) for r in db.execute('SELECT * FROM daily ORDER BY day')]
        keys=['charge','discharge','valued','saving','cost','avoided','seconds','gaps']
        def combine(selected):return {**{k:sum(r[k] for r in selected) for k in keys},'days':len(selected)}
        periods={}
        for name,days in [('today',1),('last30',30),('last365',365)]:
            start=(today-timedelta(days=days-1)).isoformat()
            periods[name]=combine([r for r in rows if start<=r['day']<=today.isoformat()])
        periods['yesterday']=combine([r for r in rows if r['day']==(today-timedelta(days=1)).isoformat()])
        grouped={}
        for label,n in [('months',7),('years',4)]:
            grouped[label]=[{'period':p,**combine([r for r in rows if r['day'][:n]==p])} for p in sorted({r['day'][:n] for r in rows},reverse=True)]
        return {'periods':periods,**grouped,'started':rows[0]['day'] if rows else None,
                'estimated':True,'enabled':c.get('statistics_enabled',True)}
