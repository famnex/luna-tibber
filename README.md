# LUNA + Tibber – lokale Linux-Steuerung, Version 2.0

Für Huawei SUN2000-5KTL-M1 mit LUNA und direktem Wechselrichter-WLAN.

## Was diese Version kann

- Lokale Huawei-Telemetrie lesen, einschließlich SOC und Ladeleistung.
- Tibber-Endkundenpreise in Viertelstundenauflösung für heute/morgen lesen.
- Einen beaufsichtigten Ladetest mit maximal 1 kW und zwei Minuten ausführen.
- Optional nach Tibber-Preisvergleich inklusive Verlusten und Verschleißreserve bis zum Ziel-SOC laden.
- Entscheidungen als JSON im Terminal und in `status.json` protokollieren.
- Einen Verlust-/Wirtschaftlichkeitsrechner ausführen.

**Stand:** Mit der installierten Python-Bibliothek und simulierten Geräten getestet.
Kein Hardwaretest an deinem Wechselrichter und kein Abruf deines Tibber-Kontos möglich.
Die Planung verwendet eingestellten Grund-/Zusatzverbrauch und optional eine konservative PV-Wetterprognose. Smart kann die normale Entladung zeitweise sperren. Ein billiger Einkauf allein garantiert keine Einsparung; Wetter, Lastprofil und Fremdsteuerung können vom Plan abweichen.

Huawei beschreibt erzwungenes Laden als Wartungs-/Testfunktion und empfiehlt für
regelmäßige Zeitfenster TOU. Zuerst den lokalen Test und das Verhalten neben Enpal prüfen.
Das Programm verändert weder Netzschutz noch Einspeiselimit, TOU, AC-Freigabe oder die
angezeigten Netzladegrenzen. Es nutzt zeitlich begrenztes Laden/Stopp sowie eine gesicherte, rücksetzbare Begrenzung der maximalen Entladeleistung.
Bei gegenseitigen Steuerbefehlen von Enpal/evcc ist kein zuverlässiger Parallelbetrieb garantiert.

## Webinterface (Version 2)

Responsive Oberfläche auf dem Pi, keine Cloud und keine zusätzlichen Python-Pakete.
Anmeldung mit eigenem Web-Passwort. Die Anwendung nutzt den normalen Linux-Benutzer.

Vorherigen CLI-Ladedienst zuerst beenden/deaktivieren, falls eingerichtet:

```bash
systemctl --user disable --now luna-tibber.service
```

Ein Fehler „Unit does not exist“ bedeutet lediglich, dass dieser Dienst nicht installiert war.
Einen direkt im Terminal laufenden Controller mit Strg+C beenden.
Dann:

```bash
cd ~/apps/luna-tibber
git pull --ff-only
.venv/bin/python -m unittest -v
bash install-web.sh
sudo loginctl enable-linger "$(id -un)"
```

Das Installationsskript fragt beim ersten Start ein Web-Passwort (mindestens 12 Zeichen)
ab. Im Browser `http://PI-LAN-IP:8099` öffnen, für den bisher beobachteten Pi
`http://<SERVER-IP>:8099`. Kein Portforwarding: HTTP ist für das vertrauenswürdige
Heimnetz gedacht. Für Zugriff über nicht vertrauenswürdige Netze TLS-Reverse-Proxy
oder einen SSH-Tunnel verwenden. Keine CORS-Freigabe, Session-Cookies HttpOnly/SameSite,
Host-Prüfung, Login-Drosselung und keine Zugangsdaten in Statusantworten.

Einrichtung vollständig für Batterie/Tibber im Browser:
1. Einstellungen: Huawei-Installateurpasswort und Tibber-Token eintragen, speichern.
2. Übersicht: Gerät auslesen. Danach Seriennummer übernehmen. Die Seriennummer
   wird nur nach einem erfolgreichen Probe-Vorgang übernehmbar.
3. Beaufsichtigten 2-Minuten-Ladetest starten und Netzbezug/Ladeleistung prüfen.
4. Danach Smart, An oder Zeitpläne aktivieren.

Die bisherige Meldung „expected_serial und password lokal setzen“ wird durch konkrete
fehlende Felder ersetzt. Ohne passende Seriennummer/Passwort sind Schreibbefehle gesperrt.
Ein Wechsel der Seriennummer verwirft die bisherige Ladetest-Freigabe.

Modi:
- **Aus**: beendet den eigenen Ladeprozess und sendet bei vorhandenen Zugangsdaten
  zusätzlich Stopp. Normale Enpal-/Huawei-Ladung/Entladung wird nicht deaktiviert.
- **Smart**: bestehender Preisfilter mit Kaufgrenze, Gesamtwirkungsgrad,
  Verschleißreserve, Mindestvorteil und konfiguriertem Verbrauchsfenster.
- **An**: sofortiges preisunabhängiges Laden mit manuell gewählter Dauer;
  SOC-Limit, AC-Freigabe, Gerätestatus, Leistungsgrenzen und Testfreigabe gelten weiter.
- **Zeitpläne**: Wochenfenster für Aus/Smart/An, auch über Mitternacht. Erster
  passender Eintrag gewinnt; sonst Aus. Zeitzone aus Einstellungen. Bei der
  Zeitumstellung werden lokale Fenster berücksichtigt; es gibt keinen separaten
  zweiten Start derselben Fensterinstanz in der wiederholten Stunde.

Nach Webserver-Neustart immer **Aus**. Zeitpläne bleiben gespeichert, müssen aber
wieder aktiviert werden. Fehler führen zu Aus, ohne automatische Wiederholung des
Ladeprozesses. Die maximale zusammenhängende Sitzung gilt auch bei Zeitplänen.
Prozessausgaben werden nur als begrenzte Ereignisliste im Speicher gehalten.

Im Modus Aus wird die Gerätetelemetrie per „Gerät / Status auslesen“ aktualisiert;
bei laufendem Laden/Smart automatisch. Die Oberfläche zeigt das Alter der letzten
Messung. Die Preisrechnung wird unabhängig davon regelmäßig aktualisiert.

WLAN-Profil/SSID werden angezeigt und die WLAN-Prüfung kann in den Einstellungen
aktiviert werden. Die privilegierte OS-Netzwerkeinrichtung (SSID/Passwort ändern,
dhcpcd-Übergabe) bleibt beim mitgelieferten `wifi.py`/NetworkManager-Werkzeug:
der Webserver erhält absichtlich keine Root-Rechte. Das ist noch keine Web-Verwaltung
sämtlicher Betriebssystem-Netzwerkeinstellungen.

Betrieb:

```bash
systemctl --user status luna-web --no-pager
journalctl --user -u luna-web -n 50 --no-pager
systemctl --user restart luna-web
```

Passwort neu setzen: Webdienst stoppen, `.venv/bin/python web.py setup` ausführen,
Webdienst wieder starten. Das setzt auch die bestehenden Web-Sitzungen zurück.
Manueller Vordergrundstart: `.venv/bin/python web.py serve --host 0.0.0.0 --port 8099`.

## Neu: WLAN-Connector für openHABian / NetworkManager

Der Connector ist Teil dieses Pakets und funktioniert mit System-Python 3.9.
Er läuft getrennt vom Ladeprozess: nur das Netzwerkwerkzeug braucht root;
Tibber-Token und Installateurpasswort bleiben beim normalen Benutzer.
`wlan0` wird für Huawei reserviert. Keine Änderungen an LAN-Profilen, kein
Neustart von NetworkManager/dhcpcd während der Einrichtung.

Für den beobachteten Pi (NetworkManager UND dhcpcd aktiv):

```bash
cd ~/apps/luna-tibber
git pull --ff-only
sudo apt install -y iw
sudo python3 wifi.py configure --interface wlan0 --exclude-dhcpcd
sudo python3 wifi.py install-service
```

`configure` fragt SSID und WLAN-Passwort sichtbar ab. Das Passwort landet nur
im root-lesbaren NetworkManager-Profil (600), nicht in Argumenten oder Logs.
Die Zusatzoption ergänzt `denyinterfaces wlan0` global in dhcpcd.conf und
legt vorher eine Sicherung unter /etc/dhcpcd.conf.luna-backup-* an.
Diese Reservierung ist erst nach einem Neustart für den Connector freigegeben:

```bash
sudo reboot
```

Neustart unterbricht openHAB und SSH kurz. Danach erneut anmelden:

```bash
cd ~/apps/luna-tibber
systemctl status luna-wifi --no-pager
journalctl -u luna-wifi -n 30 --no-pager
ip route get 192.168.200.1
ip route get 1.1.1.1
.venv/bin/python luna.py wifi-enable
.venv/bin/python luna.py probe
```

Voraussetzung für `wifi-enable` ist die normale App-Konfiguration (`setup`).
Token später sichtbar ändern, ohne sonstige Einstellungen zurückzusetzen:

```bash
.venv/bin/python luna.py credentials
```

Schutzverhalten:
- Fremde aktive Profile, fremde WLAN-Assoziation, konkurrierende automatisch
  verbindende WLAN-Profile, dedizierte wpa_supplicant-Prozesse und -Units,
  unmanaged/gesperrter Adapter, WLAN-Standardroute und Subnetzkonflikte führen
  zum Abbruch. Keine fremde Verbindung wird getrennt, kein rfkill entsperrt.
- Der globale D-Bus-Dienst wpa_supplicant ist mit NetworkManager normal und
  wird nicht allein wegen seines Laufens als Konflikt gewertet.
- Eigenes Profil verwendet weder Standardroute noch DHCP-DNS oder zusätzliche
  DHCP-Routen. IPv6 ist nur in diesem Profil deaktiviert.
- Verbindung und Route werden alle 20 Sekunden geprüft. Maximal fünf Versuche
  mit steigenden Pausen, anschließend manueller Neustart des WLAN-Dienstes.
- Ein bereits verbundenes eigenes Profil wird nicht ständig neu aktiviert.
- Fremde FusionSolar-Sitzungen auf Handys sind nicht zuverlässig erkennbar.
  Der Connector sendet selbst keine Huawei-Anmeldung/Ladebefehle.
- Die Lade-App prüft bei aktiviertem WLAN-Modus das Profil und die Route.
  Bei Verlust endet der Ladeprozess mit einem Stoppversuch. WLAN kann sich
  wiederverbinden, aber automatisches Laden muss nach dem Fehler bewusst
  neu gestartet werden. Keine endlosen Wiederanmeldungen gegen Enpal.
- `wifi.py status` prüft zusätzlich TCP-Port 6607 ohne Geräteanmeldung.
  Während watch läuft ist das Werkzeug gesperrt; für laufenden Status journalctl
  verwenden. Eigene Verbindung bleibt beim Beenden von watch bestehen.

Diagnose bei Konflikt: Meldung lesen, nicht andere Dienste pauschal abschalten.
Ein bestehendes Profil kann ohne Änderung geprüft werden:
`nmcli -f NAME,UUID,TYPE,AUTOCONNECT connection show`.
Für Änderungen an SSID/Passwort zuerst WLAN-Dienst stoppen, eigenes Profil
mit `sudo nmtui` bearbeiten und wieder starten. Profil nicht umbenennen oder
UUID/Interface/Routenschutz ändern. Gespeicherte SSID in /etc/luna-wifi.json
ist nur Metadatum; genutzt wird die Profil-UUID.

```bash
sudo systemctl stop luna-wifi
sudo python3 wifi.py status
sudo systemctl start luna-wifi
```

Bei Updates von wifi.py den Dienst stoppen, `install-service` erneut ausführen
und starten: der Dienst nutzt eine root-eigene Kopie unter /usr/local/lib,
keine veränderbare Datei im Benutzerverzeichnis.

Auf dem echten Pi noch nicht getestet; Konfliktfälle sind mit simulierten
Netzwerkantworten getestet. Das Werkzeug garantiert keine Erkennung sämtlicher
beliebiger Netzwerkprogramme. Die folgenden manuellen nmcli-Befehle sind eine
Alternative und sollen nicht zusätzlich zum Connector ausgeführt werden.

## 1. Voraussetzungen und WLAN

- Linux, Python **3.12 oder neuer**, venv/pip, LAN mit Internet, separater WLAN-Adapter.
- Das Programm läuft als normaler Benutzer. Keine Root-Rechte nötig.
- WLAN direkt mit `SUN2000-…` verbinden, nicht mit dem Enpal-Router oder dem Smart-Dongle.
- WLAN-Passwort und lokales Installateurpasswort sind zwei verschiedene Zugangsdaten.
- LAN bleibt Standardroute/DNS für Internet; WLAN dient nur `192.168.200.0/24`.
- Bei gleichlautendem Heimnetz-Subnetz zuerst die Netzkonfiguration klären.

Beispiel für NetworkManager (Adaptername/SSID ersetzen). `--ask` fragt das WLAN-Passwort
interaktiv ab und vermeidet es in der Shell-History. Die Profilanlage startet noch keine Verbindung:

```bash
nmcli device status
sudo nmcli connection add type wifi ifname wlan0 con-name huawei-local ssid 'SUN2000-DEINE_SSID'
sudo nmcli connection modify huawei-local wifi-sec.key-mgmt wpa-psk ipv4.method auto ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.method disabled connection.autoconnect yes
sudo nmcli --ask connection up huawei-local
ip route get 192.168.200.1
ip route get 1.1.1.1
```

Die erste Route muss über WLAN, die zweite über LAN führen. Bestehende WLAN-Profile nicht
blind überschreiben. Ohne NetworkManager dieselben Eigenschaften im verwendeten
Netzwerkmanager setzen. FusionSolar während der Servertests schließen, damit nicht zwei
lokale Installateur-Sitzungen konkurrieren. WLAN-/Modbus-Zugang nicht ins Internet freigeben.

## 2. Installation und Geheimnisse

Repository klonen (alternativ ZIP entpacken):

```bash
git clone https://github.com/famnex/luna-tibber.git
cd luna-tibber
```

```bash
bash install.sh
.venv/bin/python luna.py setup
```

Falls `python3` älter ist, beispielsweise:

```bash
LUNA_PYTHON=/usr/bin/python3.12 bash install.sh
```

Tibber Personal Access Token unter https://developer.tibber.com/settings/accesstoken
im eigenen Konto erzeugen. Tibber-Token wird auf Wunsch sichtbar eingegeben (Einfügen möglich). Das Huawei-Installateurpasswort bleibt verdeckt; auch dort funktioniert Einfügen. Beide **nur lokal** eingeben.
Sie landen in `config.json` mit Dateirechten 600. Nicht hier im Chat teilen.

## 3. Verbindungstest – noch keine Batterie-Schreibbefehle

```bash
.venv/bin/python luna.py probe
.venv/bin/python luna.py prices
.venv/bin/python luna.py plan
```

`probe` gibt Modell, Seriennummer, Firmware, SOC und Batterieleistung aus. `prices` gibt
`ct` in **Cent pro kWh einschließlich der von Tibber in `total` gelieferten Preisbestandteile**
aus. Zeitangaben sind UTC mit Offset; keine manuelle Sommerzeitkorrektur nötig.
Monatliche Grundgebühren sind nicht Bestandteil dieser variablen Kaufentscheidung.

Die Seriennummer aus `connected` anschließend in `config.json` bei `expected_serial`
eintragen. Gibt Tibber mehrere Zuhause zurück, deren richtige ID bei `tibber_home_id`
eintragen. Keine automatische Auswahl des ersten Zuhauses.

Standard ist `192.168.200.1`, Port `6607`, Unit-ID `0`. Bei erreichbarem WLAN, aber fehlender
Antwort kann für diese Firmware Unit-ID `1` nötig sein. Port `502` nur bei älteren
Firmwareständen verwenden. Werte gezielt einzeln ändern, keine parallelen Scanner starten.

## 4. Beaufsichtigter Ladetest

Prüfen: Netz vorhanden, Batterie ohne Alarm, SOC unter Zielwert (Standard 80 %),
„Von AC-Seite laden“ in Huawei eingeschaltet. Keine zweite aktive Batteriesteuerung
oder manuelle Wartungssitzung während des Tests. Möglichst abends ohne PV testen;
das Programm erkennt Ladeleistung, es kann deren Energiequelle noch nicht beweisen.

```bash
.venv/bin/python luna.py charge-test --execute
```

Der Auftrag ist auf zwei Minuten und höchstens 1.000 W begrenzt. Nach dem Test wird
Stopp gesendet. Nur wenn mindestens zwei Messungen positive Ladeleistung zeigen und
Stopp bestätigt wurde, entsteht `commissioned.json`. Das bestätigt Kommunikation und
Ladeleistung, nicht die tatsächliche Herkunft des Ladestroms und nicht die Dauerstabilität.
Den Netzbezug zusätzlich am Zähler oder in Huawei prüfen. Bei weiterhin 5 kW trotz
1-kW-Auftrag: Automatik nicht einschalten; Firmware/Enpal-Konflikt untersuchen.

Einzelner manueller Stopp (zuvor laufenden Dienst mit Ctrl+C/systemctl stoppen):

```bash
.venv/bin/python luna.py stop --execute
```

## 5. Beobachten und automatische Steuerung

Zunächst ohne Schreibzugriff beobachten:

```bash
.venv/bin/python luna.py run
```

Die Voreinstellungen in `config.json` sind **Beispielwerte, keine Wirtschaftlichkeitsberatung**:

| Schlüssel | Vorgabe | Bedeutung |
|---|---:|---|
| `mode` | `monitor` | `monitor` beobachtet; `auto` erlaubt Automatik zusammen mit `--execute` |
| `max_buy_ct_kwh` | 20 | Feste maximale Tibber-Kaufpreisgrenze |
| `roundtrip_efficiency` | 0.85 | Angenommener Gesamtwirkungsgrad AC→Akku→AC |
| `wear_ct_kwh` | 0 | Angenommener Verschleiß je abgegebener kWh in Cent |
| `min_saving_ct_kwh` | 2 | Mindestens verbleibender Vorteil in Cent je abgegebener kWh |
| `use_start_hour` / `use_end_hour` | 6 / 9 | Angenommenes tägliches Verbrauchsfenster, volle Stunden, innerhalb eines Tages |
| `timezone` | Europe/Berlin | Zeitzone des Verbrauchsfensters |
| `target_soc` | 80 | Software-Ladeziel; Mess-/Stoppverzögerung kann eine kleine Überschreitung verursachen |
| `charge_power_w` | 1000 | Maximale angeforderte Ladeleistung; niemals über Gerätewert |
| `max_session_minutes` | 120 | Maximale zusammenhängende Ladesitzung; danach beendet sich der Dienst |

Nach erfolgreichem Test und Prüfung des Nutzens `mode` auf `auto` ändern und starten:

```bash
.venv/bin/python luna.py run --execute
```

Es müssen **beide** Bedingungen gesetzt sein: `mode=auto` und `--execute`. Im Monitor-Modus
wird auch mit `--execute` nicht geladen. Änderungen an config.json werden beim Neustart gelesen.

Der Controller prüft SOC/Status etwa alle zehn Sekunden; Preisabrufe verwenden den gemeinsamen Cache.
Bei Preisfehlern wird kein neuer Ladevorgang gestartet und ein eigener laufender Auftrag gestoppt.
Jeder Ladeauftrag im Gerät läuft maximal zwei Minuten. Der Dienst erneuert ihn bei Bedarf.
Vor Tarifwechseln bleibt eine kurze Pause für Befehl-/Netzwerklatenz. Bei verlorener Verbindung
kann Stopp nicht garantiert werden; dann bleibt die geräteseitige Zeitbegrenzung als Rückfall.
Diese muss im beaufsichtigten Test mit deiner Firmware verifiziert werden.

Bei fehlender Ladeleistung trotz aktivem Auftrag beendet sich die Automatik, statt unbegrenzt
gegen eine andere Steuerung anzuschreiben. Bei unbestätigtem Stopp bleibt `pending-charge.json`
als Hinweis erhalten. Nicht manuell löschen, sondern Verbindung herstellen und Stopp bestätigen.
Nur eine Programminstanz pro Konfigurationsordner; weitere Diagnoseinstanzen warten nicht.

## 6. Dauerbetrieb mit systemd

Optional eine Benutzer-Unit anlegen. `/ABSOLUTER/PFAD` durch deinen tatsächlichen
Installationspfad ersetzen. Zunächst im Beobachtungsmodus starten:

```ini
[Unit]
Description=Huawei LUNA und Tibber lokal

[Service]
Type=simple
WorkingDirectory=/ABSOLUTER/PFAD/luna-tibber
ExecStart=/ABSOLUTER/PFAD/luna-tibber/.venv/bin/python /ABSOLUTER/PFAD/luna-tibber/luna.py run
Restart=no
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

Unter `~/.config/systemd/user/luna-tibber.service` speichern:

```bash
systemctl --user daemon-reload
systemctl --user enable --now luna-tibber
journalctl --user -u luna-tibber -f
```

Für Automatik zusätzlich `mode=auto` setzen und an `ExecStart` **`--execute`** anhängen.
Dann daemon-reload und restart. `Restart=no` ist absichtlich gewählt, damit ein Fehler
nicht durch wiederholtes automatisches Starten übergangen wird. Soll der Benutzerdienst
ohne Anmeldung laufen, muss der Administrator für diesen Benutzer Linger aktivieren.

## 7. Verlustrechnung

```bash
.venv/bin/python economics.py --night 20 --day 30 --efficiency 0.85 --useful-kwh 5
```

Alle Preise in ct/kWh; Wirkungsgrad umfasst AC→Batterie→AC, nicht bloß Batterie/DC.
Der Wert 0,85 ist eine **Annahme**, keine Messung deiner LUNA. Optional `--wear 3`
für angenommene zusätzliche Verschleißkosten je abgegebener kWh. Standard ist 0.

Gewinnschwelle: Tagpreis > Nachtpreis / Wirkungsgrad + Verschleißkosten.
Beispiel: 20 / 0,85 = 23,53 ct/kWh. Gegen 30 ct bleiben 6,47 ct/kWh vor Verschleiß,
bei 5 kWh tatsächlich später genutztem Strom rund 0,32 Euro.

Version 2.0 verlangt zusätzlich zur Kaufgrenze einen Preisvorteil gegenüber dem
**zeitgewichteten durchschnittlichen** Viertelstundenpreis im nächsten konfigurierten Verbrauchsfenster:
`Referenzpreis - aktueller Preis / Wirkungsgrad - Verschleiß >= Mindestvorteil`.
Der Vorteil muss außerdem positiv sein. Innerhalb des Verbrauchsfensters wird nicht
netzgeladen. Fehlen zukünftige Preise auch nur teilweise, wird nicht geladen.
`plan` prüft dies mit Tibber ohne Verbindung zum Wechselrichter. Die Rechnung steht
auch in `status.json` unter `economics`. Sommerzeit wird über Europe/Berlin berücksichtigt.
Das ist ein Preisfilter, kein optimaler Ladefahrplan: Er nimmt den späteren Verbrauch
im eingestellten Fenster an. Die aktuelle Smart-Entladeplanung berücksichtigt dagegen Grund-/Zusatzverbrauch und optional direkte Solardeckung.
Den Rechner daher nicht mit einer garantierten Einsparung verwechseln. Lade nur die Menge,
die später tatsächlich teuren Netzstrom ersetzt. Ein hoher Nacht-SOC kann sonst günstigen
Solarstrom verdrängen; frühes Entladen vor dem teuren Zeitfenster kann den Nutzen ebenfalls
aufheben. Die neuere Smart-Planung mit Entladesperren und optionaler PV-Prognose ist weiter unten beschrieben.

## Prüfung / Quellen

```bash
.venv/bin/python -m unittest -v
```

Automatisierte Tests prüfen u.a. Preisgrenzen, fehlende Preise, DST, gültige Register,
Befehlsreihenfolge, Stopp nach Schreibfehlern und Schreibsperren. Kein echter Gerätetest.

- https://github.com/wlcrs/huawei-solar-lib – verwendete Bibliothek 3.0.7 (AGPL-3.0)
- https://github.com/wlcrs/huawei_solar/wiki/Connecting-to-the-inverter
- https://github.com/wlcrs/huawei_solar/wiki/Force-charge-discharge-battery
- https://developer.tibber.com/api/reference.md – priceInfo(resolution: QUARTER_HOURLY)
- https://info.support.huawei.com/Energy/info/en_US/solar/docView/EDOC1100167258

Das Paket enthält eigenen Anwendungscode und Abhängigkeitsangaben; Drittanbieter-Bibliotheken
werden beim Installieren bezogen und unterliegen ihren jeweiligen Lizenzen.


### Einmalig „Geplant“ laden
Im Webinterface Startdatum/-uhrzeit und Ende als Uhrzeit oder Ziel-SOC wählen.
Eine Enduhrzeit vor dem Start bedeutet den Folgetag. Alle Zeiten gelten in der
konfigurierten Zeitzone; mehrdeutige/fehlende Zeiten beim Sommerzeitwechsel werden
abgewiesen. Auch SOC-Aufträge enden spätestens nach `max_session_minutes`.
Bei Uhrzeit-Aufträgen gilt zusätzlich der konfigurierte Ziel-SOC. Der SOC eines
Einmalauftrags überschreibt die Konfiguration nicht. Kein Tibber-Preisfilter.
„Aus“, Fehler oder Serverneustart beenden/verwerfen den Auftrag. Ein verpasstes
Fenster wird nicht nachgeholt. SOC wird per Abfrage geprüft, daher ist ein kleiner
Überschwinger möglich; kein exakt auf die Sekunde garantierter Stopp.

### Grenzen und Eingriffe
Die Ladesteuerung schreibt die vier Register für erzwungene Ladeleistung,
Ladedauer, Zielmodus TIME und CHARGE/STOP. Diese Positivliste wird vor jedem Schreiben
geprüft. Das ist ein Eingriff in die Wechselrichtersteuerung; es wird keine
vollständige Wiederherstellung vorheriger Registerwerte versprochen. Netzschutz,
Netzcode, BMS-Grenzen und Firmware werden nicht beschrieben.
Kurze Aufträge (höchstens zwei Minuten) begrenzen einen Verbindungsabbruch nur, wenn
die Gerätefirmware den Timer korrekt umsetzt. Softwaretests ersetzen keine Prüfung
am Gerät. Enpal-Fremdsteuerung, Firmwareverhalten, Hardwarefehler und zusätzliche
Batteriealterung bleiben Risiken. Die Wartungsfunktion ist keine Herstellerfreigabe
für diese Automatisierung. Vertrags-/Garantiebedingungen vor Dauerbetrieb klären.

### Preisübersicht und Bedienung
Das Dashboard zeigt Ladeindikatoren, Fortschrittsmeldungen, Verbindungsstatus,
veraltete Messwerte und einen per Maus, Touch oder Tastatur bedienbaren Preisgraphen.
Einstellungen sind nach Verbindung, Tibber, Ladegrenzen und Preisvergleich gruppiert.
Token und Passwort sind zunächst verdeckt; Einfügen ist möglich.
Der Vergleich nutzt den vollständigen nächsten lokalen Kalendertag (00–24 Uhr)
und dessen einstellbares Nachtfenster (Standard 00–06 Uhr). Zeitgewichtete Mittelwerte
berücksichtigen auch 23-/25-Stunden-Tage. Fehlende Intervalle verhindern einen
vollständigen Vergleich. Vorteil = Tagesmittel − Nachtmittel / Wirkungsgrad −
Verschleißreserve. Diese Orientierung ändert die Smart-Entscheidung nicht.
System-WLAN-Zugangsdaten bleiben im separat privilegierten WLAN-Connector; der
Webdienst verändert keine Betriebssystem-Netzwerkkonfiguration.

Der Smart-Vergleich nimmt gleichmäßig verteilten Verbrauch im Verbrauchsfenster an.
Ein einzelnes günstiges Intervall bestimmt den Vergleichspreis nicht mehr.

### Bedienung und Vergleichsdatum
Während des eingestellten Nachtfensters vergleicht „Automatisch“ die laufende
Nacht mit dem heutigen Tag; nach Ende des Nachtfensters den nächsten Tag.
„Heute“/„Morgen“ erlauben eine ausdrückliche Auswahl. Fehlende Preise werden nicht
durch andere Tagesdaten ersetzt. Der volle Nachtmittelwert enthält während der
laufenden Nacht auch bereits vergangene Intervalle und ist keine Ladeprognose.
In der Steuerung wählt man An/Smart/Geplant und bestätigt anschließend die passenden
Felder. Die Auswahl allein startet keine Ladung. Aus stoppt unmittelbar per Anfrage.
Verbindung und Inbetriebnahme haben einen eigenen Hauptmenüpunkt. Spinner erscheinen
an Aktionen und in einer festen Statusanzeige; Geräteaufträge bleiben bis zum Ende
als laufend markiert.

### Anmeldung und sichtbare Anzeige
Browser-Anmeldungen bleiben 30 Tage erhalten, auch nach Dienstneustart. Das
HttpOnly-Cookie enthält eine zufällige Sitzungskennung, kein Passwort. Auf dem
Server werden nur deren Hashes in web-sessions.json (600, nicht in Git) gespeichert.
Abmelden widerruft die Sitzung. Ein über web.py setup geändertes Passwort verwirft
bisherige Sitzungen beim nächsten Dienststart.
Der Wochenplan-Reiter entfällt; einmaliges Planen bleibt unter „Geplant“.
Bei sichtbarer Webseite erfolgt die normale Statusabfrage alle 60 Sekunden, nach
Steuerungswechseln alle 10 Sekunden bis zur bestätigten Änderung. Nach 3 Minuten
ohne Bestätigung erscheint ein Hinweis und der normale Takt wird wieder verwendet.
Beim Verbergen des Tabs pausiert die Anzeige; beim Öffnen wird sie aktualisiert.
Im Leerlauf werden Messwerte auf Anfrage gelesen. Während einer Steuerung werden
deren ohnehin erforderliche Sicherheitsmessungen wiederverwendet. Diese laufen
unabhängig vom geöffneten Browser weiter. Bereits gestartete Abfragen dürfen enden.

### Smart: Kapazität und günstige Ladephasen
Vor Smart die **nutzbare Akkukapazität gesamt in kWh** eintragen. Standard 0 bedeutet
unbekannt und verhindert eine Smart-Freigabe. Bedarf = Kapazität × SOC-Differenz / 100.
Dauer = Bedarf / batterieseitige Ladeleistung; eine vom Gerät gemeldete niedrigere
Maximalleistung wird berücksichtigt. Der Roundtrip-Wirkungsgrad bleibt Teil der
Preisvorteilsrechnung, wird aber nicht nochmals auf die batterieseitige Energie
angewendet. Die Vorschau benötigt einen höchstens 90 Sekunden alten SOC.
Smart verteilt den Bedarf auf die preislich günstigsten geeigneten Teile der
Viertelstundenintervalle im Nachtfenster. Kaufgrenze und Mindestvorteil bleiben
wirksam. Zwischen den Phasen sendet der Controller STOP und lädt später erneut.
Er plant anhand frischer Messwerte nach; fehlende Nachtpreise verhindern die Planung.
Schaltreserve ist berücksichtigt. Unzureichende geeignete Ladezeit wird angezeigt.
Grund-/Zusatzverbrauch und optional PV-Ertrag werden modelliert. Fremdsteuerung und Abweichungen vom Wetter-/Verbrauchsmodell bleiben möglich; Energie, Dauer und Zielerreichung sind Schätzungen. Das bestehende
Limit für zusammenhängende Ladesitzungen bleibt als Abbruchgrenze bestehen.

### Statuskarte und Countdown
Die Übersicht zeigt Batterieleistung, Flussrichtung, Akkustand als Balken, Zielmarke
und nächste Phase bzw. Ende. Bei „An“ läuft die Restzeit lokal sekündlich in MM:SS.
Bei verstecktem Tab wird nicht weiter gezeichnet; beim Zurückkehren wird synchronisiert.
Bei 00:00 wartet die Anzeige auf Serverbestätigung statt einen erfolgreichen Stopp
zu behaupten. Es entstehen keine zusätzlichen sekündlichen Geräte-/Netzabfragen.

### Phasenanzeige und Preis-Cache

Die Statuskarte zeigt geplanten Start, Ladebestätigung, Ladephase, Pause und Stopp mit Symbolen. Smart bleibt zwischen Ladefenstern aktiv. An und Geplant wechseln nach Zeitablauf bzw. nach Erreichen des Ziel-SOC automatisch auf Aus; der Server übernimmt dies auch bei geschlossenem Browser. Am bekannten Phasenwechsel fragt die sichtbare Oberfläche den Status zusätzlich ab. Angezeigte Smart-Stoppzeiten berücksichtigen den 130-Sekunden-Sicherheitsabstand des Controllers; Pläne werden anhand aktueller Messwerte neu berechnet.

Webserver und Controller teilen einen lokalen Tibber-Cache (`tibber-prices.json`, Dateirechte 0600). Er übersteht Neustarts und vermeidet doppelte Preisabrufe innerhalb von fünf Minuten. Bei Abruffehlern werden höchstens 48 Stunden alte, noch zeitlich gültige Preisintervalle weiterverwendet. Die bestehende Prüfung auf vollständige Nacht-/Verbrauchsfenster bleibt aktiv. Der Cache ist an Token und Zuhause-ID gebunden, enthält aber keine Zugangsdaten. Änderungen dieser Zugangsdaten verhindern die Wiederverwendung des alten Caches. Die Oberfläche meldet die Verwendung gespeicherter Preise bei Abruffehlern.

### Zeitlich begrenzte Entladesperre

Unter Entladung gibt es unabhängig vom Ladeauftrag „Aktiv“ und „Entladesperre“ mit Enduhrzeit und Bestätigung. Eine frühere Uhrzeit gilt für morgen (Zeitzone aus den Einstellungen). Der erste Zugriff sichert den aktuellen Wert von `STORAGE_MAXIMUM_DISCHARGING_POWER` (47077) dauerhaft, setzt ihn auf 0 W und liest ihn zur Bestätigung zurück. Dieses zusätzliche Register wird nur für die Entladesperre verwendet. Nach Ablauf bzw. nach Auswahl von Aktiv wird der Originalwert wiederhergestellt; unbekannte Fremdänderungen werden nicht überschrieben. Die Sperre gilt für die gesamte Batterieentladung, nicht nur für das Auto.

Die Wiederherstellung benötigt den laufenden Server und eine Verbindung zum Wechselrichter. Bei Ausfall kann 0 W über die Endzeit hinaus bestehen bleiben. Das Wiederherstellungsjournal übersteht Neustarts und wird erst nach erfolgreichem Rücklesen gelöscht. Nicht manuell löschen. Der Dienst versucht bei ausstehender Sperre/Wiederherstellung alle 30 Sekunden erneut; während Smart/An übernimmt derselbe Controller den Abgleich. Keine parallelen Huawei-Schreibclients. Die Funktion ist softwaregetestet, aber noch nicht an dieser Enpal-Anlage verifiziert. Erste Sperre und Freigabe beaufsichtigen.

### Stabile Preisanzeige

Vollständig vorhandene Preise für die nächsten zwölf Stunden werden ohne erneuten API-Abruf verwendet. Ab 13 Uhr lokaler Zeit wird zusätzlich nach dem vollständigen Folgetag gesucht; die Veröffentlichung muss nicht genau um 13 Uhr erfolgt sein. Fehlende Daten werden frühestens alle fünf Minuten nachgefragt. Bereits bekannte Intervalle bleiben erhalten, auch während eines Abrufs und beim Wechsel des Lademodus. Erst geänderte Tibber-Zugangsdaten leeren den aktuellen Preisbestand. Unveränderte Smart-Slotlisten werden nicht neu aufgebaut; ein bisheriger Plan bei fehlender aktueller SOC-Messung wird ausdrücklich als unbestätigt gekennzeichnet. Die Steuerung selbst verlangt weiterhin aktuelle Messwerte.


## Smart-Entladen, Statistik und App-Installation

Die neue Menüleiste bleibt unten sichtbar: Übersicht, Statistik, Verbindung, Einstellungen.

### Smart für den ganzen Tag

Unter Einstellungen zuerst **Grundverbrauch (W)** und bei Bedarf **Zusatzverbrauch (kWh) mit Zeitfenster** eintragen, dann **Smart: Entladung optimieren** aktivieren. Die Funktion ist für bestehende Installationen zunächst ausgeschaltet. Grundverbrauch meint den erwarteten durchschnittlichen Hausverbrauch während der geplanten Entladezeit, ohne das separat geladene Auto. Beispiel: 500 W über zwei Stunden entsprechen 1 kWh. Die Kapazität bleibt die nutzbare Akkukapazität in kWh.

Der Controller verteilt die aktuell vorhandene Energie nach angenommenen Entladeverlusten auf die teuersten verbleibenden Preisintervalle bis zum nächsten Nachtfenster. Dabei berücksichtigt er den eingestellten Wirkungsgrad und den Grundverbrauch. Aktueller SOC und Preise führen laufend zu einer neuen Planung. In günstigen Abschnitten wird die normale Entladung gesperrt, in teuren wieder freigegeben. Es wird **keine Zwangsentladung und keine Netzeinspeisung** angefordert. Tatsächlicher Verbrauch und Enpal/Huawei-Regelung bestimmen die Leistung. Auch während nächtlicher Ladepausen bleibt die Energie bei aktivierter Smart-Entladung reserviert. Die manuelle zeitliche Entladesperre hat Vorrang.

Der Nachtpreisvergleich nutzt bei aktivierter Smart-Entladung den gewichteten Preis der vorgesehenen Entladestunden. Die separate Tagesmittel-Anzeige bleibt ein Tagesmittel. Ladeziel und Leistung bleiben in deinen Einstellungen; eine optionale PV-Prognose ist vorhanden, ein gelerntes Verbrauchsprofil nicht. Bei unvollständigen Tagespreisen wird die automatische Entladesperre freigegeben. Es gibt keine feste App-Reserve. Geräteeigene Entladegrenzen bleiben unverändert und können die nutzbare Energie begrenzen. Starke Lastsprünge, Preis-/Messlücken und Kommunikationsausfälle begrenzen die Genauigkeit. Einmalige Ladungen und normale PV-Ladung bleiben getrennt.

Es wird **keine feste Mindestreserve** mehr abgezogen. Alte `reserve_soc`-Werte in vorhandenen Konfigurationsdateien werden beim Laden automatisch auf 0 normalisiert und haben keinen Einfluss mehr. Das Einstellungsfeld entfällt. Beispiel: 48 % bei 10 kWh ergeben rechnerisch 4,8 kWh im Akku und mit `sqrt(0,85)` rund 4,43 kWh nach Entladeverlusten. Das ist eine Modellschätzung vor geräteeigenen Entladegrenzen; deren Schutzparameter werden weder geändert noch umgangen.

Zurückgehalten wird nur Energie für den erwarteten Bedarf späterer eingeplanter Stunden. Beispiel: Bei 5 kWh verfügbarer Energie, 500 W Grundverbrauch und 2 kWh Zusatzbedarf von 18–20 Uhr mit den höchsten Preisen werden 3 kWh für diese zwei Stunden eingeplant. Die übrigen 2 kWh dürfen die anderen teuersten Stunden abdecken, auch vor der Spitze. Die Anzeige benennt die für spätere Planstunden vorgesehene Energiemenge statt einer dauerhaften Reserve. Reicht der Speicher insgesamt nicht für den erwarteten Bedarf, kann die App keine vollständige Deckung garantieren.

Für einen erwarteten Mehrverbrauch gibt es **Täglicher Zusatzverbrauch (kWh)** und ein Zeitfenster. Beispiel: 2 kWh Kochen von 17 bis 19 Uhr werden als zusätzlich 1 kW während dieser zwei Stunden eingeplant. Der normale Grundverbrauch kommt hinzu und darf diesen Zusatz nicht bereits enthalten. Standardwert 0 lässt das bisherige Modell unverändert. Die Planung verteilt verfügbare Energie nach vermiedenen Stromkosten, gewichtet den Referenzpreis mit der eingeplanten Energie und berücksichtigt den Zusatzbedarf erneut bei jeder Berechnung. Ein fester Leistungsabruf oder eine garantierte Versorgung dieses Verbrauchers ist damit nicht verbunden.

Nach den letzten reservierten Entladestunden darf tatsächlich verbliebene Energie bis zur geräteeigenen Entladegrenze normal genutzt werden. Diese Abschnitte sind im Diagramm als **Restenergie frei · Gerätegrenzen gelten** gekennzeichnet. Sie enthalten keine zusätzlich erfundene Energiemenge und erhöhen weder die SOC-Prognose noch die berechnete Ersparnis. Die App setzt dafür keinen zusätzlichen festen SOC-Stopp. Eine manuelle Sperre hat weiterhin Vorrang.

Die Vorschau umfasst schon tagsüber die kommende Nacht und den nächsten Tag, soweit vollständige Preise verfügbar sind. Das gesamte Nachtfenster bleibt bei aktivem Smart-Entladen gesperrt, auch zwischen Ladeabschnitten und nach Ladeende. Für die nächste Nacht wird der SOC nach der bis dahin geplanten Entladung geschätzt; eine manuelle Entladesperre wird in dieser Vorschau berücksichtigt. Aktueller und prognostizierter SOC werden getrennt angezeigt. Der nächste Tagesplan verwendet diesen prognostizierten SOC plus die tatsächlich eingeplante Ladeenergie. Die Steuerung berechnet später mit aktuellen SOC-Werten neu. Dafür wurden keine zusätzlichen Messabfragen eingeführt. Bei fehlenden Folgetagespreisen erscheint ein Hinweis statt erfundener Entladeabschnitte.

Alle Einstellungsfelder haben ein per Tippen oder Tastatur aufklappbares **?** mit Einheiten, Beispielen und Auswirkungen. Die Kapazitäts-, Wirkungsgrad- und Zusatzverbrauchsfelder erläutern ausdrücklich die unterschiedlichen Energiemengen.

Im Diagramm: **Grün ↗ Laden**, **Orange ↘ Entladung freigegeben**, **Violett Ⅱ Entladung pausiert**. Das sind geplante Aktionen, keine aufgezeichneten Schaltbestätigungen. Der schmale Zeitstreifen zeigt Teilintervalle. Eine Tagesvorschau nach nächtlicher Ladung verwendet den prognostizierten SOC und kann sich ändern.

### Statistik

Heute, gestern, letzte 30 und 365 Kalendertage einschließlich heute, Monats- und Jahresübersichten. Die Statistik verwendet ausschließlich **angeforderte Ladeleistung und Laufzeit sowie den berechneten Preisvorteil**. Dafür werden keine zusätzlichen Batterie- oder PV-Messwerte gelesen. Im Modus Aus ohne Entladesperre gibt es keine Hintergrundabfragen für die Statistik. Die für aktive Steuerung und Freigaben notwendigen Prüfungen bleiben bestehen; Bildschirmwerte werden weiterhin nur bei sichtbarer Webseite angefragt.

`plan-history.sqlite3` speichert die zeitlich begrenzten Ladeaufträge. Erneuerte Befehle ersetzen ihren überlappenden Vorgänger, ein Stopp kürzt den Auftrag. Nur bereits verstrichene Auftragszeit zählt; ein bloß vorgemerkter Smart-Slot wird nicht als Ersparnis verbucht. Jeder Auftrag endet spätestens nach seiner angeforderten Laufzeit, auch wenn der Webdienst ausfällt. Der erwartete spätere Preisvorteil wird dem **Tag der Ladung** zugeordnet. Fehlende Preise führen zu unbewerteter Planenergie, nicht zu erfundenen Euro-Beträgen. Alte Messstatistiken in `history.sqlite3` bleiben unangetastet und werden nicht mit den Planwerten vermischt.

Die Schätzung nimmt vollständige Netzladung mit der angeforderten Leistung und spätere Nutzung zum berechneten Referenzpreis an. Das Modell verteilt den Gesamtwirkungsgrad gleichmäßig auf beide Richtungen (`sqrt(eta)`) und berücksichtigt die Verschleißreserve. Tatsächliche Leistung, PV-Anteile und tatsächliche Entladung werden dafür nicht geprüft. Auch negative Planvorteile bleiben sichtbar. Es ist kein gemessener Einsparungs- oder Rechnungsnachweis. Einstellungen gelten ab Änderung; alte Werte werden nicht nachträglich umgerechnet. Die Erfassung lässt sich in den Einstellungen abschalten.

### Einstellungen während des Betriebs

Grundverbrauch, Zusatzbedarf, Ladeziel/-leistung, Preisgrenzen, Wirkungsgrad, Tibber-Zugang und Anzeigeoptionen lassen sich auch bei aktivem Smart oder manueller Entladesperre speichern. Der Controller übernimmt validierte Änderungen im nächsten regulären Steuerungszyklus, normalerweise nach etwa zehn Sekunden (laufende Gerätekommunikation kann dies verzögern). Die Vorschau kann die neuen Werte deshalb vor der tatsächlichen Übernahme zeigen. Das Ereignis `settings_applied` bestätigt die Übernahme.

Ein laufender Ladebefehl wird bei geänderten Steuerungswerten zuerst gestoppt und anschließend neu bewertet. Laufzeitgrenzen und manuelle Sperren werden nicht zurückgesetzt. Das individuelle Ziel und der Endzeitpunkt eines bereits geplanten Auftrags bleiben erhalten. Ein neuer allgemeiner Ziel-SOC gilt für Smart und manuelles An; geplante Einzelaufträge behalten ihr eigenes Ziel. Wird eine laufende Sitzung durch eine verkürzte Sicherheitsgrenze unzulässig, endet sie mit einer Fehlermeldung.

Nur tatsächlich geänderte Geräteverbindungsdaten (IP, Port, Unit-ID, Seriennummer, Huawei-Zugang, WLAN-Prüfung) benötigen weiterhin Aus, einen beendeten Vorgang und bestätigte Freigabe. Sonst könnte die App den alten Speicher während einer Sperre nicht mehr erreichen. Ein externer CLI-Controller und laufende Softwareupdates sperren das Speichern weiterhin. Unveränderte Verbindungsfelder verhindern keine anderen Änderungen. Im Browser werden nur geänderte Felder gesendet; leere Geheimnisse behalten ihren gespeicherten Wert.

Unveränderte Entladesperren benötigen jetzt nur eine Kontrollabfrage pro Abgleich statt zwei. Nach einer Änderung am Gerät bleibt die zusätzliche Bestätigungsabfrage bestehen. Für die Statistik entstehen weiterhin keine Messabfragen.

### Verbleibende Grenzen der Planung

Die Rechnung kennt kein gelerntes Lastprofil. Die optionale PV-Prognose modelliert eine Dachfläche mit Sicherheitsabschlag. Die Geräte-Untergrenze muss passend zum Wechselrichter eingestellt werden (nur Rechenwert, vorbelegt mit 5 %); sie wird im gemeinsamen PV-Plan vom nutzbaren SOC abgezogen. Eingestellter Grund- und Zusatzverbrauch sowie Wirkungsgrad bleiben Annahmen. Die Optimierung erfolgt innerhalb des eingestellten Nachtfensters und ist kein frei über 24 Stunden optimierter Ladeplan.

Eine Entladesperre wird durch Wiederherstellen des ursprünglichen maximalen Entladewerts aufgehoben. Anders als ein auf zwei Minuten begrenzter Ladeauftrag hat dieser Gerätewert keine autonome Ablaufzeit. Bei ausgefallenem Server oder unterbrochener Verbindung kann die Sperre deshalb bis zur erfolgreichen Wiederherstellung bestehen bleiben. Das Journal wird dafür dauerhaft gespeichert; eine lokale Kontrolle kann notwendig sein. Nach einem Neustart beginnt der Webdienst im Modus Aus, automatische Fortsetzung von Smart ist noch nicht vorgesehen.

### Updatebutton

Unter **Einstellungen → Software → Prüfen & aktualisieren** holt die App den aktuellen `main`-Stand von `famnex/luna-tibber`, prüft ihn und startet den Webdienst neu. Dafür muss die App über den mitgelieferten systemd-Benutzerdienst `luna-web.service` laufen. Einmalig diese Version installieren:

```bash
cd ~/apps/luna-tibber
git pull --ff-only && systemctl --user restart luna-web
```

Danach die Webseite neu laden. Für Updates auf **Aus** schalten, eine manuelle Entladesperre aufheben und laufende Vorgänge/Freigaben abwarten. Während des Updates werden neue Steuerungsaufträge gesperrt. Es gibt eine Fortschrittsanzeige mit Spinner; nach erfolgreichem Neustart lädt die Webseite neu. Das Update läuft unabhängig vom Browser weiter.

Der Updater akzeptiert nur den erwarteten Git-Ursprung, Branch `main`, einen sauberen Arbeitsstand und Fast-Forward-Updates. Lokale Codeänderungen führen zum Abbruch und werden nicht überschrieben. Konfiguration, Anmeldung, Preise und Statistiken bleiben lokal erhalten. Python-Abhängigkeiten werden bei unveränderten Requirements wiederverwendet; bei Änderungen wird eine separate Umgebung vorbereitet. Ein bereits installiertes Push-Paket wird berücksichtigt. Python selbst wird dabei nicht neu kompiliert oder aktualisiert.

Syntaxprüfung und Python-Tests laufen vor der Übernahme in einem separaten Git-Arbeitsverzeichnis. Nach dem Neustart werden Prozess und installierter Git-Stand am lokalen Webdienst geprüft. Bei fehlgeschlagener Aktivierung versucht der Updater, den vorherigen Code und die vorherige Python-Umgebung wiederherzustellen. Bei Stromausfall oder beschädigtem System ist manuelle Wiederherstellung gegebenenfalls notwendig. Status steht in der App, Details in `update.log`. Abhängigkeitsänderungen können auf dem Pi länger dauern. `.updates` enthält die vorbereiteten bzw. vorherigen Umgebungen; nicht löschen, solange `.venv` darauf verweist.

### PWA und Push

Siehe [PWA.md](PWA.md). PWA-Manifest, App-Symbole, Service Worker und Web Push sind enthalten. Für iPhone-Push ist eine installierte Home-Screen-App über vertrauenswürdiges HTTPS erforderlich. Eine gewöhnliche HTTP-LAN-IP bietet diese Möglichkeit nicht. Ohne HTTPS bleibt die bisherige Weboberfläche verwendbar.

Push ist pro Browser ausdrücklich opt-in. Wichtige Ereignisse: Steuerungsfehler, unbestätigter Stopp/Freigabe, länger fehlende Messwerte/Preise und Abschluss eines einmaligen Ladeauftrags. Normale Smart-Ein/Aus-Wechsel bleiben still. Wiederholte Fehlermeldungen werden 30 Minuten unterdrückt; Abonnements und Zeitpunkte bleiben nach Neustart erhalten. Der Dienst sendet an die Push-Infrastruktur des Browsers, keine Tibber- oder Huawei-Zugangsdaten. Zustellung ist best effort und ersetzt die Statusprüfung nicht.


## PV-Prognose in Smart

Unter **Einstellungen → PV-Prognose** Standort als Breitengrad/Längengrad,
Modulleistung in kWp, Dachneigung und Ausrichtung eintragen, dann aktivieren.
Die Standardwerte für Standort und Dach sind Platzhalter, keine erkannten Anlagendaten.
Ausrichtung: 0° Süd, −90° Ost, +90° West, ±180° Nord. Eine gemeinsame Dachfläche;
unterschiedliche Ost-/Westflächen derzeit nicht zusammen als Südanlage eintragen.
Grundverbrauch und Akkukapazität müssen gesetzt sein.

Quelle: [Open-Meteo Forecast API](https://open-meteo.com/en/docs), stündliche
`global_tilted_irradiance` (Mittel der **vorherigen** Stunde), UTC-Unixzeiten.
Standort, Neigung und Ausrichtung gehen an den Wetterdienst, keine Huawei-/Tibber-Zugangsdaten.
Wetterdaten CC BY 4.0; die freie API ist für nichtkommerzielle Nutzung vorgesehen.
Das einfache Modell rechnet `kWp × Einstrahlung / 1000 × 0,85`, begrenzt auf die
PV-Ausgangsleistung, anschließend multipliziert mit dem konfigurierten Prognose-Anteil.
Standard 0,7 bedeutet zusätzlich 30 % Sicherheitsabschlag. Kein Verschattungs-,
Schnee-, Temperatur- oder individuelles Modulmodell; keine Ertragsgarantie.

Bei aktivierter Smart-Entladung und vollständiger Preis-/PV-Prognose planen Laden
und Entladen gemeinsam vom aktuellen SOC bis zum Ende des Folgetags. Der Plan
minimiert erwartete Bezugskosten einschließlich Lade-/Entladeverlusten und Verschleiß;
der Mindestvorteil wird als zusätzlicher Kostenaufschlag für Netzladung berücksichtigt.
Netzladung bleibt auf das Nachtfenster und die Kaufpreisgrenze beschränkt.
PV deckt zuerst den zeitgleichen Hausbedarf; Überschüsse erreichen den Akku erst im
jeweiligen Erzeugungsintervall, begrenzt durch Ladeleistung und SOC-Obergrenze.
Dadurch kann Nachtladung den Morgen vor ausreichender Sonne überbrücken, ohne den
Speicher unnötig für den späteren Solarertrag vollzuladen. Nachts gibt es in diesem
Plan keine pauschale Entladesperre: Bestand darf verbraucht werden, wenn es im
Gesamtplan günstiger ist. Manuelle Entladesperren bleiben vorrangig.

Die Berechnung verwendet 81 SOC-Stützstellen mit kontinuierlichen Energiebilanzen
und ist eine Näherung, keine Garantie eines mathematisch exakten Optimums. Es gibt
keine zusätzlichen Wechselrichterabfragen. Fehlende/veraltete Wetterdaten werden als null Solarertrag gerechnet; bei fehlenden Tagespreisen wird die Entladung vorläufig gesperrt. Ohne aktivierte
Smart-Entladung bleibt die bisherige Ladezielberechnung erhalten.

Die Übersicht, die farbigen Diagrammabschnitte und die Steuerung verwenden denselben
Plan. Der Preisvorteil dieses Plans vergleicht mit einer Planung ohne zusätzliche
Netzladung bei gleichem Anfangsakku, Wetter und Verbrauch. Die bestehende Statistik
bleibt eine Schätzung aus angeforderten Ladebefehlen. An und Geplant bleiben unverändert.
Keine dauerhafte zusätzliche SOC-Reserve. Der automatisch berechnete Morgenpuffer gilt am Nachtende für die Versorgung bis zur ausreichenden PV.
Er darf anschließend verbraucht werden. Die Geräte-Untergrenze wird im gemeinsamen
Plan berücksichtigt (vorbelegt 5 %, bitte mit der tatsächlichen Einstellung abgleichen).
Es wird kein entsprechendes Gerätegrenzen-Register geschrieben.

### Automatisch benötigte Energie schützen
In Smart mit aktivierter Entladeoptimierung und PV-Planung wird die aktuell für
spätere Verbrauchszeiten benötigte Energie aus derselben zukünftigen Kostenkurve
berechnet wie der Ladeplan. Entscheidend sind Grund-/Zusatzverbrauch, Preise,
zeitlich verfügbare PV, Verluste, Gerätegrenze und mögliche Netzladeabschnitte.
Die Schutzgrenze hängt nicht vom momentanen SOC ab (innerhalb der eingestellten
SOC-Obergrenze): Unerwarteter Mehrverbrauch darf die benötigte Menge nicht einfach
mit nach unten ziehen. Der tatsächliche SOC bestimmt, ob noch Überschuss verfügbar
ist. Auch bei gleichen Preisen bleibt der modellierte spätere Hausbedarf geschützt.

Sobald der SOC die berechnete Grenze einschließlich Reaktionsabstand erreicht,
sperrt Smart die gesamte Entladung. Ein Auto wird nicht erkannt und muss nicht
angemeldet werden; keine Autoladezeiten und kein manuelles Mindest-SOC erforderlich.
Überschuss darf nach dem Preisplan genutzt werden. Die Grenze sinkt bzw. steigt
mit fortschreitender Zeit, Nachlademöglichkeiten, Preisen und Wetter. Vorgesehene
Netzladung ist eine Prognose, keine bereits vorhandene Energie; die Steuerung
berechnet aus jedem tatsächlichen SOC neu. Die vorhandene manuelle Entladesperre
bleibt vorrangig. Aus beendet Smart und damit diesen automatischen Schutz.

Intern wird ein Reaktionsabstand aus mindestens 1 % der Kapazität oder 30 Sekunden
bei 5 kW Entladung verwendet (größerer Wert). Die Freigabe hat einen zusätzlichen
Abstand, damit nicht ständig umgeschaltet wird. Die bestehenden Messzyklen bleiben
unverändert; es entstehen keine zusätzlichen Geräteabfragen. Es ist kein Schutz
gegen unbegrenzt lange Verbindungs-/Programmausfälle oder externe Änderungen.

Der Morgenbedarf enthält automatisch 10 % Wetter-/Verbrauchszuschlag. Diese
Energie darf später verbraucht werden; es gibt keine dauerhafte App-Reserve.
Alte Autoladezeit- und manuelle Puffer-Einstellungen werden beim Laden der
Konfiguration entfernt. Die Geräte-Untergrenze bleibt als Anlagenparameter
(vorbelegt 5 %, muss zum Wechselrichter passen), nicht als frei gesetztes
Morgen-SOC. Kein Gerätegrenzen-Register wird dadurch verändert.

Fehlt eine gültige PV-Prognose, wird konservativ ohne Solarertrag gerechnet.
Sind die nächsten Nachtpreise noch nicht veröffentlicht, bleibt ein vollständiger
bekannter Tagesplan aktiv; die nächste Nacht wird ausdrücklich als offen markiert.
Fehlen selbst die benötigten Tagespreise, wird in der PV-Smart-Steuerung vorläufig
gesperrt, bis eine belastbare Berechnung wieder möglich ist. Eine nicht erreichbare
Morgenversorgung erscheint als Planlücke; Kaufpreisgrenze und SOC-Obergrenze bleiben
verbindlich. Prognoseabweichungen sind weiterhin möglich.

Die Übersicht zeigt benötigte kWh, aktuelle Sperrgrenze, verfügbaren Überschuss und
Sperrstatus. Die dunkle Karte zeigt die konfigurierte SOC-Obergrenze. Der erwartete
Nachtend-SOC steht separat; der Ablauf enthält Zeitfenster, Mengen, Preise und Gründe.

Der gemeinsame Cache `pv-forecast.json` wird alle 3 Stunden erneuert, bei Fehlern
frühestens nach 15 Minuten erneut versucht. Nach 6 Stunden oder bei unpassenden
Anlagendaten wird er nicht mehr angerechnet. Fehlende Tagesintervalle führen zu
Planung ohne PV-Abzug. Web-Hintergrunddienst und CLI-Steuerung nutzen denselben
Cache mit Dateisperre; Browseransichten lesen nur den Cache. Keine zusätzlichen
Wechselrichterabfragen, keine neue Python-Abhängigkeit. Prognose-/Lockdateien sind
Git-ignoriert und blockieren den Updater nicht.

Die Smart-Entscheidungskarte bewertet die ausgewählten Nachtladeabschnitte
energiegewichtet statt des Strompreises beim Seitenaufruf. Bei keinem Ladebedarf
oder unvollständiger Planung wird der entsprechende Grund angezeigt; ein künftiger
Plan wird weiterhin nicht vorab als statistische Ersparnis verbucht.


### Gerätestandort und PV-Linie

In den PV-Einstellungen übernimmt **Gerätestandort übernehmen** einmalig den Standort
des Browsers (Handy/PC). Nur am tatsächlichen Anlagenstandort verwenden. Der Browser
fragt seine Standortberechtigung ab; die App zeigt die gemeldete Genauigkeit und trägt
die Koordinaten auf vier Nachkommastellen gerundet in das Formular ein. Erst
**Einstellungen speichern** übernimmt sie dauerhaft. Kein laufendes Standorttracking,
keine automatische Übernahme bei späteren Besuchen und keine IP-basierte Ersatzortung.

Browser-Geolocation benötigt einen vertrauenswürdigen HTTPS-Kontext. Über eine
LAN-Adresse mit HTTP funktioniert dies insbesondere auf dem iPhone nicht; die App
zeigt den Grund. Manuelle Koordinaten bleiben als Alternative verfügbar. Siehe
[Browser-Geolocation](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API).

Im Tibber-Diagramm bleibt die linke Achse **ct/kWh**, die goldene PV-Prognoselinie
verwendet rechts **kW**. Es sind konservative stündliche Mittelwerte einschließlich
der eingestellten Abschläge, keine gemessene Leistung und keine kWh pro Balken.
Die Linie ist stufig, um keine feinere Zeitauflösung vorzutäuschen; Datenlücken werden
nicht verbunden oder als Null ausgegeben. Beim Fokus/Antippen eines Preisbalkens steht
zusätzlich die PV-Leistung des zugehörigen Intervalls. Die Linie ist bei aktivierter
PV-Prognose auch im Modus Aus sichtbar; sie nutzt ausschließlich denselben Wettercache.


### Standort über PLZ (auch ohne Browser-HTTPS)

Unter **Einstellungen → PV-Prognose** steht **Postleitzahl (Deutschland)**.
Fünfstellige PLZ eingeben → **PLZ suchen** → passenden Ort auswählen →
**Einstellungen speichern**. Führende Nullen bleiben erhalten. Kein Adressfeld nötig.
Die Suche allein ändert weder Konfiguration noch Steuerung; nach Auswahl werden
nur die Koordinaten als Formularentwurf übernommen. Gespeichert werden die Koordinaten,
nicht die PLZ-Suchanfrage. Der Ortspunkt ist eine Näherung für die Wetterprognose.

Nur beim Suchklick fragt der Server [Zippopotam.us](https://docs.zippopotam.us/docs/getting-started/)
mit der PLZ und Ländercode DE ab (Ortsdaten: GeoNames). Die Browserverbindung zur App
kann dafür lokales HTTP sein. Keine Standortfreigabe und kein API-Schlüssel nötig.
Antworten werden im Serverprozess zwischengespeichert. Ergebnisse werden zusätzlich
auf das Land und die exakte PLZ geprüft. Suchfehler oder mehrere Treffer übernehmen
keine Koordinaten automatisch; die normalen Speicherabfragen werden nicht beeinflusst.
