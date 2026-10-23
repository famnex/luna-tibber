"""Shared, account-bound Tibber cache. Only dated prices, never credentials."""
import fcntl
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TTL = 300
MAX_AGE = 86400

def get(c, folder, fetch, now=None):
    now = now or datetime.now(timezone.utc)
    folder = Path(folder)
    key = hashlib.sha256(json.dumps([c['tibber_token'],c['tibber_home_id']]).encode()).hexdigest()
    path = folder/'tibber-prices.json'
    with (folder/'tibber-prices.lock').open('a') as lock:
        os.chmod(lock.name,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX)
        rows,stamp,attempt = [],0,0
        try:
            data=json.loads(path.read_text())
            if data['key']==key and 0<=now.timestamp()-data['fetched_at']<=MAX_AGE:
                stamp=data['fetched_at'];attempt=data.get('attempted_at',stamp)
                for row in data['prices']:
                    start,end=datetime.fromisoformat(row['start']),datetime.fromisoformat(row['end'])
                    if start.tzinfo is None or end.tzinfo is None or end<=start or not math.isfinite(row['ct']):
                        raise ValueError('Invalid cached price')
                    if end>now:rows.append({'start':start,'end':end,'ct':row['ct']})
        except (OSError,ValueError,KeyError,TypeError):
            rows,stamp,attempt=[],0,0
        if rows and 0<=now.timestamp()-attempt<TTL:
            return rows,stamp,now.timestamp()-stamp>=TTL
        fallback=False
        try:
            prices=fetch(c)
            if not prices:raise ValueError('Keine Tibber-Preise')
            rows,stamp=prices,now.timestamp()
        except Exception:
            if not rows:raise
            fallback=True
        data={'key':key,'fetched_at':stamp,'attempted_at':now.timestamp(),'prices':rows}
        fd,tmp=tempfile.mkstemp(prefix='.tibber-',dir=folder)
        try:
            with os.fdopen(fd,'w') as out:json.dump(data,out,default=lambda v:v.isoformat())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return rows,stamp,fallback
