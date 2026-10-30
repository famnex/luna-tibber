"""Additional household demand, wall-clock recurrence and holiday exclusions."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import math
import uuid
from manual import stamp,local_time


def validate(data,c,now):
    kind=data['kind'];repeat=data.get('repeat','once')
    if kind=='holiday':repeat='once'
    if repeat not in ('once','daily','weekly'):raise ValueError('Wiederholung: einmalig, täglich oder wöchentlich')
    start=local_time(data['start'],c['timezone']);end=local_time(data['end'],c['timezone'])
    if end<=start or (repeat=='once' and end<=now):raise ValueError('Ende muss nach Start und in der Zukunft liegen')
    if repeat!='once' and end-start>timedelta(hours=25):raise ValueError('Wiederholtes Verbrauchsfenster höchstens einen Tag lang')
    zone=ZoneInfo(c['timezone'])
    if repeat!='once' and end.astimezone(zone).replace(tzinfo=None)-start.astimezone(zone).replace(tzinfo=None)>timedelta(days=1):raise ValueError('Wiederholtes Verbrauchsfenster höchstens einen Tag lang')
    days=data.get('weekdays',[])
    if repeat=='weekly' and (not isinstance(days,list) or not days or any(type(d) is not int or not 0<=d<=6 for d in days)):
        raise ValueError('Mindestens einen gültigen Wochentag auswählen')
    kwh=data.get('kwh',0)
    if kind=='consumption' and (type(kwh) not in (int,float) or not math.isfinite(kwh) or not 0<kwh<=200):raise ValueError('Zusatzverbrauch: mehr als 0 und höchstens 200 kWh')
    if not isinstance(data.get('name',''),str):raise ValueError('Bezeichnung muss Text sein')
    name=data.get('name','').strip()
    if len(name)>80:raise ValueError('Bezeichnung höchstens 80 Zeichen')
    return {'id':data.get('id') or uuid.uuid4().hex,'token':uuid.uuid4().hex,'kind':kind,'name':name or ('Zusatzverbrauch' if kind=='consumption' else 'Urlaub'),
            'start':start.isoformat(),'end':end.isoformat(),'end_kind':'time','target_soc':None,'repeat':repeat,
            'weekdays':sorted(set(days)) if repeat=='weekly' else [],'kwh':float(kwh) if kind=='consumption' else 0,'timezone':c['timezone']}


def expand(rule,start,end):
    a,b=stamp(rule['start']),stamp(rule['end'])
    if rule.get('repeat','once')=='once':
        return [{**rule,'start':a.isoformat(),'end':b.isoformat()}] if a<end and b>start else []
    zone=ZoneInfo(rule['timezone']);local_a=a.astimezone(zone);local_b=b.astimezone(zone)
    day=max(local_a.date(),start.astimezone(zone).date()-timedelta(days=1));last=end.astimezone(zone).date()
    offset=(local_b.date()-local_a.date()).days
    result=[]
    while day<=last:
        if rule['repeat']=='daily' or day.weekday() in rule['weekdays']:
            left=datetime.combine(day,local_a.time().replace(tzinfo=None),zone)
            right=datetime.combine(day+timedelta(days=offset),local_b.time().replace(tzinfo=None),zone)
            # Use the first occurrence of an ambiguous clock time. Skip nonexistent clocks.
            valid=all(x.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)==x.replace(tzinfo=None) for x in (left,right))
            x,y=left.astimezone(timezone.utc),right.astimezone(timezone.utc)
            if valid and y>x and x>=a and x<end and y>start:result.append({**rule,'start':x.isoformat(),'end':y.isoformat()})
        day+=timedelta(days=1)
    return result


def intervals(rules,start,end):
    holidays=[(stamp(r['start']),stamp(r['end'])) for r in rules if r['kind']=='holiday']
    out=[]
    for rule in rules:
        if rule['kind']!='consumption':continue
        for item in expand(rule,start,end):
            a,b=stamp(item['start']),stamp(item['end']);kw=item['kwh']/((b-a).total_seconds()/3600)
            pieces=[(max(a,start),min(b,end))]
            for h,j in holidays:
                parts=[]
                for x,y in pieces:
                    if h>=y or j<=x:parts.append((x,y));continue
                    if x<h:parts.append((x,h))
                    if j<y:parts.append((j,y))
                pieces=parts
            out.extend({'start':x,'end':y,'kw':kw,'id':rule['id'],'name':rule.get('name','Zusatzverbrauch')} for x,y in pieces if y>x)
    return out


def upcoming(rows,now):
    holidays=[(stamp(r['start']),stamp(r['end'])) for r in rows if r['kind']=='holiday']
    out=[]
    for row in rows:
        if row['kind']!='consumption':out.append(row);continue
        items=expand(row,now,now+timedelta(days=15))[:1] if row.get('repeat','once')!='once' else [row]
        for item in items:
            a,b=stamp(item['start']),stamp(item['end'])
            excluded=any(h<b and j>a for h,j in holidays)
            out.append({**item,'holiday_overlap':excluded,'recurring':row.get('repeat','once')!='once'})
    return sorted(out,key=lambda r:r['start'])


def migrate(folder,c,now=None):
    """Persist the old evening routine before retiring its config value; restart-safe."""
    import json
    from luna import write_json
    now=now or datetime.now(timezone.utc);path=folder/'manual-orders.json'
    data=json.loads(path.read_text()) if path.exists() else {'serial':c['expected_serial'],'rows':[]}
    if not data.get('consumption_migrated'):
        if c.get('extra_load_kwh',0)>0:
            local=now.astimezone(ZoneInfo(c['timezone']));midnight=local.replace(hour=0,minute=0,second=0,microsecond=0)
            a=midnight+timedelta(hours=c['extra_load_start_hour']);b=midnight+timedelta(hours=c['extra_load_end_hour'])
            if b<=local:a+=timedelta(days=1);b+=timedelta(days=1)
            data['rows'].append(validate({'kind':'consumption','name':'Bisheriger Abendverbrauch','repeat':'daily','start':a.isoformat(),'end':b.isoformat(),'kwh':c['extra_load_kwh']},c,now))
        data['consumption_migrated']=True;write_json(path,data)
    config=folder/'config.json'
    if config.exists() and c.get('extra_load_kwh',0):
        saved=json.loads(config.read_text());saved['extra_load_kwh']=0.0;write_json(config,saved)


def price_tip(data,c,prices,now=None,rules=()):
    """Read-only tariff comparison, same duration/energy and local calendar day."""
    now=now or datetime.now(timezone.utc)
    rule=validate({**data,'kind':'consumption','repeat':'once'},c,now)
    a,b=stamp(rule['start']),stamp(rule['end']);duration=b-a
    if a<now:return {'state':'past','message':'Für bereits gestartete Verbräuche kein Verschiebevorschlag.'}
    zone=ZoneInfo(c['timezone']);day=a.astimezone(zone).replace(hour=0,minute=0,second=0,microsecond=0)
    left=max(now,day.astimezone(timezone.utc));right=(day+timedelta(days=1)).astimezone(timezone.utc)
    holidays=[(stamp(r['start']),stamp(r['end'])) for r in rules if r['kind']=='holiday']
    def excluded(x,y):return any(h<y and j>x for h,j in holidays)
    if excluded(a,b):return {'state':'holiday','message':'Dieser Verbrauch liegt ganz oder teilweise im Urlaub und wird dort nicht eingeplant.'}
    sorted_prices=sorted(prices,key=lambda p:p['start'])
    def cost(x):
        y=x+duration;cursor=x;weighted=0
        for p in sorted_prices:
            l,r=max(x,p['start']),min(y,p['end'])
            if r<=l:continue
            if l!=cursor:return None
            weighted+=p['ct']*(r-l).total_seconds();cursor=r
        return weighted/duration.total_seconds()*rule['kwh']/100 if cursor==y else None
    current=cost(a)
    if current is None:return {'state':'missing','message':'Für dein Zeitfenster fehlen vollständige Tibber-Preise.'}
    # Sliding window minima occur at a tariff boundary or when its end meets one.
    candidates={a,left}
    for p in sorted_prices:
        for edge in (p['start'],p['end']):
            candidates.add(edge);candidates.add(edge-duration)
    options=[]
    for x in sorted(candidates):
        if x<left or x+duration>right or excluded(x,x+duration):continue
        value=cost(x)
        if value is not None:options.append((value,abs((x-a).total_seconds()),x))
    best=min(options,default=(current,0,a));saving=current-best[0]
    return {'state':'better' if saving>=0.01 else 'good','start':best[2].isoformat(),'end':(best[2]+duration).isoformat(),
            'current_eur':round(current,4),'alternative_eur':round(best[0],4),'saving_eur':round(max(0,saving),4),
            'message':'Vergleich am selben Tag · gleiche Dauer und kWh · nur bekannte Tibber-Preise. PV und Akku nicht berücksichtigt.'}
