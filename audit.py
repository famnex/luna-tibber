"""Local diagnostic journal from existing controller events. No device/network IO."""
import hashlib
import json
import math
import os
import sqlite3
import threading
import zlib
import gzip
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

CONFIG_KEYS=('target_soc','battery_floor_soc','battery_capacity_kwh','charge_power_w',
 'roundtrip_efficiency','wear_ct_kwh','min_saving_ct_kwh','max_buy_ct_kwh',
 'base_load_w','extra_load_kwh','extra_load_start_hour','extra_load_end_hour',
 'night_start_hour','night_end_hour','use_start_hour','use_end_hour','max_session_minutes',
 'timezone','smart_discharge_enabled','pv_enabled','pv_factor','pv_kwp','pv_tilt','pv_azimuth','pv_ac_limit_kw')
EVENT_KEYS=('soc','battery_power_w','battery_status','max_charge_power_w','ac_charge_enabled',
 'eligible','reason','app_charging','price_ct_kwh','economics','watts','minutes','fields',
 'error_type','message','note','action','parameters','returncode','live','discharge_confirmation')


def clean(value,secrets=()):
    if isinstance(value,dict):return {str(k):clean(v,secrets) for k,v in value.items() if k not in ('password','tibber_token','expected_serial','host','username','pv_latitude','pv_longitude','tibber_home_id')}
    if isinstance(value,(list,tuple)):return [clean(x,secrets) for x in value]
    if isinstance(value,datetime):return value.isoformat()
    if isinstance(value,str):
        for secret in secrets:
            if secret:value=value.replace(str(secret),'[entfernt]')
        return value[:4000]
    if value is None or type(value) in (bool,int):return value
    if isinstance(value,float):return value if math.isfinite(value) else None
    return str(value)[:200]


def number(value,unit=''):
    return ('—' if type(value) not in (int,float) else f'{value:.2f}'.rstrip('0').rstrip('.').replace('.',','))+unit


def describe(kind,d):
    if kind in ('decision','snapshot','test_sample'):
        power=d.get('battery_power_w');soc=d.get('soc')
        flow='Messwert fehlt' if power is None else 'lädt' if power>100 else 'entlädt' if power< -100 else 'ruht'
        text=f"Akku {flow}: {number(soc,' %')}, {number(power/1000 if power is not None else None,' kW')}."
        if kind=='decision':
            text+=f" Netzladeentscheidung: {'freigegeben' if d.get('eligible') else 'nicht freigegeben'}. Grund: {d.get('reason','nicht gemeldet')}. Preis: {number(d.get('price_ct_kwh'),' ct/kWh')}."
            g=d.get('guard') or {}
            if g:text+=f" Schutzgrenze {number(g.get('threshold_soc'),' % SOC')}; für später {number(g.get('required_kwh'),' kWh')}; Überschuss {number(g.get('surplus_kwh'),' kWh')}."
            dispatch=d.get('dispatch') or {}
            if dispatch:text+=f" Entladung {'sperren' if dispatch.get('hold') else 'freigeben'}: {dispatch.get('reason','')} ."
            confirmed=d.get('discharge_confirmation') or {}
            if confirmed:text+=f" Letzte Gerätebestätigung: {'gesperrt' if confirmed.get('locked') else 'freigegeben'} ({confirmed.get('time','Zeit unbekannt')})."
            if not d.get('live',True):text+=' Nur Simulation – keine Schreibbefehle.'
        return text
    if kind=='charge_command':return f"Ladebefehl gesendet: {number(d.get('watts'),' W')} für {number(d.get('minutes'),' min')}. Tatsächlichen Ladebeginn zeigen die folgenden Messwerte."
    if kind in ('stopped','stopped_on_exit'):return 'Stoppbefehl erfolgreich ausgeführt. '+str(d.get('reason','Steuerung beendet.'))
    if kind=='stop_unconfirmed':return '⚠ Stopp/Freigabe nicht bestätigt. '+str(d.get('note','Gerätezustand prüfen.'))
    if kind=='discharge_synced':
        state=d.get('discharge_confirmation') or {}
        return 'Entladesteuerung abgeglichen: '+('gesperrt' if state.get('locked') else 'freigegeben oder keine eigene Sperre vorhanden')+'.'
    if kind=='target_reached':return 'Ziel erreicht bei '+number(d.get('soc'),' % SOC')+'.'
    if kind=='settings_applied':return 'Laufende Steuerung hat Einstellungen übernommen: '+', '.join(d.get('fields',[]))+'.'
    if kind=='user_action':return 'Bedienaktion übernommen: '+str(d.get('action',''))+'. '+json.dumps(d.get('parameters',{}),ensure_ascii=False)
    if kind=='service_started':return 'Webdienst gestartet. Automatische Ladung startet nach Neustart nicht von selbst.'
    if kind=='controller_exit':return f"Geräteprozess beendet (Code {d.get('returncode')})."
    if kind in ('error','price_error'):return '⚠ '+str(d.get('message') or d.get('error_type') or 'Fehler; Quelle nicht verfügbar')
    return kind.replace('_',' ')+': '+str(d.get('reason') or d.get('note') or d.get('message') or 'Ereignis der Steuerung.')


class Journal:
    def __init__(self,folder):
        self.path=folder/'diagnostics.sqlite3';self.lock=threading.RLock();self.export_lock=threading.Lock();self.error=''
        self.last_plan=None;self.plan_at=0;self.plan_signature=None;self.last_state=None;self.maintenance=0
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, time REAL, data TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,time REAL,kind TEXT,mode TEXT,job TEXT,revision TEXT,important INTEGER,text TEXT,data TEXT,plan_id INTEGER);
            CREATE INDEX IF NOT EXISTS event_time ON events(time);
            ''')
        os.chmod(self.path,0o600)
    def connect(self):return sqlite3.connect(self.path,timeout=3)
    def record(self,c,event,mode='unknown',job=None,revision=None,prices=None):
        try:
            with self.lock:self._record(c,event,mode,job,revision,prices or [])
            self.error=''
        except Exception:self.error='Diagnoseprotokoll konnte nicht gespeichert werden.'
    def _record(self,c,event,mode,job,revision,prices):
        kind=event.get('event','unknown')
        # Never persist account discovery, serial numbers or raw third-party output.
        if kind in ('home_selection_required','prices','connected'):return
        stamp=datetime.fromisoformat(event.get('time',datetime.now(timezone.utc).isoformat())).timestamp()
        secrets=tuple(c.get(k) for k in ('password','tibber_token','expected_serial','host','tibber_home_id'))
        d=clean({k:event[k] for k in EVENT_KEYS if k in event},secrets)
        dispatch=event.get('dispatch') or {}
        if dispatch:
            d['dispatch']=clean({k:dispatch.get(k) for k in ('enabled','hold','complete','reason')},secrets)
            d['guard']=clean(dispatch.get('guard'),secrets)
        preview=event.get('diagnostic_plan') or {}
        inputs={k:(event.get('diagnostic_inputs') or c).get(k) for k in CONFIG_KEYS}
        if preview:
            d['plan_summary']=clean({k:preview.get(k) for k in ('needed_kwh','planned_kwh','effective_target_soc','planning_soc','complete','reason')},secrets)
        state=(kind,mode,job,d.get('eligible'),d.get('reason'),dispatch.get('hold'),
               'charge' if (d.get('battery_power_w') or 0)>100 else 'discharge' if (d.get('battery_power_w') or 0)< -100 else 'idle')
        important=kind not in ('decision','snapshot','test_sample') or state!=self.last_state
        with self.connect() as db:
            if kind=='decision':
                # Losslessly compress every distinct exact plan. Unchanged plans
                # share a reference; every decision keeps its own measured values.
                j=preview.get('joint') or {}
                payload={'config':inputs,
                         'charging':{k:v for k,v in preview.items() if k!='joint'},
                         'joint':{k:v for k,v in j.items() if k not in ('trace','windows')},
                         'discharge_windows':dispatch.get('windows',[]),'prices':prices,
                         'pv':event.get('diagnostic_pv',{})}
                payload=clean(payload,secrets)
                raw=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
                signature=hashlib.sha256(raw).hexdigest()
                if self.last_plan is None or signature!=self.plan_signature:
                    self.last_plan=db.execute('INSERT INTO plans(time,data) VALUES (?,?)',(stamp,zlib.compress(raw,3))).lastrowid
                    self.plan_at=stamp;self.plan_signature=signature
            text=describe(kind,d)
            db.execute('INSERT INTO events(time,kind,mode,job,revision,important,text,data,plan_id) VALUES (?,?,?,?,?,?,?,?,?)',
                       (stamp,kind,mode,job,revision,int(important),text,json.dumps(d,ensure_ascii=False),self.last_plan))
            if stamp-self.maintenance>=3600:
                db.execute('DELETE FROM events WHERE time<? OR id <= (SELECT COALESCE(MAX(id),0)-70000 FROM events)',(stamp-7*86400,))
                db.execute('DELETE FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM events WHERE plan_id IS NOT NULL)')
                self.maintenance=stamp
        self.last_state=state
    def soc_series(self):
        # Reuse recorded telemetry; no extra inverter requests. One read per minute.
        now=time.time()
        with self.lock:
            if now-getattr(self,'soc_cache_at',0)<60:return self.soc_cache
            with self.connect() as db:
                rows=db.execute("SELECT time,data FROM events WHERE time>=? AND kind IN ('snapshot','decision') ORDER BY time",(now-48*3600,)).fetchall()
            buckets={}
            for stamp,raw in rows:
                value=json.loads(raw).get('soc')
                if type(value) in (int,float) and math.isfinite(value) and 0<=value<=100:
                    buckets[int(stamp//300)]={'time':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),'soc':value}
            self.soc_cache=list(buckets.values());self.soc_cache_at=now
            return self.soc_cache

    def entries(self,hours=24,before=None,all_checks=False):
        cutoff=datetime.now(timezone.utc).timestamp()-hours*3600
        with self.connect() as db:
            query='SELECT id,time,kind,mode,job,revision,important,text,data,plan_id FROM events WHERE time>=?'
            args=[cutoff]
            if before:query+=' AND id<?';args.append(before)
            if not all_checks:query+=' AND important=1'
            rows=db.execute(query+' ORDER BY id DESC LIMIT 201',args).fetchall()
        return {'events':[self.row(r) for r in rows[:200]],'before':rows[199][0] if len(rows)>200 else None,'error':self.error,'retention_days':7}
    @staticmethod
    def row(r):
        return dict(zip(('id','timestamp','event','mode','job','revision','important','text','data','plan_id'),(*r[:8],json.loads(r[8]),r[9])))
    def export(self,hours=24):
        cutoff=datetime.now(timezone.utc).timestamp()-hours*3600
        with self.connect() as db:
            rows=db.execute('SELECT id,time,kind,mode,job,revision,important,text,data,plan_id FROM events WHERE time>=? ORDER BY id LIMIT 20000',(cutoff,)).fetchall()
            ids={r[9] for r in rows if r[9] is not None}
            plans={str(i):self.decode(data) for i,data in db.execute('SELECT id,data FROM plans') if i in ids}
        return {'version':1,'exported_at':datetime.now(timezone.utc).isoformat(),'events':[self.row(r) for r in rows],
                'plans':plans,'limit_reached':len(rows)==20000,'note':'Messungen und Entscheidungen; Befehle sind kein Beleg für tatsächlichen Energiefluss. Keine rückwirkende Rekonstruktion.'}
    @staticmethod
    def decode(value):return json.loads(zlib.decompress(value) if isinstance(value,bytes) else value)
    def plan(self,key):
        with self.connect() as db:row=db.execute('SELECT data FROM plans WHERE id=?',(key,)).fetchone()
        return self.decode(row[0]) if row else None
    def prose(self,hours=24):
        data=self.export(hours);lines=['LUNA Diagnoseverlauf','Zeitstempel mit UTC-Versatz; Messungen nur während laufender Steuerung oder vorhandener Abfragen.','']
        for row in data['events']:
            plan=data['plans'].get(str(row['plan_id']),{})
            zone=ZoneInfo(plan.get('config',{}).get('timezone','Europe/Berlin'))
            stamp=datetime.fromtimestamp(row['timestamp'],timezone.utc).astimezone(zone).isoformat(timespec='seconds')
            lines.append(f"{stamp} · {row['mode']} · Plan #{row['plan_id'] or '—'}\n{row['text']}\n")
        lines+=['Vollständige Planstände, Preise und PV-Daten sind im separaten JSON-Diagnoseexport enthalten.']
        if data['limit_reached']:lines.append('Exportlimit erreicht; Zeitraum verkürzen.')
        return '\n'.join(lines)

    @contextmanager
    def download(self,hours=24,compressed=True,zone='Europe/Berlin'):
        if not self.export_lock.acquire(blocking=False):raise ValueError('Ein Export läuft bereits')
        try:
            cutoff=datetime.now(timezone.utc).timestamp()-hours*3600
            with self.connect() as db:
                rows=db.execute('SELECT id,time,kind,mode,job,revision,important,text,data,plan_id FROM events WHERE time>=? ORDER BY id LIMIT 20000',(cutoff,)).fetchall()
            deadline=time.monotonic()+60
            def check():
                if time.monotonic()>deadline:raise TimeoutError('Exportzeit überschritten')
            # Roll to disk after 1 MiB; only one decoded plan is held at a time.
            with tempfile.SpooledTemporaryFile(max_size=1024*1024,mode='w+b') as output:
                if compressed:
                    with gzip.GzipFile(fileobj=output,mode='wb',compresslevel=1) as gz:
                        def write(value):gz.write(json.dumps(value,ensure_ascii=False).encode())
                        gz.write(b'{"version":1,"exported_at":');write(datetime.now(timezone.utc).isoformat())
                        gz.write(b',"events":[')
                        for index,row in enumerate(rows):
                            check()
                            if index:gz.write(b',')
                            write(self.row(row))
                        gz.write(b'],"plans":{')
                        ids=sorted({r[9] for r in rows if r[9] is not None})
                        first=True
                        for key in ids:
                            check();plan=self.plan(key)
                            if plan is None:continue
                            if not first:gz.write(b',')
                            first=False;write(str(key));gz.write(b':');write(plan)
                            del plan
                        gz.write(b'},"limit_reached":');write(len(rows)==20000)
                        gz.write(b',"note":');write('Befehle sind kein Beleg für tatsächlichen Energiefluss. Keine rückwirkende Rekonstruktion.')
                        gz.write(b'}')
                else:
                    tz=ZoneInfo(zone)
                    output.write(b'LUNA Diagnoseverlauf\n\n')
                    for row in rows:
                        check()
                        stamp=datetime.fromtimestamp(row[1],timezone.utc).astimezone(tz).isoformat(timespec='seconds')
                        output.write(f"{stamp} · {row[3]} · Plan #{row[9] or '—'}\n{row[7]}\n\n".encode())
                    output.write('Vollständige Planstände stehen im separaten JSON.GZ-Export. Befehle sind kein Beleg für tatsächlichen Energiefluss.\n'.encode())
                    if len(rows)==20000:output.write('Exportlimit erreicht; Zeitraum verkürzen.\n'.encode())
                output.seek(0)
                yield output
        finally:self.export_lock.release()
