"""Explicit, authenticated German postcode lookup; no hardware/config mutations."""
import json
import math
import re
from functools import lru_cache
from urllib.error import HTTPError
from urllib.request import urlopen


def lookup(postcode):
    if not isinstance(postcode,str) or not re.fullmatch(r'[0-9]{5}',postcode.strip()):
        raise ValueError('Bitte eine fünfstellige deutsche PLZ eingeben')
    return list(_lookup(postcode.strip()))


@lru_cache(maxsize=64)
def _lookup(postcode):
    try:
        with urlopen('https://api.zippopotam.us/de/'+postcode,timeout=10) as response:
            data=json.loads(response.read(1_000_000))
        if not isinstance(data,dict) or data.get('error'):raise ValueError('Invalid response')
        return tuple(parse(postcode,data))
    except HTTPError as exc:
        if exc.code==404:return ()
        raise ValueError('PLZ-Suche nicht erreichbar. Bitte später erneut versuchen.') from exc
    except Exception as exc:
        raise ValueError('PLZ-Suche nicht erreichbar. Bitte erneut versuchen oder Koordinaten manuell eintragen.') from exc


def parse(postcode,data):
    if data.get('country abbreviation')!='DE' or data.get('post code')!=postcode:return []
    result=[];seen=set()
    for r in data.get('places',[]):
        if not isinstance(r,dict):continue
        name=r.get('place name');lat=r.get('latitude');lon=r.get('longitude')
        if not isinstance(name,str) or not name or isinstance(lat,bool) or isinstance(lon,bool):continue
        try:lat,lon=float(lat),float(lon)
        except (ValueError,TypeError):continue
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:continue
        label=name[:120]
        if isinstance(r.get('state'),str) and r['state'] and r['state']!=name:label+=' · '+r['state'][:120]
        key=(name,lat,lon)
        if key in seen:continue
        seen.add(key);result.append({'name':label,'latitude':lat,'longitude':lon,'postcode':postcode})
    return result
