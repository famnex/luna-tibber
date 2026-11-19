"""Bounded optimisation of the existing shared-connector vehicle schedule.

Never issues commands. Moves/splits existing energy allocations only after a
chronological replay proves reserves, capacity, availability and charge time.
Prices beyond publication and PV are estimates, not guaranteed savings.
"""
from __future__ import annotations
import math
from copy import deepcopy
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from forecast import instant, average


def pv_surplus(c: dict, rows: list, measurement: dict, now: datetime) -> list:
    from price_cache import covers
    from pv import power
    from consumption import intervals
    try:
        if not rows or not 0< c['battery_capacity_kwh'] or not 0<= (now-instant(measurement['time'])).total_seconds()<=3600:return []
        soc=float(measurement['soc'])
        if not 0<=soc<=100:return []
    except (KeyError,TypeError,ValueError):return []
    end=min(max(r['end'] for r in rows),now+timedelta(days=7));extra=intervals(c.get('_consumption_rules',[]),now,end)
    capacity=c['battery_capacity_kwh'];energy=capacity*soc/100;floor=capacity*c['battery_floor_soc']/100
    eta=math.sqrt(c['roundtrip_efficiency']);a=now;out=[];full_at=None
    while a<end:
        b=min(end,a+timedelta(minutes=15));hours=(b-a).total_seconds()/3600
        if not covers(rows,a,b):break # Unknown solar hours must not imply a full house battery.
        load=(c['base_load_w']+c['battery_idle_w'])/1000+power(extra,a,b)
        net=(power(rows,a,b)-load)*hours
        if net<0:energy=max(min(floor,energy),energy+net/eta);full_at=None
        else:
            fill=min(net,max(0,capacity-energy)/eta);energy+=fill*eta
            if energy>=capacity-1e-6:
                if full_at is None:full_at=a+timedelta(hours=fill/(net/hours)) if net else a
                available=net-fill
                start=max(a,full_at);duration=(b-start).total_seconds()/3600
                # Conservative single-phase minimum; below this EV may not start.
                if duration>0 and available/duration>=1.4:
                    out.append({'start':start,'end':b,'kw':min(c.get('car_charge_kw',11),available/duration),'full_at':full_at})
        a=b
    return out


def optimise(plan: dict, vehicles: list, baseline: dict, zone: str, now: datetime, context: dict) -> dict:
    from car_planning import trip_occurs
    from car_context import estimate_trip
    if baseline.get('status')!='planned' or not baseline.get('sessions'):return baseline
    settings=context.get('energy_settings',{});prices=context.get('forecast_prices',[])
    pv=context.get('pv_surplus',[]);tz=ZoneInfo(zone);kw=settings.get('car_charge_kw',11);eta=settings.get('car_charge_efficiency',.9)
    threshold=settings.get('forecast_min_saving_ct',5);minpv=settings.get('pv_car_min_kwh',3)
    sessions=deepcopy(baseline['sessions']);journeys=[];away={};caps={};floors={};initial={}
    horizon=max(instant(s['covers_until']) for s in sessions)
    for v in vehicles:
        p=plan['profiles'][v['id']];vid=v['id'];caps[vid]=p['capacity'];floors[vid]=p['reserve']*p['capacity']/100;initial[vid]=v['soc']*p['capacity']/100;away[vid]=[]
        for offset in range(-1,10):
            day=now.astimezone(tz).date()+timedelta(days=offset)
            for t in plan.get('trips',[]):
                if t['vehicle']!=vid or not trip_occurs(plan,t,day):continue
                a=datetime.combine(day,time.fromisoformat(t['departure']),tz).astimezone(timezone.utc)
                b=datetime.combine(day,time.fromisoformat(t['return']),tz).astimezone(timezone.utc)
                if b<=a:b+=timedelta(days=1)
                away[vid].append((a,b))
                if now<=a<horizon:journeys.append((a,vid,estimate_trip(t,p,a,context,now)['kwh']))
    def free(vid,a,b):return not any(x<b and y>a for x,y in away[vid])
    def night_key(s):
        a=instant(s['start']).astimezone(tz)
        return (a-timedelta(days=1) if a.hour<6 else a).date() if a.hour>=22 or a.hour<6 else None
    def replay(items,annotate=False):
        events=[];ordered=sorted(items,key=lambda s:instant(s['start']));nights={}
        for i,s in enumerate(ordered):
            a,b=instant(s['start']),instant(s['end']);vid=s['id'];nk=night_key(s)
            if a<now or b<=a or not free(vid,a,b) or s['kwh']>(b-a).total_seconds()/3600*kw*eta+.011:return False
            if nk is not None and nk in nights and nights[nk]!=vid:return False
            if nk is not None:nights[nk]=vid
            if i and instant(ordered[i-1]['end'])>a:return False
            events.extend([(a,1,vid,s),(b,0,vid,s)])
        events.extend((a,2,vid,kwh) for a,vid,kwh in journeys)
        energy=initial.copy();before={}
        for a,kind,vid,value in sorted(events,key=lambda e:(e[0],e[1])):
            if kind==1:before[id(value)]=energy[vid]
            elif kind==0:
                energy[vid]+=value['kwh']
                if energy[vid]>caps[vid]+.02:return False
                if annotate:
                    value['current_soc']=next(v['soc'] for v in vehicles if v['id']==vid)
                    value['expected_start_soc']=round(before[id(value)]/caps[vid]*100,1)
                    value['target_soc']=min(100,math.ceil((energy[vid]-1e-6)/caps[vid]*100))
                    value['add_soc']=round(value['kwh']/caps[vid]*100,1)
                    value['projected_before_kwh']=round(max(0,initial[vid]-before[id(value)]),2)
            else:
                energy[vid]-=value
                if energy[vid]<floors[vid]-.02:return False
        return True
    def priced(s,a,b):
        value=average(prices,a,b)
        return dict(s,start=a.isoformat(),end=b.isoformat(),source='grid',price_ct=value,
                    estimated=any(r.get('source')=='forecast' for r in prices if instant(r['start'])<b and instant(r['end'])>a)) if value is not None else None
    # First replace broad night bounds with a feasible cheapest contiguous block.
    for i,s in enumerate(sessions):
        a,b=instant(s['start']),instant(s['end']);duration=timedelta(minutes=15*math.ceil(s['kwh']/(kw*eta)*4))
        candidates=[];cursor=a.replace(second=0,microsecond=0)
        if cursor<a:cursor+=timedelta(minutes=1)
        while cursor+duration<=b:
            item=priced(s,cursor,cursor+duration)
            if item:candidates.append(item)
            cursor+=timedelta(minutes=15)
        if candidates:sessions[i]=min(candidates,key=lambda x:x['price_ct'])
        else:s['source']='grid';s['estimated']=True
    if not replay(sessions):return {**baseline,'message':baseline.get('message','')+' Preis-/PV-Optimierung konnte Ladezeit und Reserven nicht bestätigen.'}
    # Earlier full charging blocks, at most 3 days before the original allocation.
    for i,s in enumerate(list(sessions)):
        if s.get('price_ct') is None:continue
        original=instant(s['start']);duration=instant(s['end'])-original;candidates=[]
        for r in prices:
            a=instant(r['start']);b=a+duration;local=a.astimezone(tz)
            if not max(now,original-timedelta(days=3))<=a<original:continue
            # Day blocks and night blocks; never run a noon block into the evening.
            window_end=local.replace(hour=15 if 11<=local.hour<15 else 6,minute=0,second=0,microsecond=0)
            if local.hour>=22:window_end+=timedelta(days=1)
            if not (local.hour<6 or local.hour>=22 or 11<=local.hour<15) or b>window_end.astimezone(timezone.utc):continue
            item=priced(s,a,b)
            if not item or s['price_ct']-item['price_ct']<threshold:continue
            candidate=sessions[:];candidate[i]=item
            if replay(candidate):candidates.append(item)
        if candidates:
            winner=min(candidates,key=lambda x:x['price_ct']);winner['advanced_from']=s['start'];winner['saving_eur']=round((s['price_ct']-winner['price_ct'])*s['kwh']/eta/100,2);sessions[i]=winner
    # PV is allocated once, in chronological blocks, across both vehicles.
    groups=[]
    for r in pv:
        if groups and instant(groups[-1][-1]['end'])==instant(r['start']):groups[-1].append(r)
        else:groups.append([r])
    for group in groups:
        a,b=instant(group[0]['start']),instant(group[-1]['end'])
        available=sum(r['kw']*(instant(r['end'])-instant(r['start'])).total_seconds()/3600 for r in group)*eta
        if available<minpv:continue
        # Next required allocation first, then the more depleted car.
        for s in sorted(sessions,key=lambda x:(instant(x['start']),x.get('expected_start_soc',100))):
            if s.get('source')=='pv' or (s.get('price_ct') is not None and s['price_ct']<=0) or not free(s['id'],a,b):continue
            amount=min(available,s['kwh']);part=dict(s,start=a.isoformat(),end=b.isoformat(),kwh=round(amount,3),source='pv',estimated=True,full_at=instant(group[0]['full_at']).isoformat())
            for key in ('price_ct','saving_eur','advanced_from'):part.pop(key,None)
            candidate=[dict(x) for x in sessions if x is not s]
            if s['kwh']-amount>.05:candidate.append(dict(s,kwh=round(s['kwh']-amount,3)))
            candidate.append(part)
            if replay(candidate):sessions=candidate;break
    sessions.sort(key=lambda s:instant(s['start']));replay(sessions,True)
    return {'status':'planned','sessions':sessions,'message':'Gemeinsamer Plan mit Ladezeit, Fahrten und Reserve. Netzpreise und PV außerhalb bestätigter Daten sind Schätzungen; Umsetzung in evcc.'}


def pv_opportunity(vehicles: list, slots: list, settings: dict, zone: str, now: datetime) -> dict|None:
    """Conditional morning heads-up; never subtracts energy from a driving need."""
    today=now.astimezone(ZoneInfo(zone)).date();rows=[r for r in slots if instant(r['start']).astimezone(ZoneInfo(zone)).date()==today and instant(r['end'])>now]
    energy=sum(r['kw']*(instant(r['end'])-instant(r['start'])).total_seconds()/3600 for r in rows)*settings.get('car_charge_efficiency',.9)
    eligible=[v for v in vehicles if isinstance(v.get('soc'),(int,float)) and v.get('capacity') and v['soc']<98]
    if energy<settings.get('pv_car_min_kwh',3) or not eligible:return None
    v=min(eligible,key=lambda v:(v.get('deadline') or '9999',v['soc']))
    return {'id':v['id'],'name':v['name'],'start':instant(rows[0]['start']).isoformat(),'end':instant(rows[-1]['end']).isoformat(),'full_at':instant(rows[0]['full_at']).isoformat(),'kwh':round(min(energy,(100-v['soc'])*v['capacity']/100),1),'conditional':True}
