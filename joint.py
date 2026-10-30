"""Chronological PV/battery dispatch; pure computation, no device requests.

Piecewise-linear dynamic programming (81 SOC knots). Energy transitions remain
continuous: interpolation never rounds away household demand or creates energy.
Only self-consumption is discharged; grid charging can use any known economically suitable price interval.
"""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
from price_cache import planning_end


def plan(c, prices, now, soc, max_power_w=None, hold_until=None):
    if not c.get('smart_discharge_enabled') and not c.get('_orders') and not c.get('_orders_projected') and not c.get('_comparison'):
        return None
    if type(soc) not in (int,float) or not math.isfinite(soc) or not 0<=soc<=100:
        return None
    capacity=c['battery_capacity_kwh'];power=min(c['charge_power_w'],max_power_w or c['charge_power_w'])/1000
    if capacity<=0 or power<.2 or c['base_load_w']<=0:return None
    orders=c.get('_orders',[])
    if orders and not c.get('_orders_projected') and any(o['kind']=='charge' for o in orders):
        from manual import stamp
        baseline=plan({**c,'_orders':[o for o in orders if o['kind']=='hold'],'_orders_projected':True},prices,now,soc,max_power_w,hold_until)
        if baseline is None:return None
        result=baseline
        for _ in range(3):
            projected=[]
            for order in orders:
                if order['kind']!='charge':projected.append(order);continue
                start=max(now,stamp(order['start']));end=stamp(order['end'])
                trace=next((t for t in result['trace'] if datetime.fromisoformat(t['start'])<=start<datetime.fromisoformat(t['end'])),None)
                if not trace or end<=start:projected.append(order);continue
                energy=trace['start_kwh'];target=capacity*max(0,order['target_soc']-c.get('battery_floor_soc',0))/100
                # Forecast completion is revised from SOC on every controller cycle.
                rate=max(.05,power-c.get('battery_idle_w',0)/1000)
                seconds=max(0,target-energy)/rate*3600
                if seconds<=0:continue
                projected.append({**order,'start':start.isoformat(),'end':min(end,start+timedelta(seconds=seconds)).isoformat()})
            result=plan({**c,'_orders':projected,'_orders_projected':True},prices,now,soc,max_power_w,hold_until)
        result['manual_orders']=projected
        return result
    from dispatch import night_bounds,demand_rows
    from pv import rows_for
    from protection import reserve
    night_a,night_b=night_bounds(c,now)
    end=planning_end(prices,now)
    if end is None:return None
    night_complete=night_b<end
    bridge_start=night_b if night_complete else now
    solar_available=bool(rows_for(c,now,end))
    if not solar_available:
        # Unknown sunlight is never credited. Retain load/price-based protection.
        c={**c,'_pv':{'rows':[{'start':now,'end':end,'kw':0}]}}

    # Split at midnight as extra household demand repeats on each local date.
    rows=[];cursor=now;zone=ZoneInfo(c['timezone'])
    while cursor<end:
        local=cursor.astimezone(zone)
        midnight=(local.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).astimezone(timezone.utc)
        right=min(end,midnight)
        rows.extend(demand_rows(c,prices,cursor,right));cursor=right
    # Also split at charging/hold boundaries, even for hourly tariff data.
    from manual import stamp, active as active_order
    boundaries=[stamp(o[k]) for o in orders for k in ('start','end') if o.get(k)]
    split=[]
    for r in rows:
        edges=sorted({r['start'],r['end'],*[t for t in (night_a,night_b,hold_until,*boundaries) if t and r['start']<t<r['end']]})
        for a,b in zip(edges,edges[1:]):split.append({**r,'start':a,'end':b})
    rows=split;eta=math.sqrt(c['roundtrip_efficiency'])
    floor=c.get('battery_floor_soc',0)
    limit=capacity*max(0,c['target_soc']-floor)/100
    initial=capacity*max(0,soc-floor)/100
    ceiling=max(limit,initial,*[capacity*max(0,o['target_soc']-floor)/100 for o in orders if o['kind']=='charge']) # An existing SOC above the configured target is usable.
    specs=[];grid_powers=[]
    for index,r in enumerate(rows):
        seconds=(r['end']-r['start']).total_seconds();hours=seconds/3600
        load=r['load_kw']*hours
        solar_power=min(max(0,r['pv_kw']-r['gross_load_kw'])*eta,power)
        solar=solar_power*hours
        grid_power=max(0,power-solar_power)
        grid_powers.append(grid_power)
        solar-=c.get('battery_idle_w',0)/1000*hours
        following=rows[index+1] if index+1<len(rows) else None
        continues=bool(following and following['start']==r['end'] and following['ct']<=c['max_buy_ct_kwh'])
        margin_seconds=0 if continues else 130
        can_charge=r['ct']<=c['max_buy_ct_kwh'] and seconds>=margin_seconds+60
        charge=grid_power*max(0,seconds-margin_seconds)/3600 if can_charge else 0
        manual_charge=active_order(orders,r['start'],'charge')
        manual_hold=active_order(orders,r['start'],'hold')
        forced=capacity*max(0,manual_charge['target_soc']-floor)/100 if manual_charge else None
        if manual_charge:charge=grid_power*hours
        specs.append((load,solar,r['ct'],charge,bool(manual_hold or (hold_until and r['start']<hold_until)),grid_power/60,0.,forced,bool(c.get('_orders_only')),not c.get('smart_discharge_enabled')))
    # Morning energy is a time-specific minimum, released for consumption after
    # night-end. Stop bridging only once PV covers the configured household load.
    morning_rows=[(r,s) for r,s in zip(rows,specs) if r['start']>=bridge_start]
    bridge_ac=0.;bridge_idle=0.;pv_start=None
    for r,s in morning_rows:
        if r['pv_kw']>=r['gross_load_kw']+c.get('battery_idle_w',0)/1000/eta and r['pv_kw']>0:
            pv_start=r['start'];break
        if not s[4]:bridge_ac+=s[0]
        bridge_idle+=max(0,-s[1])
    buffer=bridge_ac*c.get('morning_buffer_pct',10)/100 # Time-specific allowance, not a permanent SOC floor.
    required=(bridge_ac+buffer)/eta+bridge_idle
    minimum=min(limit,required)
    checkpoint=next((i for i,r in enumerate(rows) if r['start']==night_b),None)
    if checkpoint is not None:specs[checkpoint]=(*specs[checkpoint][:6],minimum,*specs[checkpoint][7:])
    wear=c['wear_ct_kwh'];margin=c['min_saving_ct_kwh']
    knots=21 if c.get('_comparison_fast') and c.get('_comparison') else 81
    values=_values(tuple(specs),ceiling,limit,eta,wear,margin,knots=knots)
    # Protection uses the continuous value curve. Whole-interval dispatch adds
    # small non-convex steps which must not weaken the independent live guard.
    guard_values=_values(tuple(specs),ceiling,limit,eta,wear,margin,True,knots=knots)
    guard=reserve(guard_values[1],ceiling,specs[0][2],eta,wear,capacity,initial,c.get('_guard_held',False))
    guard['threshold_soc']=floor+guard['trigger_kwh']/capacity*100
    guard['release_soc']=floor+guard['release_kwh']/capacity*100
    if c.get('_orders_only') or not c.get('smart_discharge_enabled'):guard.update(hold=False,required_kwh=0)
    if guard['hold']:
        first=specs[0];specs[0]=(*first[:4],True,*first[5:])
    energy=initial;windows=[];charges=[];trace=[];actual_cost=0
    at_night=initial;at_morning=initial
    for i,(r,spec) in enumerate(zip(rows,specs)):
        if r['start']<=night_a:at_night=energy
        if r['start']<=night_b:at_morning=energy
        _,after,charge,used=_choose(energy,spec,values[i+1],ceiling,limit,eta,wear,margin)
        trace.append({'start':r['start'].isoformat(),'end':r['end'].isoformat(),'start_kwh':energy,'end_kwh':after,'grid_charge_kwh':charge,'discharge_kwh':used,'idle_kwh':c.get('battery_idle_w',0)/1000*(r['end']-r['start']).total_seconds()/3600})
        if c.get('_comparison'):
            trace[-1].update(grid_house_kwh=spec[0]-used,grid_charge_input_kwh=charge/eta,
                             cost_eur=((spec[0]-used)*spec[2]+charge/eta*spec[2]+used*wear)/100)
        actual_cost+=(spec[0]-used)*spec[2]+charge/eta*spec[2]+used*wear
        a,b=r['start'],r['end']
        if charge>1e-7:
            stop=a+timedelta(seconds=charge/grid_powers[i]*3600+130)
            charges.append({'manual':spec[7] is not None,'start':a.isoformat(),'end':stop.isoformat(),'ct':r['ct'],'battery_kwh':charge,'grid_power_w':grid_powers[i]*1000})
            windows.append({'start':a.isoformat(),'end':b.isoformat(),'action':'hold','allocated_kwh':0,'ct':r['ct']})
        elif used>1e-7:
            # Permission lasts for the row, even if the battery reaches its
            # device floor earlier. Allocated energy still reflects availability.
            windows.append({'start':a.isoformat(),'end':b.isoformat(),'action':'discharge','allocated_kwh':used,'ct':r['ct']})
        else:
            # With no stored energy or no residual demand there is nothing to reserve.
            action='hold' if spec[4] or (energy>1e-7 and spec[0]>0) else 'discharge'
            windows.append({'start':a.isoformat(),'end':b.isoformat(),'action':action,'allocated_kwh':0,'ct':r['ct']})
        energy=after
    total=sum(w['battery_kwh'] for w in charges)
    economics=None
    if total>0 and not c.get('_comparison') and not any(o['kind']=='charge' for o in orders):
        baseline=tuple((*s[:3],0,*s[4:]) for s in specs)
        base_values=_values(baseline,ceiling,limit,eta,wear,margin)
        base_cost=0;available=initial
        for i,spec in enumerate(baseline):
            _,available,_,used=_choose(available,spec,base_values[i+1],ceiling,limit,eta,wear,margin)
            base_cost+=(spec[0]-used)*spec[2]+used*wear
        useful=total*eta
        effective=sum(w['battery_kwh']/eta*w['ct'] for w in charges)/useful+wear
        saving=(base_cost-actual_cost)/useful
        economics=dict(ok=saving>0,reason='Gemeinsamer Plan gegenüber gleicher Planung ohne Netzladung',
                       effective_ct_kwh=effective,reference_ct_kwh=effective+saving,saving_ct_kwh=saving,
                       window_start=now.isoformat(),window_end=end.isoformat())
    bridge=dict(idle_kwh=bridge_idle,demand_kwh=bridge_ac,buffer_kwh=buffer,required_kwh=required,
                required_soc=floor+required/capacity*100,available_kwh=at_morning if night_complete else initial,
                shortfall_kwh=max(0,required-(at_morning if night_complete else initial)),
                pv_start=pv_start.isoformat() if pv_start else None,
                night_end=bridge_start.isoformat(),floor_soc=floor)
    phases=[]
    for w in windows:
        a=datetime.fromisoformat(w['start']);b=datetime.fromisoformat(w['end'])
        charge=next((x for x in charges if x['start']==w['start']),None)
        reason='manual' if active_order(orders,a) or (hold_until and a<hold_until) else 'reserve' if guard['hold'] and a==now else 'price'
        parts=[dict(start=w['start'],end=w['end'],action=w['action'],reason=reason,
                    kwh=w['allocated_kwh'],low_ct=w['ct'],high_ct=w['ct'])]
        if charge:
            # The charge window carries 130 s of command headroom, not energy.
            # Match the chart and controller's effective charge duration.
            stop=(datetime.fromisoformat(charge['end'])-timedelta(seconds=130)).isoformat()
            parts=[{**parts[0],'action':'charge','end':stop,'kwh':charge['battery_kwh']},
                   {**parts[0],'start':stop,'reason':'charge_complete'}]
        for item in parts:
            if datetime.fromisoformat(item['end'])<=datetime.fromisoformat(item['start']):continue
            reason=item['reason']
            if phases and phases[-1]['action']==item['action'] and phases[-1]['reason']==reason and phases[-1]['end']==item['start']:
                old=phases[-1];old['end']=item['end'];old['kwh']+=item['kwh'];old['low_ct']=min(old['low_ct'],item['low_ct']);old['high_ct']=max(old['high_ct'],item['high_ct'])
            else:phases.append(item)
    solar_summary=dict(generation_kwh=sum(r['pv_kw']*(r['end']-r['start']).total_seconds()/3600 for r in rows),direct_kwh=sum(min(r['pv_kw'],r['gross_load_kw'])*(r['end']-r['start']).total_seconds()/3600 for r in rows))
    return dict(total_cost_eur=actual_cost/100,rolling=True,plan_start=now.isoformat(),idle_w=c.get('battery_idle_w',0),idle_kwh=c.get('battery_idle_w',0)/1000*(end-now).total_seconds()/3600,night_complete=night_complete,plan_end=end.isoformat(),pv_available=solar_available,guard=guard,solar=solar_summary,phases=phases,bridge=bridge,economics=economics,charges=charges,windows=windows,trace=trace,planned_kwh=total,
                planning_soc=floor+at_night/capacity*100,morning_soc=(floor+at_morning/capacity*100) if night_complete else None,
                power_w=power*1000,night_start=max(now,night_a).isoformat(),night_end=night_b.isoformat(),
                reason='Fortlaufender Energieplan · alle bekannten Preisstunden, Verbrauch und PV')


def _interpolate(values,energy,ceiling):
    if ceiling<=0:return values[0]
    x=max(0,min(len(values)-1,energy/ceiling*(len(values)-1)))
    i=min(len(values)-2,int(x));f=x-i
    return values[i]*(1-f)+values[i+1]*f


def _choose(energy,spec,next_values,ceiling,limit,eta,wear,margin,partial_discharge=False):
    load,solar,price,max_charge,blocked,min_charge,required=spec[:7]
    forced=spec[7] if len(spec)>7 else None
    if forced is not None:
        raw=min(ceiling,energy+solar);stored=max(0,raw)
        charge=max(0,min(max_charge,forced-raw))
        after=min(ceiling,max(0,raw+charge))
        return (load*price+charge/eta*price+_interpolate(next_values,after,ceiling)+max(0,required-energy)*1_000_000,after,charge,0.)
    raw=min(ceiling,energy+solar)
    stored=max(0,raw)
    if len(spec)>8 and spec[8]:
        used=0 if blocked else min(load,stored*eta)
        after=stored-used/eta
        return (load-used)*price+_interpolate(next_values,after,ceiling),after,0.,used
    # Holding avoids needless cycling on equal costs. PV first supplies the house.
    best=(load*price+_interpolate(next_values,stored,ceiling),stored,0.,0.)
    if len(spec)>9 and spec[9] and not blocked:
        used=min(load,stored*eta);after=stored-used/eta
        best=((load-used)*price+used*wear+_interpolate(next_values,after,ceiling),after,0.,used)
    step=ceiling/(len(next_values)-1) if ceiling else 1
    if not blocked and load>0:
        # Choose a full load interval or hold, never a partial discharge to an
        # interpolation knot. Those artificial targets caused 2–3 minute pauses
        # within unchanged-price slots. Live protection may still stop earlier.
        minimum=max(0,stored-load/eta)
        targets=[minimum]
        if partial_discharge:
            targets += [j*step for j in range(math.ceil(minimum/step),math.ceil(stored/step))]
        for after in targets:
            used=(stored-after)*eta
            cost=(load-used)*price+used*wear+_interpolate(next_values,after,ceiling)
            if cost<best[0]-1e-8:best=(cost,after,0.,used)
    maximum=min(limit,raw+max_charge)
    if max_charge>0 and maximum>stored:
        targets=[maximum]+[j*step for j in range(math.floor(stored/step)+1,math.ceil(maximum/step))]
        for after in targets:
            charge=after-raw
            if charge<min_charge-1e-9:continue
            cost=load*price+charge/eta*price+charge*eta*margin+_interpolate(next_values,after,ceiling)
            if cost<best[0]-1e-8:best=(cost,after,charge,0.)
    return (best[0]+max(0,required-energy)*1_000_000,*best[1:])


@lru_cache(maxsize=4)
def _values(specs,ceiling,limit,eta,wear,margin,partial_discharge=False,knots=81):
    # About 81*81*200 simple operations, no scipy/numpy on the Raspberry Pi.
    values=[[0.]*knots for _ in range(len(specs)+1)]
    for i in range(len(specs)-1,-1,-1):
        values[i]=[_choose(ceiling*j/(knots-1),specs[i],values[i+1],ceiling,limit,eta,wear,margin,partial_discharge)[0] for j in range(knots)]
    return values
