"""Cached Open-Meteo irradiation -> conservative AC-equivalent solar forecast.
GTI is the mean of the preceding hour; UTC epochs avoid DST ambiguity.
https://open-meteo.com/en/docs (CC BY 4.0 data; free API for non-commercial use)
"""
import fcntl
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen
from price_cache import covers

KEYS=('pv_enabled','pv_latitude','pv_longitude','pv_kwp','pv_tilt','pv_azimuth','pv_ac_limit_kw','pv_factor','pv_buffer_pct')
REFRESH=3*3600
MAX_AGE=6*3600
RETRY=900


def fingerprint(c):
    return hashlib.sha256(json.dumps([c.get(k,10.0 if k=='pv_buffer_pct' else None) for k in KEYS]).encode()).hexdigest()


def fetch(c):
    query=dict(latitude=c['pv_latitude'],longitude=c['pv_longitude'],
               hourly='global_tilted_irradiance',tilt=c['pv_tilt'],azimuth=c['pv_azimuth'],
               timezone='GMT',timeformat='unixtime',forecast_days=3)
    with urlopen('https://api.open-meteo.com/v1/forecast?'+urlencode(query),timeout=15) as r:
        data=json.loads(r.read(2_000_000))
    return parse(c,data)


def parse(c,data):
    hourly=data['hourly'];times=hourly['time'];values=hourly['global_tilted_irradiance']
    if len(times)!=len(values) or not times:raise ValueError('Unvollständige PV-Prognose')
    rows=[]
    for stamp,value in zip(times,values):
        if type(stamp) not in (int,float) or not math.isfinite(stamp):raise ValueError('Ungültige Prognosezeit')
        end=datetime.fromtimestamp(stamp,timezone.utc)
        # Missing hours remain gaps, never silently become zero production.
        if value is None:continue
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=2000:
            raise ValueError('Ungültige Strahlungsprognose')
        kw=min(c['pv_ac_limit_kw'],c['pv_kwp']*value/1000*.85)*c['pv_factor']*(1-c.get('pv_buffer_pct',10.0)/100)
        rows.append({'start':end-timedelta(hours=1),'end':end,'kw':kw})
    return rows


def read(c,folder,now=None):
    now=now or datetime.now(timezone.utc)
    if not c.get('pv_enabled'):return {'enabled':False,'rows':[],'reason':'PV-Prognose deaktiviert'}
    empty={'enabled':True,'rows':[],'reason':'PV-Prognose fehlt oder ist veraltet · Planung ohne PV-Abzug'}
    try:
        d=json.loads((folder/'pv-forecast.json').read_text())
        age=now.timestamp()-d['fetched_at']
        if d['key']!=fingerprint(c) or not 0<=age<=MAX_AGE:return empty
        rows=[];last=None
        for r in d['rows']:
            a,b=datetime.fromisoformat(r['start']),datetime.fromisoformat(r['end']);kw=r['kw']
            if a.tzinfo is None or b.tzinfo is None or b-a!=timedelta(hours=1) or (last and a<last) or type(kw) not in (int,float) or not math.isfinite(kw) or not 0<=kw<=c['pv_ac_limit_kw']:
                raise ValueError('Ungültiger Prognosecache')
            rows.append({'start':a,'end':b,'kw':kw});last=b
        return {'enabled':True,'rows':rows,'age_seconds':int(age),'reason':'Konservative PV-Prognose'+(' · letzter Abruf fehlgeschlagen, gültiger Cache' if d.get('failed') else '')}
    except (OSError,ValueError,TypeError,KeyError,OverflowError):return empty


def refresh(c,folder,now=None,fetcher=None):
    """Shared cache for web worker and CLI. No hardware or telemetry calls."""
    if not c.get('pv_enabled'):return
    from luna import write_json
    now=now or datetime.now(timezone.utc);stamp=now.timestamp();path=folder/'pv-forecast.json'
    with (folder/'pv-forecast.lock').open('a') as lock:
        os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        try:d=json.loads(path.read_text())
        except (OSError,ValueError):d={}
        if not isinstance(d,dict):d={}
        if d.get('key')!=fingerprint(c):d={}
        cached=read(c,folder,now)
        if cached['rows'] and 0<=stamp-d.get('fetched_at',0)<REFRESH:return
        if 0<=stamp-d.get('attempted_at',0)<RETRY:return
        try:
            rows=(fetcher or fetch)(c)
            if not covers(rows,now,now+timedelta(hours=36)):raise ValueError('Prognose hat Lücken')
            d={'key':fingerprint(c),'fetched_at':stamp,'rows':[{**r,'start':r['start'].isoformat(),'end':r['end'].isoformat()} for r in rows]}
        except Exception:
            d={**d,'key':fingerprint(c),'failed':True}
        d['attempted_at']=stamp
        write_json(path,d)


def attach(c,folder,now=None):
    return {**c,'_pv':read(c,folder,now)}


def rows_for(c,start,end):
    rows=c.get('_pv',{}).get('rows',[]) if c.get('pv_enabled') else []
    return rows if covers(rows,start,end) else []


def power(rows,start,end):
    hours=(end-start).total_seconds()/3600
    return sum(max(0,(min(end,r['end'])-max(start,r['start'])).total_seconds())/3600*r['kw'] for r in rows)/hours if hours>0 else 0


def night_target(c,start,power_w):
    """Only lower the target when the chronological whole-day load is coverable.
    PV surplus is credited after direct load and losses, limited by charge power.
    Uncoverable demand retains the original price-prioritised energy budget.
    """
    from dispatch import night_bounds,demand_rows
    end,_=night_bounds(c,start)
    target=c['target_soc'];capacity=c['battery_capacity_kwh'];limit=capacity*target/100
    out={'applied':False,'target_soc':target,'reduction_kwh':0,'reason':c.get('_pv',{}).get('reason','PV-Prognose deaktiviert')}
    if not c.get('pv_enabled'):return out
    rows=rows_for(c,start,end)
    if end<=start or not rows:
        out['reason']='PV-Tagesprognose unvollständig · Nachtziel unverändert';return out
    if c['base_load_w']<=0 or capacity<=0:
        out['reason']='Für PV-Planung Akkukapazität und Grundverbrauch einstellen';return out
    demand=demand_rows(c,[{'start':start,'end':end,'ct':0}],start,end)
    eta=math.sqrt(c['roundtrip_efficiency']);surplus=0;net=[];generation=0;direct=0
    for r in demand:
        h=(r['end']-r['start']).total_seconds()/3600
        solar=r.get('pv_kw',0);load=r['gross_load_kw']
        generation+=solar*h;direct+=min(solar,load)*h
        charge=min(max(0,solar-load)*eta,power_w/1000)*h
        surplus+=charge
        net.append(max(0,load-solar)/eta*h-charge+c.get('battery_idle_w',0)/1000*h)
    required=0;feasible=True
    for delta in reversed(net):
        required=max(0,required+delta)
        if required>limit+1e-8:feasible=False
    adjusted=max(0,min(limit,max(limit-surplus,required))) if feasible else limit
    out.update(applied=True,target_soc=adjusted/capacity*100,reduction_kwh=limit-adjusted,
               generation_kwh=generation,direct_kwh=direct,surplus_kwh=surplus,
               reason='PV-Überschuss und zeitlicher Hausbedarf berücksichtigt' if limit-adjusted>1e-8 else 'PV berücksichtigt · voller Nachtbedarf bleibt erforderlich')
    return out
