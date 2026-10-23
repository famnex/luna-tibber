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
import time
from zoneinfo import ZoneInfo
import luna

BASE = Path(__file__).resolve().parent
MODES = {'off', 'smart', 'on', 'schedule'}
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

def next_day_comparison(c, prices, now):
    """Time weighted, complete local-day coverage; handles 23/25 hour DST days."""
    zone = ZoneInfo(c['timezone'])
    day = now.astimezone(zone).date() + timedelta(days=1)
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
        self.proc = None
        self.job = None
        self.generation = 0
        self.mode = 'off'  # Never resume charging merely because the server rebooted.
        self.until = None
        self.planned = None
        self.schedules = validate_schedules(read(folder/'schedules.json', []))
        self.last_slot = None
        self.fault = ''
        self.events = deque(maxlen=80)
        self.telemetry = {}
        self.device = read(folder/'device.json', {})
        self.last_probe_serial = None
        self.price_data = []
        self.price_at = 0
        self.price_error = ''
        self.closed = threading.Event()
        if start_worker:
            threading.Thread(target=self.worker,daemon=True).start()
            threading.Thread(target=self.price_worker,daemon=True).start()
    def config(self):
        c = {**luna.DEFAULT, **read(self.config_path,{})}
        return luna.validate(c)
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
        if job in ('run','charge','charge-test','stop'):
            cmd.append('--execute')
        if target_soc is not None:
            cmd.extend(['--target-soc',str(target_soc)])
        if job == 'probe':
            self.last_probe_serial = None
        self.proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.job = job
        proc = self.proc
        threading.Thread(target=self.collect,args=(proc,gen,job),daemon=True).start()
    def collect(self, proc, gen, job):
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue  # Never relay arbitrary library output or secrets.
            with self.lock:
                if gen != self.generation:
                    continue
                self.events.append(event)
                if event.get('event') in ('snapshot','test_sample','decision'):
                    self.telemetry = event
                if event.get('event') == 'connected':
                    self.device = event
                if event.get('event') == 'error':
                    self.fault = event.get('message','Vorgang fehlgeschlagen')
        rc = proc.wait()
        with self.lock:
            if gen == self.generation:
                self.proc = None
                self.job = None
                if rc:
                    self.fault = self.fault or f'Vorgang beendet (Code {rc})'
                    self.mode = 'off'
                if job == 'charge' and self.mode in ('on','planned'):
                    self.mode = 'off'
                    self.until = None
                    if self.planned:
                        self.planned['phase'] = 'failed' if rc else 'completed'
                if rc == 0 and job == 'probe':
                    self.device = read(self.folder/'device.json',{})
                    self.last_probe_serial = self.device.get('serial')
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
        self.generation += 1
        self.proc = None
        self.job = None
    def save_settings(self, patch):
        if self.proc or self.mode != 'off':
            raise ValueError('Vor dem Speichern auf Aus schalten und Vorgang beenden')
        allowed = set(luna.DEFAULT)-{'mode'}
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
        with (self.folder/'controller.lock').open('w') as f:
            try:
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Ein externer CLI-/Ladedienst läuft; zuerst beenden') from None
            luna.write_json(self.config_path,c)
            if c['expected_serial'] != old_serial:
                (self.folder/'commissioned.json').unlink(missing_ok=True)
        self.price_at = 0
        self.price_data = []
    def action(self, name, data):
        with self.lock:
            if name == 'settings':
                self.save_settings(data)
            elif name == 'schedules':
                rows = validate_schedules(data['rows'])
                self.stop()
                self.schedules = rows
                luna.write_json(self.folder/'schedules.json',self.schedules)
            elif name == 'adopt-serial':
                serial = self.last_probe_serial
                if not serial:
                    raise ValueError('Zuerst Gerät auslesen')
                self.save_settings({'expected_serial':serial})
            elif name == 'probe':
                if self.mode != 'off':
                    raise ValueError('Zum Auslesen zuerst auf Aus schalten')
                if not self.config_path.exists():
                    self.save_settings({})
                self.fault = ''
                self.launch('probe')
            elif name == 'test':
                if self.mode != 'off':
                    raise ValueError('Zuerst auf Aus schalten')
                self.preflight(self.config(),False)
                self.fault = ''
                self.launch('charge-test')
            elif name == 'planned':
                c = self.config()
                order = planned_order(data,c)
                self.preflight(c)
                self.fault = ''
                self.stop()
                if self.fault:
                    raise ValueError(self.fault)
                self.save_settings({})
                self.planned = order
                self.mode = 'planned'
            elif name == 'mode':
                mode = data['mode']
                if mode not in MODES:
                    raise ValueError('Unbekannter Modus')
                if mode != 'off':
                    c = self.config()
                    self.preflight(c)
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
    def worker(self):
        while not self.closed.wait(1):
            with self.lock:
                try:
                    if self.mode == 'off':
                        continue
                    if self.until and time.monotonic() >= self.until:
                        self.stop()
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
    def tick_planned(self, now=None):
        now = now or datetime.now(timezone.utc)
        order = self.planned
        if not order:
            self.stop()
            return
        end = datetime.fromisoformat(order['end'])
        if now >= end:
            self.stop()
            return
        if now < datetime.fromisoformat(order['start']):
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
        while not self.closed.is_set():
            with self.lock:
                c = self.config()
                due = time.monotonic()-self.price_at >= 300
            if due:
                try:
                    prices = luna.fetch_prices(c)
                    error = ''
                except Exception:
                    prices,error = [],'Tibber-Preise nicht verfügbar; Token und Zuhause-ID prüfen'
                with self.lock:
                    if self.config().get('tibber_token') == c['tibber_token']:
                        self.price_data,self.price_error,self.price_at = prices,error,time.monotonic()
            self.closed.wait(10)
    def snapshot(self):
        with self.lock:
            c = self.config()
            settings = {k:v for k,v in c.items() if k not in SECRETS and k != 'mode'}
            missing = [label for key,label in [('expected_serial','Seriennummer'),('password','Installateurpasswort'),('tibber_token','Tibber-Token')] if not c[key]]
            prices = self.price_data if time.monotonic()-self.price_at < 600 else []
            now = datetime.now(timezone.utc)
            plan = luna.economics_plan(c,prices,now)
            current = next((p['ct'] for p in prices if p['start']<=now<p['end']),None)
            wifi = read(Path('/etc/luna-wifi.json'),{})
            return {'mode':self.mode,'planned':self.planned,'job':self.job,'fault':self.fault,'settings':settings,
                    'secrets_set':{k:bool(c[k]) for k in SECRETS},'missing':missing,
                    'commissioned':read(self.folder/'commissioned.json',{}).get('serial') == c['expected_serial'] and bool(c['expected_serial']),
                    'telemetry':self.telemetry,'device':self.device,'economics':plan,'current_price':current,
                    'comparison':next_day_comparison(c,prices,now),
                    'price_age_seconds':max(0,int(time.monotonic()-self.price_at)) if self.price_at else None,
                    'price_error':self.price_error,'prices':prices,'schedules':self.schedules,
                    'remaining_seconds':max(0,int(self.until-time.monotonic())) if self.until else None,
                    'wifi':{k:wifi.get(k) for k in ('interface','ssid','host')},
                    'events':list(self.events)[-12:]}
    def close(self):
        self.closed.set()
        with self.lock:
            self.stop()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def send(self,code,data,content_type='application/json',cookie=None):
        body = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(body)
    def host_ok(self):
        return self.headers.get('Host','').split(':')[0] in self.server.allowed_hosts
    def authenticated(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie',''))
            token = cookie['luna'].value
            with self.server.auth_lock:
                return self.server.sessions.get(token,0)>time.monotonic()
        except (KeyError,ValueError):
            return False
    def do_GET(self):
        if not self.host_ok():
            return self.send(403,{'error':'Host nicht erlaubt'})
        static = {'/':('web.html','text/html; charset=utf-8'),'/app.js':('app.js','application/javascript'),'/style.css':('style.css','text/css')}
        if self.path in static:
            filename,kind = static[self.path]
            return self.send(200,(BASE/filename).read_bytes(),kind)
        if not self.authenticated():
            return self.send(401,{'error':'Bitte anmelden'})
        if self.path == '/api/status':
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
                    self.server.sessions = {k:v for k,v in self.server.sessions.items() if v>now}
                    token = secrets.token_urlsafe(32)
                    self.server.sessions[token]=now+43200
                return self.send(200,{'ok':True},cookie=f'luna={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
            if not self.authenticated():
                return self.send(401,{'error':'Bitte anmelden'})
            if self.path == '/api/logout':
                cookie=SimpleCookie(self.headers.get('Cookie',''))
                with self.server.auth_lock:
                    self.server.sessions.pop(cookie['luna'].value,None)
                return self.send(200,{'ok':True},cookie='luna=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if not self.path.startswith('/api/'):
                return self.send(404,{'error':'Nicht gefunden'})
            self.server.app.action(self.path[5:],data)
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
        server.daemon_threads=True
        server.app,server.auth=app,auth
        server.sessions={}
        server.attempts=deque()
        server.auth_lock=threading.Lock()
        server.allowed_hosts={'localhost','127.0.0.1',args.host}
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
