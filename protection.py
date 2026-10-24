"""Local-clock EV protection; no EVCC or additional inverter measurements."""
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo


def windows(c,start,end):
    if not c.get('ev_protection_enabled'):return []
    local=start.astimezone(ZoneInfo(c['timezone'])).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=1)
    result=[]
    while local.astimezone(timezone.utc)<end:
        a=local+timedelta(hours=c['ev_start_hour'])
        b=local+timedelta(hours=c['ev_end_hour'])
        if b<=a:b+=timedelta(days=1)
        a,b=a.astimezone(timezone.utc),b.astimezone(timezone.utc)
        if a<end and b>start:result.append((max(a,start),min(b,end)))
        local+=timedelta(days=1)
    return result


def active(c,now):
    return bool(windows(c,now,now+timedelta(seconds=1)))
