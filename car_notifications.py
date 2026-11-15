"""Background EV reminders based on the same advice shown on the dashboard."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import time


def alerts(advice,now=None,zone='Europe/Berlin'):
    now=now or datetime.now(timezone.utc);result=[];tz=ZoneInfo(zone)
    def number(value):return f'{value:.1f}'.rstrip('0').rstrip('.').replace('.',',')
    for car in advice.get('vehicles',[]):
        rotation=car.get('rotation') if advice.get('priority_kind')=='rotation' and advice.get('priority')==car['id'] else None
        # A coordinated plan notifies only the car assigned to the next night.
        if advice.get('rotation',{}).get('status')=='planned' and not rotation:continue
        stock=car.get('opportunity') if advice.get('priority_kind')=='stock' and advice.get('priority')==car['id'] else None
        deadline=(rotation or stock or {}).get('start') or car.get('deadline')
        if not deadline:continue
        when=datetime.fromisoformat(deadline);hours=(when-now).total_seconds()/3600
        if not 0<=hours<=24:continue
        urgent=hours<=3;stage='urgent' if urgent else 'ahead'
        if car.get('charging_status')=='charging' and not urgent:continue
        target=(rotation or stock or {}).get('target_soc',car.get('target_soc'))
        missing=(rotation or stock or {}).get('kwh',car.get('missing_kwh'))
        extra=rotation.get('add_soc') if rotation else (missing/car['capacity']*100 if car.get('capacity') else max(0,target-car['soc']))
        first=car['id']==advice.get('priority');disconnected=car.get('connector_status')=='disconnected'
        day=(when.astimezone(tz).date()-now.astimezone(tz).date()).days
        night='diese Nacht' if day==0 or (day==1 and when.astimezone(tz).hour<7) else 'morgen Nacht' if day==1 else 'am '+when.astimezone(tz).strftime('%d.%m.')
        journey='die morgige Fahrt' if day==1 else 'die heutige Fahrt' if day==0 else 'die Fahrt am '+when.astimezone(tz).strftime('%d.%m.')
        need_time=night if rotation or stock else ('vor der morgigen Fahrt' if day==1 else 'vor der heutigen Fahrt' if day==0 else 'vor der Fahrt am '+when.astimezone(tz).strftime('%d.%m.'))
        others=[r['name'] for r in advice['vehicles'] if r['id']!=car['id'] and r.get('connected')]
        if first and disconnected and others:
            action=f"{', '.join(others)} ist angesteckt, aber {car['name']} muss {need_time} laden. Bitte umstecken."
        elif first and disconnected and all(r.get('connector_status')=='disconnected' for r in advice['vehicles']):
            action=f"Kein Auto ist angesteckt. {car['name']} muss {need_time} laden."
        elif rotation or stock:
            action=f"{car['name']} {'kann günstig' if stock else 'muss'} {night} laden."
        else:action=f"Die Ladung von {car['name']} reicht für {journey} nicht aus."
        if car.get('unreachable') and not rotation:
            body=action+' Eine volle Batterie reicht nicht: zusätzliches Zwischenladen einplanen.'
        else:body=action+f" Mindestens ca. {number(extra)} Prozentpunkte ({number(missing)} kWh) nachladen; Ziel {target} %."
        if car.get('connector_status')=='connected' or car.get('connected'):
            body+=' Bereits angeschlossen – kein Umstecken nötig. Ladung in evcc einplanen, falls noch nicht geschehen.'
        elif car.get('connector_status') not in ('connected','disconnected'):
            body+=' Anschlussstatus unbekannt; Anschluss und Ladeplanung in evcc prüfen.'
        if first and advice.get('rotation',{}).get('status')=='conflict':body+=' Gemeinsamer Wochenplan hat einen Ladekonflikt; zusätzlichen Ladetermin prüfen.'
        result.append({'key':f"ev:{car['id']}:{when.astimezone(tz).date()}:{stage}",'title':'LUNA · '+car['name'],'body':body})
    return result


class CarNotifier:
    def __init__(self,app):self.app=app;self.seen={}
    def tick(self,now=None):
        from car_planning import advice
        now=now or datetime.now(timezone.utc);app=self.app
        ntfy=getattr(app,'ntfy',None)
        web_push=app.whatsapp.status()['car_alerts']
        if not web_push and not (ntfy and ntfy.status()['car_alerts']):self.seen={};return
        c=app.config();d=advice(app.car_planning.read(),app.vehicle_probe.cache,c['timezone'],now,app.car_context.snapshot(c))
        current=alerts(d,now,c['timezone']);keys={a['key'] for a in current}
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
