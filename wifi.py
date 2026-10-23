#!/usr/bin/env python3
"""NetworkManager connector, Python 3.9+, independent of charging credentials."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

STATE = Path('/etc/luna-wifi.json')
PROFILE = Path('/etc/NetworkManager/system-connections/luna-huawei.nmconnection')
BOOT = Path('/proc/sys/kernel/random/boot_id')

class Conflict(RuntimeError):
    pass

def command(*args):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=50,
                           env={**os.environ, 'LC_ALL': 'C'})
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Netzwerkwerkzeug fehlt oder Zeitüberschreitung: ' + args[0]) from None
    if p.returncode:
        # Do not echo command arguments or NetworkManager output (may contain secrets).
        raise RuntimeError('Netzwerkbefehl fehlgeschlagen: ' + args[0])
    return p.stdout.strip()

def active(service):
    return subprocess.run(['systemctl', 'is-active', '--quiet', service],
                          timeout=10).returncode == 0

def nm(field, *args):
    return command('nmcli', '-g', field, *args)

def write(path, content, mode=0o600):
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'w') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)

def escape(value):
    if '\n' in value or '\r' in value or '\x00' in value:
        raise ValueError('Zeilenumbrüche/NUL sind nicht erlaubt')
    return value.replace('\\', '\\\\').replace(' ', '\\s').replace('\t', '\\t')

def profile_text(c, password):
    return '''[connection]
id=luna-huawei
uuid={uuid}
type=wifi
interface-name={interface}
autoconnect=false

[wifi]
mode=infrastructure
ssid={ssid}

[wifi-security]
key-mgmt=wpa-psk
psk={password}

[ipv4]
method=auto
never-default=true
ignore-auto-dns=true
ignore-auto-routes=true

[ipv6]
method=disabled
'''.format(**{**c, 'ssid': escape(c['ssid']), 'password': escape(password)})

def load():
    c = json.loads(STATE.read_text())
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', c['interface']):
        raise ValueError('Ungültiger Adaptername')
    uuid.UUID(c['uuid'])
    ipaddress.IPv4Address(c['host'])
    return c

def guard(c, configuring=False, prepare_handoff=False):
    prepare_handoff = configuring and prepare_handoff and active("dhcpcd")
    interface = c['interface']
    if not active('NetworkManager'):
        raise Conflict('NetworkManager ist nicht aktiv')
    kind = nm('GENERAL.TYPE', 'device', 'show', interface)
    if kind != 'wifi':
        raise Conflict('Adapter fehlt oder ist kein WLAN-Adapter')
    state = nm('GENERAL.STATE', 'device', 'show', interface)
    if state.startswith('10 ') or (state.startswith('20 ') and not prepare_handoff):
        raise Conflict('WLAN ist unmanaged, gesperrt oder nicht verfügbar; keine Übernahme')
    current = nm('GENERAL.CON-UUID', 'device', 'show', interface)
    if current not in ('', '--', c['uuid']):
        raise Conflict('Adapter wird bereits von einer anderen NetworkManager-Verbindung benutzt')
    # An association invisible to NetworkManager indicates another owner.
    link = command('iw', 'dev', interface, 'link')
    if 'Connected to ' in link and current != c['uuid']:
        raise Conflict('WLAN-Verbindung außerhalb unseres Profils erkannt')
    if active('wpa_supplicant@' + interface + '.service'):
        raise Conflict('Separate wpa_supplicant-Instanz belegt den Adapter')
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            argv = (proc / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        except OSError:
            continue
        if argv and Path(argv[0]).name == 'wpa_supplicant':
            if ('-i' + interface) in argv or any(a == '-i' and i + 1 < len(argv) and argv[i+1] == interface for i, a in enumerate(argv)):
                if not prepare_handoff:
                    raise Conflict('Eigenständiger wpa_supplicant-Prozess belegt den Adapter')
    # The global D-Bus wpa_supplicant service is normal for NetworkManager.
    for uid in nm('UUID', 'connection', 'show').splitlines():
        if uid == c['uuid']:
            continue
        if nm('connection.type', 'connection', 'show', 'uuid', uid) != '802-11-wireless':
            continue
        bound = nm('connection.interface-name', 'connection', 'show', 'uuid', uid)
        auto = nm('connection.autoconnect', 'connection', 'show', 'uuid', uid)
        if bound in ('', '--', interface) and auto == 'yes':
            raise Conflict('Anderes automatisch verbindendes WLAN-Profil vorhanden: ' + uid)
    for route in json.loads(command('ip', '-j', '-4', 'route', 'show', 'table', 'all')):
        dest, dev = route.get('dst', ''), route.get('dev', '')
        if dest == 'default' and dev == interface:
            raise Conflict('WLAN wird als Standardroute verwendet; Verbindung bleibt unverändert')
        if dev and dev != interface and dest != 'default':
            try:
                network = ipaddress.ip_network(dest, strict=False)
            except ValueError:
                continue
            if ipaddress.ip_address(c['host']) in network:
                raise Conflict('Wechselrichter-Netz überschneidet sich mit einem anderen Adapter')
    if not configuring:
        for field, expected in [('connection.interface-name', interface),
                                ('802-11-wireless.mode', 'infrastructure'),
                                ('ipv4.never-default', 'yes'),
                                ('ipv4.ignore-auto-dns', 'yes'),
                                ('ipv4.ignore-auto-routes', 'yes'),
                                ('ipv6.method', 'disabled')]:
            if nm(field, 'connection', 'show', 'uuid', c['uuid']) != expected:
                raise Conflict('Huawei-Profil wurde verändert: ' + field)
    if not configuring and active('dhcpcd'):
        text = Path('/etc/dhcpcd.conf').read_text()
        if ('denyinterfaces ' + interface) not in text.splitlines():
            raise Conflict('dhcpcd hat keinen expliziten Ausschluss für den WLAN-Adapter')
        if c.get('dhcpcd_boot') == BOOT.read_text().strip():
            raise Conflict('dhcpcd-Ausschluss vorbereitet: vor WLAN-Start bitte neu starten')

def health(c):
    current = nm('GENERAL.CON-UUID', 'device', 'show', c['interface'])
    if current != c['uuid']:
        return False
    routes = json.loads(command('ip', '-j', '-4', 'route', 'get', c['host']))
    if not routes or routes[0].get('dev') != c['interface']:
        return False
    return True

def check_app(host):
    c = load()
    if host != c['host'] or not health(c):
        raise RuntimeError('Huawei-WLAN nicht bereit; wifi.py status prüfen')

def configure(args):
    if STATE.exists() or PROFILE.exists():
        raise Conflict('WLAN-Konfiguration existiert bereits; status/connect verwenden')
    c = {'interface': args.interface, 'uuid': str(uuid.uuid4()),
         'host': '192.168.200.1', 'port': 6607, 'ssid': ''}
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', c['interface']):
        raise ValueError('Ungültiger Adaptername')
    dual = active('dhcpcd')
    guard(c, configuring=True, prepare_handoff=dual and args.exclude_dhcpcd)
    if dual and not args.exclude_dhcpcd:
        raise Conflict('dhcpcd läuft ebenfalls. --exclude-dhcpcd reserviert nur diesen WLAN-Adapter für NetworkManager')
    c['ssid'] = input('Huawei WLAN-Name (SSID): ').strip()
    password = input('WLAN-Passwort (sichtbar): ')
    if not c['ssid'] or len(c['ssid'].encode()) > 32:
        raise ValueError('SSID muss 1–32 Bytes lang sein')
    if not (8 <= len(password) <= 63 and password.isascii()) and not re.fullmatch('[0-9a-fA-F]{64}', password):
        raise ValueError('WPA-Passwort: 8–63 ASCII-Zeichen oder 64 Hex-Zeichen')
    content = profile_text(c, password)
    if dual:
        p = Path('/etc/dhcpcd.conf')
        old = p.read_text()
        backup = p.with_name('dhcpcd.conf.luna-backup-' + str(time.time_ns()))
        shutil.copy2(p, backup)
        # Put global directive BEFORE any interface/profile blocks.
        write(p, '# LUNA: dedicated WLAN; LAN remains unchanged\ndenyinterfaces ' + c['interface'] + '\n' + old, 0o644)
        c['dhcpcd_boot'] = BOOT.read_text().strip()
    write(PROFILE, content)
    write(STATE, json.dumps(c, indent=2) + '\n', 0o644)
    command('nmcli', 'connection', 'load', str(PROFILE))
    print('Profil gespeichert. ' + ('Ein Neustart ist nötig, bevor WLAN verbunden wird.' if dual else 'Jetzt connect ausführen.'))

def connect(c):
    guard(c)
    if health(c):
        return
    command('nmcli', '--wait', '35', 'connection', 'up', 'uuid', c['uuid'], 'ifname', c['interface'])
    if not health(c):
        raise RuntimeError('WLAN aktiviert, aber Route zum Wechselrichter fehlt')

def status(c):
    guard(c)
    ready = health(c)
    reachable = False
    if ready:
        try:
            with socket.create_connection((c['host'], c['port']), timeout=3):
                reachable = True
        except OSError:
            pass
    print(json.dumps({'interface': c['interface'], 'wifi_ready': ready,
                      'inverter_tcp_reachable': reachable}, ensure_ascii=False))

def watch(c):
    failures = 0
    last = None
    while True:
        try:
            connect(c)
            failures = 0
            message = 'WLAN verbunden; Route geprüft'
        except Conflict:
            # Never fight another network owner or override a foreign connection.
            raise
        except RuntimeError:
            failures += 1
            message = 'WLAN nicht erreichbar; Versuch ' + str(failures) + '/5'
        if message != last:
            print(message, flush=True)
            last = message
        if failures >= 5:
            raise RuntimeError('Fünf WLAN-Versuche fehlgeschlagen; Dienst manuell neu starten')
        time.sleep(min(300, 15 * 2 ** failures) if failures else 20)

def install_service():
    target = Path('/usr/local/lib/luna-tibber-wifi.py')
    write(target, Path(__file__).read_text(), 0o644)
    write(Path('/etc/systemd/system/luna-wifi.service'), '''[Unit]
Description=LUNA dedicated Huawei WLAN connector
After=NetworkManager.service dhcpcd.service
Requires=NetworkManager.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/lib/luna-tibber-wifi.py watch
Restart=no
UMask=0077

[Install]
WantedBy=multi-user.target
''', 0o644)
    command('systemctl', 'daemon-reload')
    command('systemctl', 'enable', 'luna-wifi.service')
    print('WLAN-Dienst installiert und aktiviert. Start mit sudo systemctl start luna-wifi')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['configure', 'status', 'connect', 'watch', 'install-service'])
    p.add_argument('--interface', default='wlan0')
    p.add_argument('--exclude-dhcpcd', action='store_true')
    args = p.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Bitte dieses Netzwerkwerkzeug mit sudo python3 wifi.py aufrufen')
    os.umask(0o077)
    with open('/run/luna-wifi.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('WLAN-Connector läuft bereits; zuerst Dienst stoppen')
        if args.command == 'configure':
            configure(args)
        elif args.command == 'install-service':
            load()
            install_service()
        else:
            c = load()
            {'status': status, 'connect': connect, 'watch': watch}[args.command](c)

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
