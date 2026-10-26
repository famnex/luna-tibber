"""Read-only plan explanations and sampled measured/forecast comparison.

House AC = inverter AC - meter power (Huawei export-positive convention).
No automatic adjustment: EV/heat-pump loads cannot be separated by one meter.
"""
import math
from datetime import datetime,timezone
from zoneinfo import ZoneInfo


def finite(x):return type(x) in (int,float) and math.isfinite(x)
def fmt(x):return f'{x:.2f}'.replace('.',',')


def plan_change(old,new):
    if not old:return None
    a,b=old['joint'],new['joint']
    # Compare the same target night, not a rolling switch to the following day.
    if a.get('night_end')!=b.get('night_end'):return None
    ac,bc=a.get('planned_kwh',0),b.get('planned_kwh',0)
    ap,bp=(a.get('solar') or {}).get('generation_kwh'),(b.get('solar') or {}).get('generation_kwh')
    changed=[]
    if finite(ap) and finite(bp) and abs(ap-bp)>=.05:
        changed.append(f'PV-Prognose {fmt(ap)} → {fmt(bp)} kWh')
    if old['config']!=new['config']:changed.append('Einstellungen geändert')
    if old['prices_hash']!=new['prices_hash']:changed.append('Preisdaten geändert')
    if finite(old['soc']) and finite(new['soc']) and old['soc']!=new['soc']:
        changed.append(f'SOC {fmt(old["soc"])} → {fmt(new["soc"])} %')
    if not changed or (abs(ac-bc)<.1 and bool(a.get('guard',{}).get('hold'))==bool(b.get('guard',{}).get('hold'))):return None
    bridge=b.get('bridge') or {}
    text='Neu berechnet: '+ '; '.join(changed)+f'. Netzladung {fmt(ac)} → {fmt(bc)} kWh.'
    if finite(b.get('morning_soc')) and finite(bridge.get('required_soc')):
        text+=f' Am Nachtende erwartet {fmt(b["morning_soc"])} %, morgens benötigt {fmt(bridge["required_soc"])} % inklusive Puffer und Gerätegrenze.'
    text+=' Entladung '+('gesperrt.' if b.get('guard',{}).get('hold') else 'freigegeben.')
    return text


def sample_context(c,pv,stamp):
    local=datetime.fromtimestamp(stamp,timezone.utc).astimezone(ZoneInfo(c.get('timezone') or 'Europe/Berlin'))
    a,b=c.get('extra_load_start_hour',17),c.get('extra_load_end_hour',19)
    a=17 if a is None else a;b=19 if b is None else b
    evening=a<=local.hour+local.minute/60<b
    base=c.get('base_load_w');extra=c.get('extra_load_kwh') or 0
    load=(base+extra*1000/(b-a) if evening and b>a else base) if finite(base) else None
    forecast=None
    for r in pv.get('rows',[]):
        try:
            left=datetime.fromisoformat(str(r['start'])).timestamp();right=datetime.fromisoformat(str(r['end'])).timestamp()
            if left<=stamp<right:forecast=r['kw']*1000;break
        except (ValueError,KeyError,TypeError):continue
    return {'load_w':load,'base_w':base,'evening':evening,'pv_forecast_w':forecast,
            'capacity_kwh':c.get('battery_capacity_kwh'),'date':local.date().isoformat(),
            'extra_load_kwh':extra,'extra_hours':b-a,'pv_factor':c.get('pv_factor'),'battery_idle_w':c.get('battery_idle_w')}


def summarize(rows,hours,config=None):
    config=config or {}
    series=[];soc_series={};dates=set();contexts=[]
    totals={key:{'actual_kwh':0.,'planned_kwh':0.,'hours':0.} for key in ('house','outside_evening','evening','pv')}
    previous=None;valid=0;invalid=0;limits=[];spans=[];span=None
    for stamp,d in rows:
        soc,power=d.get('soc'),d.get('battery_power_w')
        confirmation=d.get('discharge_confirmation') or {}
        if finite(soc) and finite(power):
            soc_series[int(stamp//60)]={'time':stamp,'soc':soc}
            locked=confirmation.get('locked') is True
            # A decision contains telemetry read BEFORE sync. Do not attribute
            # the pre-command power to the subsequently confirmed hold.
            try:
                if datetime.fromisoformat(confirmation['time']).timestamp()>stamp:locked=False
            except (ValueError,KeyError,TypeError):pass
            if locked:
                if span is None or stamp-span['end']>120:
                    if span:spans.append(span)
                    span={'start':stamp,'end':stamp,'start_soc':soc,'end_soc':soc,'samples':0,'max_discharge_w':0.,'reported_discharge_kwh':0.}
                dt=stamp-span['end']
                span['reported_discharge_kwh']+=max(0,-power)*dt/3600000
                span.update(end=stamp,end_soc=soc,samples=span['samples']+1,max_discharge_w=max(span['max_discharge_w'],max(0,-power)))
            elif span:
                spans.append(span);span=None
        m=d.get('meter')
        if not m:continue
        if not m.get('valid') or not all(finite(m.get(k)) for k in ('house_w','pv_dc_w')):
            invalid+=1;series.append({'time':stamp,'house_w':None,'pv_dc_w':None,'load_w':None,'pv_forecast_w':None});previous=None;continue
        valid+=1
        try:
            confirmed_at=datetime.fromisoformat(confirmation['time']).timestamp()
            measured_at=datetime.fromisoformat(m['measured_at']).timestamp()
            confirmed_before_read=confirmed_at<=measured_at
        except (ValueError,KeyError,TypeError):confirmed_before_read=False
        if confirmed_before_read and confirmation.get('locked') is True and m.get('discharge_limit_w',0)>0:
            limits.append({'time':stamp,'limit_w':m['discharge_limit_w']})
        context=d.get('measurement_context') or {}
        series.append({'time':stamp,'house_w':max(0,m['house_w']),'pv_dc_w':max(0,m['pv_dc_w']),
                       'load_w':context.get('load_w'),'pv_forecast_w':context.get('pv_forecast_w')})
        contexts.append(context)
        dates.add(context.get('date') or datetime.fromtimestamp(stamp,timezone.utc).astimezone(ZoneInfo(config.get('timezone','Europe/Berlin'))).date().isoformat())
        if previous:
            t,p,pc=previous;dt=(stamp-t)/3600
            # Never fill gaps or aggregate across changed assumptions / load windows.
            if 0<dt<=10/60 and context.get('evening')==pc.get('evening'):
                for key,actual,planned in [('house','house_w','load_w'),('evening' if context.get('evening') else 'outside_evening','house_w','load_w'),('pv','pv_dc_w','pv_forecast_w')]:
                    if all(finite(v) for v in (pc.get(planned),context.get(planned))):
                        out=totals[key];out['hours']+=dt
                        out['actual_kwh']+=(max(0,p[actual])+max(0,m[actual]))/2*dt/1000
                        out['planned_kwh']+=(pc[planned]+context[planned])/2*dt/1000
        previous=(stamp,m,context)
    if span:spans.append(span)
    for out in totals.values():
        out['difference_pct']=(out['actual_kwh']/out['planned_kwh']-1)*100 if out['planned_kwh']>.01 else None
        out['difference_kwh']=out['actual_kwh']-out['planned_kwh']
        out['actual_mean_w']=out['actual_kwh']*1000/out['hours'] if out['hours'] else None
        out['planned_mean_w']=out['planned_kwh']*1000/out['hours'] if out['hours'] else None
    spans=[{**s,'soc_drop':s['start_soc']-s['end_soc']} for s in spans if s['samples']>=2 and s['end']-s['start']>=60]
    advice=recommendations(totals,contexts,dates,config)
    return {'series':series,'soc_series':list(soc_series.values()),'recommendations':advice,'tolerance_pct':config.get('diagnosis_tolerance_pct',10),'totals':totals,'valid_samples':valid,'invalid_samples':invalid,'requested_hours':hours,
            'hold_spans':spans[-30:],'limit_mismatches':limits[-30:]}


def recommendations(totals,contexts,dates,c):
    tolerance=c.get('diagnosis_tolerance_pct',10)
    result=[]
    def add(title,text,key,level='info'):
        result.append(dict(title=title,text=text,setting=key,level=level))
    outside=totals['outside_evening'];diff=outside['difference_pct']
    stable=all(x.get('base_w')==c.get('base_load_w') for x in contexts)
    if diff is not None and abs(diff)<=tolerance:
        add('Grundverbrauch vorerst beibehalten',f"Ø {fmt(outside['actual_mean_w'])} W statt {fmt(outside['planned_mean_w'])} W ({diff:+.1f} %). Innerhalb der eingestellten ±{tolerance:g} %. Bisher {fmt(outside['hours'])} h erfasst.",'base_load_w','ok')
    elif diff is None or outside['hours']<12 or len(dates)<2 or not stable:
        add('Grundverbrauch: weitere Daten sammeln','Für einen Zahlenvorschlag mindestens 12 erfasste Stunden an zwei Tagen bei unveränderter Grundlast-Einstellung abwarten. Auto und andere Sonderlasten vorher ausschließen.','base_load_w')
    else:
        suggested=round(outside['actual_mean_w']/10)*10
        add('Grundverbrauch prüfen',f"Abweichung {diff:+.1f} %. Rechnerischer Vergleichswert: {suggested} W (aktuell {c.get('base_load_w',0):g} W). Nur übernehmen, wenn Auto und andere Sonderlasten nicht enthalten sind; dies ist keine isolierte Grundlastmessung.",'base_load_w','review')
    evening=totals['evening']
    if evening['hours']<3 or len(dates)<2:
        add('Abendbedarf noch nicht bewertbar','Mindestens zwei weitgehend erfasste Abendfenster vergleichen. Den Zusatzbedarf nicht aus einer kurzen Kochspitze hochrechnen.','extra_load_kwh')
    else:
        add('Abendfenster vergleichen',f"{fmt(evening['actual_kwh'])} kWh gemessen gegenüber {fmt(evening['planned_kwh'])} kWh geplant über {fmt(evening['hours'])} h. Bei wiederholter Mehrlast zuerst Uhrzeiten und dann täglichen Zusatzverbrauch prüfen. Auto und andere Verbraucher zählen mit.",'extra_load_kwh','review')
    pv=totals['pv']
    add('PV-Faktor nicht aus DC-Werten kalibrieren',f"Aktueller Faktor {c.get('pv_factor',.7):g}: 0,7 bedeutet 30 % Abschlag. DC-Messung und AC-Prognose sind nicht direkt gleichwertig; deshalb kein automatischer Prozentvorschlag aus dieser Differenz. Mehrtägig Zeitpunkt und Tagesverlauf prüfen.",'pv_factor')
    add('Morgenpuffer getrennt einstellen',f"Aktuell {c.get('morning_buffer_pct',10):g} % Zuschlag auf den erwarteten Hausbedarf bis zur PV-Deckung. Bei wiederkehrender Unterdeckung erhöhen; die PV-Prognose selbst wird dadurch nicht verändert.",'morning_buffer_pct')
    add('Akku-Eigenverbrauch bleibt eine Annahme',f"Aktuell {c.get('battery_idle_w',100):g} W. SOC-Verlust unter Sperre kann auch durch SOC-Korrekturen entstehen. Erst mehrere lange, bestätigte Ruhephasen vergleichen; nicht aus einer einzelnen Nacht nachregeln.",'battery_idle_w')
    return result
