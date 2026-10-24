# LUNA als App und mit Push

## Update

```bash
cd ~/apps/luna-tibber
git pull --ff-only
systemctl --user restart luna-web
```

Für Web Push zusätzlich, optional für die restlichen Funktionen:

```bash
.venv/bin/python -m pip install -r requirements-push.txt
systemctl --user restart luna-web
```

Auf 32-Bit-Systemen können Abhängigkeiten ohne passendes Wheel einen Build benötigen. Die übrige App funktioniert auch ohne dieses Zusatzpaket; bei fehlendem Paket zeigt sie den Hinweis in den Einstellungen. Python muss weiterhin mindestens 3.12 sein.

## HTTPS

Die URL muss ein vom Gerät vertrauenswürdig geprüftes HTTPS-Zertifikat haben. Ein selbstsigniertes Zertifikat mit Browserwarnung genügt nicht. HTTPS kann ein bestehender Reverse Proxy übernehmen; dieser muss `/` einschließlich aller `/api/`-Anfragen an den lokalen Port 8099 weitergeben. Nur den für deine Geräte vorgesehenen Zugriff freigeben; eine öffentliche Portfreigabe ist für Push allein nicht notwendig.

Dem Server die verwendete HTTPS-Adresse ausdrücklich mitteilen:

```bash
systemctl --user edit luna-web
```

In die Override-Datei, mit deiner tatsächlichen Adresse:

```ini
[Service]
Environment="LUNA_PUBLIC_ORIGIN=https://DEINE-LUNA-ADRESSE"
```

Danach:

```bash
systemctl --user daemon-reload
systemctl --user restart luna-web
```

Die Origin aktiviert sichere Cookies und erlaubt diesen Hostnamen. Anschließend die HTTPS-Adresse verwenden; HTTP-Anmeldung funktioniert mit Secure-Cookies nicht mehr. Zugang zum Backend-Port auf das vertrauenswürdige Netz/den Proxy beschränken.

Alternativ kann der Python-Server selbst TLS mit einem bereits vorhandenen vertrauenswürdigen Zertifikat bereitstellen:

```ini
[Service]
Environment="LUNA_PUBLIC_ORIGIN=https://DEINE-LUNA-ADRESSE:8099"
Environment="LUNA_TLS_CERT=/ABSOLUTER/PFAD/fullchain.pem"
Environment="LUNA_TLS_KEY=/ABSOLUTER/PFAD/privkey.pem"
```

Zertifikat/Schlüssel müssen für den Dienstbenutzer lesbar sein. Zertifikatserneuerung und gegebenenfalls Dienstneustart übernimmt deine Zertifikatsverwaltung. HTTPS-Zertifikat und DNS werden von diesem Repository nicht automatisch eingerichtet.

## Installieren und Push erlauben

1. HTTPS-Adresse öffnen und anmelden.
2. Einstellungen → App installieren. Auf dem iPhone: Safari → Teilen → Zum Home-Bildschirm.
3. Die installierte App öffnen.
4. In Einstellungen eine Kontakt-E-Mail für die Web-Push-Serverkennung speichern.
5. „Push aktivieren“ anklicken und die Browserberechtigung erlauben.
6. Mit „Testnachricht“ prüfen. Jedes Gerät separat anmelden; „Push ausschalten“ meldet dieses Gerät ab.

Server, Internetzugang und Browser-Push-Dienst müssen für die Zustellung verfügbar sein. Beim Öffnen einer Nachricht muss die App-Adresse erreichbar sein, gegebenenfalls über das Heimnetz/VPN. Der Test ist eine Zustellungsanforderung, keine Zustellgarantie.

## Offline und Daten

Offline erscheint eine eigene Hinweisseite. Steuerungsbefehle werden niemals offline zwischengespeichert oder später automatisch abgesendet; Status-/API-Antworten werden nicht im Service-Worker-Cache gespeichert. Die tatsächliche Steuerung läuft auf dem Linux-Server.

`push-key.pem`, `push-subscriptions.json`, `push-events.json`, `history.sqlite3` und vorhandene Konfigurations-/Sitzungsdateien gehören ausschließlich auf den Server. Das Repository ignoriert sie. Der private VAPID-Schlüssel muss bei Updates erhalten bleiben, sonst müssen Geräte Push neu abonnieren.
