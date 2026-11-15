"""Driving requirements only. Does not issue commands or change the energy planner."""
import json
import math
import os
import threading
from datetime import date, time

class CarPlanning:
    def __init__(self, folder):
        self.path=folder/'car-planning.json';self.lock=threading.Lock()
    def read(self):
        try:return json.loads(self.path.read_text())
        except FileNotFoundError:return {'revision':0,'profiles':{},'trips':[]}
    def save(self, data):
        with self.lock:
            old=self.read()
            if data.get('revision')!=old['revision']:raise ValueError('Plan wurde inzwischen geändert. Bitte neu laden.')
            profiles=data.get('profiles',{});trips=data.get('trips',[])
            if not isinstance(profiles,dict) or len(profiles)>10 or not isinstance(trips,list) or len(trips)>200:raise ValueError('Zu viele Fahrzeuge oder Fahrten.')
            def number(value, low, high):
                if isinstance(value,bool):raise ValueError('Ungültiger Zahlenwert')
                n=float(value)
                if not math.isfinite(n) or not low<=n<=high:raise ValueError('Zahlenwert außerhalb des erlaubten Bereichs')
                return n
            cleaned={}
            for key,p in profiles.items():
                if not isinstance(key,str) or not key or len(key)>200 or not isinstance(p,dict):raise ValueError('Ungültiges Fahrzeug')
                cleaned[key]={'name':str(p.get('name',''))[:60], 'consumption':number(p.get('consumption',18),5,60),
                              'capacity':None if p.get('capacity') in (None,'') else number(p['capacity'],5,200),
                              'reserve':number(p.get('reserve',20),0,80)}
            rows=[];ids=set()
            for t in trips:
                if not isinstance(t,dict):raise ValueError('Ungültige Fahrt')
                tid=str(t.get('id',''));vid=str(t.get('vehicle',''))
                if not tid or len(tid)>100 or tid in ids or vid not in cleaned:raise ValueError('Fahrt ohne eindeutiges Fahrzeug / ID')
                ids.add(tid)
                kind=t.get('kind');days=t.get('days',[])
                if kind not in ('once','weekly'):raise ValueError('Ungültige Wiederholung')
                if kind=='weekly' and (not isinstance(days,list) or not days or any(type(d)!=int or d not in range(7) for d in days)):raise ValueError('Wochentage auswählen')
                day=str(t.get('date',''))
                if kind=='once':date.fromisoformat(day)
                dep=str(t.get('departure',''));ret=str(t.get('return',''))
                for value in (dep,ret):
                    if len(value)!=5:raise ValueError('Uhrzeit als HH:MM eingeben')
                    time.fromisoformat(value)
                rows.append({'id':tid,'vehicle':vid,'name':str(t.get('name','Fahrt'))[:80], 'km':number(t.get('km'),0.1,3000),
                             'kind':kind,'days':sorted(set(days)) if kind=='weekly' else [],'date':day if kind=='once' else '',
                             'departure':dep,'return':ret})
            result={'revision':old['revision']+1,'profiles':cleaned,'trips':rows}
            tmp=self.path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as f:json.dump(result,f)
            os.replace(tmp,self.path);return result
