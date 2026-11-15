"""Cached weather and dated prices for EV advice; never controls a charger."""
import hashlib
import json
import math
import os
import statistics
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

class CarContext:
    def __init__(self, folder):
        self.path=folder/'car-context.json';self.lock=threading.Lock()
        try:self.data=json.loads(self.path.read_text())
        except (OSError,ValueError):self.data={}
        self.attempt=0
    def snapshot(self, config):
        with self.lock:
            data=dict(self.data)
        if data.get('account')!=self.account(config):data['prices']=[]
        if data.get('location')!=self.location(config):data['weather']=[]
        return data
    @staticmethod
    def account(c):
        return hashlib.sha256(json.dumps([c.get('tibber_token'),c.get('tibber_home_id')]).encode()).hexdigest()
    @staticmethod
    def location(c):return [c.get('pv_latitude'),c.get('pv_longitude')]
    def refresh(self,c,prices,now=None):
        now=now or datetime.now(timezone.utc);data=self.snapshot(c)
        merged={r['start']:r for r in data.get('prices',[])}
        for r in prices:merged[r['start'].isoformat()]={'start':r['start'].isoformat(),'end':r['end'].isoformat(),'ct':r['ct']}
        data['prices']=[r for r in merged.values() if now-timedelta(days=8)<datetime.fromisoformat(r['end'])<now+timedelta(days=3)]
        data['account']=self.account(c)
        location=self.location(c)
        if all(type(v) in (float,int) for v in location) and -90<=location[0]<=90 and -180<=location[1]<=180 and (data.get('location')!=location or now.timestamp()-data.get('weather_at',0)>10800) and now.timestamp()-self.attempt>900:
            self.attempt=now.timestamp()
            try:
                query=urllib.parse.urlencode(dict(latitude=location[0],longitude=location[1],hourly='temperature_2m',timezone='GMT',timeformat='unixtime',forecast_days=8))
                with urllib.request.urlopen('https://api.open-meteo.com/v1/forecast?'+query,timeout=10) as response:raw=json.loads(response.read(500000))
                weather=[{'time':t,'c':v} for t,v in zip(raw['hourly']['time'],raw['hourly']['temperature_2m']) if type(t) in (int,float) and type(v) in (int,float) and math.isfinite(v) and -70<=v<=60]
                if weather:data.update(weather=weather,weather_at=now.timestamp(),location=location)
            except Exception:pass # Existing forecast retained; seasonal fallback after six hours.
        with self.lock:
            self.data=data
            tmp=self.path.with_suffix('.tmp');fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as out:json.dump(data,out)
            os.replace(tmp,self.path)
    def worker(self,closed,config,prices):
        while not closed.is_set():
            try:self.refresh(config(),list(prices()))
            except Exception:pass
            closed.wait(300)


def estimate_trip(t,p,start,context=None,now=None):
    """Transparent planning assumptions, not a measured vehicle calibration.

    Temperate base + cold driving losses + cabin heating and one warm-up per leg.
    Return km are halves of the entered TOTAL; return time remains arrival home.
    """
    context=context or {};now=now or datetime.now(timezone.utc)
    count=2 if t.get('round_trip',True) else 1;km=t['km']/count
    times=[start]
    if count==2:
        ret=datetime.combine(start.date(),datetime.strptime(t['return'],'%H:%M').time(),start.tzinfo)
        if ret<=start:ret+=timedelta(days=1)
        # Approximate return departure from arrival using a generic 50 km/h.
        times.append(max(start,ret-timedelta(hours=km/50)))
    energy=0;temperatures=[];sources=[]
    for when in times:
        weather=context.get('weather',[]) if 0<=now.timestamp()-context.get('weather_at',0)<=21600 else []
        sample=min(weather,key=lambda r:abs(r['time']-when.timestamp()),default=None)
        if sample and abs(sample['time']-when.timestamp())<=3600:temp=sample['c'];source='Wetterprognose'
        else:temp=[3,4,7,11,15,18,20,20,16,11,6,3][when.month-1];source='Saisonannahme'
        cold=max(0,20-temp);heat=0.65 if p.get('heat_pump',False) else 1
        driving=km*p['consumption']/100*(1+0.006*cold)
        cabin=(km/50*1.2+0.35)*cold/20*heat
        cooling=km/50*0.06*max(0,temp-25)
        energy+=driving+cabin+cooling;temperatures.append(round(temp,1));sources.append(source)
    return {'kwh':round(energy,3),'temperatures':temperatures,'source':'Wetterprognose' if all(s=='Wetterprognose' for s in sources) else 'Saisonannahme','legs':count}


def cheap_night(context,zone,now):
    """Compare contiguous two-hour windows, never isolated price spikes."""
    tz=ZoneInfo(zone);rows=[]
    for r in (context or {}).get('prices',[]):
        try:
            a=datetime.fromisoformat(r['start']);b=datetime.fromisoformat(r['end']);ct=float(r['ct'])
            if a.tzinfo and b>a and math.isfinite(ct):rows.append((a,b,ct))
        except (ValueError,TypeError,KeyError):continue
    rows.sort();windows=[]
    for start,_,_ in rows:
        end=start+timedelta(hours=2);a=start.astimezone(tz);b=(end-timedelta(seconds=1)).astimezone(tz)
        # A night runs 22:00–06:00. Each endpoint must belong to the same night.
        def night(d):return (d-timedelta(hours=6)).date() if d.hour<6 else d.date()
        if not (a.hour>=22 or a.hour<6) or not (b.hour>=22 or b.hour<6) or night(a)!=night(b):continue
        cursor=start;cost=0
        for x,y,ct in rows:
            if y<=cursor:continue
            if x>cursor or cursor>=end:break
            stop=min(y,end);cost+=ct*(stop-cursor).total_seconds();cursor=stop
        if cursor==end:windows.append((start,end,cost/7200,night(a)))
    historical={}
    for a,b,ct,day in windows:
        if b<=now and a>=now-timedelta(days=7):historical[day]=min(historical.get(day,float('inf')),ct)
    future=[w for w in windows if now<=w[0]<now+timedelta(hours=24)]
    result={'history_nights':len(historical),'qualified':False}
    if len(historical)<3:result['reason']=f'Nachtpreisvergleich: {len(historical)}/3 vergangene Nächte erfasst.';return result
    if not future:result['reason']='Noch kein vollständiges kommendes Nachtfenster bekannt.';return result
    a,b,ct,_=min(future,key=lambda w:w[2]);reference=statistics.median(historical.values())
    reduction=reference-ct
    result.update(start=a.isoformat(),end=b.isoformat(),ct=round(ct,2),reference_ct=round(reference,2),qualified=reduction>=max(5,abs(reference)*0.2))
    result['reason']='Mindestens 5 ct/kWh und 20 % unter dem Median der günstigsten 2-Stunden-Fenster vergangener Nächte.' if result['qualified'] else 'Kein außergewöhnlicher Nachtpreis: normales Bedarfsziel.'
    return result
