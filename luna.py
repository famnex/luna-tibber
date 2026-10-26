#!/usr/bin/env python3
"""Local SUN2000 commissioning and Tibber threshold charging. Python 3.12+."""
import argparse
import asyncio
import fcntl
import getpass
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
DEFAULT = {
    "host": "192.168.200.1", "port": 6607, "unit_id": 0,
    "expected_serial": "", "username": "installer", "password": "",
    "tibber_token": "", "tibber_home_id": "", "mode": "monitor",
    "max_buy_ct_kwh": 20.0, "target_soc": 80.0, "charge_power_w": 1000,
    "battery_capacity_kwh": 0.0,
    "battery_floor_soc": 5.0,
    "smart_discharge_enabled": False, "base_load_w": 0, "reserve_soc": 0.0,
    "extra_load_kwh": 0.0, "extra_load_start_hour": 17, "extra_load_end_hour": 19,
    "pv_enabled": False, "pv_latitude": 0.0, "pv_longitude": 0.0, "pv_kwp": 0.0,
    "pv_tilt": 30.0, "pv_azimuth": 0.0, "pv_ac_limit_kw": 5.0, "pv_factor": 0.7,
    "statistics_enabled": True, "push_contact": "",
    "max_session_minutes": 120, "wifi_enabled": False,
    "roundtrip_efficiency": 0.85, "wear_ct_kwh": 0.0, "min_saving_ct_kwh": 2.0,
    "night_start_hour": 0, "night_end_hour": 6,
    "use_start_hour": 6, "use_end_hour": 9, "timezone": "Europe/Berlin",
}
QUERY = '''{ viewer { homes { id appNickname currentSubscription {
 priceInfo(resolution: QUARTER_HOURLY) {
 today { total startsAt currency } tomorrow { total startsAt currency }
 } } } } }'''

CONNECTION_KEYS={'host','port','unit_id','expected_serial','username','password','wifi_enabled'}
PASSIVE_KEYS={'statistics_enabled','push_contact','reserve_soc'}

def runtime_settings(c,path,target_soc=None):
    """Reload local configuration only; never reconnect or reset a running order."""
    if not path.exists():raise RuntimeError('Konfiguration fehlt; Steuerung wird beendet')
    fresh=validate({**DEFAULT,**json.loads(path.read_text())})
    if any(fresh[k]!=c[k] for k in CONNECTION_KEYS):
        raise RuntimeError('Geräteverbindung während Steuerung geändert; kontrollierter Abbruch')
    fresh['mode']=c['mode']
    if c.get('_manual'):fresh['_manual']=True
    if target_soc is not None:fresh['target_soc']=target_soc
    changed={k for k in DEFAULT if fresh[k]!=c[k]}
    return fresh,changed

def emit(event, **data):
    print(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "event": event,
                      **data}, ensure_ascii=False, default=str), flush=True)

def write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    os.chmod(path, 0o600)

def validate(c):
    # Legacy configuration key: no fixed application reserve remains.
    c["reserve_soc"] = 0.0
    for key in ("ev_protection_enabled","ev_start_hour","ev_end_hour","morning_buffer_kwh"):c.pop(key,None)
    for key, low, high in [("battery_floor_soc",0,30),("pv_latitude",-90,90),("pv_longitude",-180,180),("pv_kwp",0,100),("pv_tilt",0,90),("pv_azimuth",-180,180),("pv_ac_limit_kw",0.1,100),("pv_factor",0,1),("extra_load_kwh",0,50),("base_load_w", 0, 10000), ("battery_capacity_kwh", 0, 100), ("target_soc", 10, 95), ("charge_power_w", 200, 5000),
                            ("roundtrip_efficiency", 0.5, 1), ("wear_ct_kwh", 0, 100),
                            ("min_saving_ct_kwh", 0, 100), ("max_buy_ct_kwh", -100, 100), ("max_session_minutes", 2, 240)]:
        value = c[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Ungültiger Wert: {key} (Bereich {low} bis {high})")
    for key in ('statistics_enabled','smart_discharge_enabled','pv_enabled'):
        if type(c[key]) is not bool:raise ValueError('Ungültiger Schalter: '+key)
    if c['pv_enabled'] and c['pv_latitude']==0 and c['pv_longitude']==0:raise ValueError('Für PV-Prognose tatsächlichen Standort statt 0/0 eintragen')
    if c['pv_enabled'] and (c['pv_kwp']<=0 or c['base_load_w']<=0 or c['battery_capacity_kwh']<=0):raise ValueError('Für PV-Prognose kWp, Grundverbrauch und Akkukapazität eintragen')
    if c['smart_discharge_enabled'] and c['base_load_w']<=0:raise ValueError('Für Smart-Entladen Grundverbrauch größer 0 W einstellen')
    if c["mode"] not in ("monitor", "auto"):
        raise ValueError("mode muss monitor oder auto sein")
    for key, low, high in [("port", 1, 65535), ("unit_id", 0, 247)]:
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError(f"Ungültig: {key}")
    if type(c["charge_power_w"]) is not int:
        raise ValueError("charge_power_w muss ganzzahlig sein")
    if c['push_contact'] and ('@' not in c['push_contact'] or len(c['push_contact'])>240 or any(x.isspace() for x in c['push_contact'])):
        raise ValueError('Ungültige Push-Kontakt-E-Mail')
    if c['battery_floor_soc']>=c['target_soc']:raise ValueError('Geräte-Untergrenze muss unter dem Ziel-SOC liegen')
    ZoneInfo(c["timezone"])
    if not (type(c['extra_load_start_hour']) is int and type(c['extra_load_end_hour']) is int
            and 0<=c['extra_load_start_hour']<c['extra_load_end_hour']<=24):
        raise ValueError('Zusatzverbrauch: ganzzahlige Stunden 0 <= Start < Ende <= 24')
    if not (type(c["use_start_hour"]) is int and type(c["use_end_hour"]) is int
            and 0 <= c["use_start_hour"] < c["use_end_hour"] <= 24):
        raise ValueError("Verbrauchsfenster: ganzzahlige Stunden 0 <= Start < Ende <= 24")
    if not (type(c['night_start_hour']) is int and type(c['night_end_hour']) is int
            and 0 <= c['night_start_hour'] < c['night_end_hour'] <= 24):
        raise ValueError('Nachtvergleich: ganzzahlige Stunden 0 <= Start < Ende <= 24')
    return c

def cached_prices(c, folder):
    from price_cache import get
    return get(c, folder, fetch_prices)[0]

def fetch_prices(c):
    if not c["tibber_token"]:
        raise ValueError("Tibber-Token fehlt; zuerst setup ausführen")
    request = Request("https://api.tibber.com/v1-beta/gql",
        data=json.dumps({"query": QUERY}).encode(),
        headers={"Authorization": "Bearer " + c["tibber_token"],
                 "Content-Type": "application/json", "User-Agent": "LunaTibberLocal/1.0"})
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
    if result.get("errors"):
        raise ValueError("Tibber meldet einen GraphQL-Fehler; Token/Abonnement prüfen")
    homes = result["data"]["viewer"]["homes"]
    if c["tibber_home_id"]:
        homes = [h for h in homes if h["id"] == c["tibber_home_id"]]
    if len(homes) != 1:
        emit("home_selection_required", homes=[{"id": h["id"], "name": h.get("appNickname")} for h in homes])
        raise ValueError("Bitte tibber_home_id in config.json eindeutig setzen")
    subscription = homes[0].get("currentSubscription")
    info = subscription and subscription.get("priceInfo")
    if not info:
        raise ValueError("Keine Tibber-Preise für dieses Zuhause")
    prices = {}
    for item in (info.get("today") or []) + (info.get("tomorrow") or []):
        if item["currency"] != "EUR":
            raise ValueError("Nur EUR-Tarife unterstützt")
        value = item["total"]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Ungültiger Tibber-Preis")
        start = datetime.fromisoformat(item["startsAt"])
        if start.tzinfo is None:
            raise ValueError("Preis-Zeitzone fehlt")
        start = start.astimezone(timezone.utc)
        prices[start] = {"start": start, "end": start + timedelta(minutes=15), "ct": value * 100}
    return sorted(prices.values(), key=lambda p: p["start"])

def economics_plan(c, prices, now):
    """Price filter based on the configured consumption/discharge forecast."""
    if c.get('smart_discharge_enabled'):
        from dispatch import economics
        return economics(c,prices,now)
    local = now.astimezone(ZoneInfo(c["timezone"]))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(hours=c["use_start_hour"])
    end = midnight + timedelta(hours=c["use_end_hour"])
    if start <= local < end:
        return {"ok": False, "reason": "Verbrauchsfenster läuft; kein zusätzliches Netzladen"}
    if local >= end:
        start += timedelta(days=1)
        end += timedelta(days=1)
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    current = next((p for p in prices if p["start"] <= now < p["end"]), None)
    if current is None:
        return {"ok": False, "reason": "Aktueller Preis fehlt"}
    future = sorted((p for p in prices if start <= p["start"] < end), key=lambda p: p["start"])
    cursor = start
    for p in future:
        if p["start"] != cursor or p["end"] != cursor + timedelta(minutes=15):
            return {"ok": False, "reason": "Preislücke im Verbrauchsfenster"}
        cursor = p["end"]
    if cursor != end:
        return {"ok": False, "reason": "Preise des Verbrauchsfensters noch nicht vollständig verfügbar"}
    reference = sum(p["ct"] * (p["end"] - p["start"]).total_seconds() for p in future) / (end - start).total_seconds()
    effective = current["ct"] / c["roundtrip_efficiency"] + c["wear_ct_kwh"]
    saving = reference - effective
    ok = saving > 0 and saving >= c["min_saving_ct_kwh"]
    return {"ok": ok, "reason": "Preisvorteil nach Verlusten ausreichend" if ok else "Preisvorteil nach Verlusten zu klein",
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "reference_ct_kwh": reference, "effective_ct_kwh": effective,
            "saving_ct_kwh": saving, "assumption": "Strom ersetzt Netzbezug im konfigurierten Verbrauchsfenster"}

def decide(c, snapshot, prices, now):
    c.pop("_diagnostic_plan",None)
    slot = next((p for p in prices if p["start"] <= now < p["end"]), None)
    if c.get("_manual"):
        slot = {"start": now, "end": now + timedelta(minutes=15), "ct": None}
    if slot is None:
        return False, "Kein gültiger aktueller Preis", None
    if snapshot["soc"] >= c["target_soc"]:
        return False, "Ziel-SOC erreicht", slot
    if snapshot["battery_status"] not in (1, 2, 4):
        return False, "Batterie offline oder gestört", slot
    if not snapshot["ac_charge_enabled"]:
        return False, "Von AC-Seite laden ist deaktiviert", slot
    if c.get("_manual"):
        return True, "Manuelles Laden bis Ziel-SOC oder Zeitlimit", slot
    if slot["ct"] > c["max_buy_ct_kwh"]:
        return False, "Preis oberhalb Kaufgrenze", slot
    from smart import plan as smart_plan
    plan = smart_plan(c, prices, now, snapshot['soc'], snapshot.get('max_charge_power_w'),c.get('_hold_until'))
    c['_diagnostic_plan']=plan
    windows=plan['windows']
    for index,window in enumerate(windows):
        start,end=datetime.fromisoformat(window['start']),datetime.fromisoformat(window['end'])
        # Cross a tariff boundary only when the next interval is also selected.
        for following in windows[index+1:]:
            if abs((datetime.fromisoformat(following['start'])-(end-timedelta(seconds=130))).total_seconds())>1:break
            end=datetime.fromisoformat(following['end'])
        # Never cross a price gap or purchase ceiling, even with a bad plan.
        safe_end=slot['end']
        for price in sorted(prices,key=lambda p:p['start']):
            if price['start']==safe_end and price['ct']<=c['max_buy_ct_kwh'] and safe_end<end:
                safe_end=price['end']
        end=min(end,safe_end)
        if start <= now < end and (end-now).total_seconds() >= 130:
            return True, 'Smart: ausgewählter günstiger Ladeabschnitt', {**slot,'end':end}
    return False, plan['reason'] if not plan['windows'] else 'Smart wartet auf einen günstigeren Ladeabschnitt', slot

class Huawei:
    def __init__(self, c):
        self.c, self.client, self.device = c, None, None
    async def connect(self):
        from huawei_solar import create_tcp_client, create_device_instance, SUN2000Device
        self.client = create_tcp_client(self.c["host"], self.c["port"], unit_id=self.c["unit_id"], timeout=5)
        self.device = await asyncio.wait_for(create_device_instance(self.client), 60)
        if not isinstance(self.device, SUN2000Device) or self.device.model_name != "SUN2000-5KTL-M1":
            raise ValueError("Dieses Paket ist auf SUN2000-5KTL-M1 begrenzt")
        if self.c["expected_serial"] and self.device.serial_number != self.c["expected_serial"]:
            raise ValueError("Seriennummer stimmt nicht mit config.json überein")
        emit("connected", model=self.device.model_name, serial=self.device.serial_number,
             firmware=self.device.firmware_version, software=self.device.software_version)
    async def snapshot(self):
        from huawei_solar import register_names as rn
        fields = {"soc": rn.STORAGE_STATE_OF_CAPACITY,
            "battery_power_w": rn.STORAGE_CHARGE_DISCHARGE_POWER,
            "battery_status": rn.STORAGE_RUNNING_STATUS,
            "max_charge_power_w": rn.STORAGE_MAXIMUM_CHARGE_POWER,
            "ac_charge_enabled": rn.STORAGE_CHARGE_FROM_GRID_FUNCTION}
        values = await asyncio.wait_for(self.device.batch_update(list(fields.values())), 30)
        result = {k: values[v].value for k, v in fields.items()}
        for key in ("soc", "battery_power_w", "max_charge_power_w"):
            if not isinstance(result[key], (int, float)) or not math.isfinite(result[key]):
                raise ValueError(f"Ungültige Huawei-Telemetrie: {key}")
        if not 0 <= result["soc"] <= 100:
            raise ValueError("SOC außerhalb 0–100")
        result["battery_status"] = int(result["battery_status"])
        result["ac_charge_enabled"] = bool(result["ac_charge_enabled"])
        # Optional read-only diagnostics never prevent battery control.
        if not hasattr(self,'_meter_at'):
            try:self._meter_at=float(json.loads(self.meter_sample_path.read_text())['at'])
            except (AttributeError,OSError,ValueError,KeyError,TypeError):self._meter_at=0
        if time.time()-self._meter_at>=300:
            self._meter_at=time.time()
            try:
                if getattr(self,'meter_sample_path',None):write_json(self.meter_sample_path,{'at':self._meter_at})
                fields={'grid_w':rn.POWER_METER_ACTIVE_POWER,'inverter_w':rn.ACTIVE_POWER,
                        'pv_dc_w':rn.INPUT_POWER,'meter_status':rn.METER_STATUS,
                        'import_kwh':rn.GRID_ACCUMULATED_ENERGY,'export_kwh':rn.GRID_EXPORTED_ENERGY,
                        'discharge_limit_w':rn.STORAGE_MAXIMUM_DISCHARGING_POWER}
                values=await asyncio.wait_for(self.device.batch_update(list(fields.values())),8)
                meter={k:values[v].value for k,v in fields.items()}
                meter['meter_status']=int(meter['meter_status'])
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in meter.values()):
                    raise ValueError('Invalid meter data')
                meter['measured_at']=datetime.now(timezone.utc).isoformat()
                meter['house_w']=meter['inverter_w']-meter['grid_w']
                meter['valid']=meter['meter_status']==1 and meter['house_w']>=-50
                result['meter']=meter
            except Exception as exc:
                result['meter']={'valid':False,'error':type(exc).__name__}
        return result
    async def meter_test(self):
        from huawei_solar import register_names as rn
        fields=[('Zählerstatus','METER_STATUS'),('Zählertyp','METER_TYPE'),
                ('Netzleistung','POWER_METER_ACTIVE_POWER'),('Netzeinspeisung Zähler','GRID_EXPORTED_ENERGY'),
                ('Netzbezug Zähler','GRID_ACCUMULATED_ENERGY'),('PV-Eingangsleistung','INPUT_POWER'),
                ('Wechselrichter AC-Leistung','ACTIVE_POWER'),('Ertrag gesamt','ACCUMULATED_YIELD_ENERGY')]
        rows=[]
        for label,name in fields:
            try:
                key=getattr(rn,name)
                values=await asyncio.wait_for(self.device.batch_update([key]),8)
                result=values[key];value=result.value
                if isinstance(value,(int,float)) and not math.isfinite(value):raise ValueError()
                rows.append(dict(label=label,register=name,value=str(value),unit=str(getattr(result,'unit','') or ''),ok=True))
            except Exception as exc:
                rows.append(dict(label=label,register=name,ok=False,error=type(exc).__name__))
        return rows

    async def login(self):
        missing = [label for key, label in (("expected_serial", "Wechselrichter-Seriennummer"), ("password", "Huawei-Installateurpasswort")) if not self.c[key]]
        if missing:
            raise ValueError("Fehlt in den Einstellungen: " + ", ".join(missing))
        await asyncio.wait_for(self.device.login(self.c["username"], self.c["password"]), 30)
    async def write(self, name, value):
        from huawei_solar import register_names as rn
        allowed = {rn.STORAGE_MAXIMUM_DISCHARGING_POWER, rn.STORAGE_FORCIBLE_CHARGE_POWER,
                   rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
                   rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
                   rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE}
        if name not in allowed:
            raise ValueError("Schreibzugriff auf dieses Register nicht erlaubt")
        if not await asyncio.wait_for(self.device.set(name, value), 15):
            raise RuntimeError("Huawei hat den Schreibbefehl nicht bestätigt")
    async def charge(self, watts, minutes):
        from huawei_solar import register_names as rn, register_values as rv
        if not 1 <= minutes <= 2 or not 200 <= watts <= 5000:
            raise ValueError("Ladeauftrag außerhalb der Paketgrenzen")
        # Duration is written BEFORE start. No unbounded SOC-only commands.
        await self.write(rn.STORAGE_FORCIBLE_CHARGE_POWER, watts)
        await self.write(rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD, minutes)
        await self.write(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, rv.StorageForcibleChargeDischargeTargetMode.TIME)
        await self.write(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE, rv.StorageForcibleChargeDischarge.CHARGE)
    async def stop_charge(self):
        from huawei_solar import register_names as rn, register_values as rv
        await self.write(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE, rv.StorageForcibleChargeDischarge.STOP)
    async def close(self):
        if self.device:
            await self.device.stop()
        elif self.client:
            await self.client.disconnect()

async def operate(args, c, folder):
    if args.command == "charge":
        c = {**c, "_manual": True, "mode": "auto"}
    if args.command in ("prices", "plan"):
        prices = await asyncio.to_thread(cached_prices, c, folder)
        if args.command == "plan":
            emit("plan", **economics_plan(c, prices, datetime.now(timezone.utc)))
        else:
            emit("prices", slots=prices)
        return
    if c.get("wifi_enabled"):
        from wifi import check_app
        await asyncio.to_thread(check_app, c["host"])
    hw = Huawei(c)
    hw.meter_sample_path=folder/"meter-sample-at.json"
    pending = folder / "pending-charge.json"
    commissioned = folder / "commissioned.json"
    status_path = folder / "status.json"
    own_charge = False
    live = args.execute and (args.command != "run" or c["mode"] == "auto")
    if args.command in ("charge-test", "stop", "discharge-sync") and not args.execute:
        raise ValueError("Für diesen ausdrücklich gewünschten Schreibtest --execute ergänzen")
    if args.command in ("run", "charge") and c["mode"] == "auto" and not args.execute:
        raise ValueError("Automatik zusätzlich mit --execute starten")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    try:
        await hw.connect()
        if args.command == "meter-test":
            emit("meter_test", rows=await hw.meter_test())
            return
        if args.command == "discharge-sync":
            from discharge import sync
            await hw.login()
            await asyncio.wait_for(sync(hw,folder),60)
            from discharge import read as read_discharge
            emit("discharge_synced",discharge_confirmation=read_discharge(folder/"discharge-status.json"))
            return
        if args.command == "stop":
            await hw.login()
            await hw.stop_charge()
            pending.unlink(missing_ok=True)
            emit("stopped")
            return
        initial = await hw.snapshot()
        emit("snapshot", **initial)
        if args.command in ("probe", "sample"):
            write_json(folder / "device.json", {"serial": hw.device.serial_number, "model": hw.device.model_name, "time": datetime.now(timezone.utc).isoformat(), **initial})
            return
        if live:
            await hw.login()
        if pending.exists():
            if live:
                await hw.stop_charge()
                pending.unlink()
                emit("recovered_previous_charge")
            else:
                raise RuntimeError("Unbestätigter früherer Ladeauftrag: zuerst stop --execute ausführen")
        if args.command == "charge-test":
            commissioned.unlink(missing_ok=True)
            if initial["soc"] >= c["target_soc"] or not initial["ac_charge_enabled"] or initial["battery_status"] not in (1, 2, 4):
                raise ValueError("SOC/AC-Freigabe/Batteriestatus erlaubt keinen Test")
            watts = min(1000, c["charge_power_w"], int(initial["max_charge_power_w"]))
            write_json(pending, {"serial": hw.device.serial_number, "purpose": "test"})
            own_charge = True
            await asyncio.wait_for(hw.charge(watts, 2), 60)
            emit("test_started", watts=watts, max_minutes=2)
            positive_samples = 0
            for _ in range(12):
                try:
                    await asyncio.wait_for(stop_event.wait(), 10)
                    break
                except TimeoutError:
                    pass
                sample = await hw.snapshot()
                emit("test_sample", **sample)
                if sample["battery_power_w"] > watts * 1.25 + 100:
                    raise RuntimeError("Ladeleistung über Testlimit; keine Automatikfreigabe")
                if sample["soc"] >= c["target_soc"]:
                    break
                positive_samples += sample["battery_power_w"] > 100
            await hw.stop_charge()
            own_charge = False
            pending.unlink(missing_ok=True)
            if positive_samples < 2 or stop_event.is_set():
                raise RuntimeError("Test nicht bestätigt; keine Automatikfreigabe erzeugt")
            write_json(commissioned, {"serial": hw.device.serial_number, "tested_at": datetime.now(timezone.utc).isoformat()})
            emit("test_passed", note="Ladeleistung erkannt und Stopp bestätigt; Netzbezug separat prüfen")
            return
        if live:
            if not commissioned.exists() or json.loads(commissioned.read_text())["serial"] != hw.device.serial_number:
                raise ValueError("Erst charge-test --execute erfolgreich durchführen")
        prices, fetched, attempted = [], 0.0, -300.0
        deadline, session_start = 0.0, None
        no_charge_samples = 0
        while not stop_event.is_set():
            fresh,changed=runtime_settings(c,getattr(args,'config',folder/'config.json'),getattr(args,'target_soc',None))
            if changed:
                # End the old finite command before applying different power/limits.
                # Preserve the session clock and external manual discharge request.
                if own_charge and changed-PASSIVE_KEYS:
                    await hw.stop_charge()
                    own_charge=False;deadline=0
                    pending.unlink(missing_ok=True)
                    emit('stopped',reason='Einstellungen werden übernommen')
                if changed & {'tibber_token','tibber_home_id'}:
                    prices=[];attempted=-300.0
                c=fresh;hw.c=c
                emit('settings_applied',fields=sorted(changed))
            mono = time.monotonic()
            if not c.get("_manual") and mono - attempted >= 300:
                attempted = mono
                from pv import refresh as refresh_pv
                await asyncio.to_thread(refresh_pv,c,folder)
                try:
                    prices = await asyncio.to_thread(cached_prices, c, folder)
                    fetched = time.monotonic()
                except Exception as exc:
                    prices = []
                    emit("price_error", error_type=type(exc).__name__)
            if c.get("wifi_enabled"):
                await asyncio.to_thread(check_app, c["host"])
            snapshot = await hw.snapshot()
            now = datetime.now(timezone.utc)
            from pv import attach as attach_pv
            if not c.get("_manual"):c=attach_pv(c,folder,now)
            from discharge import read as read_discharge
            request=read_discharge(folder/'discharge-request.json')
            c['_hold_until']=datetime.fromisoformat(request['until']) if request.get('until') else None
            prior=read_discharge(folder/'discharge-status.json')
            c['_guard_held']=bool(prior.get('locked') and prior.get('source')=='smart')
            eligible, reason, slot = decide(c, snapshot, prices, now)
            from dispatch import plan as discharge_plan
            dispatch=discharge_plan({**c,'charge_power_w':min(c['charge_power_w'],snapshot.get('max_charge_power_w',c['charge_power_w']))},prices,now,snapshot['soc'],c.get('_hold_until')) if not c.get('_manual') else None
            if live:
                from discharge import sync
                await asyncio.wait_for(sync(hw,folder,smart_hold=bool(dispatch and dispatch['hold'])),60)
            state = {"time": now.isoformat(), "live": live, **snapshot,
                     "app_charging": bool(live and own_charge), "dispatch": dispatch,
                     "economics": economics_plan(c, prices, now),
                     "price_ct_kwh": slot["ct"] if slot else None, "eligible": eligible, "reason": reason}
            write_json(status_path, state)
            from audit import CONFIG_KEYS
            emit("decision", **state, diagnostic_inputs={k:c.get(k) for k in CONFIG_KEYS}, diagnostic_plan=c.get('_diagnostic_plan',{}),
                 diagnostic_pv=c.get('_pv',{}),
                 discharge_confirmation=read_discharge(folder/'discharge-status.json') if live else {})
            if c.get("_manual") and snapshot["soc"] >= c["target_soc"]:
                emit("target_reached", soc=snapshot["soc"])
                break
            if live:
                if own_charge and snapshot["battery_power_w"] > c["charge_power_w"] * 1.25 + 100:
                    raise RuntimeError("Ladeleistung überschreitet Vorgabe; mögliche Fremdsteuerung")
                if own_charge and session_start and time.monotonic() - session_start > 60:
                    no_charge_samples = no_charge_samples + 1 if snapshot["battery_power_w"] <= 100 else 0
                    if no_charge_samples >= 6:
                        raise RuntimeError("Keine anhaltende Ladeleistung: mögliche Fremdsteuerung; Automatik beendet")
                if session_start and time.monotonic() - session_start >= c["max_session_minutes"] * 60:
                    raise RuntimeError("Maximale Sitzungslänge erreicht; Einstellungen prüfen und Dienst manuell neu starten")
                if eligible:
                    if time.monotonic() >= deadline - 30:
                        # Allow 70 seconds for command latency before the interval ends.
                        minutes = min(2, int(((slot["end"] - now).total_seconds() - 70) // 60))
                        watts = min(c["charge_power_w"], int(snapshot["max_charge_power_w"]))
                        write_json(pending, {"serial": hw.device.serial_number, "purpose": "auto", "at": now.isoformat()})
                        own_charge = True
                        await asyncio.wait_for(hw.charge(watts, minutes), 60)
                        deadline = time.monotonic() + minutes * 60
                        session_start = session_start or time.monotonic()
                        emit("charge_command", watts=watts, minutes=minutes)
                elif own_charge:
                    await hw.stop_charge()
                    own_charge = False
                    pending.unlink(missing_ok=True)
                    session_start, deadline, no_charge_samples = None, 0, 0
                    emit("stopped", reason=reason)
            try:
                await asyncio.wait_for(stop_event.wait(), 10)
            except TimeoutError:
                pass
    finally:
        if own_charge:
            try:
                await hw.stop_charge()
                pending.unlink(missing_ok=True)
                emit("stopped_on_exit")
            except Exception:
                emit("stop_unconfirmed", note="Lokal prüfen; letzter Auftrag war auf maximal zwei Minuten begrenzt")
        if live and args.command == 'run' and (folder/'discharge-restore.json').exists():
            try:
                from discharge import sync
                await asyncio.wait_for(sync(hw,folder,smart_hold=False),60)
            except Exception:
                emit('stop_unconfirmed',note='Entladesperre: Wiederherstellung ausstehend')
        await hw.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=BASE / "config.json")
    parser.add_argument("command", choices=["setup", "credentials", "wifi-enable", "probe", "prices", "plan", "charge-test", "stop", "run", "charge", "sample", "discharge-sync", "meter-test"])
    parser.add_argument("--execute", action="store_true", help="Schreibzugriff ausdrücklich einschalten")
    parser.add_argument("--target-soc", type=float, help="Temporärer Ziel-SOC nur für charge")
    args = parser.parse_args()
    path = args.config.resolve()
    os.umask(0o077)
    if args.command == "setup":
        if path.exists():
            raise ValueError("config.json existiert bereits; direkt bearbeiten")
        c = dict(DEFAULT)
        c["tibber_token"] = getpass.getpass("Tibber Personal Access Token (verdeckt): ").strip()
        c["password"] = getpass.getpass("Lokales Huawei-Installateurpasswort (verdeckt): ")
        write_json(path, c)
        print("Konfiguration angelegt. Jetzt probe; danach expected_serial eintragen.")
        return
    if path.stat().st_mode & 0o077:
        raise ValueError("Konfiguration enthält Geheimnisse: chmod 600 config.json")
    c = validate({**DEFAULT, **json.loads(path.read_text())})
    if args.target_soc is not None:
        if args.command != "charge":
            raise ValueError("--target-soc nur bei charge erlaubt")
        c["target_soc"] = args.target_soc
        validate(c)
    # A separate status/probe cannot race with a running controller.
    with (path.parent / "controller.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Eine Instanz läuft bereits; Dienst zuerst stoppen") from None
        if args.command == "credentials":
            token = getpass.getpass("Neuer Tibber-Token (verdeckt; Enter behält bisherigen): ").strip()
            if token:
                c["tibber_token"] = token
            write_json(path, c)
            print("Token gespeichert.")
            return
        if args.command == "wifi-enable":
            from wifi import load
            load()
            c["wifi_enabled"] = True
            write_json(path, c)
            print("WLAN-Prüfung aktiviert. Netzwerkdienst separat starten.")
            return
        asyncio.run(operate(args, c, path.parent))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        # Do not log credentials or HTTP request bodies from library exceptions.
        emit("error", error_type=type(exc).__name__, message=str(exc) if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) else "Verbindung/API fehlgeschlagen; Netzwerk, Zugang und Firmware prüfen")
        sys.exit(1)
