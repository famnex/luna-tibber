#!/usr/bin/env python3
"""Local LUNA dashboard. One controller process; password login and same-origin API."""
import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import fcntl
import getpass
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import time
from zoneinfo import ZoneInfo
import luna
import updater

BASE = Path(__file__).resolve().parent
MODES = {'off', 'smart'}
SECRETS = {'password', 'tibber_token'}

def read(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default

def validate_schedules(rows):
    if not isinstance(rows, list) or len(rows) > 30:
        raise ValueError('Maximal 30 Zeitpläne')
    for r in rows:
        if set(r) != {'days', 'start', 'end', 'mode'} or r['mode'] not in {'off','smart','on'}:
            raise ValueError('Ungültiger Zeitplan')
        if not isinstance(r['days'],list) or not r['days'] or any(type(d) is not int or not 0 <= d <= 6 for d in r['days']):
            raise ValueError('Wochentage: Montag=0 bis Sonntag=6')
        for key in ('start','end'):
            t = datetime.strptime(r[key], '%H:%M')
            if t.strftime('%H:%M') != r[key]:
                raise ValueError('Uhrzeit muss HH:MM sein')
        if r['start'] == r['end']:
            raise ValueError('Start und Ende müssen verschieden sein')
    return rows

def schedule_at(rows, now):
    """First matching row wins. Overnight intervals belong to their start day."""
    clock = now.strftime('%H:%M')
    for i, row in enumerate(rows):
        overnight = row['end'] < row['start']
        day = now.date()
        if overnight and clock < row['end']:
            day -= timedelta(days=1)
        in_time = (clock >= row['start'] or clock < row['end']) if overnight else row['start'] <= clock < row['end']
        if in_time and day.weekday() in row['days']:
            return row['mode'], f'{day}:{i}'
    return 'off', 'outside'

def next_day_comparison(c, prices, now, day_offset=1):
    """Time weighted, complete local-day coverage; handles 23/25 hour DST days."""
    zone = ZoneInfo(c['timezone'])
    day = now.astimezone(zone).date() + timedelta(days=day_offset)
    midnight = datetime.combine(day,datetime.min.time(),tzinfo=zone)
    start = midnight.astimezone(timezone.utc)
    end = (midnight+timedelta(days=1)).astimezone(timezone.utc)
    night_start = (midnight+timedelta(hours=c['night_start_hour'])).astimezone(timezone.utc)
    night_end = (midnight+timedelta(hours=c['night_end_hour'])).astimezone(timezone.utc)
    def average(a,b):
        cursor,total = a,0.0
        for row in sorted(prices,key=lambda p:p['start']):
            left,right = max(a,row['start']),min(b,row['end'])
            if right <= left:
                continue
            if left != cursor:  # Missing or overlapping prices are not a complete series.
                return None
            total += row['ct']*(right-left).total_seconds()
            cursor = right
        return total/(b-a).total_seconds() if cursor == b and b>a else None
    daily,night = average(start,end),average(night_start,night_end)
    effective = None if night is None else night/c['roundtrip_efficiency']+c['wear_ct_kwh']
    saving = None if daily is None or effective is None else daily-effective
    return {'date':str(day),'day_ct':daily,'night_ct':night,'effective_ct':effective,
            'saving_ct':saving,'night_start':night_start.isoformat(),'night_end':night_end.isoformat(),
            'complete':daily is not None and night is not None}

def smart_preview(c, prices, now, telemetry=None, hold_until=None):
    from smart import plan
    telemetry=telemetry or {}
    stamp=telemetry.get('time')
    fresh=stamp and 0 <= (now-datetime.fromisoformat(stamp)).total_seconds() <= 90
    return plan(c,prices,now,telemetry.get('soc') if fresh else None,
                telemetry.get('max_charge_power_w') if fresh else None,hold_until)


def planned_order(data, c, now=None):
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(c['timezone'])
    local = datetime.fromisoformat(data['start'])
    if local.tzinfo is not None:
        raise ValueError('Start als lokale Uhrzeit mit Datum eingeben')
    start = local.replace(tzinfo=zone).astimezone(timezone.utc)
    if start.astimezone(zone).replace(tzinfo=None) != local or local.replace(tzinfo=zone,fold=0).utcoffset() != local.replace(tzinfo=zone,fold=1).utcoffset():
        raise ValueError('Start liegt in einer mehrdeutigen oder fehlenden Zeit bei Zeitumstellung')
    if start <= now:
        raise ValueError('Start muss in der Zukunft liegen')
    kind = data['end_kind']
    target = c['target_soc']
    end = start + timedelta(minutes=c['max_session_minutes'])
    if kind == 'time':
        clock = datetime.strptime(data['end'], '%H:%M').time()
        finish = datetime.combine(local.date(),clock)
        if finish <= local:
            finish += timedelta(days=1)
        end = finish.replace(tzinfo=zone).astimezone(timezone.utc)
        if end.astimezone(zone).replace(tzinfo=None) != finish or finish.replace(tzinfo=zone,fold=0).utcoffset() != finish.replace(tzinfo=zone,fold=1).utcoffset():
            raise ValueError('Ende liegt in einer Zeitumstellung')
    elif kind == 'soc':
        target = data['target_soc']
        if type(target) not in (int,float) or not 10 <= target <= 95:
            raise ValueError('Ziel-SOC muss zwischen 10 und 95 Prozent liegen')
    else:
        raise ValueError('Ende muss Uhrzeit oder SOC sein')
    if not 120 <= (end-start).total_seconds() <= c['max_session_minutes']*60:
        raise ValueError('Ladefenster: mindestens 2 Minuten, höchstens maximale Sitzungslänge')
    return {'start':start.isoformat(),'end':end.isoformat(),'target_soc':target,'end_kind':kind,'phase':'waiting'}

class Dashboard:
    def __init__(self, folder=BASE, start_worker=True):
        self.folder = folder
        self.config_path = folder/'config.json'
        self.lock = threading.RLock()
        from consumption_advice import AdviceCache
        self.consumption_advice=AdviceCache()
        self.proc = None
        self.job = None
        self.update_preparing = False
        self.update_progress = None
        self.generation = 0
        self.mode = 'off'  # Never resume charging merely because the server rebooted.
        self.until = None
        self.planned = None
        self.manual_running = None
        self.schedules = validate_schedules(read(folder/'schedules.json', []))
        self.last_slot = None
        self.fault = ''
        self.events = deque(maxlen=80)
        self.telemetry = {}
        self.device = read(folder/'device.json', {})
        self.last_probe_serial = None
        self.price_data = []
        self.price_at = 0
        self.price_fetched_at = 0
        self.price_error = ''
        self.sample_at = -60
        self.hourly_sample_at = -3600
        self.discharge_at = -30
        self.closed = threading.Event()
        from history import History
        from notifications import Notifications
        self.history=History(folder)
        from audit import Journal
        self.journal=Journal(folder)
        self.notifications=Notifications(folder,start_worker=start_worker)
        self.sample_failures=0
        self.price_failed_since=None
        self.revision=updater.revision(folder)
        self.update_settings={"port":8099,"tls":False,"old_pid":os.getpid()}
        (self.folder/'manual-suspended.json').unlink(missing_ok=True)
        from manual import migrate
        migrate(self.folder,self.config()['expected_serial'])
        from consumption import migrate as migrate_consumption
        migrate_consumption(self.folder,self.config())
        self.audit_event({'event':'service_started'})
        if start_worker:
            threading.Thread(target=self.worker,daemon=True).start()
            threading.Thread(target=self.price_worker,daemon=True).start()
    def audit_event(self,event,job=None,mode=None):
        try:self.journal.record(self.config(),event,mode or self.mode,job or self.job,self.revision,self.price_data)
        except Exception:self.journal.error='Diagnoseprotokoll konnte nicht gespeichert werden.'

    def config(self):
        c = {**luna.DEFAULT, **read(self.config_path,{})}
        c=luna.validate(c)
        from manual import load as load_orders
        if (self.folder/'manual-orders.json').exists():c['_consumption_rules']=[r for r in load_orders(self.folder,c['expected_serial']) if r['kind'] in ('consumption','holiday')]
        return c
    def preflight(self, c, commissioning=True):
        missing = [label for key,label in [('expected_serial','Seriennummer (Gerät auslesen und übernehmen)'),('password','Huawei-Installateurpasswort')] if not c[key]]
        if missing:
            raise ValueError('Bitte ergänzen: ' + ', '.join(missing))
        if commissioning and read(self.folder/'commissioned.json',{}).get('serial') != c['expected_serial']:
            raise ValueError('Bitte zuerst den beaufsichtigten 2-Minuten-Ladetest erfolgreich durchführen')
    def launch(self, job, target_soc=None):
        if self.proc is not None:
            raise ValueError('Ein Vorgang läuft noch; zuerst stoppen')
        self.generation += 1
        gen = self.generation
        cmd = [sys.executable,str(BASE/'luna.py'),'--config',str(self.config_path),job]
        if job in ('run','charge','charge-test','stop','discharge-sync'):
            cmd.append('--execute')
        if job=='run' and self.mode=='off':cmd.append('--orders-only')
        if target_soc is not None:
            cmd.extend(['--target-soc',str(target_soc)])
        if job == 'probe':
            self.last_probe_serial = None
        self.proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.job = job
        proc = self.proc
        threading.Thread(target=self.collect,args=(proc,gen,job,self.mode),daemon=True).start()
    def collect(self, proc, gen, job, mode=None):
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue  # Never relay arbitrary library output or secrets.
            self.audit_event(event,job,mode)
            with self.lock:
                if gen != self.generation:
                    continue
                event={k:v for k,v in event.items() if k not in ("diagnostic_plan","diagnostic_pv","diagnostic_inputs")}
                self.events.append(event)
                if event.get('event') in ('snapshot','test_sample','decision'):
                    self.telemetry = event
                if event.get('event')=='charge_command' and job in ('run','charge'):
                    try:self.history.record(self.config(),event,self.price_data)
                    except Exception:self.events.append({'event':'statistics_error','message':'Planstatistik konnte nicht gespeichert werden'})
                if event.get('event') in ('stopped','stopped_on_exit','target_reached'):
                    self.finish_history(datetime.fromisoformat(event['time']))
                if event.get('event') == 'meter_test':
                    luna.write_json(self.folder/'meter-test.json',event)
                if event.get('event') == 'connected':
                    self.device = event
                if event.get('event') == 'stop_unconfirmed':
                    self.alert('restore','⚠ LUNA · Freigabe prüfen','Stopp oder Entladefreigabe nicht bestätigt. Gerät und Verbindung prüfen.')
                if event.get('event') == 'target_reached' and job=='charge':
                    self.alert('completed','✓ LUNA · Ladeziel erreicht','Der einmalige Ladeauftrag ist abgeschlossen.',cooldown=60)
                if event.get('event') == 'error' and job != 'sample':
                    self.fault = event.get('message','Vorgang fehlgeschlagen')
                    self.alert('controller-error','⚠ LUNA · Steuerung prüfen','Ein Steuerungsfehler ist aufgetreten. Details stehen in der App.')
        rc = proc.wait()
        with self.lock:
            self.audit_event({"event":"controller_exit","returncode":rc},job,mode)
            if gen == self.generation:
                self.proc = None
                self.job = None
                if job=='sample':
                    self.sample_failures=self.sample_failures+1 if rc else 0
                    if self.sample_failures>=5:self.alert('offline','⚠ LUNA · Verbindung fehlt','Seit mehreren Minuten keine Messwerte. Automatik und Verbindung prüfen.')
                if rc and job != 'sample':
                    self.fault = self.fault or f'Vorgang beendet (Code {rc})'
                    self.mode = 'off'
                    self.until = None
                    if self.planned:
                        self.planned['phase'] = 'failed'
                if job == 'charge' and self.mode in ('on','planned'):
                    self.mode = 'off'
                    self.until = None
                    if self.planned:
                        self.planned['phase'] = 'failed' if rc else 'completed'
                if rc == 0 and job == 'probe':
                    self.device = read(self.folder/'device.json',{})
                    self.last_probe_serial = self.device.get('serial')
    def finish_history(self,now=None):
        try:self.history.finish(now)
        except Exception:self.events.append({'event':'statistics_error','message':'Planstatistik konnte nicht abgeschlossen werden'})

    def alert(self,key,title,body,cooldown=1800):
        contact=self.config().get('push_contact','')
        self.notifications.emit(key,title,body,'mailto:'+contact if contact else '',cooldown)

    def stop(self):
        # Called with lock held; collector needs lock, so poll process directly.
        self.mode = 'off'
        self.planned = None
        self.until = None
        self.last_slot = None
        p = self.proc
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=40)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
                self.fault = 'Stopp nicht bestätigt; letzter Ladeauftrag maximal zwei Minuten. Gerät prüfen.'
        self.finish_history()
        self.generation += 1
        self.proc = None
        self.job = None
    def save_settings(self, patch):
        old_prices=self.config()
        allowed = set(luna.DEFAULT)-{'mode'}
        if any(k.startswith('extra_load_') for k in patch):
            # Legacy fields remain readable for old exports, but cannot add hidden demand.
            patch={k:v for k,v in patch.items() if not k.startswith('extra_load_')}
        if not set(patch) <= allowed:
            raise ValueError('Unbekannte Einstellung')
        c = self.config()
        old_serial = c['expected_serial']
        for key,value in patch.items():
            if key in SECRETS and value == '':
                continue
            if type(value) is not type(luna.DEFAULT[key]) and not (type(value) in (int,float) and type(luna.DEFAULT[key]) in (int,float)):
                raise ValueError('Ungültiger Typ: '+key)
            c[key] = value
        ipaddress.IPv4Address(c['host'])
        c['mode'] = 'auto'  # Web server is the single authority for off/smart/on.
        luna.validate(c)
        changed={k for k in luna.DEFAULT if c[k]!=old_prices[k]}
        request=read(self.folder/'discharge-request.json',{})
        hold=request.get('until') and datetime.fromisoformat(request['until'])>datetime.now(timezone.utc)
        from manual import load as load_orders
        if changed & luna.CONNECTION_KEYS and (any(r['kind'] in ('hold','charge') for r in load_orders(self.folder,old_serial)) or self.proc or self.mode!='off' or hold or
                any((self.folder/n).exists() for n in ('discharge-restore.json','pending-charge.json'))):
            raise ValueError('Nur Geräteverbindung/Zugang benötigen Aus und bestätigte Freigabe; andere Einstellungen sind im Betrieb änderbar')
        with (self.folder/'controller.lock').open('w') as f:
            # Our subprocess consumes atomic file updates in its normal control loop.
            # For an external owner, continue refusing concurrent configuration writes.
            if self.proc is None or self.proc.poll() is not None:
                try:
                    fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('Ein externer CLI-/Ladedienst läuft; zuerst beenden') from None
            luna.write_json(self.config_path,{k:v for k,v in c.items() if not k.startswith('_')})
            if c['expected_serial'] != old_serial:
                (self.folder/'commissioned.json').unlink(missing_ok=True)
                if (self.folder/'manual-orders.json').exists():
                    saved=read(self.folder/'manual-orders.json',{});saved['serial']=c['expected_serial']
                    luna.write_json(self.folder/'manual-orders.json',saved)
        if any(c[k]!=old_prices[k] for k in c if k.startswith('pv_')):self.price_at=0
        if any(c[k]!=old_prices[k] for k in ('tibber_token','tibber_home_id')):
            self.price_at = 0
            self.price_fetched_at = 0
            self.price_data = []
    def update_status(self):
        return {**(self.update_progress or updater.read_status(self.folder)),'revision':self.revision}

    def prepare_update(self):
        try:
            with self.lock:
                c=self.config()
                resume_smart=self.mode=='smart'
                luna.write_json(self.folder/'manual-suspended.json',{'reason':'update'})
                need_stop=self.mode!='off' or self.job in ('run','charge','charge-test','stop') or (self.folder/'pending-charge.json').exists()
                request=read(self.folder/'discharge-request.json',{})
                need_release=bool(request.get('until')) or (self.folder/'discharge-restore.json').exists()
                if need_stop or need_release:self.preflight(c,commissioning=False)
                self.fault=''
                if need_release:luna.write_json(self.folder/'discharge-request.json',{'serial':c['expected_serial'],'until':None})
                # Collector must keep draining stdout while the controller exits.
                # Waiting under self.lock can fill its pipe and turn a clean STOP
                # into a timeout. update_preparing excludes competing commands.
                self.mode='off';self.planned=None;self.until=None;self.last_slot=None
                proc=self.proc
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=5)
                    raise ValueError('Update abgebrochen: Geräteprozess hat den Stopp nicht rechtzeitig bestätigt.')
            with self.lock:
                self.stop()
                if self.fault:raise ValueError(self.fault)
            # No lock while doing device IO: progress remains reachable. All other
            # commands and sampling are excluded by update_preparing.
            for command,needed in [('stop',need_stop),('discharge-sync',need_release)]:
                if not needed:continue
                self.update_progress={'state':'preparing','step':2 if command=='stop' else 3,'message':'Ladestopp am Wechselrichter bestätigen …' if command=='stop' else 'Entladefreigabe am Wechselrichter bestätigen …','at':time.time()}
                result=subprocess.run([sys.executable,str(BASE/'luna.py'),'--config',str(self.config_path),command,'--execute'],
                                      stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
                for line in result.stdout.splitlines():
                    try:self.audit_event(json.loads(line),command,'off')
                    except ValueError:pass
                if result.returncode:raise ValueError('Update abgebrochen: Stopp oder Entladefreigabe nicht bestätigt. Verbindung prüfen.')
            with self.lock:
                if any((self.folder/n).exists() for n in ('pending-charge.json','discharge-restore.json')):
                    raise ValueError('Update abgebrochen: Gerätebestätigung steht aus.')
                self.update_progress={'state':'preparing','step':3,'message':'Update-Dienst starten …','at':time.time()}
                updater.start(self.folder,**self.update_settings,resume_smart=resume_smart,resume_serial=c['expected_serial'])
                self.update_progress=None
        except Exception as exc:
            with self.lock:
                self.update_progress={'state':'failed','message':str(exc) if isinstance(exc,ValueError) else 'Update-Vorbereitung fehlgeschlagen; Gerät und Verbindung prüfen.'}
        finally:
            with self.lock:
                self.update_preparing=False
                if not updater.busy(self.folder):(self.folder/'manual-suspended.json').unlink(missing_ok=True)

    def action(self, name, data):
        with self.lock:
            if self.update_preparing or updater.busy(self.folder):raise ValueError('Update läuft; Steuerung vorübergehend gesperrt')
            if name == 'update':
                try:updater.inspect_repo(self.folder)
                except updater.UpdateError as exc:raise ValueError(str(exc)) from None
                self.update_preparing=True
                self.update_progress={'state':'preparing','message':'Steuerung stoppen und Entladesperre freigeben …','step':1,'at':time.time()}
                threading.Thread(target=self.prepare_update,daemon=True).start()
            elif name == 'push-subscribe':
                contact=self.config().get('push_contact','')
                self.notifications.subscribe(data['subscription'],'mailto:'+contact if contact else '')
            elif name == 'push-unsubscribe':
                self.notifications.unsubscribe(data['endpoint'])
            elif name == 'push-test':
                self.alert('test','✓ LUNA · Push bereit','Wichtige Meldungen erreichen dieses Gerät.',cooldown=60)
            elif name in ('template-save','template-delete'):
                from consumption import template_change
                path=self.folder/'consumption-templates.json'
                rows=template_change(read(path,[]),data,delete=name=='template-delete')
                luna.write_json(path,rows)
            elif name in ('manual-save','manual-delete'):
                from manual import load, upsert
                c=self.config()
                if data.get('kind') not in ('consumption','holiday') and name=='manual-save':self.preflight(c)
                rows=load(self.folder,c['expected_serial'])
                if name=='manual-save':rows=upsert(rows,data,c)
                else:
                    if not any(r['id']==data.get('id') for r in rows):raise ValueError('Auftrag nicht mehr vorhanden')
                    rows=[r for r in rows if r['id']!=data['id']]
                luna.write_json(self.folder/'manual-orders.json',{**read(self.folder/'manual-orders.json',{}),'serial':c['expected_serial'],'rows':rows})
                self.fault='';self.discharge_at=-30
                self.audit_event({'event':'manual_changed','action':name,'orders':rows})
            elif name == 'discharge':
                raise ValueError('Entladesperren unter Manuell verwalten')
            elif name == 'settings':
                self.save_settings(data)
            elif name == 'schedules':
                raise ValueError('Zeitaufträge unter Manuell anlegen')
            elif name == 'adopt-serial':
                serial = self.last_probe_serial
                if not serial:
                    raise ValueError('Zuerst Gerät auslesen')
                self.save_settings({'expected_serial':serial})
            elif name in ('probe','meter-test'):
                if self.mode != 'off':
                    raise ValueError('Zum Auslesen zuerst auf Aus schalten')
                if not self.config_path.exists():
                    self.save_settings({})
                self.fault = ''
                self.launch(name)
            elif name == 'test':
                if self.mode != 'off':
                    raise ValueError('Zuerst auf Aus schalten')
                self.preflight(self.config(),False)
                self.fault = ''
                self.launch('charge-test')
            elif name == 'planned':
                raise ValueError('Ladeaufträge unter Manuell anlegen')
            elif name == 'mode':
                mode = data['mode']
                if mode not in MODES:
                    raise ValueError('Unbekannter Modus')
                (self.folder/'update-resume.json').unlink(missing_ok=True)
                if mode != 'off':
                    c = self.config()
                    self.preflight(c)
                    if mode == 'smart' and c['battery_capacity_kwh'] <= 0:
                        raise ValueError('Nutzbare Akkukapazität in kWh zuerst in den Einstellungen eintragen')
                    if mode == 'smart' and not c['tibber_token']:
                        raise ValueError('Tibber-Token fehlt')
                    minutes = data.get('minutes',30)
                    if mode == 'on' and (type(minutes) is not int or not 2 <= minutes <= c['max_session_minutes']):
                        raise ValueError('Manuelle Dauer: 2 bis maximale Sitzungslänge in Minuten')
                self.fault = ''
                self.stop()
                if mode != 'off' and self.fault:
                    raise ValueError(self.fault)
                if mode == 'off':
                    # Also send STOP for a pending/previous command, when credentials exist.
                    c = self.config()
                    if c['expected_serial'] and c['password']:
                        self.launch('stop')
                else:
                    # Persist auto flag without otherwise changing settings.
                    self.save_settings({})
                    self.mode = mode
                    self.until = time.monotonic()+minutes*60 if mode == 'on' else None
            else:
                raise ValueError('Unbekannte Aktion')
    def resume_after_update(self):
        path=self.folder/'update-resume.json'
        if not path.exists():return
        pending=read(path,{})
        status=updater.read_status(self.folder)
        if status.get('state') in updater.ACTIVE:return
        path.unlink(missing_ok=True)  # Consume once; ordinary restarts never resume.
        if (status.get('state') not in ('done','current') or not pending.get('token')
                or status.get('token')!=pending['token'] or time.time()-pending.get('created',0)>3600):
            return
        try:
            c=self.config()
            if c['expected_serial']!=pending.get('serial'):raise ValueError('Gerätezuordnung hat sich geändert')
            if self.fault:raise ValueError(self.fault)
            self.preflight(c)
            if c['battery_capacity_kwh']<=0 or not c['tibber_token']:raise ValueError('Smart-Einstellungen unvollständig')
            self.mode='smart'
            self.audit_event({'event':'smart_resumed','reason':'Nach erfolgreichem Update wieder aktiviert'})
        except ValueError as exc:
            self.mode='off';self.fault='Smart nach Update nicht aktiviert: '+str(exc)

    def worker(self):
        while not self.closed.wait(1):
            with self.lock:
                try:
                    if self.update_preparing or updater.busy(self.folder):continue
                    (self.folder/'manual-suspended.json').unlink(missing_ok=True)
                    self.resume_after_update()
                    if self.fault:continue
                    from manual import load as load_orders, active as active_order, expire
                    for expired in expire(self.folder):self.audit_event({'event':'manual_completed','order_id':expired['id'],'reason':'Zeitfenster abgelaufen'})
                    now=datetime.now(timezone.utc)
                    orders=load_orders(self.folder,self.config()['expected_serial'],now)
                    charge=active_order(orders,now,'charge')
                    if self.mode=='off' and self.job=='run' and (not charge or self.manual_running!=charge['token']):
                        self.stop();self.manual_running=None
                        continue
                    if self.mode=='off' and charge and not self.proc:
                        self.preflight(self.config());self.save_settings({})
                        self.manual_running=charge['token'];self.launch('run')
                        continue
                    request=read(self.folder/'discharge-request.json',{})
                    needs_restore=(self.folder/'discharge-restore.json').exists()
                    hold=bool(active_order(orders,now,'hold')) or (request.get('until') and datetime.fromisoformat(request['until'])>now)
                    if (hold or needs_restore) and not self.proc and time.monotonic()-self.discharge_at>=30:
                        self.discharge_at=time.monotonic()
                        self.preflight(self.config())
                        self.launch('discharge-sync')
                        continue
                    if self.job == 'discharge-sync':
                        continue
                    if self.mode == 'off':
                        self.hourly_sample()
                        continue
                    if self.job in ('sample','probe','charge-test','stop'):
                        continue
                    if self.expire_order():
                        continue
                    if self.mode == 'planned':
                        self.tick_planned()
                        continue
                    mode,key = self.mode,self.mode
                    if mode == 'schedule':
                        mode,key = schedule_at(self.schedules,datetime.now(ZoneInfo(self.config()['timezone'])))
                    if key != self.last_slot:
                        if self.proc:
                            original,until = self.mode,self.until
                            self.stop()
                            if self.fault:
                                raise ValueError(self.fault)
                            self.mode,self.until = original,until
                        self.last_slot = key
                        if mode != 'off':
                            self.fault = ''
                            self.preflight(self.config())
                            self.launch('charge' if mode=='on' else 'run')
                except Exception as exc:
                    self.stop()
                    self.fault = str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'Steuerung fehlgeschlagen'
    def expire_order(self):
        if self.until is not None and time.monotonic() >= self.until:
            self.stop()
            self.alert('completed','✓ LUNA · Ladeauftrag beendet','Das eingestellte Zeitfenster ist abgelaufen.',cooldown=60)
            return True
        return False

    def tick_planned(self, now=None):
        now = now or datetime.now(timezone.utc)
        order = self.planned
        if not order:
            self.stop()
            return
        end = datetime.fromisoformat(order['end'])
        if now >= end:
            self.stop()
            self.alert('completed','✓ LUNA · Ladefenster beendet','Der geplante Auftrag ist abgelaufen.',cooldown=60)
            return
        if now < datetime.fromisoformat(order['start']):
            self.hourly_sample()
            return
        if order['phase'] == 'waiting':
            if (end-now).total_seconds() < 120:
                self.stop()
                return
            self.preflight(self.config())
            self.until = time.monotonic() + (end-now).total_seconds()
            self.launch('charge',target_soc=order['target_soc'])
            order['phase'] = 'charging'

    def price_worker(self):
        price_revision=None;pv_at=-300.0
        from price_cache import revision,poll_interval
        while not self.closed.is_set():
            with self.lock:
                c = self.config()
                observed_revision=revision(self.folder)
                due = time.monotonic()-self.price_at >= poll_interval(c) or observed_revision!=price_revision
            if due:
                try:
                    from pv import refresh as refresh_pv
                    if time.monotonic()-pv_at>=300:
                        pv_at=time.monotonic()
                        refresh_pv(c,self.folder)
                except Exception:pass
                try:
                    from price_cache import get
                    prices,stamp,fallback = get(c,self.folder,luna.fetch_prices)
                    error = 'Tibber nicht erreichbar · gespeicherte Preise werden verwendet' if fallback else ''
                except Exception:
                    stamp = 0
                    prices,error = [],'Tibber-Preise nicht verfügbar; Token und Zuhause-ID prüfen'
                price_revision=observed_revision
                with self.lock:
                    if all(self.config().get(k)==c[k] for k in ('tibber_token','tibber_home_id')):
                        self.price_data,self.price_error,self.price_at = prices,error,time.monotonic()
                        self.price_fetched_at = stamp
                        if not prices:
                            self.price_failed_since=self.price_failed_since or time.monotonic()
                            if time.monotonic()-self.price_failed_since>=1800:
                                self.alert('prices','⚠ LUNA · Preise fehlen','Tibber-Preise sind länger nicht verfügbar. Smart kann nicht vollständig planen.')
                        else:self.price_failed_since=None
            self.closed.wait(10)
    def hourly_sample(self):
        # Low-frequency history collection also with a closed browser. Controller
        # telemetry takes precedence; failed reads retry no faster than five minutes.
        with self.lock:
            if self.proc or self.update_preparing or updater.busy(self.folder):return
            stamp=self.telemetry.get('time');soc=self.telemetry.get('soc')
            try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()
            except (ValueError,TypeError):age=3600
            if type(soc) in (int,float) and 0<=soc<=100 and 0<=age<3600:return
            if time.monotonic()-self.hourly_sample_at<300:return
            if not self.config_path.exists() or not self.config().get('expected_serial'):return
            self.hourly_sample_at=time.monotonic()
            self.request_sample()

    def request_sample(self, fast=False):
        # Visible browser or hourly history task. Reuse ongoing controller measurements.
        with self.lock:
            if self.update_preparing or updater.busy(self.folder) or self.proc or not self.config_path.exists() or time.monotonic()-self.sample_at < (10 if fast else 60):
                return
            self.sample_at = time.monotonic()
            self.launch('sample')

    def snapshot(self):
        with self.lock:
            c = self.config()
            settings = {k:v for k,v in c.items() if k not in SECRETS and k not in ('mode','reserve_soc') and not k.startswith('_')}
            missing = [label for key,label in [('expected_serial','Seriennummer'),('password','Installateurpasswort'),('tibber_token','Tibber-Token')] if not c[key]]
            prices = self.price_data
            now = datetime.now(timezone.utc)
            from pv import attach as attach_pv
            c=attach_pv(c,self.folder,now)
            request=read(self.folder/'discharge-request.json',{})
            hold_until=datetime.fromisoformat(request['until']) if request.get('until') else None
            prior=read(self.folder/'discharge-status.json',{})
            c['_guard_held']=bool(prior.get('locked') and prior.get('source')=='smart')
            from manual import load as load_orders
            all_orders=load_orders(self.folder,c['expected_serial'],now)
            c['_orders']=[r for r in all_orders if r['kind'] in ('hold','charge')]
            if self.mode=='off' and c['_orders']:c={**c,'_orders_only':True,'smart_discharge_enabled':True}
            preview=smart_preview(c,prices,now,self.telemetry,hold_until)
            from smart import planned_economics
            plan=planned_economics(c,prices,preview)
            from dispatch import timeline
            dispatch=timeline(c,prices,now,preview['soc'],preview,hold_until)
            current = next((p['ct'] for p in prices if p['start']<=now<p['end']),None)
            wifi = read(Path('/etc/luna-wifi.json'),{})
            return {'consumption_templates':read(self.folder/'consumption-templates.json',[]),'manual_orders':all_orders,'manual_occurrences':__import__('consumption').upcoming(all_orders,now),'consumption_forecast':__import__('consumption').intervals(c.get('_consumption_rules',[]),now,now+timedelta(hours=48)),'discharge':{'request':read(self.folder/'discharge-request.json',{}),'status':read(self.folder/'discharge-status.json',{}),'restore_pending':(self.folder/'discharge-restore.json').exists()},'mode':self.mode,'planned':self.planned,'job':self.job,'fault':self.fault,'settings':settings,
                    'secrets_set':{k:bool(c[k]) for k in SECRETS},'missing':missing,
                    'commissioned':read(self.folder/'commissioned.json',{}).get('serial') == c['expected_serial'] and bool(c['expected_serial']),
                    'pv_forecast':{**{k:v for k,v in c['_pv'].items() if k!='rows'},'series':[{**r,'start':r['start'].isoformat(),'end':r['end'].isoformat()} for r in c['_pv']['rows']]},'smart_preview':preview,'dispatch_preview':dispatch,'push':self.notifications.status(),'update':self.update_status(),
                    'battery_history':self.journal.soc_series(),'meter_test':read(self.folder/'meter-test.json',{}),'telemetry':self.telemetry,'device':self.device,'economics':plan,'current_price':current,
                    'comparison':next_day_comparison(c,prices,now,0 if now.astimezone(ZoneInfo(c['timezone'])).hour < c['night_end_hour'] else 1),
                    'comparisons':{key:next_day_comparison(c,prices,now,offset) for key,offset in [('today',0),('tomorrow',1)]},
                    'price_age_seconds':max(0,int(time.time()-self.price_fetched_at)) if self.price_fetched_at else None,
                    'price_error':self.price_error,'prices':prices,'schedules':self.schedules,
                    'remaining_seconds':max(0,int(self.until-time.monotonic())) if self.until else None,
                    'server_time':datetime.now(timezone.utc).isoformat(),
                    'wifi':{k:wifi.get(k) for k in ('interface','ssid','host')},
                    'events':list(self.events)[-12:]}
    def close(self):
        self.closed.set()
        self.notifications.closed.set()
        with self.lock:
            self.stop()

SESSION_SECONDS = 30 * 24 * 60 * 60

def session_key(token):
    return hashlib.sha256(token.encode()).hexdigest()

def load_sessions(path, auth):
    data = read(path,{})
    if data.get('auth_hash') != auth['hash']:
        return {}
    return {k:v for k,v in data.get('sessions',{}).items() if isinstance(v,(int,float)) and v>time.time()}

def save_sessions(server):
    path = getattr(server,'session_path',None)
    if path is not None:
        luna.write_json(path,{'auth_hash':server.auth['hash'],'sessions':server.sessions})

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def send(self,code,data,content_type='application/json',cookie=None,filename=None):
        body = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        if cookie:
            if getattr(self.server,'secure_cookies',False):cookie+='; Secure'
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(body)
    def send_download(self,stream,kind):
        stream.seek(0,2);size=stream.tell();stream.seek(0)
        self.send_response(200)
        self.send_header('Content-Type','application/gzip' if kind=='json.gz' else 'text/plain; charset=utf-8')
        self.send_header('Content-Disposition',f'attachment; filename="luna-diagnose-{datetime.now(timezone.utc):%Y-%m-%d}.{kind}"')
        self.send_header('Content-Length',str(size));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
        import shutil
        try:shutil.copyfileobj(stream,self.wfile,64*1024)
        except (BrokenPipeError,ConnectionResetError):pass

    def host_ok(self):
        try:return urlsplit('//'+self.headers.get('Host','')).hostname in self.server.allowed_hosts
        except ValueError:return False
    def authenticated(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie',''))
            token = cookie['luna'].value
            with self.server.auth_lock:
                return self.server.sessions.get(session_key(token),0)>time.time()
        except (KeyError,ValueError):
            return False
    def do_GET(self):
        if not self.host_ok():
            return self.send(403,{'error':'Host nicht erlaubt'})
        static = {'/':('web.html','text/html; charset=utf-8'),'/app.js':('app.js','application/javascript'),'/style.css':('style.css','text/css')}
        static.update({
            '/manual-ui.js':('manual-ui.js','application/javascript'),'/theme.js':('theme.js','application/javascript'),'/journal.js':('journal.js','application/javascript'),'/features.js':('features.js','application/javascript'),'/sw.js':('sw.js','application/javascript'),
            '/manifest.webmanifest':('manifest.webmanifest','application/manifest+json'),
            '/offline.html':('offline.html','text/html; charset=utf-8'),'/icon.svg':('icon.svg','image/svg+xml'),
            **{f'/icon-{n}.png':(f'icon-{n}.png','image/png') for n in (180,192,512)}})
        asset_path = self.path.split('?',1)[0]
        if asset_path in static:
            filename,kind = static[asset_path]
            return self.send(200,(BASE/filename).read_bytes(),kind)
        if self.path=='/healthz':
            return self.send(200,{'ok':True,'pid':os.getpid(),'revision':getattr(self.server,'started_revision',None)})
        if not self.authenticated():
            return self.send(401,{'error':'Bitte anmelden'})
        if self.path=='/api/update':
            return self.send(200,self.server.app.update_status())
        if self.path.split('?',1)[0]=='/api/journal/timeline':
            from urllib.parse import urlsplit,parse_qs
            try:
                day=parse_qs(urlsplit(self.path).query).get('day',[''])[0]
                result=self.server.app.journal.timeline(day,self.server.app.config()['timezone'])
            except (ValueError,TypeError):return self.send(400,{'error':'Bitte einen Tag aus den letzten sieben Tagen wählen.'})
            except Exception:return self.send(503,{'error':'Historie derzeit nicht lesbar. Bitte erneut versuchen.'})
            return self.send(200,result)
        if self.path.split('?',1)[0]=='/api/journal/plan':
            from urllib.parse import urlsplit,parse_qs
            try:
                key=int(parse_qs(urlsplit(self.path).query).get('id',['0'])[0])
                if key<=0:raise ValueError()
            except (ValueError,TypeError):return self.send(400,{'error':'Ungültiger Plan'})
            plan=self.server.app.journal.plan(key)
            return self.send(200,plan) if plan is not None else self.send(404,{'error':'Plan nicht mehr gespeichert'})
        if self.path.split('?',1)[0] in ('/api/journal','/api/journal/export','/api/journal/text','/api/journal/diagnosis'):
            from urllib.parse import urlsplit,parse_qs
            try:
                query=parse_qs(urlsplit(self.path).query)
                hours=int(query.get('hours',['24'])[0]);before=int(query.get('before',['0'])[0])
                if hours not in (6,12,24,48) or before<0:raise ValueError()
            except (ValueError,TypeError):return self.send(400,{'error':'Ungültiger Zeitraum'})
            journal=self.server.app.journal;path=self.path.split('?',1)[0]
            if path=='/api/journal/diagnosis':return self.send(200,journal.diagnosis(hours,self.server.app.config()))
            if path in ('/api/journal/export','/api/journal/text'):
                try:
                    with journal.download(hours,path.endswith('/export'),self.server.app.config()['timezone']) as stream:
                        return self.send_download(stream,'json.gz' if path.endswith('/export') else 'txt')
                except Exception:return self.send(503,{'error':'Export derzeit nicht möglich. Kürzeren Zeitraum wählen oder erneut versuchen.'})
            return self.send(200,journal.entries(hours,before,query.get('all',['0'])[0]=='1'))
        if self.path=='/api/history':
            return self.send(200,self.server.app.history.summary(self.server.app.config()))
        if self.path in ('/api/status','/api/status?fast=1'):
            self.server.app.request_sample(fast=self.path.endswith('?fast=1'))
            return self.send(200,self.server.app.snapshot())
        self.send(404,{'error':'Nicht gefunden'})
    def do_POST(self):
        if not self.host_ok() or self.headers.get('X-Luna') != '1' or self.headers.get('Content-Type') != 'application/json':
            return self.send(403,{'error':'Anfrage nicht erlaubt'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 32768:
                raise ValueError('Ungültige Anfragegröße')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError('Ungültige Anfrage')
            if self.path == '/api/login':
                with self.server.auth_lock:
                    now = time.monotonic()
                    attempts = self.server.attempts
                    while attempts and attempts[0]<now-60:
                        attempts.popleft()
                    if len(attempts)>=5:
                        return self.send(429,{'error':'Zu viele Versuche; eine Minute warten'})
                    attempts.append(now)
                    auth = self.server.auth
                    digest = hashlib.pbkdf2_hmac('sha256',str(data.get('password','')).encode(),bytes.fromhex(auth['salt']),300000).hex()
                    if not hmac.compare_digest(digest,auth['hash']):
                        return self.send(401,{'error':'Passwort falsch'})
                    self.server.sessions = {k:v for k,v in self.server.sessions.items() if v>time.time()}
                    token = secrets.token_urlsafe(32)
                    self.server.sessions[session_key(token)]=time.time()+SESSION_SECONDS
                    save_sessions(self.server)
                return self.send(200,{'ok':True},cookie=f'luna={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}')
            if not self.authenticated():
                return self.send(401,{'error':'Bitte anmelden'})
            if self.path == '/api/logout':
                cookie=SimpleCookie(self.headers.get('Cookie',''))
                with self.server.auth_lock:
                    self.server.sessions.pop(session_key(cookie['luna'].value),None)
                    save_sessions(self.server)
                return self.send(200,{'ok':True},cookie='luna=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if not self.path.startswith('/api/'):
                return self.send(404,{'error':'Nicht gefunden'})
            if self.path == '/api/consumption-tip':
                from pv import attach
                from manual import load
                app=self.server.app;now=datetime.now(timezone.utc)
                with app.lock:
                    c=attach(app.config(),app.folder,now);prices=list(app.price_data)
                    telemetry=dict(app.telemetry);mode=app.mode
                    c['_orders']=[r for r in load(app.folder,c['expected_serial'],now) if r['kind'] in ('hold','charge')]
                    prior=read(app.folder/'discharge-status.json',{})
                    c['_guard_held']=bool(prior.get('locked') and prior.get('source')=='smart')
                    until=read(app.folder/'discharge-request.json',{}).get('until')
                    hold_until=datetime.fromisoformat(until) if until else None
                return self.send(200,app.consumption_advice.get(data,c,prices,telemetry,mode,now,hold_until))
            if self.path == '/api/pv-location':
                from geocoding import lookup
                return self.send(200,{'results':lookup(data.get('postcode'))})
            self.server.app.action(self.path[5:],data)
            safe={k:v for k,v in data.items() if k in ('mode','minutes','start','end','end_kind','target_soc','until')}
            if self.path=='/api/settings':safe={'fields':list(data.keys())}
            self.server.app.audit_event({'event':'user_action','action':self.path[5:],'parameters':safe})
            self.send(200,{'ok':True})
        except (ValueError,KeyError) as exc:
            self.send(400,{'error':str(exc)})
        except Exception:
            self.send(500,{'error':'Vorgang fehlgeschlagen; Verbindung oder Dateirechte prüfen'})

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['setup','serve'])
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=8099)
    p.add_argument('--public-origin',default=os.environ.get('LUNA_PUBLIC_ORIGIN',''))
    p.add_argument('--tls-cert',default=os.environ.get('LUNA_TLS_CERT',''))
    p.add_argument('--tls-key',default=os.environ.get('LUNA_TLS_KEY',''))
    args=p.parse_args()
    os.umask(0o077)
    auth_path=BASE/'web-auth.json'
    if args.command=='setup':
        password=getpass.getpass('Neues Web-Passwort (mindestens 12 Zeichen): ')
        if len(password)<12 or password!=getpass.getpass('Wiederholen: '):
            raise ValueError('Passwort zu kurz oder Wiederholung abweichend')
        salt=secrets.token_bytes(16)
        luna.write_json(auth_path,{'salt':salt.hex(),'hash':hashlib.pbkdf2_hmac('sha256',password.encode(),salt,300000).hex()})
        print('Web-Passwort gespeichert. Start: .venv/bin/python web.py serve --host 0.0.0.0')
        return
    auth=read(auth_path,None)
    if not auth or auth_path.stat().st_mode & 0o077:
        raise ValueError('Zuerst web.py setup ausführen; web-auth.json muss Dateirechte 600 haben')
    with (BASE/'web.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        app=Dashboard()
        server=ThreadingHTTPServer((args.host,args.port),Handler)
        server.secure_cookies=bool(args.tls_cert or args.public_origin)
        if bool(args.tls_cert)!=bool(args.tls_key):raise ValueError('TLS-Zertifikat und Schlüssel gemeinsam angeben')
        if args.tls_cert:
            import ssl
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(args.tls_cert,args.tls_key)
            server.socket=context.wrap_socket(server.socket,server_side=True)
        server.daemon_threads=True
        server.app,server.auth=app,auth
        server.started_revision=app.revision
        app.update_settings={"port":args.port,"tls":bool(args.tls_cert),"old_pid":os.getpid()}
        server.session_path=BASE/'web-sessions.json'
        server.sessions=load_sessions(server.session_path,auth)
        server.attempts=deque()
        server.auth_lock=threading.Lock()
        server.allowed_hosts={'localhost','127.0.0.1',args.host}
        if args.public_origin:
            origin=urlsplit(args.public_origin)
            if origin.scheme!='https' or not origin.hostname or origin.username or origin.path not in ('','/') or origin.query or origin.fragment:
                raise ValueError('Öffentliche Adresse muss eine HTTPS-Origin ohne Pfad sein')
            server.allowed_hosts.add(origin.hostname)
        for addr in json.loads(subprocess.check_output(['ip','-j','-4','addr','show'],text=True)):
            server.allowed_hosts.update(x['local'] for x in addr.get('addr_info',[]) if 'local' in x)
        def shutdown(*_):
            threading.Thread(target=server.shutdown,daemon=True).start()
        signal.signal(signal.SIGTERM,shutdown)
        signal.signal(signal.SIGINT,shutdown)
        print(f'LUNA Web auf {args.host}:{args.port}; Modus Aus. Nur vertrauenswürdiges Heimnetz.',flush=True)
        try:
            server.serve_forever()
        finally:
            app.close()
            server.server_close()

if __name__=='__main__':
    main()
