"""Battery-side energy allocation to cheapest eligible tariff intervals."""
import math
from datetime import datetime,timedelta


def plan(c, prices, now, soc, max_power_w=None, hold_until=None):
    from luna import economics_plan
    out = dict(windows=[], soc=soc, target_soc=c['target_soc'],
               capacity_kwh=c['battery_capacity_kwh'], power_w=c['charge_power_w'],
               needed_kwh=None, duration_minutes=None, complete=False, reason='',
               planning_soc=soc,projected=False,projection_complete=False,planned_kwh=0)
    def finish(reason):
        out['reason'] = reason
        return out
    if c['battery_capacity_kwh'] <= 0:
        return finish('Nutzbare Akkukapazität in den Einstellungen eintragen')
    if type(soc) not in (int, float) or not math.isfinite(soc) or not 0 <= soc <= 100:
        return finish('Aktueller Akkustand fehlt; Messung abwarten')
    power = min(c['charge_power_w'], max_power_w) if max_power_w is not None else c['charge_power_w']
    if type(power) not in (int, float) or not math.isfinite(power) or power < 200:
        return finish('Keine nutzbare Ladeleistung verfügbar')
    out['power_w'] = power
    from joint import plan as joint_plan
    joint=joint_plan(c,prices,now,soc,power,hold_until)
    if joint is not None:
        out.update(windows=joint['charges'],needed_kwh=joint['planned_kwh'],
                   duration_minutes=sum((datetime.fromisoformat(w['end'])-datetime.fromisoformat(w['start'])).total_seconds()-130 for w in joint['charges'])/60,
                   planned_kwh=joint['planned_kwh'],complete=True,projected=True,
                   projection_complete=True,planning_soc=joint['planning_soc'],
                   effective_target_soc=joint['morning_soc'],joint=joint,
                   night_start=joint['night_start'],night_end=joint['night_end'])
        if joint['charges']:return finish(joint['reason'])
        known=[p['ct'] for p in prices if p['end']>now and p['start']<datetime.fromisoformat(joint['plan_end'])]
        if known and min(known)>c['max_buy_ct_kwh']:
            from diagnosis import fmt
            return finish(f"Keine Netzladung: günstigster bekannter Preis {fmt(min(known))} ct/kWh > Kaufgrenze {fmt(c['max_buy_ct_kwh'])} ct/kWh")
        if not joint['night_complete']:return finish('Keine wirtschaftliche Netzladung im bekannten Zeitraum')
        from diagnosis import fmt
        bridge=joint['bridge']
        status='Morgenbedarf gedeckt' if bridge['shortfall_kwh']<.001 else 'Morgenbedarf nicht vollständig gedeckt'
        return finish(f"0 kWh Netzladung im bekannten Zeitraum · {status}: erwartet {fmt(joint['morning_soc'])} %, benötigt {fmt(bridge['required_soc'])} % SOC inkl. Puffer/Gerätegrenze · PV-Prognose {fmt(joint['solar']['generation_kwh'])} kWh")
    from dispatch import night_bounds
    start,end=night_bounds(c,now)
    from price_cache import planning_end
    a,b=now,planning_end(prices,now)
    out.update(night_start=start.isoformat(),night_end=end.isoformat(),plan_start=now.isoformat(),plan_end=b.isoformat() if b else None)
    if b is None:return finish('Preislücke · keine verlässliche Planung')
    # Without Smart discharge, retain the configured target. There is no
    # controllable load model with which to promise a reduced PV-based target.
    planning_soc=soc
    pv={'target_soc':c['target_soc'],'reduction_kwh':0,'applied':False}
    out.update(effective_target_soc=pv['target_soc'])
    need = max(0, pv['target_soc'] - planning_soc) * c['battery_capacity_kwh'] / 100
    idle=c.get('battery_idle_w',0)/1000*max(0,(b-a).total_seconds())/3600
    if not out['projected']:idle+=c.get('battery_idle_w',0)/1000*max(0,(a-now).total_seconds())/3600
    need+=idle
    out['idle_kwh']=idle
    out['needed_kwh'] = need
    out['duration_minutes'] = need / (power / 1000) * 60
    if need <= 0:
        out['complete'] = True
        return finish('PV deckt den geplanten Restbedarf; keine Netzladung nötig' if pv['reduction_kwh']>0 else 'Ziel-SOC erreicht; kein Laden erforderlich')
    rows = sorted((p for p in prices if p['end'] > a and p['start'] < b), key=lambda p: p['start'])
    cursor = a
    for row in rows:
        left, right = max(a, row['start']), min(b, row['end'])
        if left != cursor or right <= left:
            return finish('Preislücke; keine verlässliche Planung')
        cursor = right
    if cursor != b:
        return finish('Bekannter Preiszeitraum unvollständig')
    candidates = []
    for row in rows:
        left, right = max(a, row['start']), min(b, row['end'])
        if (right-left).total_seconds() < 190 or row['ct'] > c['max_buy_ct_kwh']:
            continue
        if economics_plan(c, prices, left)['ok']:
            candidates.append((row['ct'], left, right))
    remaining = need
    for price, left, right in sorted(candidates, key=lambda x: (x[0], x[1])):
        # Reserve command latency and the controller's 130-second end margin.
        available = ((right-left).total_seconds()-130)/3600*power/1000
        energy = min(remaining, available)
        seconds = max(190, math.ceil(energy/(power/1000)*3600)+130)
        end = min(right, left+timedelta(seconds=seconds))
        out['windows'].append(dict(start=left.isoformat(), end=end.isoformat(), ct=price, battery_kwh=energy))
        remaining -= energy
        if remaining < 1e-8:
            break
    out['windows'].sort(key=lambda p: p['start'])
    out['complete'] = remaining < 1e-8
    out['planned_kwh'] = need-max(0,remaining)
    return finish('Günstigste geeignete Abschnitte ausgewählt' if out['complete'] else
                  'Ziel voraussichtlich nicht erreichbar: zu wenig geeignete Ladezeit innerhalb der bekannten Preise und Preisgrenzen')


def planned_economics(c,prices,preview):
    """UI evaluates the selected future purchases, not the price at page-open time."""
    if preview.get('joint'):
        return preview['joint'].get('economics') or {'ok':False,'reason':preview['reason']}
    from datetime import datetime
    from luna import economics_plan
    values=[]
    for w in preview.get('windows',[]):
        e=economics_plan(c,prices,datetime.fromisoformat(w['start']))
        if 'saving_ct_kwh' not in e:return {'ok':False,'reason':'Preisvergleich des Ladeplans unvollständig'}
        values.append((w['battery_kwh'],e))
    total=sum(n for n,e in values)
    if total<=0:return {'ok':False,'reason':preview.get('reason','Kein Netzladeabschnitt geplant')}
    result={k:sum(n*e[k] for n,e in values)/total for k in ('effective_ct_kwh','reference_ct_kwh','saving_ct_kwh')}
    return {**result,'ok':result['saving_ct_kwh']>0 and result['saving_ct_kwh']>=c['min_saving_ct_kwh'],
            'reason':'Preisvergleich der geplanten Ladeabschnitte'+(' · Teilplan' if not preview.get('complete') else ''),
            'window_start':values[0][1]['window_start'],'window_end':values[-1][1]['window_end']}
