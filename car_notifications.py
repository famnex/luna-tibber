"""Evening EV connection reminders based on the same read-only nightly plan as the dashboard."""
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo


def alerts(advice, now=None, zone='Europe/Berlin', settings=None):
    """Notify at the chosen local clock time only when tonight's car needs plugging in.

    A nightly session spans 22:00–06:00. 18:00 refers to the evening *before*
    that night, never to the following afternoon. Repeats are opt-in and
    stop when the charging window begins, so no night-time swaps are requested.
    """
    now=now or datetime.now(timezone.utc)
    tz=ZoneInfo(zone)
    local=now.astimezone(tz)
    preference=settings or {'enabled':True,'time':'18:00','repeat':False}
    if preference.get('enabled',True) is not True:return []
    try:chosen=time.fromisoformat(preference.get('time','18:00'))
    except (ValueError,TypeError):chosen=time(18)
    priority=next((v for v in advice.get('vehicles',[]) if v.get('id')==advice.get('priority')),None)
    if not priority or priority.get('charging_status')=='charging':return []
    # No connection reminder when the selected car is already plugged in.
    if priority.get('connected') or priority.get('connector_status')=='connected':return []
    rotation=priority.get('rotation') if advice.get('priority_kind')=='rotation' else None
    stock=priority.get('opportunity') if advice.get('priority_kind')=='stock' else None
    planned=rotation or stock
    if advice.get('rotation',{}).get('status')=='planned' and not planned:return []
    if planned:
        start=datetime.fromisoformat(planned['start']).astimezone(tz)
        end=datetime.fromisoformat(planned['end']).astimezone(tz) if planned.get('end') else start+timedelta(hours=8)
        # At 02:00 it is still the night of the previous calendar day.
        night_day=start.date()-timedelta(days=1) if start.hour<6 else start.date()
    else:
        # If the joint plan cannot provide a night, fall back to the imminent
        # uncovered departure, to avoid silently hiding an urgent need.
        if not priority.get('deadline'):return []
        end=datetime.fromisoformat(priority['deadline']).astimezone(tz)
        night_day=end.date()-timedelta(days=1) if end.hour<22 else end.date()
        start=datetime.combine(night_day,time(22),tzinfo=tz)
    reminder_at=datetime.combine(night_day,chosen,tzinfo=tz)
    if chosen.hour<6:reminder_at+=timedelta(days=1)
    # A reminder set to 18:00 is eligible until the 22:00 charging window.
    # Explicitly configured late times are respected; never alert after its end.
    cutoff=start if reminder_at<start else end
    if not reminder_at<=local<cutoff:return []
    if end<=local:return []
    # Repeat every full hour after the chosen time, only if enabled and the
    # requested car is still disconnected. No hourly alerts after 22:00.
    elapsed=int((local-reminder_at).total_seconds()//3600)
    if elapsed and preference.get('repeat') is True:
        if local>=start:return []
        stage='repeat-'+str(elapsed)
    else:
        stage='initial'
    others=[v.get('name','anderes Auto') for v in advice['vehicles']
            if v.get('id')!=priority['id'] and (v.get('connected') or v.get('connector_status')=='connected')]
    if others:
        action=', '.join(others)+' ist angesteckt. Bitte auf '+priority['name']+' umstecken.'
    elif priority.get('connector_status')=='disconnected':
        action=priority['name']+' bitte anschließen. Aktuell ist kein Auto angeschlossen.'
    else:
        action='Bitte prüfen, ob '+priority['name']+' angeschlossen ist (Anschlussstatus unbekannt).'
    target=(planned or {}).get('target_soc',priority.get('target_soc'))
    need=(planned or {}).get('kwh',priority.get('missing_kwh'))
    def number(value):return f'{value:.1f}'.rstrip('0').rstrip('.').replace('.',',')
    soc=priority.get('soc')
    before=rotation.get('expected_start_soc') if rotation else None
    levels='🔋 '+number(soc)+' %' if isinstance(soc,(int,float)) else ''
    if isinstance(before,(int,float)) and abs(before-soc)>0.2:levels+=' ↘ '+number(before)+' %'
    if isinstance(target,(int,float)):levels+=' → '+number(target)+' %'
    if isinstance(need,(int,float)):levels+=' · +'+number(need)+' kWh'
    context='Diese Nacht ist eine Ladung für '+priority['name']+' vorgesehen. ' if planned else 'Vor der nächsten Fahrt muss '+priority['name']+' laden. '
    if priority.get('unreachable') and not rotation:
        context+='Eine volle Batterie reicht nicht; Zwischenladen einplanen. '
    return [{'key':f"ev:{priority['id']}:{night_day.isoformat()}:{stage}",
             'title':'LUNA · '+('Umstecken' if others else 'Anschließen')+': '+priority['name'],
             'body':context+action+((' '+levels) if levels else '')}]


class CarNotifier:
    def __init__(self,app):self.app=app;self.seen={}
    def tick(self,now=None):
        from car_planning import advice
        now=now or datetime.now(timezone.utc);app=self.app
        ntfy=getattr(app,'ntfy',None)
        web_push=app.whatsapp.status()['car_alerts']
        if not web_push and not (ntfy and ntfy.status()['car_alerts']):self.seen={};return
        c=app.config();plan=app.car_planning.read()
        d=advice(plan,app.vehicle_probe.cache,c['timezone'],now,app.car_context.snapshot(c))
        current=alerts(d,now,c['timezone'],plan.get('connection_reminder'));keys={a['key'] for a in current}
        self.seen={k:v for k,v in self.seen.items() if k in keys}
        for a in current:
            start=self.seen.setdefault(a['key'],now.timestamp())
            if now.timestamp()-start<60:continue # Two checks; no alert for a transient refresh.
            app.whatsapp.emit(a['key'],a['title'],a['body'],'car',43200)
            if ntfy:ntfy.emit(a['key'],a['title'],a['body'],'car',43200)
            contact=c.get('push_contact','')
            if web_push:app.notifications.emit(a['key'],a['title'],a['body'],'mailto:'+contact if contact else '',43200)
    def worker(self):
        while not self.app.closed.is_set():
            try:self.tick()
            except Exception:pass # No credentials or telemetry in exceptions/logs.
            self.app.closed.wait(60)
