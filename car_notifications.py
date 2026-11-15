"""Background EV reminders based on the same advice shown on the dashboard."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import time


def alerts(advice,now=None,zone='Europe/Berlin'):
    now=now or datetime.now(timezone.utc);result=[]
    for car in advice.get('vehicles',[]):
        deadline=car.get('deadline')
        stock=car.get('opportunity') if advice.get('priority_kind')=='stock' and advice.get('priority')==car['id'] else None
        if stock:deadline=stock['start']
        if not deadline:continue
        when=datetime.fromisoformat(deadline);hours=(when-now).total_seconds()/3600
        if not 0<=hours<=24:continue
        urgent=hours<=3;stage='urgent' if urgent else 'ahead'
        if car.get('charging_status')=='charging' and not urgent:continue
        target=stock['target_soc'] if stock else car['target_soc'];missing=stock['kwh'] if stock else car['missing_kwh']
        stamp=when.astimezone(ZoneInfo(zone)).strftime('%d.%m. %H:%M')
        first=car['id']==advice.get('priority')
        disconnected=car.get('connector_status')=='disconnected'
        if first and disconnected:
            title='LUNA · '+car['name']+' anschließen'
            others=[r['name'] for r in advice['vehicles'] if r['id']!=car['id'] and r.get('connected')]
            action=('Aktuell ist '+', '.join(others)+' angesteckt. ' if others else '')+'Für die Planung wird '+car['name']+' benötigt.'
        else:
            title='LUNA · Ladebedarf '+car['name']
            action='Angesteckt; Ladefortschritt prüfen.' if car.get('connected') else ('Anschlussstatus unbekannt; bitte prüfen.' if not disconnected else 'Zusätzlichen Ladetermin einplanen.')
        body=f"{action}\n{'Günstiges Nachtfenster ab' if stock else 'Fahrtbedarf bis'} {stamp}: Ziel ca. {target} %, noch ca. {missing:g} kWh. Aktuell {car['soc']:g} %."
        if car.get('unreachable'):body+=' Mehr Energie als eine volle Batterie nötig: Zwischenladen erforderlich.'
        body+=' Schätzung; LUNA steuert die Wallbox noch nicht.'
        # Day and urgency are stable against revised minute-by-minute targets.
        result.append({'key':f"ev:{car['id']}:{when.astimezone(ZoneInfo(zone)).date()}:{stage}",'title':title,'body':body})
    return result


class CarNotifier:
    def __init__(self,app):self.app=app;self.seen={}
    def tick(self,now=None):
        from car_planning import advice
        now=now or datetime.now(timezone.utc);app=self.app
        if not app.whatsapp.status()['car_alerts']:self.seen={};return
        c=app.config();d=advice(app.car_planning.read(),app.vehicle_probe.cache,c['timezone'],now,app.car_context.snapshot(c))
        current=alerts(d,now,c['timezone']);keys={a['key'] for a in current}
        self.seen={k:v for k,v in self.seen.items() if k in keys}
        for a in current:
            start=self.seen.setdefault(a['key'],now.timestamp())
            if now.timestamp()-start<60:continue # Two checks; no alert for a transient refresh.
            app.whatsapp.emit(a['key'],a['title'],a['body'],'car',43200)
            contact=c.get('push_contact','')
            app.notifications.emit(a['key'],a['title'],a['body'],'mailto:'+contact if contact else '',43200)
    def worker(self):
        while not self.app.closed.is_set():
            try:self.tick()
            except Exception:pass # No credentials or telemetry in exceptions/logs.
            self.app.closed.wait(60)
