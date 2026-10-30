"""Rolling discharge allocation. Release normal self-consumption, never force export."""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from price_cache import covers


def night_bounds(c,now):
    local=now.astimezone(ZoneInfo(c['timezone']))
    midnight=local.replace(hour=0,minute=0,second=0,microsecond=0)
    start=midnight+timedelta(hours=c['night_start_hour'])
    end=midnight+timedelta(hours=c['night_end_hour'])
    if local>=end:start+=timedelta(days=1);end+=timedelta(days=1)
    return start.astimezone(timezone.utc),end.astimezone(timezone.utc)


def demand_rows(c,prices,start,end):
    """Split tariffs at demand boundaries; daily extra demand is AC-side kWh."""
    local=start.astimezone(ZoneInfo(c['timezone']))
    midnight=local.replace(hour=0,minute=0,second=0,microsecond=0)
    extra_a=(midnight+timedelta(hours=c.get('extra_load_start_hour',17))).astimezone(timezone.utc)
    extra_b=(midnight+timedelta(hours=c.get('extra_load_end_hour',19))).astimezone(timezone.utc)
    hours=(extra_b-extra_a).total_seconds()/3600
    extra_kw=c.get('extra_load_kwh',0)/hours if hours>0 else 0
    from consumption import intervals
    extras=intervals(c.get('_consumption_rules',[]),start,end)
    if '_consumption_rules' in c:extra_kw=0
    from pv import rows_for,power
    solar=rows_for(c,start,end)
    rows=[]
    for p in prices:
        a,b=max(start,p['start']),min(end,p['end'])
        if b<=a:continue
        edges=sorted({a,b,*[t for t in (extra_a,extra_b,*[t for x in extras for t in (x["start"],x["end"])],*[r["start"] for r in solar],*[r["end"] for r in solar]) if a<t<b]})
        for left,right in zip(edges,edges[1:]):
            kw=c['base_load_w']/1000+(extra_kw if extra_a<=left<extra_b else 0)+sum(x['kw'] for x in extras if x['start']<=left<x['end'])
            pv_kw=power(solar,left,right)
            rows.append({**p,'start':left,'end':right,'gross_load_kw':kw,'pv_kw':pv_kw,'load_kw':max(0,kw-pv_kw)})
    return sorted(rows,key=lambda p:p['start'])


def plan(c, prices, now, soc, hold_until=None):
    out={'enabled':bool(c.get('smart_discharge_enabled')), 'hold':False, 'complete':False,
         'windows':[], 'reason':'Smart-Entladen deaktiviert', 'available_kwh':None,
         'base_load_w':c.get('base_load_w',0),
         'stored_kwh':None,'reserved_later_kwh':None,
         'extra_load_kwh':c.get('extra_load_kwh',0)}
    if not out['enabled']:return out
    capacity=c['battery_capacity_kwh']; load=c.get('base_load_w',0)
    if capacity<=0 or load<=0:
        out['reason']='Akkukapazität und Grundverbrauch einstellen';return out
    if type(soc) not in (int,float) or not math.isfinite(soc) or not 0<=soc<=100:
        out['reason']='Aktuellen Akkustand abwarten';return out
    eta=math.sqrt(c['roundtrip_efficiency'])
    usable=soc/100*capacity
    reserve_start,reserve_end=night_bounds(c,now)
    if now<reserve_start:reserve_end=reserve_start
    idle=c.get('battery_idle_w',0)/1000*max(0,(reserve_end-now).total_seconds())/3600
    budget=max(0,usable-idle)*eta
    out.update(stored_kwh=usable,available_kwh=budget,reserved_later_kwh=0)
    if not c.get('_legacy_dispatch'):
        from joint import plan as joint_plan
        joint=joint_plan(c,prices,now,soc,hold_until=hold_until)
        if joint is not None:
            out.update(windows=joint['windows'],hold=joint['windows'][0]['action']=='hold',
                       complete=True,reason='Automatisch benötigte Energie schützen' if joint['guard']['hold'] else joint['reason'],joint=True,guard=joint['guard'],
                       reserved_later_kwh=None)
            return out
        if c.get('smart_discharge_enabled'):
            _,until=night_bounds(c,now)
            out.update(hold=True,reason='Preisdaten unvollständig · benötigte Energie vorläufig schützen',
                       guard={'hold':True,'unavailable':True},
                       windows=[{'start':now.isoformat(),'end':until.isoformat(),'action':'hold','allocated_kwh':0}])
            return out
    night_a,night_b=night_bounds(c,now)
    if night_a<=now<night_b:
        # Avoid cycling the freshly charged energy back out between cheap slots.
        out.update(hold=True,complete=True,reserved_later_kwh=budget,reason='Energie bis zum Tagesplan halten',windows=[{
            'start':now.isoformat(),'end':night_b.isoformat(),'action':'hold','allocated_kwh':0}])
        return out
    end=night_a
    if budget<=1e-9:
        out.update(hold=bool(idle>0 and usable>0),complete=True,reason='Verbleibende Energie für Akku-Eigenverbrauch' if idle>0 and usable>0 else 'Keine Energie mehr eingeplant · normale Gerätegrenzen',windows=[{
            'start':now.isoformat(),'end':end.isoformat(),'action':'hold' if idle>0 and usable>0 else 'discharge','allocated_kwh':0,'surplus_only':True}])
        return out
    if not covers(prices,now,end):
        out['reason']='Tagespreise unvollständig · normale Entladung';return out
    start=min(end,max(now,hold_until)) if hold_until else now
    if start>now:out['windows'].append({'start':now.isoformat(),'end':start.isoformat(),'action':'hold','allocated_kwh':0})
    rows=demand_rows(c,prices,start,end)
    allocations={}
    # Highest avoided purchase cost first; equal prices prefer the earlier slot.
    for p in sorted(rows,key=lambda p:(-p['ct'],p['start'])):
        demand=(p['end']-p['start']).total_seconds()/3600*p['load_kw']
        take=min(budget,demand);budget-=take
        allocations[p['start']]=take
    for p in rows:
        seconds=allocations[p['start']]/p['load_kw']*3600 if p['load_kw']>0 else 0
        split=min(p['end'],p['start']+timedelta(seconds=seconds))
        if seconds>=30:
            out['windows'].append({'start':p['start'].isoformat(),'end':split.isoformat(),'action':'discharge','ct':p['ct'],'allocated_kwh':allocations[p['start']]})
        else:split=p['start']
        if split<p['end']:
            out['windows'].append({'start':split.isoformat(),'end':p['end'].isoformat(),'action':'hold','ct':p['ct'],'allocated_kwh':0})
    # Once all reserved demand has passed, release any *actual* surplus. This is
    # permission, not forecast energy: never count it again in cost/SOC arithmetic.
    released=[w for w in out['windows'] if w['action']=='discharge']
    if released:
        tail=max(datetime.fromisoformat(w['end']) for w in released)
        for w in out['windows']:
            if datetime.fromisoformat(w['start'])>=tail:
                w.update(action='discharge',surplus_only=True)
    out['reserved_later_kwh']=sum(w.get('allocated_kwh',0) for w in out['windows'] if datetime.fromisoformat(w['start'])>now)
    out['complete']=True
    out['hold']=bool(out['windows'] and out['windows'][0]['action']=='hold')
    out['reason']='Energie für teurere Stunden reservieren' if out['hold'] else 'Entladung für Hausverbrauch freigegeben'
    return out


def projected_soc(c,prices,now,soc,until,hold_until=None):
    forecast=plan(c,prices,now,soc,hold_until)
    if not forecast['complete'] or not c['battery_capacity_kwh']:return soc,False
    used=0
    for w in forecast['windows']:
        a,b=datetime.fromisoformat(w['start']),datetime.fromisoformat(w['end'])
        fraction=max(0,(min(b,until)-a).total_seconds())/(b-a).total_seconds()
        used+=w.get('allocated_kwh',0)*min(1,fraction)
    idle=c.get('battery_idle_w',0)/1000*max(0,(until-now).total_seconds())/3600
    return max(0,soc-(used/math.sqrt(c['roundtrip_efficiency'])+idle)/c['battery_capacity_kwh']*100),True


def timeline(c,prices,now,soc,charge_preview,hold_until=None):
    """UI forecast; future SOC is an estimate, never sent as a control measurement."""
    if charge_preview.get('joint'):
        joint=charge_preview['joint']
        return {'enabled':True,'hold':joint['windows'][0]['action']=='hold','complete':True,
                'windows':joint['windows'],'reason':joint['reason'],'joint':True,'guard':joint['guard'],
                'stored_kwh':soc/100*c['battery_capacity_kwh'],
                'available_kwh':soc/100*c['battery_capacity_kwh']*math.sqrt(c['roundtrip_efficiency']),
                'reserved_later_kwh':None,'base_load_w':c['base_load_w'],'extra_load_kwh':c['extra_load_kwh'],'future_complete':True,
                'future_soc':joint['morning_soc'],'future_start':joint['night_end']}
    result=plan(c,prices,now,soc,hold_until)
    rows=list(result['windows'])
    if not result['enabled'] or result['available_kwh'] is None:return result
    night_a,night_b=night_bounds(c,now)
    if now<night_a:
        rows.append({'start':night_a.isoformat(),'end':night_b.isoformat(),'action':'hold','projected':True,'allocated_kwh':0})
    projected=charge_preview.get('planning_soc',soc)
    if c['battery_capacity_kwh']>0:
        projected=max(c.get('battery_floor_soc',0),min(100,projected+(charge_preview.get('planned_kwh',0)-charge_preview.get('idle_kwh',0))/c['battery_capacity_kwh']*100))
    future=plan(c,prices,night_b,projected,hold_until)
    if future['complete']:
        rows += [{**w,'projected':True} for w in future['windows']]
    return {**result,'windows':rows,'future_complete':future['complete'],
            'future_reason':future['reason'],'future_soc':projected,'future_start':night_b.isoformat()}


def economics(c,prices,now):
    """Compare night input with the forecast discharge slots, not the full day mean."""
    local=now.astimezone(ZoneInfo(c['timezone']))
    start=local.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(hours=c['night_end_hour'])
    if local>=start:start+=timedelta(days=1)
    start=start.astimezone(timezone.utc)
    forecast=plan({**c,'_legacy_dispatch':True},prices,start,c['target_soc'])
    if not forecast['complete']:return {'ok':False,'reason':forecast['reason']}
    slots=[w for w in forecast['windows'] if w['action']=='discharge']
    energy=sum(w.get('allocated_kwh',0) for w in slots)
    current=next((p for p in prices if p['start']<=now<p['end']),None)
    if not current or not energy:return {'ok':False,'reason':'Keine bewertbare spätere Entladung'}
    reference=sum(w['ct']*w.get('allocated_kwh',0) for w in slots)/energy
    effective=current['ct']/c['roundtrip_efficiency']+c['wear_ct_kwh']
    saving=reference-effective
    return {'ok':saving>0 and saving>=c['min_saving_ct_kwh'],
            'reason':'Preisvergleich mit den reservierten Entladestunden',
            'window_start':start.isoformat(),'window_end':forecast['windows'][-1]['end'],
            'reference_ct_kwh':reference,'effective_ct_kwh':effective,'saving_ct_kwh':saving,
            'assumption':'Grundverbrauch und Ziel-SOC; direkte PV-Deckung bei gültiger Prognose'}
