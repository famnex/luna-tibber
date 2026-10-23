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
    "max_session_minutes": 120,
    "roundtrip_efficiency": 0.85, "wear_ct_kwh": 0.0, "min_saving_ct_kwh": 2.0,
    "use_start_hour": 6, "use_end_hour": 9, "timezone": "Europe/Berlin",
}
QUERY = '''{ viewer { homes { id appNickname currentSubscription {
 priceInfo(resolution: QUARTER_HOURLY) {
 today { total startsAt currency } tomorrow { total startsAt currency }
 } } } } }'''

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
    for key, low, high in [("target_soc", 10, 95), ("charge_power_w", 200, 5000),
                            ("roundtrip_efficiency", 0.5, 1), ("wear_ct_kwh", 0, 100),
                            ("min_saving_ct_kwh", 0, 100), ("max_buy_ct_kwh", -100, 100), ("max_session_minutes", 2, 240)]:
        value = c[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Ungültiger Wert: {key} (Bereich {low} bis {high})")
    if c["mode"] not in ("monitor", "auto"):
        raise ValueError("mode muss monitor oder auto sein")
    for key, low, high in [("port", 1, 65535), ("unit_id", 0, 247)]:
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError(f"Ungültig: {key}")
    if type(c["charge_power_w"]) is not int:
        raise ValueError("charge_power_w muss ganzzahlig sein")
    ZoneInfo(c["timezone"])
    if not (type(c["use_start_hour"]) is int and type(c["use_end_hour"]) is int
            and 0 <= c["use_start_hour"] < c["use_end_hour"] <= 24):
        raise ValueError("Verbrauchsfenster: ganzzahlige Stunden 0 <= Start < Ende <= 24")
    return c

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
    """Conservative price filter for an explicitly assumed consumption window."""
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
    reference = min(p["ct"] for p in future)
    effective = current["ct"] / c["roundtrip_efficiency"] + c["wear_ct_kwh"]
    saving = reference - effective
    ok = saving > 0 and saving >= c["min_saving_ct_kwh"]
    return {"ok": ok, "reason": "Preisvorteil nach Verlusten ausreichend" if ok else "Preisvorteil nach Verlusten zu klein",
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "reference_ct_kwh": reference, "effective_ct_kwh": effective,
            "saving_ct_kwh": saving, "assumption": "Strom ersetzt Netzbezug im konfigurierten Verbrauchsfenster"}

def decide(c, snapshot, prices, now):
    slot = next((p for p in prices if p["start"] <= now < p["end"]), None)
    if slot is None:
        return False, "Kein gültiger aktueller Preis", None
    if snapshot["soc"] >= c["target_soc"]:
        return False, "Ziel-SOC erreicht", slot
    if snapshot["battery_status"] not in (1, 2, 4):
        return False, "Batterie offline oder gestört", slot
    if not snapshot["ac_charge_enabled"]:
        return False, "Von AC-Seite laden ist deaktiviert", slot
    if slot["ct"] > c["max_buy_ct_kwh"]:
        return False, "Preis oberhalb Kaufgrenze", slot
    if (slot["end"] - now).total_seconds() < 130:
        return False, "Preisintervall endet in weniger als 130 Sekunden", slot
    plan = economics_plan(c, prices, now)
    return plan["ok"], plan["reason"], slot

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
        return result
    async def login(self):
        if not self.c["expected_serial"] or not self.c["password"]:
            raise ValueError("Vor Schreibzugriff expected_serial und password lokal setzen")
        await asyncio.wait_for(self.device.login(self.c["username"], self.c["password"]), 30)
    async def write(self, name, value):
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
    if args.command in ("prices", "plan"):
        prices = await asyncio.to_thread(fetch_prices, c)
        if args.command == "plan":
            emit("plan", **economics_plan(c, prices, datetime.now(timezone.utc)))
        else:
            emit("prices", slots=prices)
        return
    hw = Huawei(c)
    pending = folder / "pending-charge.json"
    commissioned = folder / "commissioned.json"
    status_path = folder / "status.json"
    own_charge = False
    live = args.execute and (args.command != "run" or c["mode"] == "auto")
    if args.command in ("charge-test", "stop") and not args.execute:
        raise ValueError("Für diesen ausdrücklich gewünschten Schreibtest --execute ergänzen")
    if args.command == "run" and c["mode"] == "auto" and not args.execute:
        raise ValueError("Automatik zusätzlich mit --execute starten")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)
    try:
        await hw.connect()
        if args.command == "stop":
            await hw.login()
            await hw.stop_charge()
            pending.unlink(missing_ok=True)
            emit("stopped")
            return
        initial = await hw.snapshot()
        emit("snapshot", **initial)
        if args.command == "probe":
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
            for _ in range(6):
                try:
                    await asyncio.wait_for(stop_event.wait(), 20)
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
            mono = time.monotonic()
            if mono - attempted >= 300:
                attempted = mono
                try:
                    prices = await asyncio.to_thread(fetch_prices, c)
                    fetched = time.monotonic()
                except Exception as exc:
                    prices = []
                    emit("price_error", error_type=type(exc).__name__)
            snapshot = await hw.snapshot()
            now = datetime.now(timezone.utc)
            eligible, reason, slot = decide(c, snapshot, prices if time.monotonic() - fetched < 600 else [], now)
            state = {"time": now.isoformat(), "live": live, **snapshot,
                     "economics": economics_plan(c, prices, now),
                     "price_ct_kwh": slot["ct"] if slot else None, "eligible": eligible, "reason": reason}
            write_json(status_path, state)
            emit("decision", **state)
            if live:
                if own_charge and snapshot["battery_power_w"] > c["charge_power_w"] * 1.25 + 100:
                    raise RuntimeError("Ladeleistung überschreitet Vorgabe; mögliche Fremdsteuerung")
                if own_charge and session_start and time.monotonic() - session_start > 60:
                    no_charge_samples = no_charge_samples + 1 if snapshot["battery_power_w"] <= 100 else 0
                    if no_charge_samples >= 3:
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
                await asyncio.wait_for(stop_event.wait(), 20)
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
        await hw.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=BASE / "config.json")
    parser.add_argument("command", choices=["setup", "probe", "prices", "plan", "charge-test", "stop", "run"])
    parser.add_argument("--execute", action="store_true", help="Schreibzugriff ausdrücklich einschalten")
    args = parser.parse_args()
    path = args.config.resolve()
    os.umask(0o077)
    if args.command == "setup":
        if path.exists():
            raise ValueError("config.json existiert bereits; direkt bearbeiten")
        c = dict(DEFAULT)
        c["tibber_token"] = getpass.getpass("Tibber Personal Access Token (verdeckt): ")
        c["password"] = getpass.getpass("Lokales Huawei-Installateurpasswort (verdeckt): ")
        write_json(path, c)
        print("Konfiguration angelegt. Jetzt probe; danach expected_serial eintragen.")
        return
    if path.stat().st_mode & 0o077:
        raise ValueError("Konfiguration enthält Geheimnisse: chmod 600 config.json")
    c = validate({**DEFAULT, **json.loads(path.read_text())})
    # A separate status/probe cannot race with a running controller.
    with (path.parent / "controller.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Eine Instanz läuft bereits; Dienst zuerst stoppen") from None
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
