"""Read-only dashboard history, derived solely from the existing journal."""
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def finite(value):return type(value) in (int,float) and math.isfinite(value)
def epoch(value):
    try:return datetime.fromisoformat(value).timestamp()
    except (ValueError,TypeError):return None


def day_bounds(day,zone,now):
    tz=ZoneInfo(zone);date=datetime.strptime(day,'%Y-%m-%d').date()
    today=datetime.fromtimestamp(now,tz).date()
    if date>today or (today-date).days>6:raise ValueError('Tag außerhalb der letzten sieben Tage')
    start=datetime.combine(date,datetime.min.time(),tz).timestamp()
    end=datetime.combine(date+timedelta(days=1),datetime.min.time(),tz).timestamp()
    return start,end


def charge_source(data,stamp):
    """Only near-simultaneous, valid meter evidence identifies historical supply."""
    meter=data.get('meter') or {};at=epoch(meter.get('measured_at'))
    grid=meter.get('grid_w');solar=meter.get('pv_dc_w')
    if not meter.get('valid') or at is None or abs(stamp-at)>30 or not finite(grid) or not finite(solar):return 'unknown'
    if grid< -100 and 0<=solar<=20:return 'grid'
    if grid>=-20 and solar>100:return 'pv'
    return 'unknown' # Import and PV together do not identify the battery's share.


def summarize(rows,start,end,now):
    end=min(end,now);updates={};soc={};pv={};switches=[];confirmations={}
    for stamp,kind,d in rows:
        if d.get('live') is False:continue
        if kind in ('service_started','controller_exit','error'):
            updates.setdefault(stamp,{}).update(power=None,locked=None)
        c=d.get('discharge_confirmation') or {};confirmed=epoch(c.get('time'))
        # Confirmation may follow telemetry in the same record. Apply at its own time.
        if confirmed is not None and confirmed<=end and type(c.get('locked')) is bool:
            updates.setdefault(max(start-120,confirmed),{})['locked']=c['locked']
        power=d.get('battery_power_w')
        if kind in ('snapshot','decision','test_sample') and finite(power):
            updates.setdefault(stamp,{}).update(power=power,source=charge_source(d,stamp))
        if start<=stamp<=end:
            value=d.get('soc')
            if finite(value) and 0<=value<=100:soc[int(stamp//60)]={'time':stamp,'soc':value}
            meter=d.get('meter') or {};measured=epoch(meter.get('measured_at'))
            if meter.get('valid') and measured is not None and start<=measured<=end and finite(meter.get('pv_dc_w')):
                pv[measured]={'time':measured,'kw':max(0,meter['pv_dc_w'])/1000}
            label={'charge_command':'Ladebefehl gesendet','stopped':'Stopp bestätigt',
                   'stopped_on_exit':'Stopp bestätigt','stop_unconfirmed':'Stopp unbestätigt',
                   'target_reached':'Ladeziel erreicht'}.get(kind)
            if label:switches.append({'time':stamp,'label':label})
        if confirmed is not None and confirmed<=end and type(c.get('locked')) is bool:
            confirmations[confirmed]=c['locked']
    prior=None
    for stamp,locked in sorted(confirmations.items()):
        if locked!=prior and stamp>=start:
            switches.append({'time':stamp,'label':'Entladesperre bestätigt' if locked else 'Entladung freigegeben'})
        prior=locked
    # Bound the last observation: never paint an observed state up to "now" blindly.
    times=sorted(t for t in updates if start-120<=t<=end)
    last=times[-1] if times else start
    boundaries=sorted({start,end,*[t for t in times if t>=start],*[min(end,t+120) for t in times if t>=start-120]})
    power=None;power_at=None;source='unknown';locked=None;confirmation_at=None;lock_changed_at=None;index=0;phases=[]
    for left,right in zip(boundaries,boundaries[1:]):
        while index<len(times) and times[index]<=left:
            t=times[index];u=updates[t];index+=1
            if 'power' in u:power=u['power'];power_at=t;source=u.get('source','unknown')
            if 'locked' in u:
                # A renewed confirmation is not a new control state. Only a
                # real change invalidates telemetry sampled before the change.
                if u['locked']!=locked:lock_changed_at=t
                locked=u['locked'];confirmation_at=t
        fresh=power_at is not None and left-power_at<120 and finite(power) and left<last and (lock_changed_at is None or lock_changed_at<=power_at)
        held=locked is True and left<last and (fresh or (confirmation_at is not None and left-confirmation_at<120))
        action='charge' if fresh and power>100 else 'discharge' if fresh and power< -100 else 'hold' if held else 'idle' if fresh else 'unknown'
        state={'action':action,'locked':held,'source':source if action=='charge' else None}
        if phases and phases[-1]['action']==action and phases[-1]['locked']==held and phases[-1].get('source')==state['source']:phases[-1]['end']=right
        else:phases.append({'start':left,'end':right,**state})
    switches=sorted(switches,key=lambda x:x['time'])
    return {'start':start,'end':end,'phases':phases,'summary':compact_phases(infer_sources(phases,switches)),
            'soc':list(soc.values()),'pv':sorted(pv.values(),key=lambda x:x['time']),
            'switches':switches,'switch_groups':compact_switches(switches),'samples':len(soc)}


def infer_sources(phases,switches=()):
    """Display-only source continuity, bounded to thirty minutes from real evidence.

    No inference across gaps or noncharging phases. A discharge lock does not
    prohibit charging. Allow up to 120 seconds of delayed telemetry after a stop.
    Disagreeing neighboring sources remain unknown. Never chain estimated evidence.
    """
    result=[dict(p) for p in phases]
    stops=[e['time'] for e in switches if e['label'] in ('Stopp bestätigt','Stopp unbestätigt','Ladeziel erreicht')]
    groups=[]
    for i,p in enumerate(phases):
        if p['action']!='charge':continue
        if (groups and groups[-1][-1]==i-1 and phases[i-1]['end']==p['start']):groups[-1].append(i)
        else:groups.append([i])
    for group in groups:
        anchors=[i for i in group if phases[i].get('source') in ('grid','pv')]
        for i in group:
            p=phases[i]
            if p.get('source') in ('grid','pv'):continue
            left=next((a for a in reversed(anchors) if a<i),None)
            right=next((a for a in anchors if a>i),None)
            nearby=[]
            for a in (left,right):
                if a is None:continue
                q=phases[a]
                distance=max(0,p['end']-q['end'],q['start']-p['start'])
                # A stop is a command boundary, not instantaneous meter evidence.
                # Only a preceding anchor can explain a short trailing reading.
                crossed=[t for t in stops if min(p['start'],q['start'])<=t<max(p['end'],q['end'])]
                delayed_tail=all(a<i and q['end']<=t and p['end']<=t+120 for t in crossed)
                if distance<=1800 and delayed_tail:nearby.append(q['source'])
            # Even a distant disagreeing neighbor indicates a possible source change.
            conflict=left is not None and right is not None and phases[left]['source']!=phases[right]['source']
            if nearby and len(set(nearby))==1 and not conflict:
                result[i].update(source=nearby[0],source_estimated=True)
    return result


def compact_phases(phases):
    """Display-only: absorb brief observations between equal stable phases.

    Never bridge missing telemetry, confirmed lock changes or measured discharge
    under a lock. The original observations remain available for diagnosis.
    """
    result=[]
    for p in phases:
        if (result and result[-1]['end']==p['start'] and result[-1]['action']==p['action']
                and result[-1]['locked']==p['locked'] and result[-1].get('source')==p.get('source')):
            result[-1]['end']=p['end']
            result[-1]['source_estimated']=bool(result[-1].get('source_estimated') or p.get('source_estimated'))
            continue
        result.append({**p,'brief_count':0,'brief_seconds':0})
        while len(result)>=3:
            a,b,c=result[-3:]
            if not (a['end']==b['start'] and b['end']==c['start']
                    and a.get('source')==c.get('source') and a['action']==c['action'] and a['locked']==b['locked']==c['locked']
                    and b['end']-b['start']<60
                    and min(a['end']-a['start'],c['end']-c['start'])>=60
                    and all(x['action']!='unknown' for x in (a,b,c))
                    and not (b['action']=='discharge' and b['locked'])
                    and not (b['action']=='charge' and b.get('source')!=a.get('source'))):break
            result[-3:] = [{**a,'end':c['end'],'source_estimated':any(x.get('source_estimated') for x in (a,b,c)),
                'brief_count':a['brief_count']+b['brief_count']+c['brief_count']+1,
                'brief_seconds':a['brief_seconds']+b['end']-b['start']+c['brief_seconds']}]
    return result


def compact_switches(switches):
    """Repeated finite charge commands renew one session; stops remain explicit."""
    result=[]
    for e in switches:
        if (result and e['label']=='Ladebefehl gesendet' and result[-1]['label']==e['label']
                and 0<=e['time']-result[-1]['end']<=180):
            result[-1]['end']=e['time'];result[-1]['count']+=1
        else:result.append({**e,'end':e['time'],'count':1})
    return result
