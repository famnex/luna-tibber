"""Pure counterfactual dispatch comparisons. No device/network access or writes."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import hashlib,json,threading,time
import consumption
import joint
from price_cache import planning_end

def unavailable(message):
    return {'state':'unavailable','basis':'dispatch','message':message,'suggestions':[]}

def compare(data,c,prices,telemetry,mode,now=None,hold_until=None):
    now=now or datetime.now(timezone.utc)
    try:age=(now-datetime.fromisoformat(telemetry['time'])).total_seconds()
    except (KeyError,TypeError,ValueError):age=99999
    soc=telemetry.get('soc')
    if type(soc) not in (int,float) or not 0<=soc<=100 or not 0<=age<=90:
        return unavailable('Aktuellen Akkustand abwarten (höchstens 90 Sekunden alt).')
    if mode=='smart' and not c.get('smart_discharge_enabled') and not c.get('_orders'):
        return unavailable('Für diesen vollständigen Smart-Vergleich die Entladeoptimierung in den Einstellungen aktivieren.')
    rules=[r for r in c.get('_consumption_rules',[]) if r['id']!=data.get('id')]
    normalized=consumption.with_duration({**data,'repeat':'once'},c,now)
    rule=consumption.validate({**normalized,'kind':'consumption','repeat':'once'},c,now)
    a,b=consumption.stamp(rule['start']),consumption.stamp(rule['end'])
    if a<now:
        if now-a<=timedelta(minutes=2):b=now+(b-a);a=now
        else:return unavailable('Beginn aktualisieren; der Entwurf liegt in der Vergangenheit.')
    duration=b-a
    seed=consumption.price_tip(normalized,c,prices,now,rules)
    if seed['state'] not in ('good','better'):return {**seed,'basis':'dispatch'}
    end=planning_end(prices,now)
    if end is None or b>end:return unavailable('Zusammenhängende Preise für die Planung fehlen.')
    zone=ZoneInfo(c['timezone']);day=a.astimezone(zone).replace(hour=0,minute=0,second=0,microsecond=0)
    left=max(now,day.astimezone(timezone.utc))
    right=min(end,(day+timedelta(days=1)).astimezone(timezone.utc))
    holidays=[(consumption.stamp(r['start']),consumption.stamp(r['end'])) for r in rules if r['kind']=='holiday']
    def eligible(x):return x>=left and x+duration<=right and not any(h<x+duration and j>x for h,j in holidays)
    starts={a}
    starts.update(consumption.stamp(x['start']) for x in seed.get('suggestions',[]))
    # Bound CPU work on Pi 3: tariff choices plus three-hour anchors and the
    # strongest PV window. Only the evaluated alternatives are ranked.
    for hour in range(0,24,3):
        x=(day+timedelta(hours=hour)).astimezone(timezone.utc)
        if eligible(x):starts.add(x)
    if eligible(left):starts.add(left)
    from pv import rows_for
    solar=rows_for(c,now,end)
    edges={left,*[r['start'] for r in solar],*[r['end']-duration for r in solar]}
    def surplus(x):
        return sum(max(0,(min(x+duration,r['end'])-max(x,r['start'])).total_seconds())*max(0,r['kw']-c['base_load_w']/1000) for r in solar)
    pv_options=[x for x in edges if eligible(x)]
    if pv_options:starts.add(max(pv_options,key=lambda x:(surplus(x),-x.timestamp())))
    starts={x for x in starts if eligible(x)}
    if a not in starts:return unavailable('Das gesamte Zeitfenster muss im Vergleichstag und in den bekannten Preisen liegen.')
    config={**c,'_consumption_rules':rules,'_comparison':True}
    if mode!='smart':config['_orders_only']=True
    else:config.pop('_orders_only',None)
    max_power=telemetry.get('max_charge_power_w')
    def calculate(extra):
        return joint.plan({**config,'_consumption_rules':rules+extra},prices,now,soc,max_power,hold_until)
    baseline=calculate([])
    if baseline is None:return unavailable('Akkukapazität, Ladeleistung und Grundlast für die Planung prüfen.')
    capacity=c['battery_capacity_kwh'];floor=c.get('battery_floor_soc',0)
    def cost_after(plan,start):
        total=0
        for row in plan['trace']:
            l,r=consumption.stamp(row['start']),consumption.stamp(row['end'])
            if r>start:total+=row['cost_eur']*max(0,(r-max(start,l)).total_seconds())/(r-l).total_seconds()
        return total
    def soc_at(plan,at):
        for row in plan['trace']:
            l,r=consumption.stamp(row['start']),consumption.stamp(row['end'])
            if l<=at<=r:
                f=(at-l).total_seconds()/(r-l).total_seconds()
                return floor+100*(row['start_kwh']+(row['end_kwh']-row['start_kwh'])*f)/capacity
        return floor+100*plan['trace'][-1]['end_kwh']/capacity
    evaluated=[]
    for x in sorted(starts):
        y=x+duration;extra={**rule,'start':x.isoformat(),'end':y.isoformat()}
        plan=calculate([extra])
        if plan is None:return unavailable('Vergleichsplanung konnte nicht vollständig berechnet werden.')
        delta=plan['total_cost_eur']-baseline['total_cost_eur']
        held=sum(max(0,(min(y,consumption.stamp(w['end']))-max(x,consumption.stamp(w['start']))).total_seconds()) for w in plan['windows'] if w['action']=='hold')/60
        evaluated.append({'start':x.isoformat(),'end':y.isoformat(),'cost_eur':delta,
                          'later_extra_eur':cost_after(plan,y)-cost_after(baseline,y),
                          'end_soc':soc_at(plan,y),'horizon_soc':soc_at(plan,end),
                          'pv_direct_kwh':max(0,plan['solar']['direct_kwh']-baseline['solar']['direct_kwh']),
                          'hold_minutes':round(held),'automatic_hold':mode=='smart' and c.get('smart_discharge_enabled',False) and held>0})
    current=next(r for r in evaluated if consumption.stamp(r['start'])==a)
    best=min(evaluated,key=lambda r:(r['cost_eur'],r['start']))
    first=min(evaluated,key=lambda r:r['start'])
    selected={first['start']:(first,'now' if consumption.stamp(first['start'])==now else 'earliest'),
              best['start']:(best,'best')}
    if first['start']==best['start']:selected[first['start']]=(first,'now' if consumption.stamp(first['start'])==now else 'earliest')
    spacing=timedelta(hours=1)
    def alternative(lo,hi,role):
        pool=[r for r in evaluated if lo<=consumption.stamp(r['start'])<=hi and all(abs(consumption.stamp(r['start'])-consumption.stamp(k))>=spacing for k in selected)]
        if pool:
            middle=lo+(hi-lo)/2
            choice=min(pool,key=lambda r:(abs(consumption.stamp(r['start'])-middle),r['cost_eur']))
            selected[choice['start']]=(choice,role)
    first_at,best_at,last=consumption.stamp(first['start']),consumption.stamp(best['start']),max(consumption.stamp(r['start']) for r in evaluated)
    if best_at-first_at>=2*spacing:alternative(first_at+spacing,best_at-spacing,'between')
    alternative(best_at+spacing,last,'later')
    if len(selected)<4:alternative(first_at+spacing,last,'later')
    suggestions=[]
    for row,role in sorted(selected.values(),key=lambda pair:pair[0]['start']):
        suggestions.append({**row,'role':role,'cheapest':abs(row['cost_eur']-best['cost_eur'])<1e-7,
                            'saving_eur':current['cost_eur']-row['cost_eur'],'extra_eur':row['cost_eur']-best['cost_eur']})
    message=('Mehrkosten gegenüber demselben Plan ohne diesen Verbrauch · '+str(len(evaluated))+' Startzeiten geprüft. '
             +'PV, Akku, Verluste, Verschleiß und späterer Netzbezug berücksichtigt. '
             +('Smart plant Entladepausen mit. ' if mode=='smart' and c.get('smart_discharge_enabled') else 'Keine zusätzlichen automatischen Entladesperren. ')
             +('PV-Prognose fehlt: ohne PV gerechnet. ' if c.get('pv_enabled') and not baseline['pv_available'] else '')
             +'Nur bekannte Preisstunden; ohne Einspeisevergütung. Restenergie nach dem Horizont nicht bewertet.')
    return {'state':'better' if current['cost_eur']-best['cost_eur']>=.01 else 'good','basis':'dispatch',
            'current_eur':current['cost_eur'],'suggestions':suggestions,'message':message,'horizon_end':end.isoformat(),
            'evaluated':len(evaluated),'soc':soc,'pv_available':baseline['pv_available']}

class AdviceCache:
    """One bounded calculation at a time; small minute/config/SOC keyed cache."""
    def __init__(self):self.lock=threading.Lock();self.rows={}
    def get(self,data,c,prices,telemetry,mode,now,hold_until=None):
        safe={k:v for k,v in c.items() if k not in ('password','tibber_token')}
        signature=json.dumps([data,safe,prices,telemetry.get('soc'),telemetry.get('max_charge_power_w'),mode,int(now.timestamp()/60),hold_until],sort_keys=True,default=str)
        key=hashlib.sha256(signature.encode()).hexdigest()
        if not self.lock.acquire(timeout=.05):return unavailable('Vergleich wird bereits berechnet. Bitte kurz warten.')
        try:
            try:fresh=0<=(now-datetime.fromisoformat(telemetry['time'])).total_seconds()<=90
            except (KeyError,TypeError,ValueError):fresh=False
            cached=self.rows.get(key) if fresh else None
            if cached and time.monotonic()-cached[0]<60:return cached[1]
            result=compare(data,c,prices,telemetry,mode,now,hold_until)
            if result.get('state') not in ('unavailable','missing'):
                self.rows[key]=(time.monotonic(),result)
                while len(self.rows)>8:self.rows.pop(next(iter(self.rows)))
            return result
        finally:self.lock.release()
