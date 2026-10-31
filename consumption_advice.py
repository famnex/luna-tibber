"""Pure counterfactual dispatch comparisons. No device/network access or writes."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import hashlib,json,threading,time
import consumption
import joint
from price_cache import planning_end

def unavailable(message):
    return {'state':'unavailable','basis':'dispatch','message':message,'suggestions':[]}

def hourly_prices(prices, now):
    """Time-weighted hourly estimates, never bridge missing price intervals."""
    end=planning_end(prices,now)
    if end is None:return prices
    result=[];a=now
    while a<end:
        b=min(end,a.replace(minute=0,second=0,microsecond=0)+timedelta(hours=1))
        cost=seconds=0.
        for row in prices:
            overlap=max(0,(min(b,row['end'])-max(a,row['start'])).total_seconds())
            cost+=overlap*row['ct'];seconds+=overlap
        if abs(seconds-(b-a).total_seconds())>.01:return prices
        result.append({'start':a,'end':b,'ct':cost/seconds});a=b
    return result

def compare(data,c,prices,telemetry,mode,now=None,hold_until=None):
    now=now or datetime.now(timezone.utc)
    hourly=c.get('_comparison_hourly',False)
    if hourly:
        prices=hourly_prices(prices,now)
        from pv import rows_for,power
        end=planning_end(prices,now)
        solar=rows_for(c,now,end) if end else []
        if solar:
            c={**c,'_pv':{**c.get('_pv',{}),'rows':[{'start':r['start'],'end':r['end'],'kw':power(solar,r['start'],r['end'])} for r in prices]}}
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
    starts={a,*[consumption.stamp(x) for x in c.get('_comparison_starts',[])]}
    fast=c.get('_comparison_fast',False)
    starts.update(consumption.stamp(x['start']) for x in seed.get('suggestions',[]))
    # Bound CPU work on Pi 3: tariff choices plus three-hour anchors and the
    # strongest PV window. Only the evaluated alternatives are ranked.
    for hour in (range(24) if hourly else [] if fast else range(0,24,3)):
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
    def usage(plan,x,y):
        # Sources cannot be assigned to an individual appliance physically.
        # Allocate the household mix proportionally to the extra load in each row.
        sources={'pv':0.,'battery':0.,'grid':0.};direct=0.
        extra_kw=rule['kwh']/((y-x).total_seconds()/3600)
        for row in plan['trace']:
            l,r=consumption.stamp(row['start']),consumption.stamp(row['end'])
            seconds=max(0,(min(y,r)-max(x,l)).total_seconds())
            if not seconds:continue
            fraction=seconds/(r-l).total_seconds()
            extra=extra_kw*seconds/3600
            gross=row['gross_load_kwh']*fraction
            share=min(1,extra/gross) if gross>0 else 0
            pv=row['pv_house_kwh']*fraction*share
            battery=row['discharge_kwh']*fraction*share
            grid=max(0,extra-pv-battery)
            sources['pv']+=pv;sources['battery']+=battery;sources['grid']+=grid
            direct+=(grid*row['price_ct']+battery*c['wear_ct_kwh'])/100
        return sources,direct
    evaluated=[]
    for x in sorted(starts):
        y=x+duration;extra={**rule,'start':x.isoformat(),'end':y.isoformat()}
        plan=calculate([extra])
        if plan is None:return unavailable('Vergleichsplanung konnte nicht vollständig berechnet werden.')
        delta=plan['total_cost_eur']-baseline['total_cost_eur']
        held=sum(max(0,(min(y,consumption.stamp(w['end']))-max(x,consumption.stamp(w['start']))).total_seconds()) for w in plan['windows'] if w['action']=='hold')/60
        sources,direct=usage(plan,x,y)
        later=cost_after(plan,y)-cost_after(baseline,y)
        holds=[{'start':max(x,consumption.stamp(w['start'])).isoformat(),'end':min(y,consumption.stamp(w['end'])).isoformat()} for w in plan['windows'] if w['action']=='hold' and consumption.stamp(w['start'])<y and consumption.stamp(w['end'])>x]
        merged=[]
        for window in holds:
            if merged and merged[-1]['end']==window['start']:merged[-1]['end']=window['end']
            else:merged.append(dict(window))
        holds=merged
        evaluated.append({'usage_cost_eur':direct,'plan_adjustment_eur':delta-direct-later,'sources_kwh':sources,'hold_windows':holds,'start':x.isoformat(),'end':y.isoformat(),'cost_eur':delta,
                          'later_extra_eur':later,
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
             +('Stundenschätzung: gemittelte Stundenpreise, stündliche PV und grobes Akku-Rechenraster. ' if hourly else 'Schnellschätzung mit gröberem Akku-Rechenraster. ' if fast else '')
             +'PV, Akku, Verluste, Verschleiß und späterer Netzbezug berücksichtigt. '
             +('Smart plant Entladepausen mit. ' if mode=='smart' and c.get('smart_discharge_enabled') else 'Keine zusätzlichen automatischen Entladesperren. ')
             +('PV-Prognose fehlt: ohne PV gerechnet. ' if c.get('pv_enabled') and not baseline['pv_available'] else '')
             +'Quellen anteilig aus dem Hausverbrauch geschätzt. Nutzung: Netzstrom plus Akkuverschleiß; frühere Anschaffungskosten der Akkuladung nicht enthalten. Plananpassung: übrige Kostenänderungen vor und während der Nutzung. Sperren sind Planvorschauen, keine neuen manuellen Befehle. '
             +'Nur bekannte Preisstunden; ohne Einspeisevergütung. Restenergie nach dem Horizont nicht bewertet.')
    return {'state':'better' if current['cost_eur']-best['cost_eur']>=.01 else 'good','basis':'dispatch',
            'calculated_at':now.isoformat(),'current_eur':current['cost_eur'],'suggestions':suggestions,'message':message,'horizon_end':end.isoformat(),
            'estimate':hourly,'evaluated':len(evaluated),'soc':soc,'pv_available':baseline['pv_available']}

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


def _comparison_worker(connection, args):
    """Separate low-priority CPU process; cannot block the HTTP interpreter."""
    try:
        import os
        if hasattr(os, 'nice'): os.nice(10)
        data,c,prices,telemetry,mode,now,hold_until=args
        estimate=compare(data,{**c,'_comparison_hourly':True},prices,telemetry,mode,now,hold_until)
        connection.send(('estimate',estimate))
        refined={**c,'_comparison_starts':[r['start'] for r in estimate.get('suggestions',[])]}
        connection.send(('final',compare(data,refined,prices,telemetry,mode,now,hold_until)))
    except Exception as exc:
        connection.send(('final',unavailable('Vergleich fehlgeschlagen: '+str(exc))))
    finally:
        connection.close()


class BackgroundAdvice:
    """One isolated job, explicit polling, hard deadline even after browser closes."""
    def __init__(self, timeout=8):
        self.lock=threading.Lock();self.job=None;self.timeout=timeout

    def poll(self, token):
        with self.lock:
            job=self.job
            if not job or token!=job['token']:
                return unavailable('Vergleich abgelaufen. Bitte erneut berechnen.')
            if job['result'] is not None:return job['result']
            return {**(job.get('estimate') or {}),'state':'pending','job':token,'suggestions':(job.get('estimate') or {}).get('suggestions',[]),
                    'message':(job.get('estimate') or {}).get('message','PV, Akku und Folgekosten werden verglichen …'),
                    'elapsed_seconds':int(time.monotonic()-job['started'])}

    def get(self,data,c,prices,telemetry,mode,now,hold_until=None):
        import multiprocessing,uuid
        with self.lock:
            if self.job and self.job['result'] is None:
                return {'state':'busy','suggestions':[], 'message':'Vorheriger Vergleich wird abgeschlossen …'}
            # Immediate, explicitly tariff-only fallback, replaced as soon as the
            # hourly battery/PV estimate arrives. Never invent a missing price.
            fallback=consumption.price_tip(data,c,prices,now,[r for r in c.get('_consumption_rules',[]) if r.get('id')!=data.get('id')])
            if fallback.get('suggestions'):
                fallback={**fallback,'calculated_at':now.isoformat(),'estimate':True,'basis':'tariff','message':'Vorläufig nur Stromtarif · PV, Akku und Folgekosten noch nicht berücksichtigt.'}
            job={'token':uuid.uuid4().hex,'started':time.monotonic(),'result':None,'estimate':fallback}
            self.job=job
            context=multiprocessing.get_context('spawn')
            receive,send=context.Pipe(duplex=False)
            process=context.Process(target=_comparison_worker,args=(send,(data,{**c,'_comparison_fast':True},prices,telemetry,mode,now,hold_until)),daemon=True)
            try:process.start()
            except Exception:
                receive.close();send.close();self.job=None
                return unavailable('Vergleich konnte nicht gestartet werden. Bitte erneut versuchen.')
            send.close()
            def finish():
                result=None;deadline=time.monotonic()+self.timeout
                try:
                    while time.monotonic()<deadline and receive.poll(max(0,deadline-time.monotonic())):
                        kind,value=receive.recv()
                        if kind=='estimate':
                            if value.get('suggestions'):
                                with self.lock:job['estimate']=value
                        else:
                            result=value;break
                except (EOFError,OSError):pass
                finally:
                    with self.lock:
                        if result is None or not result.get('suggestions'):
                            if job['estimate'].get('suggestions'):
                                result={**job['estimate'],'message':job['estimate']['message']+' Genauere Berechnung nicht verfügbar; Schätzung bleibt nutzbar.'}
                        job['result']=result or unavailable('Für diesen Zeitraum fehlen vergleichbare Daten.')
                    if process.is_alive():process.terminate()
                    process.join(timeout=2);receive.close()
            threading.Thread(target=finish,daemon=True).start()
        return self.poll(job['token'])
