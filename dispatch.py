"""Rolling discharge allocation. Release normal self-consumption, never force export."""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from price_cache import covers


def plan(c, prices, now, soc):
    out={'enabled':bool(c.get('smart_discharge_enabled')), 'hold':False, 'complete':False,
         'windows':[], 'reason':'Smart-Entladen deaktiviert', 'available_kwh':None,
         'reserve_soc':c.get('reserve_soc',20), 'base_load_w':c.get('base_load_w',0)}
    if not out['enabled']:return out
    capacity=c['battery_capacity_kwh']; load=c.get('base_load_w',0)
    if capacity<=0 or load<=0:
        out['reason']='Akkukapazität und Grundverbrauch einstellen';return out
    if type(soc) not in (int,float) or not math.isfinite(soc) or not 0<=soc<=100:
        out['reason']='Aktuellen Akkustand abwarten';return out
    local=now.astimezone(ZoneInfo(c['timezone']))
    midnight=local.replace(hour=0,minute=0,second=0,microsecond=0)
    night_a=midnight+timedelta(hours=c['night_start_hour'])
    night_b=midnight+timedelta(hours=c['night_end_hour'])
    if night_a<=local<night_b:
        # Avoid cycling the freshly charged energy back out between cheap slots.
        out.update(hold=True,complete=True,reason='Nachtreserve halten',windows=[{
            'start':now.isoformat(),'end':night_b.astimezone(timezone.utc).isoformat(),'action':'hold'}])
        return out
    end=night_a if local<night_a else night_a+timedelta(days=1)
    end=end.astimezone(timezone.utc)
    if not covers(prices,now,end):
        out['reason']='Tagespreise unvollständig · normale Entladung';return out
    eta=math.sqrt(c['roundtrip_efficiency'])
    budget=max(0,soc-out['reserve_soc'])/100*capacity*eta
    out['available_kwh']=budget
    rows=[{**p,'start':max(now,p['start']),'end':min(end,p['end'])} for p in prices if p['end']>now and p['start']<end]
    allocations={}
    # Highest avoided purchase cost first; equal prices prefer the earlier slot.
    for p in sorted(rows,key=lambda p:(-p['ct'],p['start'])):
        demand=(p['end']-p['start']).total_seconds()/3600*load/1000
        take=min(budget,demand);budget-=take
        allocations[p['start']]=take
    for p in rows:
        seconds=allocations[p['start']]/(load/1000)*3600
        split=min(p['end'],p['start']+timedelta(seconds=seconds))
        if seconds>=30:
            out['windows'].append({'start':p['start'].isoformat(),'end':split.isoformat(),'action':'discharge','ct':p['ct']})
        else:split=p['start']
        if split<p['end']:
            out['windows'].append({'start':split.isoformat(),'end':p['end'].isoformat(),'action':'hold','ct':p['ct']})
    out['complete']=True
    out['hold']=bool(out['windows'] and out['windows'][0]['action']=='hold')
    out['reason']='Energie für teurere Stunden reservieren' if out['hold'] else 'Entladung für Hausverbrauch freigegeben'
    return out


def timeline(c,prices,now,soc,charge_preview):
    """UI forecast; future SOC is an estimate, never sent as a control measurement."""
    result=plan(c,prices,now,soc)
    rows=list(result['windows'])
    local=now.astimezone(ZoneInfo(c['timezone']))
    if c['night_start_hour']<=local.hour<c['night_end_hour'] and result['complete']:
        start=local.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(hours=c['night_end_hour'])
        projected=soc
        if c['battery_capacity_kwh']>0 and soc is not None:
            projected=min(c['target_soc'],soc+charge_preview.get('planned_kwh',0)/c['battery_capacity_kwh']*100)
        future=plan(c,prices,start.astimezone(timezone.utc),projected)
        rows += [{**w,'projected':True} for w in future['windows']]
    return {**result,'windows':rows}


def economics(c,prices,now):
    """Compare night input with the forecast discharge slots, not the full day mean."""
    local=now.astimezone(ZoneInfo(c['timezone']))
    start=local.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(hours=c['night_end_hour'])
    if local>=start:start+=timedelta(days=1)
    start=start.astimezone(timezone.utc)
    forecast=plan(c,prices,start,c['target_soc'])
    if not forecast['complete']:return {'ok':False,'reason':forecast['reason']}
    slots=[w for w in forecast['windows'] if w['action']=='discharge']
    seconds=sum((datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds() for w in slots)
    current=next((p for p in prices if p['start']<=now<p['end']),None)
    if not current or not seconds:return {'ok':False,'reason':'Keine bewertbare spätere Entladung'}
    reference=sum(w['ct']*(datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds() for w in slots)/seconds
    effective=current['ct']/c['roundtrip_efficiency']+c['wear_ct_kwh']
    saving=reference-effective
    return {'ok':saving>0 and saving>=c['min_saving_ct_kwh'],
            'reason':'Preisvergleich mit den reservierten Entladestunden',
            'window_start':start.isoformat(),'window_end':forecast['windows'][-1]['end'],
            'reference_ct_kwh':reference,'effective_ct_kwh':effective,'saving_ct_kwh':saving,
            'assumption':'Grundverbrauch und Ziel-SOC; keine PV-Prognose'}
