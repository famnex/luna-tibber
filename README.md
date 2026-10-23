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
Dies ist eine erste technische Version, kein fertiger Ertragsoptimierer. Keine PV-Prognose,
keine Verbrauchsprognose und keine automatische Entladesperre für günstige Stunden. Der Wechselrichter entscheidet außerhalb unserer Ladebefehle weiter selbst
über die Entladung. Ein billiger Einkauf allein garantiert daher keine Einsparung.

Huawei beschreibt erzwungenes Laden als Wartungs-/Testfunktion und empfiehlt für
regelmäßige Zeitfenster TOU. Zuerst den lokalen Test und das Verhalten neben Enpal prüfen.
Das Programm verändert weder Netzschutz noch Einspeiselimit, TOU, AC-Freigabe oder die
angezeigten Netzladegrenzen. Es löst ausschließlich zeitlich begrenztes Laden und Stopp aus.
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

Alle 20 Sekunden werden SOC/Status geprüft; Preise werden alle fünf Minuten abgefragt.
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
im eingestellten Fenster an und kennt weder dessen Energiemenge noch PV-Ertrag.
Insbesondere verhindert das Programm keine frühere Entladung durch Enpal.
Den Rechner daher nicht mit einer garantierten Einsparung verwechseln. Lade nur die Menge,
die später tatsächlich teuren Netzstrom ersetzt. Ein hoher Nacht-SOC kann sonst günstigen
Solarstrom verdrängen; frühes Entladen vor dem teuren Zeitfenster kann den Nutzen ebenfalls
aufheben. PV-/Verbrauchsprognose und koordiniertes Entladen sind nächste Ausbauschritte.

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
Die Software schreibt ausschließlich die vier Register für erzwungene Ladeleistung,
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
