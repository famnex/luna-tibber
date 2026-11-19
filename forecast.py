"""Cached retail price forecasts. All prices ct/kWh, all instants aware UTC.

Energyforecast v2 supplies wholesale prices; only learned Tibber add-ons turn
these into estimated retail prices. Missing/stale profile slots remain gaps.
This service never supplies speculative prices to the inverter controller.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

UTC = timezone.utc
DEFAULTS = {'energyforecast_api_key':'', 'forecast_state':'HE',
            'forecast_min_saving_ct':5.0, 'car_charge_kw':11.0,
            'car_charge_efficiency':0.90, 'pv_car_min_kwh':3.0,
            'pv_reminder_time':'08:00'}
STATES = 'BW BY BE BB HB HH HE MV NI NW RP SL SN ST SH TH'.split()

def validate(c: dict) -> None:
    if not isinstance(c.get('energyforecast_api_key',''),str):raise ValueError('API-Schlüssel muss Text sein')
    if c.get('forecast_state','HE') not in STATES:raise ValueError('Ungültiges Bundesland')
    for key,lo,hi in [('forecast_min_saving_ct',0,100),('car_charge_kw',1,22),('car_charge_efficiency',.5,1),('pv_car_min_kwh',.5,50)]:
        v=c.get(key,DEFAULTS[key])
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Ungültige Prognose-Einstellung: '+key)
    from datetime import time
    t=c.get('pv_reminder_time','08:00')
    if len(t)!=5:raise ValueError('Morgen-Erinnerung als HH:MM eingeben')
    time.fromisoformat(t)

def instant(value) -> datetime:
    d=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('Zeitzone fehlt')
    return d.astimezone(UTC)

def atomic(path: Path, data: dict) -> None:
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.forecast-')
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f,default=lambda v:v.isoformat())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def account(c: dict) -> str:
    return hashlib.sha256(json.dumps([c.get('tibber_token'),c.get('tibber_home_id'),c.get('timezone'),c.get('forecast_state','HE')]).encode()).hexdigest()

def easter(year: int) -> date:
    a=year%19;b=year//100;cc=year%100;d=b//4;e=b%4;f=(b+8)//25;g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30;i=cc//4;k=cc%4;l=(32+2*e+2*i-h-k)%7;m=(a+11*h+22*l)//451
    n=h+l-7*m+114
    return date(year,n//31,n%31+1)

def day_type(day: date, state: str) -> str:
    """State-wide German holidays; municipality-specific days need local review."""
    y=day.year;ep=easter(y)
    fixed={(1,1),(5,1),(10,3),(12,25),(12,26)}
    if state in ('BW','BY','ST'):fixed.add((1,6))
    if state in ('BE','MV'):fixed.add((3,8))
    if state in ('BB','HB','HH','MV','NI','SN','ST','SH','TH'):fixed.add((10,31))
    if state in ('BW','BY','NW','RP','SL'):fixed.add((11,1))
    if state=='SL':fixed.add((8,15))
    if state=='TH':fixed.add((9,20))
    movable={ep+timedelta(days=n) for n in (-2,1,39,50)}
    if state in ('BW','BY','HE','NW','RP','SL'):movable.add(ep+timedelta(days=60))
    if state=='SN':
        x=date(y,11,22)
        movable.add(x-timedelta(days=(x.weekday()-2)%7))
    return 'weekend' if day.weekday()>=5 or (day.month,day.day) in fixed or day in movable else 'weekday'

def learn(c: dict, folder: Path, rows: list, now: datetime) -> None:
    """Called under the shared Tibber cache lock. Latest dated observation wins."""
    path=Path(folder)/'price-addons.json'
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):data={}
    before=json.dumps(data,sort_keys=True)
    if data.get('account')!=account(c):data={'account':account(c),'profile':{}}
    days={}
    zone=ZoneInfo(c.get('timezone','Europe/Berlin'))
    for r in sorted(rows,key=lambda r:r['start']):
        energy=r.get('energy_ct')
        if not isinstance(energy,(int,float)) or not math.isfinite(energy):continue
        start=instant(r['start']);local=start.astimezone(zone)
        bucket=data['profile'].setdefault(day_type(local.date(),c.get('forecast_state','HE')),{});key=local.strftime('%H:%M')
        days.setdefault(local.date().isoformat(),{})[key]={'ct':r['ct']-energy*1.19,'observed':start.isoformat()}
        if key not in bucket or instant(bucket[key]['observed'])<=start:
            bucket[key]={'ct':r['ct']-energy*1.19,'observed':start.isoformat()}
    # A complete local clock-day is a fallback, including cached historical days.
    complete=[(day,values) for day,values in days.items() if len(values)==96]
    if complete:
        day,values=max(complete)
        previous=data['profile'].get('latest',{})
        if not previous or max(v['observed'] for v in previous.values())<=max(v['observed'] for v in values.values()):data['profile']['latest']=values
    if json.dumps(data,sort_keys=True)!=before:atomic(path,data)

def parse(payload: dict, now: datetime) -> list:
    if payload.get('generated_at') and not -300<=(now-instant(payload['generated_at'])).total_seconds()<=86400:raise ValueError('Veraltete Prognose')
    rows={}
    for r in payload.get('data',[]):
        try:
            a,b=instant(r['start']),instant(r['end']);v=r['price_ct_kwh']
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):continue
            if b-a!=timedelta(minutes=15) or not now-timedelta(days=1)<=a<now+timedelta(days=14):continue
            rows[a]={'start':a,'end':b,'wholesale_ct':float(v)}
        except (KeyError,ValueError,TypeError):continue
    if not rows:raise ValueError('Keine gültigen Prognosepreise')
    return sorted(rows.values(),key=lambda r:r['start'])

def merge(c: dict, exact: list, predicted: list, profile: dict, now: datetime) -> list:
    zone=ZoneInfo(c.get('timezone','Europe/Berlin'));rows={}
    for r in predicted:
        a,b=instant(r['start']),instant(r['end']);local=a.astimezone(zone)
        slot=profile.get(day_type(local.date(),c.get('forecast_state','HE')),{}).get(local.strftime('%H:%M'))
        fallback=False
        if not slot or not -2<=(now-instant(slot['observed'])).total_seconds()/86400<=35:
            slot=profile.get('latest',{}).get(local.strftime('%H:%M'));fallback=True
        if not slot or not -2<=(now-instant(slot['observed'])).total_seconds()/86400<=35:continue
        rows[a]={'start':a,'end':b,'ct':r['wholesale_ct']*1.19+slot['ct'],'source':'forecast','addon_fallback':fallback}
    for r in exact:
        a,b=instant(r['start']),instant(r['end'])
        rows[a]={'start':a,'end':b,'ct':r['ct'],'source':'tibber'}
    return sorted((r for r in rows.values() if r['end']>now-timedelta(days=1)),key=lambda r:r['start'])

def average(rows: list, start: datetime, end: datetime):
    """Duration-weighted price; incomplete windows have no numeric estimate."""
    cursor=start;cost=0
    for r in rows:
        a,b=instant(r['start']),instant(r['end'])
        if b<=cursor:continue
        if a>cursor:break
        stop=min(b,end);cost+=r['ct']*(stop-cursor).total_seconds();cursor=stop
        if cursor>=end:return cost/(end-start).total_seconds()
    return None

def overview(rows: list, now: datetime, zone: str) -> list:
    tz=ZoneInfo(zone);local=now.astimezone(tz);out=[]
    if not rows:return out
    end=max(instant(r['end']) for r in rows).astimezone(tz).date()
    reference=sum(r['ct'] for r in rows)/len(rows)
    for i in range(min(14,(end-local.date()).days+1)):
        day=local.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=i);item={'date':day.date().isoformat()}
        for name,h1,h2 in [('night',0,5),('noon',11,15)]:
            a=day.replace(hour=h1).astimezone(UTC);b=day.replace(hour=h2).astimezone(UTC)
            value=average(rows,a,b)
            relevant=[r for r in rows if instant(r['start'])<b and instant(r['end'])>a]
            item[name]=None if value is None else {'ct':round(value,2),'estimated':any(r['source']=='forecast' for r in relevant),'trend':'cheap' if value<reference-3 else 'expensive' if value>reference+3 else 'medium'}
        if item['night'] or item['noon']:out.append(item)
    return out

class Forecast:
    def __init__(self, folder: Path):
        self.folder=Path(folder);self.lock=threading.Lock();self.attempt=0;self.attempt_key='';self.error=''
    def key(self,c):return hashlib.sha256((c.get('energyforecast_api_key') or os.getenv('ENERGYFORECAST_API_KEY','')).encode()).hexdigest()
    def refresh(self,c: dict,now: datetime|None=None) -> None:
        now=now or datetime.now(UTC);token=c.get('energyforecast_api_key') or os.getenv('ENERGYFORECAST_API_KEY','')
        if not token:return
        with self.lock:
            cache=self.cached(c,now)
            if cache and now.timestamp()-cache['fetched_at']<21600:return
            key=self.key(c)
            if self.attempt_key==key and now.timestamp()-self.attempt<900:return
            self.attempt=now.timestamp();self.attempt_key=key
            try:
                with urlopen('https://www.energyforecast.de/api/v2/forecast?'+urlencode({'token':token,'market_zone':'DE-LU'}),timeout=8) as response:payload=json.load(response)
                rows=parse(payload,now)
                atomic(self.folder/'energyforecast.json',{'key':key,'fetched_at':now.timestamp(),'rows':rows})
                self.error=''
            except Exception:self.error='Energyforecast nicht erreichbar oder ungültige Antwort. Gespeicherte Prognose höchstens 24 Stunden nutzbar.'
    def cached(self,c,now):
        try:
            d=json.loads((self.folder/'energyforecast.json').read_text())
            if d['key']==self.key(c) and 0<=now.timestamp()-d['fetched_at']<86400:return d
        except (OSError,ValueError,KeyError,TypeError):pass
        return None
    def snapshot(self,c: dict,exact: list,now: datetime|None=None) -> dict:
        now=now or datetime.now(UTC);cache=self.cached(c,now);profile={}
        try:
            d=json.loads((self.folder/'price-addons.json').read_text())
            if d.get('account')==account(c):profile=d['profile']
        except (OSError,ValueError,KeyError):pass
        enabled=bool(c.get('energyforecast_api_key') or os.getenv('ENERGYFORECAST_API_KEY'))
        rows=merge(c,exact,(cache or {}).get('rows',[]) if enabled else [],profile,now)
        return {'prices':rows,'days':overview(rows,now,c.get('timezone','Europe/Berlin')),'configured':enabled,'fetched_at':(cache or {}).get('fetched_at'),'error':self.error,
                'provider_until':max((r['end'] for r in (cache or {}).get('rows',[])),default=None),
                'addon_fallback':any(r.get('addon_fallback') for r in rows),
                'profile_slots':{k:len(v) for k,v in profile.items()},'settings':{k:c.get(k,v) for k,v in DEFAULTS.items() if k!='energyforecast_api_key'}}
