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
        items=expand(row,now,now+timedelta(days=15))[:2] if row.get('repeat','once')!='once' else [row]
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
