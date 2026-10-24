"""Plan-only savings ledger. Never reads battery telemetry or requests measurements."""
import math
import os
import sqlite3
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo


class History:
    def __init__(self,folder):
        # Keep the previous measurement-based database untouched and separate.
        self.path=folder/'plan-history.sqlite3'
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS intervals (
                command TEXT, day TEXT, start REAL, end REAL,
                charge_rate REAL, useful_rate REAL, valued_rate REAL,
                saving_rate REAL, cost_rate REAL, avoided_rate REAL);
            CREATE INDEX IF NOT EXISTS interval_end ON intervals(end);''')
        os.chmod(self.path,0o600)
    def connect(self):return sqlite3.connect(self.path,timeout=10)
    def finish(self,now=None):
        stamp=(now or datetime.now(timezone.utc)).timestamp()
        with self.connect() as db:
            db.execute('UPDATE intervals SET end=MAX(start,?) WHERE end>?',(stamp,stamp))
    def record(self,c,event,prices):
        if not c.get('statistics_enabled') or event.get('event')!='charge_command':return
        try:
            start=datetime.fromisoformat(event['time']);watts=event['watts'];minutes=event['minutes']
            if start.tzinfo is None or type(watts) not in (int,float) or not math.isfinite(watts) or not 0<watts<=5000 or type(minutes) is not int or not 1<=minutes<=2:return
        except (KeyError,ValueError,TypeError):return
        from luna import economics_plan
        current=next((p['ct'] for p in prices if p['start']<=start<p['end']),None)
        reference=economics_plan(c,prices,start).get('reference_ct_kwh')
        eta=math.sqrt(c['roundtrip_efficiency'])
        charge_rate=watts/3600000
        useful_rate=charge_rate*eta
        valued=all(type(v) in (int,float) and math.isfinite(v) for v in (current,reference))
        cost_rate=charge_rate/eta*current/100 if valued else 0
        avoided_rate=useful_rate*reference/100 if valued else 0
        saving_rate=avoided_rate-cost_rate-useful_rate*c['wear_ct_kwh']/100 if valued else 0
        end=start+timedelta(minutes=minutes);zone=ZoneInfo(c['timezone'])
        command=start.isoformat()
        with self.connect() as db:
            if db.execute('SELECT 1 FROM commands WHERE id=?',(command,)).fetchone():return
            db.execute('INSERT INTO commands VALUES(?)',(command,))
            # Renewed finite-duration commands replace their predecessor, not add to it.
            db.execute('UPDATE intervals SET end=MAX(start,?) WHERE end>?',(start.timestamp(),start.timestamp()))
            left=start
            while left<end:
                local=left.astimezone(zone)
                midnight=(local.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).astimezone(timezone.utc)
                right=min(end,midnight)
                db.execute('INSERT INTO intervals VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (command,local.date().isoformat(),left.timestamp(),right.timestamp(),charge_rate,useful_rate,useful_rate if valued else 0,saving_rate,cost_rate,avoided_rate))
                left=right
    def summary(self,c,now=None):
        now=now or datetime.now(timezone.utc);today=now.astimezone(ZoneInfo(c['timezone'])).date()
        with self.connect() as db:
            db.row_factory=sqlite3.Row
            rows=[dict(r) for r in db.execute('''SELECT day,
                SUM(duration*charge_rate) charge, SUM(duration*useful_rate) discharge,
                SUM(duration*valued_rate) valued, SUM(duration*saving_rate) saving,
                SUM(duration*cost_rate) cost, SUM(duration*avoided_rate) avoided,
                SUM(duration) seconds, 0 gaps
                FROM (SELECT *,MAX(0,MIN(end,?)-start) duration FROM intervals WHERE start<? AND end>start)
                GROUP BY day ORDER BY day''',(now.timestamp(),now.timestamp()))]
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
                'estimated':True,'source':'plan','enabled':c.get('statistics_enabled',True)}
