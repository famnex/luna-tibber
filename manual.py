"""Persisted manual interventions; UTC intervals are half-open [start, end)."""
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def stamp(value):
    d=datetime.fromisoformat(value)
    if d.tzinfo is None:raise ValueError('Zeitpunkt ohne Zeitzone')
    return d.astimezone(timezone.utc)


def local_time(value, zone):
    d=datetime.fromisoformat(value)
    if d.tzinfo is not None:return d.astimezone(timezone.utc)
    z=ZoneInfo(zone); aware=d.replace(tzinfo=z)
    if aware.astimezone(timezone.utc).astimezone(z).replace(tzinfo=None)!=d or aware.utcoffset()!=d.replace(tzinfo=z,fold=1).utcoffset():
        raise ValueError('Uhrzeit liegt in einer Zeitumstellung; eindeutige Zeit wählen')
    return aware.astimezone(timezone.utc)


def load(folder, serial=None, now=None):
    now=now or datetime.now(timezone.utc)
    path=folder/'manual-orders.json'
    if (folder/'manual-suspended.json').exists():return []
    if not path.exists():return []
    data=json.loads(path.read_text())
    if serial is not None and data.get('serial')!=serial:
        if data.get('rows'):raise ValueError('Manuelle Aufträge gehören zu einer anderen Wechselrichter-Seriennummer')
        return []
    done=folder/'manual-completed'
    return sorted([r for r in data['rows'] if (r.get('repeat','once')!='once' or not r.get('end') or stamp(r['end'])>now) and not (done/r['token']).exists()],key=lambda r:r['start'])


def active(rows, now, kind=None):
    return next((r for r in rows if (r['kind'] in ('hold','charge') if kind is None else r['kind']==kind) and stamp(r['start'])<=now and (not r.get('end') or now<stamp(r['end']))),None)


def complete(folder, order):
    # Separate immutable completion markers avoid races with dashboard CRUD.
    root=folder/'manual-completed';root.mkdir(mode=0o700,exist_ok=True)
    (root/order['token']).touch(mode=0o600,exist_ok=True)


def upsert(rows, data, c, now=None):
    now=now or datetime.now(timezone.utc)
    kind=data.get('kind');end_kind=data.get('end_kind')
    if kind in ('consumption','holiday'):
        from consumption import validate
        ident=data.get('id')
        if ident and not any(r['id']==ident for r in rows):raise ValueError('Eintrag nicht mehr vorhanden')
        if len(rows)>=50 and not ident:raise ValueError('Maximal 50 Einträge')
        return sorted([r for r in rows if r['id']!=ident]+[validate(data,c,now)],key=lambda r:r['start'])
    if kind not in ('hold','charge'):raise ValueError('Entladesperre oder Ladeauftrag wählen')
    if end_kind not in (('time','forever') if kind=='hold' else ('time','soc')):raise ValueError('Ungültige Endbedingung')
    ident=data.get('id')
    if ident and not any(r['id']==ident for r in rows):raise ValueError('Auftrag nicht mehr vorhanden; Liste aktualisieren')
    start=now if not data.get('start') else local_time(data['start'],c['timezone'])
    if start<now: start=now # Editing an active intervention takes effect now.
    target=data.get('target_soc',c['target_soc']) if end_kind=='soc' else c['target_soc']
    if type(target) not in (int,float) or not math.isfinite(target) or not 10<=target<=95:raise ValueError('Ziel-SOC: 10 bis 95 %')
    end=None if end_kind=='forever' else start+timedelta(minutes=c['max_session_minutes']) if end_kind=='soc' else local_time(data['end'],c['timezone'])
    minimum=180 if kind=='charge' else 120
    if end and (end-start).total_seconds()<minimum:raise ValueError('Ladefenster mindestens drei Minuten; Entladesperre mindestens zwei Minuten')
    if kind=='charge' and (end-start).total_seconds()>c['max_session_minutes']*60:raise ValueError('Ladefenster überschreitet die maximale Ladesitzung')
    if len(rows)>=50 and not ident:raise ValueError('Maximal 50 manuelle Eingriffe')
    if kind=='charge' and target<=c.get('battery_floor_soc',0):raise ValueError('Ziel-SOC muss über der Geräte-Untergrenze liegen')
    rest=[r for r in rows if r['id']!=ident]
    far=datetime.max.replace(tzinfo=timezone.utc)
    for r in rest:
        if r['kind']==kind and start<(stamp(r['end']) if r.get('end') else far) and stamp(r['start'])<(end or far):
            raise ValueError('Überschneidung mit bestehender '+('Entladesperre' if kind=='hold' else 'Ladeorder')+'; bestehenden Eintrag bearbeiten')
    item={'id':ident or uuid.uuid4().hex,'token':uuid.uuid4().hex,'kind':kind,'start':start.isoformat(),'end':end.isoformat() if end else None,'end_kind':end_kind,'target_soc':target if kind=='charge' else None}
    return sorted(rest+[item],key=lambda r:r['start'])


def migrate(folder, serial, now=None):
    """Preserve a pre-existing manual lock on upgrade without duplicating it."""
    from luna import write_json
    now=now or datetime.now(timezone.utc)
    old=folder/'discharge-request.json'
    if not old.exists():return
    request=json.loads(old.read_text())
    if (folder/'manual-orders.json').exists():
        saved=json.loads((folder/'manual-orders.json').read_text())
        if request.get('until') and saved.get('migrated_legacy_until')==request['until'] and request.get('serial')==serial:
            write_json(old,{'serial':serial,'until':None})
        return
    if not request.get('until') or stamp(request['until'])<=now:return
    if request.get('serial')!=serial:raise ValueError('Bestehende Entladesperre: Seriennummer weicht ab')
    order={'id':uuid.uuid4().hex,'token':uuid.uuid4().hex,'kind':'hold','start':now.isoformat(),'end':request['until'],'end_kind':'time','target_soc':None}
    write_json(folder/'manual-orders.json',{'serial':serial,'rows':[order],'migrated_legacy_until':request['until']})
    write_json(old,{'serial':serial,'until':None})


def expire(folder, now=None):
    now=now or datetime.now(timezone.utc)
    path=folder/'manual-orders.json'
    if not path.exists():return []
    expired=[]
    for order in json.loads(path.read_text())['rows']:
        if order.get('repeat','once')=='once' and order.get('end') and stamp(order['end'])<=now and not (folder/'manual-completed'/order['token']).exists():
            complete(folder,order);expired.append(order)
    return expired
