"""Read-only Tibber Data API probe; credentials never enter status/audit exports."""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit, parse_qs, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SCOPES = 'openid offline_access data-api-user-read data-api-homes-read data-api-vehicles-read'
REDIRECT = 'http://localhost:8099/tibber-callback'

class VehicleProbe:
    def __init__(self, folder):
        self.path = folder / 'vehicle-tibber-private.json'
        self.lock = threading.Lock()
        self.pending = {}
        try:self.cache = json.loads((folder/'vehicle-cache.json').read_text())
        except (OSError, ValueError):self.cache = None
        self.error = ''
        self.last_attempt = 0
        try:
            self.credentials = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.credentials = {}

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(self.credentials, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def status(self):
        return {'connected': bool(self.credentials.get('refresh_token')), 'redirect_uri': REDIRECT,
                'scopes': SCOPES, 'result': self.cache, 'error': self.error}

    def request(self, url, form=None, token=None):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        body = None
        if form is not None:
            body = urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        try:
            with urlopen(Request(url, data=body, headers=headers), timeout=8) as response:
                return json.loads(response.read(2_000_000))
        except HTTPError as exc:
            # Never expose remote response bodies, which may contain credentials.
            messages = {401:'Tibber-Anmeldung abgelaufen. Bitte erneut verbinden.',
                        403:'Tibber verweigert den Zugriff. Fahrzeug-Leserechte prüfen.',
                        429:'Tibber begrenzt die Abfragen. Bitte später erneut versuchen.'}
            raise ValueError(messages.get(exc.code, f'Tibber antwortet mit HTTP {exc.code}.')) from None
        except (URLError, TimeoutError, ValueError):
            raise ValueError('Tibber derzeit nicht erreichbar oder Antwort ungültig.') from None

    def begin(self, data, session):
        client = str(data.get('client_id', '')).strip()
        secret = str(data.get('client_secret', '')).strip()
        if not client or not secret or len(client)>512 or len(secret)>4096:
            raise ValueError('Client-ID und Client-Secret eingeben.')
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(32)
        self.pending = {k:v for k,v in self.pending.items() if v["expires"] > time.time()}
        if len(self.pending)>=10:
            raise ValueError("Zu viele offene Anmeldungen. Bitte zehn Minuten warten.")
        self.pending[state] = dict(client_id=client, client_secret=secret, verifier=verifier,
                            state=state, session=session, expires=time.time()+600)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        return {'url':'https://thewall.tibber.com/connect/authorize?' + urlencode(dict(
            response_type='code', client_id=client, redirect_uri=REDIRECT, scope=SCOPES,
            state=state, code_challenge=challenge, code_challenge_method='S256'))}

    def finish(self, data, session):
        address = str(data.get('callback_url','')).strip()
        if address.startswith('localhost:8099/'):
            address = 'http://' + address
        try:
            url = urlsplit(address)
            valid = (url.scheme == 'http' and url.hostname == 'localhost' and
                     url.port == 8099 and url.path == '/tibber-callback' and
                     url.username is None and url.password is None and not url.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('Adresse ungültig: die vollständige Rückleitung http://localhost:8099/tibber-callback?code=…&state=… einfügen.')
        query = parse_qs(url.query)
        if len(query.get('state',[])) != 1 or len(query.get('code',[])) != 1:
            raise ValueError('Rückleitung unvollständig: genau ein code und ein state werden benötigt. Vollständige Browseradresse kopieren.')
        state = query['state'][0]
        pending = self.pending.get(state)
        if not pending:
            raise ValueError('Diese Rückleitung gehört zu keinem offenen Anmeldelink. Nach Serverneustart oder mit einem alten Link bitte die Anmeldung neu beginnen.')
        if pending['expires'] < time.time():
            self.pending.pop(state, None)
            raise ValueError('Anmeldelink ist älter als zehn Minuten. Bitte neu beginnen.')
        if pending['session'] != session:
            raise ValueError('Anmeldung in einem anderen Browser begonnen. Rückleitung dort einfügen oder hier neu beginnen.')
        code = query.get('code',[''])[0]
        if not code:
            raise ValueError('Kein Anmeldecode vorhanden. Tibber-Freigabe prüfen.')
        self.pending.pop(state, None)
        credentials = {k:pending[k] for k in ('client_id','client_secret')}
        tokens = self.request('https://thewall.tibber.com/connect/token', dict(credentials,
            grant_type='authorization_code',code=code,redirect_uri=REDIRECT,code_verifier=pending['verifier']))
        if not tokens.get('access_token') or not tokens.get('refresh_token'):
            raise ValueError('Tibber hat keine dauerhafte Freigabe geliefert. offline_access aktivieren.')
        self.credentials = dict(credentials, access_token=tokens['access_token'],refresh_token=tokens['refresh_token'],
                                expires=time.time()+float(tokens.get('expires_in',3600)))
        self.save()
        self.cache = None
        (self.path.parent/'vehicle-cache.json').unlink(missing_ok=True)
        self.last_attempt = 0
        return self.status()

    def token(self):
        c = self.credentials
        if not c.get('refresh_token'):
            raise ValueError('Bitte zuerst mit Tibber verbinden.')
        if c.get('expires',0) < time.time()+60:
            tokens = self.request('https://thewall.tibber.com/connect/token', dict(
                grant_type='refresh_token',refresh_token=c['refresh_token'],client_id=c['client_id'],client_secret=c['client_secret']))
            if not tokens.get('access_token'):
                raise ValueError('Tibber-Anmeldung erneuern.')
            c.update(access_token=tokens['access_token'],refresh_token=tokens.get('refresh_token',c['refresh_token']),
                     expires=time.time()+float(tokens.get('expires_in',3600)))
            self.save()
        return c['access_token']

    @staticmethod
    def rows(value, key):
        if isinstance(value,list): return value
        if isinstance(value,dict):
            for name in (key,'data','items'):
                if name in value: return VehicleProbe.rows(value[name],key)
        raise ValueError('Unbekanntes Tibber-Antwortformat. Keine Daten verworfen; API-Format prüfen.')

    def probe(self):
        if time.time()-self.last_attempt < 60:
            if self.cache: return self.cache
            raise ValueError('Bitte eine Minute bis zum nächsten Versuch warten.')
        self.last_attempt = time.time()
        token = self.token()
        base = 'https://data-api.tibber.com/v1/homes'
        homes = self.rows(self.request(base, token=token),'homes')
        devices = []
        seen = set()
        errors = []
        deadline = time.monotonic()+25
        for home in homes[:10]:
            hid = str(home.get('id',''))
            if not hid: continue
            if time.monotonic()>deadline:
                errors.append('Zeitlimit erreicht; Ergebnis unvollständig.'); break
            prefix = base+'/'+quote(hid,safe='')+'/devices'
            for device in self.rows(self.request(prefix,token=token),'devices')[:20]:
                did = str(device.get('id',''))
                if not did or did in seen: continue
                seen.add(did)
                if time.monotonic()>deadline:
                    errors.append('Zeitlimit erreicht; Ergebnis unvollständig.'); break
                try:
                    detail = self.request(prefix+'/'+quote(did,safe=''),token=token)
                    devices.append({'home_id':hid,'device':device,'details':detail})
                except ValueError as exc:
                    devices.append({'home_id':hid,'device':device,'error':str(exc)})
        self.cache = {'fetched_at':time.time(), 'devices':devices, 'warnings':errors,
                      'note':'Abrufzeit ist kein Messzeitpunkt. Angezeigt werden ausschließlich die von Tibber freigegebenen Daten.'}
        self.error = ''
        cache_path = self.path.parent/'vehicle-cache.json'
        tmp = cache_path.with_suffix('.tmp')
        fd = os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(self.cache,f)
        os.replace(tmp,cache_path)
        return self.cache

    def worker(self, closed):
        while not closed.is_set():
            if self.credentials.get('refresh_token'):
                try:self.action('read',{},'background')
                except Exception:self.error = 'Fahrzeugdaten konnten nicht aktualisiert werden. Letzte Werte werden angezeigt.'
            closed.wait(300)

    def action(self, action, data, session):
        if not self.lock.acquire(blocking=False):
            raise ValueError('Tibber-Abfrage läuft bereits. Bitte kurz warten.')
        try:
            if action=='begin': return self.begin(data,session)
            if action=='finish': return self.finish(data,session)
            if action=='read': return self.probe()
            if action=='disconnect':
                self.credentials={};self.pending={};self.cache=None;self.last_attempt=0
                self.path.unlink(missing_ok=True)
                (self.path.parent/'vehicle-cache.json').unlink(missing_ok=True)
                self.error = ''
                return self.status()
            raise ValueError('Unbekannte Fahrzeugaktion')
        finally:
            self.lock.release()
