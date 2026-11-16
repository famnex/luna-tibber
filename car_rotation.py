"""Seven-night energy allocation for one connector. No charger commands."""
import math
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
from car_context import estimate_trip


def coordinate(plan,vehicles,zone,now,context=None):
    local=now.astimezone(ZoneInfo(zone))
    if len(vehicles)!=2 or any('soc' not in r or not plan['profiles'].get(r['id'],{}).get('capacity') for r in vehicles):
        return {'status':'missing','sessions':[],'message':'Gemeinsame Planung benötigt aktuelle Ladestände und Kapazitäten beider Autos.'}
    start=local.replace(hour=22,minute=0,second=0,microsecond=0)
    if local.hour<6:start-=timedelta(days=1)
    windows=[(max(local,start+timedelta(days=i)),start+timedelta(days=i+1,hours=-16)) for i in range(7)]
    horizon=windows[-1][1]+timedelta(days=1)
    journeys=[[],[]];away=[[],[]];caps=[];floors=[];initial=[]
    for j,row in enumerate(vehicles):
        p=plan['profiles'][row['id']];caps.append(p['capacity']);floors.append(p['capacity']*p['reserve']/100);initial.append(p['capacity']*row['soc']/100)
        for day_offset in range(-1,9):
            day=local.date()+timedelta(days=day_offset)
            for t in plan.get('trips',[]):
                if t['vehicle']!=row['id'] or not (t['kind']=='weekly' and day.weekday() in t['days'] or t['kind']=='once' and t['date']==day.isoformat()):continue
                depart=datetime.combine(day,time.fromisoformat(t['departure']),local.tzinfo)
                home=datetime.combine(day,time.fromisoformat(t['return']),local.tzinfo)
                if home<=depart:home+=timedelta(days=1)
                away[j].append((depart,home))
                if local<=depart<horizon:journeys[j].append((depart,estimate_trip(t,p,depart,context,now)['kwh']))
    def demand(j,a,b):return sum(kwh for depart,kwh in journeys[j] if a<=depart<b)
    first=windows[0][1]
    prefix=[demand(j,local,first) for j in range(2)]
    energy=[initial[j]-prefix[j] for j in range(2)]
    failure={'status':'conflict','sessions':[],'message':'Im Nachtfenster 22–06 Uhr ist kein gemeinsamer Energieplan möglich. Zusätzlichen Ladetermin vor der Nacht oder unterwegs prüfen.'}
    if any(prefix[j]>0 and energy[j]<floors[j]-0.001 for j in range(2)):return failure
    daily=[[demand(j,b,windows[i+1][1] if i<6 else horizon) for j in range(2)] for i,(a,b) in enumerate(windows)]
    allowed=[[not any(x<b and y>a for x,y in away[j]) for j in range(2)] for a,b in windows]
    def depletion(j):
        remaining=initial[j]
        for departure,kwh in sorted(journeys[j]):
            remaining-=kwh
            if remaining<floors[j]-0.001:return departure.timestamp()
        return float('inf')
    deadlines=[depletion(j) for j in range(2)]
    best=None;best_score=None
    def search(i,e,schedule):
        nonlocal best,best_score
        if i==7:
            # Few sessions first; favor the connected car, then delay unnecessary top-ups.
            active=[(k,j) for k,j in enumerate(schedule) if j is not None]
            first_car=active[0][1] if active else None
            bargain=sum(1 for k,j in active if vehicles[j].get('opportunity') and windows[k][0]<=datetime.fromisoformat(vehicles[j]['opportunity']['start'])<windows[k][1])
            score=(len(active),-bargain,deadlines[first_car] if first_car is not None else float('inf'),0 if first_car is None or vehicles[first_car]['connected'] else 1,-sum(k for k,j in active),tuple(2 if j is None else j for j in schedule))
            if best_score is None or score<best_score:best_score=score;best=schedule[:]
            return
        if best_score and sum(j is not None for j in schedule)>best_score[0]:return
        for choice in (None,0,1):
            if choice is not None and (not allowed[i][choice] or caps[choice]-e[choice]<0.01):continue
            charged=e[:]
            if choice is not None:charged[choice]=caps[choice]
            after=[charged[j]-daily[i][j] for j in range(2)]
            if any(daily[i][j]>0 and after[j]<floors[j]-0.001 for j in range(2)):continue
            search(i+1,after,schedule+[choice])
    search(0,energy,[])
    if best is None:return failure
    # Convert feasibility's full charges to minimum targets covering the next own slot.
    sessions=[];e=energy[:]
    for i,choice in enumerate(best):
        if choice is not None:
            next_own=next((k for k in range(i+1,7) if best[k]==choice),7)
            need=floors[choice]+sum(daily[k][choice] for k in range(i,next_own))
            opportunity=vehicles[choice].get('opportunity')
            if opportunity and windows[i][0]<=datetime.fromisoformat(opportunity['start'])<windows[i][1]:need=max(need,opportunity['target_soc']*caps[choice]/100)
            target=min(caps[choice],max(e[choice],need))
            target_soc=min(100,math.ceil(target/caps[choice]*100))
            target=target_soc*caps[choice]/100
            if target>e[choice]+0.01:
                sessions.append({'id':vehicles[choice]['id'],'name':vehicles[choice]['name'],'start':windows[i][0].isoformat(),'end':windows[i][1].isoformat(),
                                 'current_soc':vehicles[choice]['soc'],'expected_start_soc':round(e[choice]/caps[choice]*100,1),
                                 'projected_before_kwh':round(max(0,initial[choice]-e[choice]),2),
                                 'target_soc':target_soc,'kwh':round(target-e[choice],2),'add_soc':round((target-e[choice])/caps[choice]*100,1),'covers_until':(windows[next_own][1] if next_own<7 else horizon).isoformat(),
                                 'other_next_night':i<6 and best[i+1] is not None and best[i+1]!=choice})
                e[choice]=target
        e=[e[j]-daily[i][j] for j in range(2)]
    return {'status':'planned','sessions':sessions,'message':'Gemeinsamer Energieplan: höchstens ein Auto pro Nacht. Ladeleistung und erreichbare Ladedauer noch nicht geprüft.'}
