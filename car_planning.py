"""Driving requirements only. Does not issue commands or change the energy planner."""
import json
import math
import os
import threading
from datetime import date, time

class CarPlanning:
    def __init__(self, folder):
        self.path=folder/'car-planning.json';self.lock=threading.Lock()
    def read(self):
        try:
            data=json.loads(self.path.read_text())
            # Preserve existing shared holidays as independently editable per-car copies.
            periods=[]
            for h in data.get('holidays',[]):
                if h.get('vehicle'):periods.append(h)
                else:
                    for i,vid in enumerate(sorted(data.get('profiles',{}))):
                        periods.append(dict(h,id=h['id'][:70]+'-car-'+str(i),vehicle=vid))
            data['holidays']=periods
            return data
        except FileNotFoundError:return {'revision':0,'profiles':{},'trips':[],'holidays':[]}
    def save(self, data):
        with self.lock:
            old=self.read()
            if data.get('revision')!=old['revision']:raise ValueError('Plan wurde inzwischen geändert. Bitte neu laden.')
            profiles=data.get('profiles',{});trips=data.get('trips',[])
            if not isinstance(profiles,dict) or len(profiles)>10 or not isinstance(trips,list) or len(trips)>200:raise ValueError('Zu viele Fahrzeuge oder Fahrten.')
            def number(value, low, high):
                if isinstance(value,bool):raise ValueError('Ungültiger Zahlenwert')
                n=float(value)
                if not math.isfinite(n) or not low<=n<=high:raise ValueError('Zahlenwert außerhalb des erlaubten Bereichs')
                return n
            cleaned={}
            for key,p in profiles.items():
                if not isinstance(key,str) or not key or len(key)>200 or not isinstance(p,dict):raise ValueError('Ungültiges Fahrzeug')
                cleaned[key]={'name':str(p.get('name',''))[:60], 'consumption':number(p.get('consumption',18),5,60),
                              'capacity':None if p.get('capacity') in (None,'') else number(p['capacity'],5,200),
                              'reserve':number(p.get('reserve',20),0,80),'heat_pump':p.get('heat_pump') is True}
            rows=[];ids=set()
            for t in trips:
                if not isinstance(t,dict):raise ValueError('Ungültige Fahrt')
                tid=str(t.get('id',''));vid=str(t.get('vehicle',''))
                if not tid or len(tid)>100 or tid in ids or vid not in cleaned:raise ValueError('Fahrt ohne eindeutiges Fahrzeug / ID')
                ids.add(tid)
                kind=t.get('kind');days=t.get('days',[])
                if kind not in ('once','weekly'):raise ValueError('Ungültige Wiederholung')
                if kind=='weekly' and (not isinstance(days,list) or not days or any(type(d)!=int or d not in range(7) for d in days)):raise ValueError('Wochentage auswählen')
                day=str(t.get('date',''))
                if kind=='once':date.fromisoformat(day)
                dep=str(t.get('departure',''));ret=str(t.get('return',''))
                for value in (dep,ret):
                    if len(value)!=5:raise ValueError('Uhrzeit als HH:MM eingeben')
                    time.fromisoformat(value)
                rows.append({'id':tid,'vehicle':vid,'name':str(t.get('name','Fahrt'))[:80], 'km':number(t.get('km'),0.1,3000),
                             'kind':kind,'days':sorted(set(days)) if kind=='weekly' else [],'date':day if kind=='once' else '',
                             'departure':dep,'return':ret,'round_trip':t.get('round_trip',True) is True})
            holidays=data.get('holidays',old.get('holidays',[]))
            if not isinstance(holidays,list) or len(holidays)>100:raise ValueError('Zu viele Urlaubszeiträume.')
            periods=[];period_ids=set()
            for h in holidays:
                if not isinstance(h,dict):raise ValueError('Ungültiger Urlaub')
                hid=str(h.get('id',''))
                if not hid or len(hid)>100 or hid in period_ids:raise ValueError('Urlaub benötigt eine eindeutige ID')
                vid=str(h.get('vehicle',''))
                if vid not in cleaned:raise ValueError('Urlaub benötigt ein gültiges Fahrzeug.')
                start=date.fromisoformat(str(h.get('start','')));end=date.fromisoformat(str(h.get('end','')))
                if end<start:raise ValueError('Urlaubsende muss nach dem Beginn liegen.')
                period_ids.add(hid)
                periods.append({'id':hid,'vehicle':vid,'name':str(h.get('name','Urlaub'))[:80], 'start':start.isoformat(),'end':end.isoformat()})
            reminder=str(data.get('reminder_time',old.get('reminder_time','18:00')))
            if len(reminder)!=5:raise ValueError('Erinnerungszeit als HH:MM eingeben')
            time.fromisoformat(reminder)
            result={'reminder_time':reminder,'revision':old['revision']+1,'profiles':cleaned,'trips':rows,'holidays':sorted(periods,key=lambda h:h['start'])}
            tmp=self.path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as f:json.dump(result,f)
            os.replace(tmp,self.path);return result


def trip_occurs(plan, trip, day):
    key=day.isoformat()
    if trip['kind']=='once':return trip['date']==key
    return (day.weekday() in trip['days'] and
            not any(h.get('vehicle')==trip['vehicle'] and h['start']<=key<=h['end'] for h in plan.get('holidays',[])))


def advice(plan, snapshot, zone='Europe/Berlin', now=None, context=None):
    """Read-only demand priority, not an optimized charging schedule."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    now=now or datetime.now(timezone.utc)
    from car_context import estimate_trip, cheap_night
    local=now.astimezone(ZoneInfo(zone));result={'vehicles':[], 'priority':None,'warnings':[], 'estimates':[], 'night':cheap_night(context,zone,now)}
    # Same estimates for the week cards and recommendations, including today's past departures.
    for offset in range(7):
        day=local.date()+timedelta(days=offset)
        for t in plan.get('trips',[]):
            if not trip_occurs(plan,t,day):continue
            p=plan.get('profiles',{}).get(t['vehicle'],{'consumption':18})
            start=datetime.combine(day,time.fromisoformat(t['departure']),local.tzinfo)
            result['estimates'].append(dict(id=t['id'],date=day.isoformat(),**estimate_trip(t,p,start,context,now)))
    fetched=(snapshot or {}).get('fetched_at',0)
    if not fetched or now.timestamp()-fetched>1800:
        result['warnings'].append('Fahrzeugdaten fehlen oder sind älter als 30 Minuten. Anschluss-Empfehlung erst nach Aktualisierung.');return result
    for v in snapshot.get('devices',[]):
        vid=v['device']['id'];p=plan.get('profiles',{}).get(vid,{})
        detail=v.get('details',{});caps={c.get('id'):c for c in detail.get('capabilities',[])}
        name=p.get('name') or detail.get('info',{}).get('name') or v['device'].get('info',{}).get('name') or 'Fahrzeug'
        row={'id':vid,'name':name,'connected':caps.get('connector.status',{}).get('value')=='connected','connector_status':caps.get('connector.status',{}).get('value','unknown'),'charging_status':caps.get('charging.status',{}).get('value','unknown')}
        result['vehicles'].append(row)
        if v.get('error'):row['message']='Fahrzeugdaten nicht verfügbar.';continue
        try:soc=float(caps['storage.stateOfCharge']['value'])
        except (KeyError,ValueError,TypeError):row['message']='Ladestand fehlt.';continue
        if not math.isfinite(soc) or not 0<=soc<=100:row['message']='Ladestand ungültig.';continue
        stamp=next((caps['storage.stateOfCharge'].get(k) for k in ('updatedAt','timestamp','lastUpdated') if caps['storage.stateOfCharge'].get(k)),None)
        if stamp:
            try:
                measured=datetime.fromisoformat(str(stamp).replace('Z','+00:00'))
                if measured.tzinfo is None or (now-measured).total_seconds()>1800 or (now-measured).total_seconds() < -300:raise ValueError()
            except (ValueError,TypeError):row['message']='Ladestand nicht ausreichend aktuell.';continue
        row['estimated']=not bool(stamp)
        capacity=p.get('capacity')
        if not capacity:row['message']='Nutzbare Batteriekapazität unter Fahrzeug & Bedarfsannahmen ergänzen.';continue
        trips=[]
        for offset in range(8):
            day=local.date()+timedelta(days=offset)
            for t in plan.get('trips',[]):
                if t['vehicle']!=vid:continue
                if not trip_occurs(plan,t,day):continue
                start=datetime.combine(day,time.fromisoformat(t['departure']),local.tzinfo)
                if start>=local:trips.append((start,t))
        trips.sort(key=lambda x:x[0]);row['soc']=soc;row['capacity']=capacity
        if not trips:row['message']='Keine kommende Fahrt in den nächsten 7 Tagen.';continue
        energy=0;reserve=p['reserve'];available=max(0,(soc-reserve)*capacity/100)
        row['next_departure']=trips[0][0].isoformat();row['next_km']=trips[0][1]['km']
        for start,t in trips:
            energy+=estimate_trip(t,p,start,context,now)['kwh']
            if energy>available+0.001:
                required=reserve+energy/capacity*100
                # Target only the day's trips up to and including the first unmet trip;
                # earlier driving since this snapshot is accounted for in the cumulative total.
                row.update(deadline=start.isoformat(),missing_kwh=round(energy+(reserve-soc)*capacity/100,2),target_soc=min(100,math.ceil(required)),unreachable=required>100)
                row['message']='Ladung vor dieser Fahrt erforderlich.'
                break
        else:row['message']='Vorhandene Energie reicht rechnerisch für die erfassten Fahrten.'
        # Seven-day energy stock replaces repeated small daily top-ups only on exceptional nights.
        night=result['night']
        if night.get('qualified'):
            window_end=datetime.fromisoformat(night['end'])
            # Do not defer a more urgent trip until a cheap window, or propose charging away.
            if trips[0][0]>=window_end:
                stock=sum(estimate_trip(t,p,start,context,now)['kwh'] for start,t in trips if start<local+timedelta(days=7))
                target=min(100,math.ceil(reserve+stock/capacity*100))
                # Only a meaningful top-up (>=10 percentage points), not a few percent nightly.
                if target-soc>=10 and target>row.get('target_soc',0):
                    row['opportunity']={'target_soc':target,'kwh':round((target-soc)*capacity/100,2), 'start':night['start'],'end':night['end']}
                    row['message']='Günstige Nacht für mehrere Fahrtage nutzen.'
    candidates=[r for r in result['vehicles'] if r.get('deadline')]
    candidates.sort(key=lambda r:(r['deadline'],-r['missing_kwh']))
    if candidates:
        result['priority']=candidates[0]['id']
        if len(candidates)>1:
            result['warnings'].append('Beide Autos brauchen Ladung. Reihenfolge nach erster Unterdeckung; kein nächtlicher Wechsel eingeplant. Ladezeiten und Wechsel vor dem Schlafengehen müssen noch geprüft werden.')
    opportunities=[r for r in result['vehicles'] if r.get('opportunity')]
    if opportunities:
        window_end=datetime.fromisoformat(result['night']['end'])
        urgent=[r for r in candidates if datetime.fromisoformat(r['deadline'])<=window_end]
        if not urgent:
            # One connector: choose one car, never schedule a midnight swap.
            opportunities.sort(key=lambda r:(not r['connected'], -r['opportunity']['kwh']))
            result['priority']=opportunities[0]['id'];result['priority_kind']='stock'
    from car_rotation import coordinate
    result['rotation']=coordinate(plan,result['vehicles'],zone,now,context)
    if context and context.get('energy_settings'):
        from car_energy import optimise,pv_opportunity
        result['rotation']=optimise(plan,result['vehicles'],result['rotation'],zone,now,context)
        result['pv_opportunity']=pv_opportunity(result['vehicles'],context.get('pv_surplus',[]),context['energy_settings'],zone,now)
    if result['rotation']['status']=='planned':
        result['warnings']=[w for w in result['warnings'] if not w.startswith('Beide Autos brauchen Ladung.')]
        sessions=result['rotation']['sessions']
        result['priority']=sessions[0]['id'] if sessions else None
        if sessions:
            result['priority_kind']='rotation'
            chosen=next(r for r in result['vehicles'] if r['id']==result['priority'])
            chosen['rotation']=sessions[0]
        else:result.pop('priority_kind',None)
    elif result['rotation']['status']=='conflict':
        result['warnings'].append(result['rotation']['message'])
        result.pop('priority_kind',None)
    if any(r.get('estimated') for r in result['vehicles']):result['warnings'].append('Vorläufig anhand der zuletzt abgerufenen Ladestände; Tibber liefert nicht für alle Werte eine Messzeit.')
    return result
