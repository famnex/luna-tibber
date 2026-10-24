"""Persistent restore journal for a temporary maximum-discharge-power limit."""
import json
from datetime import datetime, timezone
from huawei_solar import register_names as rn
from luna import write_json


def read(path):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return {}


async def sync(hw, folder, now=None, smart_hold=False):
    now=now or datetime.now(timezone.utc)
    request=read(folder/'discharge-request.json')
    journal=folder/'discharge-restore.json'
    saved=read(journal)
    manual=bool(request.get('until') and datetime.fromisoformat(request['until'])>now)
    active=manual or smart_hold
    if not active and not saved:return
    serial=hw.device.serial_number
    if (manual and request['serial']!=serial) or (saved and saved['serial']!=serial):
        raise ValueError('Entladesperre: Seriennummer weicht ab; Wiederherstellung nicht ausgeführt')
    async def value():
        result=await hw.device.batch_update([rn.STORAGE_MAXIMUM_DISCHARGING_POWER])
        v=result[rn.STORAGE_MAXIMUM_DISCHARGING_POWER].value
        if type(v) not in (int,float) or not 0<=v<=10000 or int(v)!=v:
            raise ValueError('Ungültige maximale Entladeleistung')
        return int(v)
    if saved and (type(saved.get('original_w')) is not int or not 0<saved['original_w']<=10000):
        raise ValueError('Ungültiger gesicherter Entladeleistungswert')
    current=await value()
    if active:
        if not saved:
            if current==0:raise ValueError('Entladung bereits extern gesperrt; Originalwert unbekannt')
            saved={'serial':serial,'original_w':current}
            write_json(journal,saved)  # Persist before any inverter change.
        elif current not in (0,saved['original_w']) or (current!=0 and read(folder/'discharge-status.json').get('locked')):
            raise ValueError('Fremde Änderung der Entladeleistung erkannt; keine Überschreibung')
        desired=0
    else:
        desired=saved['original_w']
        if current not in (0,desired):
            raise ValueError('Fremde Änderung der Entladeleistung; Wiederherstellung ausstehend')
    if current!=desired:
        await hw.write(rn.STORAGE_MAXIMUM_DISCHARGING_POWER,desired)
    if await value()!=desired:
        raise RuntimeError('Entladeleistung nicht bestätigt; Wiederherstellung bleibt vorgemerkt')
    write_json(folder/'discharge-status.json',{'locked':active,'source':'manual' if manual else 'smart' if active else None,'until':request.get('until') if manual else None,'time':now.isoformat(),'power_w':desired})
    if not active:journal.unlink()
