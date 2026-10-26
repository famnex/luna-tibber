'use strict';
const $=id=>document.getElementById(id);
let initialized=false,busy=false,refreshing=false,settingsDirty=false,settingsBaseline={},chartSignature="",lastStatus=null,chosenMode=null,modeDirty=false,pendingButton=null;
const labels={battery_idle_w:"Akku-Eigenverbrauch (W, Schätzung)",battery_floor_soc:'Geräte-Untergrenze SOC (%) – nur Berechnung',pv_enabled:'PV-Prognose berücksichtigen',pv_latitude:'Breitengrad',pv_longitude:'Längengrad',pv_kwp:'PV-Leistung dieser Dachfläche (kWp)',pv_tilt:'Dachneigung (Grad)',pv_azimuth:'Ausrichtung (0 Süd, −90 Ost, +90 West)',pv_ac_limit_kw:'Maximale PV-Ausgangsleistung (kW)',pv_factor:'Prognose-Anteil (0–1, z. B. 0.7)',smart_discharge_enabled:'Smart: Entladung optimieren',base_load_w:'Erwarteter Grundverbrauch (W)',extra_load_kwh:'Täglicher Zusatzverbrauch (kWh)',extra_load_start_hour:'Zusatzverbrauch ab Stunde',extra_load_end_hour:'Zusatzverbrauch bis Stunde',statistics_enabled:'Planersparnis speichern (ohne Messabfragen)',push_contact:'Kontakt-E-Mail für Push',battery_capacity_kwh:'Nutzbare Akkukapazität gesamt (kWh, erforderlich für Smart)',host:'Wechselrichter-IP',port:'Port',unit_id:'Unit-ID',expected_serial:'Wechselrichter-Seriennummer',username:'Huawei-Benutzername',password:'Huawei-Installateurpasswort',tibber_token:'Tibber Personal Access Token',tibber_home_id:'Tibber Zuhause-ID (bei mehreren Zuhause)',max_buy_ct_kwh:'Maximaler Kaufpreis (ct/kWh)',target_soc:'Ziel-Akkustand (%)',charge_power_w:'Angeforderte Ladeleistung (W)',max_session_minutes:'Maximale Ladesitzung (Minuten)',roundtrip_efficiency:'Gesamtwirkungsgrad (z. B. 0.85)',wear_ct_kwh:'Verschleißreserve (ct/kWh)',min_saving_ct_kwh:'Mindestvorteil (ct/kWh)',use_start_hour:'Verbrauchsfenster ab Stunde',use_end_hour:'Verbrauchsfenster bis Stunde',night_start_hour:'Nachtvergleich ab Stunde (0–23)',night_end_hour:'Nachtvergleich bis Stunde (1–24)',timezone:'Zeitzone',wifi_enabled:'WLAN-Profil vor Laden prüfen'};
const types={};
const modes={off:'Aus',smart:'Smart',on:'An',schedule:'Zeitplan',planned:'Geplant'};
const ct=n=>typeof n==='number'?n.toLocaleString('de-DE',{maximumFractionDigits:2})+' ct/kWh':'—';
async function api(action,data){const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Luna':'1'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw new Error(d.error);return d;}
function showBusy(active,text='Bitte warten …',button=null){$('progressbar').hidden=!active;$('progresstext').textContent=text;if(button){button.classList.toggle('button-loading',active);button.setAttribute('aria-busy',String(active));}}
let noticeTimer;
function notify(s,kind='success'){clearTimeout(noticeTimer);$('notice').textContent=s;$('notice').dataset.kind=kind;if(kind==='success'&&s)noticeTimer=setTimeout(()=>{$('notice').textContent='';},5000);}
const actionLabels={discharge:'Entladung ändern','push-test':'Testnachricht senden',settings:'Einstellungen speichern',schedules:'Zeitpläne speichern',planned:'Ladeauftrag planen',probe:'Gerät auslesen',test:'Ladetest starten','adopt-serial':'Seriennummer übernehmen',mode:'Steuerung umschalten'};
async function perform(name,data={},button=null){if(busy)return false;busy=true;pendingButton=button;showBusy(true,(actionLabels[name]||'Aktion')+' …',button);document.body.classList.add('working');const buttons=[...document.querySelectorAll('#dashboard button')];buttons.forEach(b=>b.disabled=true);$('dashboard').setAttribute('aria-busy','true');notify('');try{await api(name,data);if(['mode','planned','test','discharge'].includes(name))watchChange(name,data);if(name==='mode'||name==='planned'){modeDirty=false;chosenMode=name==='planned'?'planned':data.mode;}notify(name==='probe'||name==='test'?'':name==='settings'?'Gespeichert · laufende Steuerung übernimmt Änderungen im nächsten Zyklus.':name==='planned'?'Ladeauftrag eingeplant. Start und Ende stehen unten.':name==='mode'&&data.mode==='off'?'Stopp angefordert. Bestätigung im Gerätestatus abwarten.':'Änderung übernommen.');if(name==='settings'){settingsDirty=false;initialized=false;}await refresh();return true;}catch(e){notify(e.message,'error');return false;}finally{showBusy(false,'',pendingButton);pendingButton=null;busy=false;buttons.forEach(b=>b.disabled=false);if(lastStatus)renderUpdate(lastStatus.update,lastStatus);document.body.classList.remove('working');$('dashboard').setAttribute('aria-busy','false');}}

const settingHelp={
 battery_idle_w:'Zusätzlicher kontinuierlicher Verbrauch auf der Batterieseite, auch bei Entladesperre. Vorläufig 100 W aus dem beobachteten SOC-Rückgang; kein gemessener Herstellerwert. 100 W über 6 Stunden entsprechen 0,6 kWh. Nicht zusätzlich im Haus-Grundverbrauch eintragen. Nur Verluste ansetzen, die nicht bereits im Gesamtwirkungsgrad enthalten sind. 0 deaktiviert den Zusatz.',
 battery_floor_soc:'Trage die im Wechselrichter eingestellte Entlade-Untergrenze ein (bei deinem Screenshot 5 %). Dieser Anteil steht rechnerisch nicht für den Hausverbrauch zur Verfügung. Die App ändert diese Geräteeinstellung nicht.',

 pv_enabled:'Nutzt Open-Meteo-Wetterdaten für eine Dachfläche. Standort und Dachparameter werden an Open-Meteo übertragen, keine Zugangsdaten. Aktivierung benötigt kWp, Grundverbrauch und Akkukapazität. Wirkt nur auf Smart; An und Geplant behalten ihre Ziele.',
 pv_latitude:'Breitengrad deiner Anlage als Dezimalzahl, z. B. 51.2. Aus einer Karte übernehmen. Über „Gerätestandort übernehmen“ kannst du den Standort dieses Handys/PCs einmalig einsetzen (HTTPS und Browserfreigabe nötig). Der Standort wird für die Wetterprognose an Open-Meteo gesendet.',
 pv_longitude:'Längengrad deiner Anlage als Dezimalzahl, z. B. 10.0. Westliche Längen sind negativ. Erst den tatsächlichen Standort eintragen, dann die Prognose aktivieren.',
 pv_kwp:'Installierte Modulleistung in kWp für eine gemeinsame Ausrichtung und Neigung. Nicht die Akkukapazität oder Wechselrichterleistung. Mehrere unterschiedlich ausgerichtete Dachflächen werden in dieser Version noch nicht getrennt modelliert.',
 pv_tilt:'Neigung der Module gegen die Horizontale: 0 ist flach, 90 senkrecht. Der voreingestellte Wert 30 ist ein Platzhalter und muss zu deiner Anlage passen.',
 pv_azimuth:'Ausrichtung nach Open-Meteo-Konvention: 0 = Süden, −90 = Osten, +90 = Westen, ±180 = Norden. Nicht die Kompassskala 0 = Norden verwenden.',
 pv_ac_limit_kw:'Obergrenze der nutzbaren PV-Ausgangsleistung in kW. Beim SUN2000-5KTL-M1 hier konservativ 5. Sie begrenzt nur die Prognose und verändert keine Einstellung im Wechselrichter.',
 pv_factor:'Welchen Anteil des modellierten Ertrags Smart anrechnet. 0.7 nutzt 70 %, also 30 % Sicherheitsabschlag. Zusätzlich rechnet das einfache Modell mit 15 % Anlagenverlusten. Verschattung, Schnee und individuelle Modulwerte werden nicht automatisch erkannt.',

 smart_discharge_enabled:'Smart hält Energie für teure Stunden zurück und gibt die normale Entladung frei. Während des gesamten Nachtfensters bleibt die Entladung gesperrt, auch nach Ladeende. Nach den eingeplanten Entladestunden darf verbleibende Energie bis zur normalen Geräteabschaltung genutzt werden. Nur im Modus Smart aktiv; eine manuelle Sperre hat Vorrang.',
 base_load_w:'Erwarteter laufender Hausverbrauch ohne den unten eingetragenen Zusatzverbrauch. Beispiel: 500 W benötigen in zwei Stunden 1 kWh. Es wird ein gleichmäßiger Verbrauch angenommen, keine zusätzliche Messung gestartet. Bei aktivierter PV-Prognose wird erwartete direkte Solardeckung abgezogen.',
 extra_load_kwh:'Zusätzliche Energie pro Tag, z. B. 2 kWh zum Kochen. Sie wird zusätzlich zum Grundverbrauch gleichmäßig auf das eingestellte Zeitfenster verteilt. 0 deaktiviert den Zusatzbedarf. Dies beeinflusst die Auswahl teurer Entladestunden, garantiert aber weder einen bestimmten Energieertrag noch eine feste Leistung.',
 extra_load_start_hour:'Beginn des täglichen Zusatzverbrauchs in deiner Zeitzone, z. B. 17 für Kochen ab 17 Uhr. Das Zeitfenster muss am selben Kalendertag enden.',
 extra_load_end_hour:'Ende des täglichen Zusatzverbrauchs, z. B. 19. Bei 2 kWh zwischen 17 und 19 Uhr rechnet Smart zusätzlich mit 1 kW in diesem Zeitraum. Nicht auch im Grundverbrauch mitzählen.',
 statistics_enabled:'Speichert geschätzte Preisvorteile aus angeforderten Ladeleistungen, Laufzeiten und Preisen. Keine zusätzlichen Speicherabfragen. Tatsächliche Ersparnis und tatsächlicher Energiefluss werden dafür nicht gemessen.',
 push_contact:'Kontakt-E-Mail zur Kennzeichnung des Web-Push-Dienstes. Keine Empfängeradresse für Meldungen. Benachrichtigungen müssen unten pro Browser aktiviert werden.',
 battery_capacity_kwh:'Gesamte nutzbare Kapazität des Speichers. Bei deinem 10-kWh-Speicher: 10. Nicht den aktuellen Energieinhalt eintragen. Es gibt keine zusätzliche feste App-Reserve. Geräteeigene Entladegrenzen bleiben wirksam.',
 host:'Adresse des Wechselrichters, die der Server erreicht. Bei direktem Geräte-WLAN ist das typischerweise dessen lokale Adresse. Nicht die IP des Raspberry Pi eintragen.',
 port:'Port für die lokale Verbindung zum Wechselrichter. Den bei der Inbetriebnahme erfolgreich getesteten Wert beibehalten.',
 unit_id:'Geräteadresse auf der lokalen Kommunikationsverbindung. Nur ändern, wenn die Geräteauslesung dies erfordert; den getesteten Wert beibehalten.',
 expected_serial:'Erwartete Seriennummer des Wechselrichters. Sie muss mit dem ausgelesenen Gerät übereinstimmen, bevor geschrieben wird. Über Verbindung auslesen und übernehmen.',
 username:'Lokaler Huawei-Benutzername für den Gerätezugriff, üblicherweise installer. Kein Enpal- oder Tibber-Login.',
 password:'Lokales Huawei-Installateurpasswort. Einfügen ist möglich. Leer lassen behält das gespeicherte Passwort; es wird nicht an den Browser zurückgesendet.',
 tibber_token:'Persönlicher Tibber-API-Token zum Abruf deiner Strompreise. Verdeckte Eingabe erlaubt Einfügen. Leer lassen behält einen vorhandenen Token.',
 tibber_home_id:'Kennung des Tibber-Zuhauses. Bei mehreren Zuhause das richtige auswählen bzw. dessen ID eintragen. Bei nur einem Zuhause kann das Feld leer bleiben.',
 max_buy_ct_kwh:'Obergrenze für Smart-Netzladen inklusive Tarifbestandteilen. Zusätzlich müssen Verluste, Verschleißreserve und Mindestvorteil passen. An und Geplant führen keinen Preisvergleich aus.',
 target_soc:'Gewünschter Ladestand. Das individuelle Ziel eines bereits geplanten Auftrags bleibt erhalten. Smart berechnet daraus den Energiebedarf. Mit PV-Prognose ist dies die Obergrenze; ein erwarteter Solarüberschuss kann das nächtliche Ladeziel senken. Für eine zukünftige Nacht berücksichtigt Smart bei aktivierter Entladeoptimierung den vorher geplanten Verbrauch. Der Plan wird mit dem späteren tatsächlichen SOC neu berechnet.',
 charge_power_w:'Angeforderte Ladeleistung in Watt, z. B. 5000 W = 5 kW. Die Gerätelimits gelten weiterhin. Dauer ungefähr = benötigte kWh geteilt durch kW; Kommunikationspausen verlängern das Zeitfenster.',
 max_session_minutes:'Harte Zeitgrenze einer zusammenhängenden Ladesitzung. Eine Überschreitung beendet die Automatik. Änderungen verlängern keinen laufenden Timer. Auch manuelle und geplante Aufträge sind zeitlich begrenzt.',
 roundtrip_efficiency:'Annahme für Laden UND Entladen zusammen: 0,85 bedeutet 85 % bzw. insgesamt 15 % Verlust. Für 1 kWh nutzbare Energie werden rechnerisch 1 / 0,85 kWh eingekauft. Das Modell verteilt Verluste gleichmäßig auf beide Richtungen; kein gemessener Wirkungsgrad.',
 wear_ct_kwh:'Optionaler Rechenaufschlag pro später nutzbarer kWh für Batterieverschleiß. Kein zusätzlicher Strompreis. 0 berücksichtigt nur Energieverluste.',
 min_saving_ct_kwh:'Erforderlicher Vorteil je später nutzbarer kWh nach Verlusten und Verschleiß. Beispiel: 2 bedeutet, dass Smart mindestens 2 ct/kWh Vorteil erwartet.',
 use_start_hour:'Beginn des Verbrauchsfensters für den Preisvergleich, wenn Smart-Entladen ausgeschaltet ist. Bei aktiver Entladeoptimierung werden stattdessen die eingeplanten Entladestunden bewertet.',
 use_end_hour:'Ende des Verbrauchsfensters am selben Tag. Preise werden zeitgewichtet gemittelt. Diese Einstellung hat keinen Einfluss auf die separate 00–24-Uhr-Tagesdurchschnittsanzeige.',
 night_start_hour:'Beginn des täglichen Smart-Ladefensters in lokaler Zeit. Smart darf nur darin laden. Bei aktiver Entladeoptimierung wird innerhalb des gesamten Nachtfensters keine normale Entladung freigegeben.',
 night_end_hour:'Ende des Nachtfensters am selben Tag, z. B. 6 für 06:00 Uhr. Danach beginnt die Tagesplanung. Nach einem früheren Ladeende bleibt die Entladung bis hier gesperrt. Für 00–06 Uhr Start 0, Ende 6 eintragen.',
 timezone:'Zeitzone für Preisdiagramm und Zeitfenster, z. B. Europe/Berlin. Zeitumstellungen werden berücksichtigt; eine Nacht kann dann länger oder kürzer sein.',
 wifi_enabled:'Prüft das separat eingerichtete Geräte-WLAN vor dem Laden. Das WLAN-Profil muss bereits über den Connector auf dem Server eingerichtet sein; dieses Feld verbindet kein beliebiges WLAN neu.'
};
let locating=false;
function useDeviceLocation(button){
 if(locating)return;
 if(!window.isSecureContext){notify('Gerätestandort benötigt eine vertrauenswürdige HTTPS-Verbindung. Über die lokale HTTP-Adresse bitte die PLZ-Suche verwenden oder Koordinaten manuell eintragen.','error');return;}
 if(!navigator.geolocation){notify('Dieser Browser stellt keinen Gerätestandort bereit. Koordinaten bitte manuell eintragen.','error');return;}
 const lat=$('setting-pv_latitude'),lon=$('setting-pv_longitude');
 const before=[lat.value,lon.value];locating=true;button.disabled=true;button.classList.add('button-loading');button.setAttribute('aria-busy','true');
 notify('Standort wird ermittelt · bitte den Browserzugriff erlauben.','info');
 const done=()=>{locating=false;button.disabled=false;button.classList.remove('button-loading');button.setAttribute('aria-busy','false');};
 const failed=error=>{done();notify(({1:'Standortzugriff nicht erlaubt. Bitte in den Browser-/Geräteeinstellungen freigeben oder Koordinaten manuell eintragen.',2:'Standort konnte nicht bestimmt werden. Bitte erneut versuchen oder Koordinaten eintragen.',3:'Standortabfrage hat zu lange gedauert. Bitte erneut versuchen oder Koordinaten eintragen.'})[error?.code]||'Standortabfrage fehlgeschlagen. Koordinaten bitte manuell eintragen.','error');};
 try{navigator.geolocation.getCurrentPosition(position=>{
  done();
  if(button.isConnected===false)return;
  if(lat.value!==before[0]||lon.value!==before[1]){notify('Standortfelder wurden inzwischen geändert. Deine Eingaben bleiben erhalten.','info');return;}
  const {latitude,longitude,accuracy}=position.coords;
  if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||Math.abs(latitude)>90||Math.abs(longitude)>180){failed({});return;}
  lat.value=latitude.toFixed(4);lon.value=longitude.toFixed(4);settingsDirty=true;
  notify('Gerätestandort übernommen'+(Number.isFinite(accuracy)?' · Genauigkeit ca. '+Math.round(accuracy)+' m':'')+'. Nur am Anlagenstandort verwenden. Bitte Einstellungen speichern.','info');
 },failed,{enableHighAccuracy:true,timeout:15000,maximumAge:60000});}catch(error){failed(error);}
}
function postcodeField(){
 const field=document.createElement('div');field.className='setting-field postcode-field';
 const label=document.createElement('label');label.textContent='Postleitzahl (Deutschland)';label.htmlFor='pv-postcode';
 const input=document.createElement('input');input.id='pv-postcode';input.type='text';input.inputMode='numeric';input.maxLength=5;input.autocomplete='postal-code';input.placeholder='z. B. 10115';
 const search=document.createElement('button');search.type='button';search.textContent='PLZ suchen';
 const info=document.createElement('p');info.className='muted';info.setAttribute('role','status');info.textContent='Suche über Zippopotam.us/GeoNames. Nur die PLZ wird übertragen; keine Adresse erforderlich.';
 const results=document.createElement('div');results.className='postcode-results';
 field.append(label,input,search,info,results);
 let loading=false;
 input.oninput=()=>{results.replaceChildren();info.textContent='PLZ suchen und passenden Ort auswählen.';};
 search.onclick=async()=>{
  if(loading)return;
  const postcode=input.value.trim();results.replaceChildren();
  if(!/^[0-9]{5}$/.test(postcode)){info.textContent='Bitte eine fünfstellige deutsche PLZ eingeben.';return;}
  loading=true;search.disabled=true;search.classList.add('button-loading');search.setAttribute('aria-busy','true');info.textContent='Orte zur PLZ werden gesucht …';
  try{
   const data=await api('pv-location',{postcode});
   if(input.value.trim()!==postcode||field.isConnected===false)return;
   if(!data.results?.length){info.textContent='Kein Ort für diese PLZ gefunden. Bitte PLZ prüfen oder Koordinaten manuell eintragen.';return;}
   info.textContent='Passenden Ort auswählen. Die Koordinaten werden erst mit „Einstellungen speichern“ dauerhaft übernommen.';
   for(const place of data.results){
    const choose=document.createElement('button');choose.type='button';choose.textContent=postcode+' '+place.name;
    choose.onclick=()=>{
     if(input.value.trim()!==postcode)return;
     $('setting-pv_latitude').value=Number(place.latitude).toFixed(4);$('setting-pv_longitude').value=Number(place.longitude).toFixed(4);settingsDirty=true;
     info.textContent='✓ '+postcode+' '+place.name+' übernommen · bitte Einstellungen speichern.';results.replaceChildren();notify('Standort übernommen · Einstellungen speichern.','info');
    };results.append(choose);
   }
  }catch(error){if(input.value.trim()===postcode)info.textContent=error.message;}
  finally{loading=false;search.disabled=false;search.classList.remove('button-loading');search.setAttribute('aria-busy','false');}
 };
 input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();search.onclick();}};
 return field;
}
function fillSettings(s,secrets){
 settingsBaseline={...s};const box=$('fields');box.replaceChildren();const sections={};
 const group=k=>k==='battery_floor_soc'?'Gerätegrenze für die Berechnung':k.startsWith('pv_')?'PV-Prognose':['host','port','unit_id','expected_serial','username','password','wifi_enabled'].includes(k)?'Wechselrichter & Verbindung':k.startsWith('tibber')?'Tibber-Zugang':['target_soc','charge_power_w','max_session_minutes','battery_capacity_kwh'].includes(k)?'Ladegrenzen':['battery_idle_w','smart_discharge_enabled','base_load_w','extra_load_kwh','extra_load_start_hour','extra_load_end_hour'].includes(k)?'Smart-Entladung & Bedarf':['statistics_enabled','push_contact'].includes(k)?'Statistik & Benachrichtigungen':'Preise, Vergleich & Zeitzone';
 for(const [key,label] of Object.entries(labels)){
  const field=document.createElement('div');field.className='setting-field';
  const heading=document.createElement('div');heading.className='setting-heading';
  const l=document.createElement('label');l.textContent=label;l.htmlFor='setting-'+key;
  const help=document.createElement('button');help.type='button';help.className='help-button';help.textContent='?';help.setAttribute('aria-label','Hilfe: '+label);help.setAttribute('aria-expanded','false');help.setAttribute('aria-controls','help-'+key);
  const description=document.createElement('p');description.id='help-'+key;description.className='setting-help';description.hidden=true;description.textContent=settingHelp[key];
  help.onclick=()=>{description.hidden=!description.hidden;help.setAttribute('aria-expanded',String(!description.hidden));};
  heading.append(l,help);field.append(heading);
  const i=document.createElement('input');i.name=key;i.id='setting-'+key;i.setAttribute('aria-describedby',description.id);types[key]=typeof s[key];i.type=typeof s[key]==='boolean'?'checkbox':typeof s[key]==='number'?'number':'text';
  if(i.type==='number')i.step='any';if(key==='password'||key==='tibber_token')i.type='password';i.autocomplete='off';
  if(i.type==='checkbox')i.checked=s[key];else i.value=s[key]??'';
  if(key==='password'||key==='tibber_token')i.placeholder=secrets[key]?'Gespeichert – leer lassen zum Behalten':'Noch nicht gespeichert';
  field.append(i,description);
  if(key==='pv_latitude'){const b=document.createElement('button');b.type='button';b.textContent='⌖ Gerätestandort übernehmen';b.onclick=()=>useDeviceLocation(b);field.append(b);}
  if(key==='password'||key==='tibber_token'){const b=document.createElement('button');b.type='button';b.textContent='Anzeigen / verbergen';b.onclick=()=>i.type=i.type==='password'?'text':'password';field.append(b);}
  const g=group(key);if(!sections[g]){const section=document.createElement('details');section.className='card settings-group';const h=document.createElement('summary');h.textContent=g;const grid=document.createElement('div');grid.className='fields';if(g==='PV-Prognose')grid.append(postcodeField());section.append(h,grid);box.append(section);sections[g]=grid;}
  sections[g].append(field);
 }
}
async function refresh(){if(document.hidden||refreshing)return;refreshing=true;try{const r=await fetch('/api/status'+(watch?'?fast=1':''));if(r.status===401){$('connection').textContent='Webinterface erreichbar · bitte anmelden';$('login').hidden=false;$('dashboard').hidden=true;$('logout').hidden=true;return;}if(!r.ok)throw new Error('Status nicht erreichbar');const d=await r.json();if(document.hidden)return;trackTransition(d);lastStatus=d;countdownAnchor=performance.now();renderBatteryCard(d);renderControl(d);renderExtras(d);renderMeterTest(d);renderOverview(d);$('connection').textContent='● Verbunden · aktualisiert '+new Date().toLocaleTimeString('de-DE');$('connection').classList.remove('offline');renderPrices(d);$('login').hidden=true;$('dashboard').hidden=false;$('logout').hidden=false;if(!initialized){fillSettings(d.settings,d.secrets_set);initialized=true;}const p=d.planned;$('plannedstatus').textContent=p?`${p.phase==='waiting'?'Wartet':p.phase==='charging'?'Lädt':p.phase==='completed'?'Beendet':'Fehler'} · ${new Date(p.start).toLocaleString('de-DE',{timeZone:d.settings.timezone})} bis spätestens ${new Date(p.end).toLocaleString('de-DE',{timeZone:d.settings.timezone})} · Ziel ${p.target_soc} %`:'Kein einmaliger Auftrag.';const t=d.telemetry;const age=t.time?(Date.now()-Date.parse(t.time))/1000:null;$('soc').textContent=typeof t.soc==='number'?t.soc.toFixed(1)+' %':'—';$('battery').value=t.soc??0;$('power').textContent=typeof t.battery_power_w==='number'?(t.battery_power_w/1000).toFixed(2)+' kW':'—';$('sampletime').textContent=age===null?'Noch keine Messung':`Letzte Messung vor ${Math.max(0,Math.floor(age))} s${age>90?' · veraltet':''}`;$('price').textContent=ct(d.current_price);$('modebadge').textContent=modes[d.mode];$('activity').classList.toggle('spinning',!!d.job);$('activity').textContent=d.fault?'Steuerung meldet einen Fehler – Details unten.':d.job==='sample'?'Messwerte werden aktualisiert …':d.job==='probe'?'Gerät wird ausgelesen …':d.job==='stop'?'Stopp wird an den Wechselrichter gesendet …':d.job==='charge-test'?'Beaufsichtigter Ladetest läuft …':d.job?(t.eligible?'Ladeauftrag aktiv · '+(t.reason||'Ladung freigegeben'):'Steuerung aktiv · '+(t.reason||'Warte auf Messwerte')):d.mode==='planned'?'Geplant: wartet auf Startzeit.':d.mode==='off'?'Aus: keine automatische oder geplante Ladung durch diese App.':'Wartet auf das nächste Zeitfenster.';if(!busy){for(const [id,job] of [['probe','probe'],['test','charge-test']])$(id).classList.toggle('button-loading',d.job===job);}$('fault').hidden=!d.fault;$('fault').textContent=d.fault;$('missing').hidden=!d.missing.length;$('missing').textContent='Noch einzurichten: '+d.missing.join(', ');$('device').textContent=d.device.serial?`${d.device.model||'Huawei'} · Seriennummer ${d.device.serial}`:'Gerät noch nicht ausgelesen';$('wifi').textContent=d.wifi.interface?`WLAN-Profil: ${d.wifi.interface} · ${d.wifi.ssid} · ${d.wifi.host} (Systemdienst)`:'WLAN-Connector noch nicht eingerichtet';$('commissioned').hidden=d.job==='charge-test';$('commissioned').textContent=d.commissioned?'Ladetest bestätigt.':'Ladetest noch nicht bestätigt.';$('events').textContent=d.events.map(x=>JSON.stringify(x)).join('\n');}catch(e){$('connection').textContent='Verbindung unterbrochen · angezeigte Werte können veraltet sein';$('connection').classList.add('offline');}finally{refreshing=false;scheduleRefresh();}}
$('loginform').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;showBusy(true,'Anmeldung läuft …',b);notify('Anmeldung läuft …','loading');try{await api('login',{password:$('loginpassword').value});$('loginpassword').value='';initialized=false;notify('');await refresh();}catch(err){notify(err.message,'error');}finally{showBusy(false,'',b);b.disabled=false;}};
$('logout').onclick=async()=>{if(settingsDirty&&!confirm('Ungespeicherte Einstellungen verwerfen und abmelden?'))return;notify('Abmeldung läuft …','loading');try{await api('logout',{});initialized=false;settingsDirty=false;notify('Abgemeldet.');await refresh();}catch(e){notify(e.message,'error');}};
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(s=>s.hidden=s.id!==b.dataset.tab);document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('selected',x===b));});
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{chosenMode=b.dataset.mode;modeDirty=true;renderControl(lastStatus);});
$('confirmmode').onclick=async e=>{
 if(!modeDirty||!lastStatus)return;
 if(chosenMode==='planned'){
  if(!$('plannedform').reportValidity())return;
  await perform('planned',{start:$('plannedstart').value,end_kind:$('plannedkind').value,end:$('plannedend').value,target_soc:Number($('plannedsoc').value)},e.currentTarget);
 }else{
  if(chosenMode==='on'&&!$('minutes').reportValidity())return;
  await perform('mode',{mode:chosenMode,minutes:Number($('minutes').value)},e.currentTarget);
 }
 if(lastStatus)renderControl(lastStatus);
};
$('cancelmode').onclick=()=>{modeDirty=false;chosenMode=lastStatus?.mode||'off';renderControl(lastStatus);};

$('dischargemode').onchange=()=>{$('dischargeuntilwrap').hidden=$('dischargemode').value!=='hold';};
$('dischargeform').onsubmit=e=>{e.preventDefault();perform('discharge',{mode:$('dischargemode').value,until:$('dischargeuntil').value},e.submitter);};
function renderDischarge(d){
 const x=d.discharge;if(!x)return;
 const requested=x.request.until&&Date.parse(x.request.until)>Date.now();
 const stamp=x.status.time, fresh=stamp&&Date.now()-Date.parse(stamp)<90000;
 const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:d.settings.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 $('dischargestatus').textContent=requested?(fresh&&x.status.locked?'🔒 Entladesperre bestätigt':'⌛ Entladesperre angefordert / Bestätigung ausstehend')+' · bis '+fmt(x.request.until):x.status.source==='smart'&&fresh&&x.status.locked?'Ⅱ Smart · Energie reserviert':x.restore_pending?'⌛ Entladung freigeben · Wiederherstellung ausstehend':'✓ Aktiv · keine Entladesperre durch diese App';
}
$('metertest').onclick=e=>perform('meter-test',{},e.currentTarget);
$('probe').onclick=e=>perform('probe',{},e.currentTarget);
$('adopt').onclick=async e=>{await perform('adopt-serial',{},e.currentTarget);initialized=false;await refresh();};
$('test').onclick=e=>{if(confirm('Beaufsichtigten Test starten? Maximal 1 kW für zwei Minuten. Netzbezug vor Ort prüfen.'))perform('test',{},e.currentTarget);};
$('settingsform').addEventListener('invalid',e=>{const group=e.target.closest('details');if(group)group.open=true;},true);
$('settingsform').onsubmit=async e=>{e.preventDefault();const data={};for(const i of $('fields').querySelectorAll('input[name]')){const value=i.type==='checkbox'?i.checked:types[i.name]==='number'?Number(i.value):i.value;if((i.name==='password'||i.name==='tibber_token')&&value==='')continue;if(value!==settingsBaseline[i.name])data[i.name]=value;}await perform('settings',data,e.submitter);};
$('plannedkind').onchange=()=>{$('endtimelabel').hidden=$('plannedkind').value!=='time';$('endsoclabel').hidden=$('plannedkind').value!=='soc';$('plannedend').required=$('plannedkind').value==='time';};
$('plannedform').onsubmit=e=>{e.preventDefault();};

$('settingsform').addEventListener('input',e=>{if(e.target.id==='pv-postcode')return;settingsDirty=true;notify('Ungespeicherte Einstellungen · Speichern ist auch während Smart oder einer Entladesperre möglich.','info');});
window.addEventListener('beforeunload',e=>{if(settingsDirty){e.preventDefault();e.returnValue='';}});
function renderPrices(d){
function formatPriceAge(seconds){
 if(typeof seconds!=='number'||!Number.isFinite(seconds))return 'unbekannt';
 const minutes=Math.max(0,Math.floor(seconds/60));
 if(minutes<60)return minutes+' Min.';
 const hours=Math.floor(minutes/60),rest=minutes%60;
 return hours+' Std.'+(rest?' '+rest+' Min.':'');
}

 const comp=$('compareday').value==='auto'?d.comparison:d.comparisons[$('compareday').value];const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:d.settings.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 $('comparedate').textContent='Vergleichstag: '+comp.date+' · Nachtfenster '+fmt(comp.night_start)+' bis '+fmt(comp.night_end);
 $('dayaverage').textContent=ct(comp.day_ct);$('nightaverage').textContent=ct(comp.night_ct);$('nightsaving').textContent=ct(comp.saving_ct);
 $('comparereason').textContent=!comp.complete?'Für den ausgewählten Vergleichstag fehlen vollständige Preise. Anderen Tag auswählen oder Veröffentlichung abwarten.':`Effektiver Speicherstrompreis: ${ct(comp.effective_ct)}. ${comp.saving_ct>0?'Rechnerisch günstiger als der Tagesdurchschnitt.':'Gegenüber dem Tagesdurchschnitt kein Preisvorteil.'}`;
 const rows=d.prices||[];const chart=$('pricechart');$('chartinfo').textContent=d.price_error||(!rows.length?'Noch keine Preise verfügbar. Tibber-Zugang in den Einstellungen prüfen.':`${fmt(rows[0].start)} – ${fmt(rows[rows.length-1].end)} · Stand vor ${formatPriceAge(d.price_age_seconds)} · PV-Linie geglättet`);const phases=chartPhases(d);const allSolar=solarSeries(d),solar=chartVisibility.pv?allSolar:[],battery=batterySeries(d);const signature=JSON.stringify([rows,phases,solar,battery,chartVisibility.battery,d.settings.pv_enabled,d.settings.timezone,chart.clientWidth||1000,Math.floor(Date.now()/900000)]);if(signature===chartSignature)return;chartSignature=signature;chart.replaceChildren();if($('pvlegend'))$('pvlegend').hidden=!allSolar.length;if(!rows.length)return;
 const ns='http://www.w3.org/2000/svg';const el=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
 const chartWidth=Math.max(340,chart.clientWidth||1000);const svg=el('svg',{viewBox:`0 0 ${chartWidth} 280`,role:'group','aria-label':solar.length?'Tibber-Preise links in ct/kWh und PV-Prognose rechts in kW; Balken auswählbar':'Tibber-Preise, einzelne Balken auswählbar'});const min=Math.min(0,...rows.map(p=>p.ct)),max=Math.max(1,...rows.map(p=>p.ct)),span=max-min||1;const first=Date.parse(rows[0].start),last=Date.parse(rows[rows.length-1].end);const right=chartWidth-(chartVisibility.battery?112:solar.length?62:14);const x=t=>55+(Date.parse(t)-first)/(last-first)*(right-55);const y=v=>235-(v-min)/span*205;
 for(let i=0;i<=4;i++){const v=min+span*i/4;svg.append(el('line',{x1:55,x2:right,y1:y(v),y2:y(v),stroke:'#dce5dd'}),el('text',{x:46,y:y(v)+4,'text-anchor':'end'},v.toFixed(1)));}
 svg.append(el('line',{x1:55,x2:right,y1:y(0),y2:y(0),stroke:'#728779'}));
 rows.forEach((p,i)=>{const current=Date.parse(p.start)<=Date.now()&&Date.now()<Date.parse(p.end);const entry=phaseEntryAt(phases,Date.parse(p.start));const phase=entry?.action;const pvValue=solarAverage(solar,Date.parse(p.start),Date.parse(p.end));const bp=battery.measured.find(q=>q.time>=Date.parse(p.start)&&q.time<Date.parse(p.end))||battery.forecast.find(q=>q.time>=Date.parse(p.start)&&q.time<Date.parse(p.end));const label=(bp?'Akku '+bp.soc.toFixed(1)+' % · ':'')+(entry?phaseDescription(entry)+' · ':'')+fmt(p.start)+' – '+fmt(p.end)+': '+ct(p.ct)+(d.settings.pv_enabled?' · PV-Prognose: '+(pvValue===null?'keine Daten':pvValue.toLocaleString('de-DE',{maximumFractionDigits:2})+' kW (Stundenmittel)'):'');const bar=el('rect',{x:x(p.start),y:Math.min(y(0),y(p.ct)),width:Math.max(1,x(p.end)-x(p.start)-1),height:Math.max(2,Math.abs(y(p.ct)-y(0))),fill:current?'#d58924':'#edb85f',rx:1.5,stroke:current?'#172b25':'none','stroke-width':current?2:0,tabindex:0,role:'img','aria-label':label});bar.append(el('title',{},label));for(const event of ['pointerenter','focus','click'])bar.addEventListener(event,()=>{$('chartdetail').textContent=label;});svg.append(bar);if(i%Math.ceil(rows.length/(chartWidth<600?4:6))===0)svg.append(el('text',{x:x(p.start),y:263,'text-anchor':'start'},new Date(p.start).toLocaleTimeString('de-DE',{timeZone:d.settings.timezone,hour:'2-digit',minute:'2-digit'})));});
 for(const phase of phases){const left=Math.max(first,Date.parse(phase.start)),right=Math.min(last,Date.parse(phase.end));if(right<=left)continue;const band=el('rect',{x:x(new Date(left).toISOString()),y:239,width:Math.max(1,x(new Date(right).toISOString())-x(new Date(left).toISOString())),height:7,fill:phaseColor(phase.action)});band.append(el('title',{},phaseDescription(phase)+' · '+fmt(left)+' – '+fmt(right)));svg.append(band);}
 svg.append(el('text',{x:55,y:16},'ct/kWh'));
 if(solar.length){
  const peak=Math.max(.5,Math.ceil(Math.max(...solar.map(r=>r.kw))*2)/2),sy=v=>235-v/peak*205;
  svg.append(el('text',{x:right+12,y:16,class:'pv-axis'},'PV · kW'),el('line',{x1:right,x2:right,y1:30,y2:235,stroke:'#22734e'}));
  for(let i=0;i<=4;i++){const v=peak*i/4;svg.append(el('text',{x:right+12,y:sy(v)+4,class:'pv-axis'},v.toLocaleString('de-DE',{maximumFractionDigits:2})));}
  const path=smoothSolarPath(solar,first,last,t=>x(new Date(t).toISOString()),sy);
  svg.append(el('path',{d:path,fill:'none',stroke:'#fff','stroke-width':6,'stroke-opacity':.85,'vector-effect':'non-scaling-stroke','pointer-events':'none','aria-hidden':'true'}));
  const line=el('path',{d:path,fill:'none',stroke:'#22734e','stroke-width':3,'vector-effect':'non-scaling-stroke','pointer-events':'none',class:'pv-line'});
  line.append(el('title',{},'PV-Prognose · geglättete Darstellung der Stundenmittel · rechte Achse; Tooltips zeigen Originalwerte'));svg.append(line);
 }
 const legend=$('pvlegend');if(legend)legend.hidden=!allSolar.length;
 if(chartVisibility.battery){
  const sy=v=>235-v/100*205;
  svg.append(el('text',{x:right+64,y:16,class:'soc-axis'},'Akku %'));
  for(const v of [0,25,50,75,100])svg.append(el('text',{x:right+64,y:sy(v)+4,class:'soc-axis'},String(v)));
  for(const [points,dashed] of [[battery.measured,false],[battery.forecast,true]]){
   const line=el('path',{d:socPath(points,first,last,x,sy),fill:'none',stroke:'#6864b4','stroke-width':2.5,'stroke-dasharray':dashed?'6 4':'none','pointer-events':'none'});svg.append(line);
  }
 }
 if($('batterychartnote'))$('batterychartnote').textContent='Akku: Linie verbindet Messpunkte geglättet (Zwischenwerte geschätzt) · gestrichelt = '+(d.mode==='smart'?'Smart-Plan':'PV-/Verbrauchsschätzung')+'. '+(!battery.forecast.length?'Keine belastbare Prognose verfügbar. ':'')+'Datenlücken bleiben offen.';
 chart.append(svg);
}

$('modedialog').addEventListener('cancel',()=>{modeDirty=false;chosenMode=lastStatus?.mode;renderControl(lastStatus);});
for(const [id,key] of [['pvlegend','pv'],['batterylegend','battery']])$(id).onclick=()=>{chartVisibility[key]=!chartVisibility[key];$(id).setAttribute('aria-pressed',String(chartVisibility[key]));if(lastStatus)renderPrices(lastStatus);};
$('compareday').onchange=()=>{if(lastStatus)renderPrices(lastStatus);};
function renderControl(d){
 if(!d)return;
 if(!modeDirty)chosenMode=d.mode;
 for(const [id,mode] of [['manualcontrols','on'],['plannedcontrols','planned'],['smartcontrols','smart']])$(id).hidden=chosenMode!==mode;
 document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('active',b.dataset.mode===chosenMode);b.setAttribute('aria-pressed',String(b.dataset.mode===chosenMode));});
 if(modeDirty&&!$('modedialog').open)$('modedialog').showModal();if(!modeDirty&&$('modedialog').open)$('modedialog').close();
 $('modedraft').textContent=modeDirty?'Auswahl: '+modes[chosenMode]+' · Erst mit der Schaltfläche unten aktivieren. Aktuell: '+modes[d.mode]:chosenMode==='off'?'Aus: kein Ladeauftrag durch diese App.':'Aktueller Modus: '+modes[d.mode];
 $('plannedform').hidden=d.mode==='planned'&&!modeDirty;
 $('modeconfirmation').hidden=!modeDirty;
 const c=d.settings;
 const preview=d.smart_preview;
 const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:c.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 $('smarttiming').textContent=preview.joint?(preview.joint.night_complete===false?'☀ Tagesplan aktiv · nächste Nacht noch offen':preview.windows.length?'↗ '+preview.planned_kwh.toLocaleString('de-DE',{maximumFractionDigits:2})+' kWh Netzladung geplant':'☾ Keine Netzladung geplant'):preview.reason;
 const number=n=>typeof n==='number'?n.toLocaleString('de-DE',{maximumFractionDigits:2}):'—';
 $('smarttarget').textContent=preview.joint?.night_complete===false?`Plan bis ${fmt(preview.joint.plan_end)}`:preview.joint?`☾ ${fmt(preview.night_end)}: ca. ${number(preview.effective_target_soc)} % SOC${preview.planned_kwh>0?' · '+Math.round(preview.duration_minutes)+' min bei '+number(preview.power_w/1000)+' kW':''}`:`SOC ${number(preview.soc)} → ${number(preview.target_soc)} % · ${number(preview.needed_kwh)} kWh`;
 if(preview.soc===null&&$('smartslots').children.length){
  $('smarttiming').textContent='Messung wird aktualisiert · bisheriger Plan, derzeit nicht bestätigt';
 }else{
  const texts=preview.joint?phaseFacts(preview.joint,c):preview.windows.map(slot=>`${fmt(slot.start)} – ${fmt(slot.end)} · ${ct(slot.ct)}`);
  const signature=JSON.stringify(texts);
  if($('smartslots').dataset.signature!==signature){
   $('smartslots').replaceChildren(...texts.map(text=>{const row=document.createElement('li');row.textContent=text;return row;}));
   $('smartslots').dataset.signature=signature;
  }
 }

 const info=chosenMode==='off'?'Die erzwungene Ladung und aktive Zeitplanung dieser App werden beendet.':chosenMode==='smart'?`Ziel bis ${c.target_soc} % · Leistung bis ${c.charge_power_w} W · Kaufgrenze ${ct(c.max_buy_ct_kwh)} · Mindestvorteil ${ct(c.min_saving_ct_kwh)}.`:chosenMode==='on'?`Ziel ${c.target_soc} % · Leistung bis ${c.charge_power_w} W · maximale Sitzung ${c.max_session_minutes} Minuten. Kein Preisvergleich.`:`Leistung bis ${c.charge_power_w} W · maximale Sitzung ${c.max_session_minutes} Minuten. Start und Ende wie oben eingegeben.`;
 $('modepreview').textContent=info+' Ohne Bestätigung bleibt der aktive Modus unverändert.';
}

let countdownAnchor=0;
function drawCountdown(){
 if(document.hidden||!lastStatus)return;
 const d=lastStatus;
 if(d.remaining_seconds===null){$('countdown').textContent='—';$('timerhint').textContent=d.mode==='planned'?'Wartet auf geplanten Start':'Kein zeitbegrenzter Auftrag';return;}
 const left=Math.max(0,Math.ceil(d.remaining_seconds-(performance.now()-countdownAnchor)/1000));
 const mins=Math.floor(left/60),secs=left%60;
 $('countdown').textContent=String(mins).padStart(2,'0')+':'+String(secs).padStart(2,'0');
 $('timerhint').textContent=left?'Bis zum Zeitlimit · Ziel-SOC kann früher stoppen':'Zeitlimit erreicht · Statusbestätigung abwarten';
}
function phaseInfo(d,now=Date.now()){
 const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:d.settings.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 const t=d.telemetry||{}, fresh=t.time&&Math.abs(now-Date.parse(t.time))<=90000;
 const loading=fresh&&t.battery_power_w>100;
 if(d.fault)return ['⚠ Steuerungsfehler',d.fault];
 if(d.mode==='off')return ['○ Aus','Kein Ladeauftrag aktiv'];
 if(d.mode==='planned'&&d.planned){
  const p=d.planned;
  if(now>=Date.parse(p.end))return ['⌛ Auftrag beendet · Stopp wird bestätigt','Automatischer Wechsel zu Aus'];
  const end=p.end_kind==='soc'?`■ Stopp bei ${p.target_soc} % · spätestens ${fmt(p.end)}`:`■ Geplanter Stopp um ${fmt(p.end)}`;
  if(p.phase==='waiting'&&now<Date.parse(p.start))return ['◷ Warte auf geplanten Start',`▶ Geplanter Start um ${fmt(p.start)} · ${end}`];
  return [loading?'ϟ Lade …':'⌛ Warte auf Ladebestätigung',end];
 }
 if(d.mode==='smart'){
  const p=d.smart_preview,slots=p.windows||[];
  if(d.discharge?.request?.until&&Date.parse(d.discharge.request.until)>now)return ['🔒 Manuelle Entladesperre','Freigabe um '+fmt(d.discharge.request.until)];
  if(d.dispatch_preview?.enabled&&d.dispatch_preview.complete&&d.dispatch_preview.available_kwh!==null){const q=d.dispatch_preview;return [q.hold?'Ⅱ Smart · Entladung pausiert':'↘ Smart · Entladung freigegeben',q.reason];}
  const active=slots.find(w=>Date.parse(w.start)<=now&&now<Date.parse(w.end)-130000);
  const next=slots.find(w=>Date.parse(w.start)>now);
  if(active){const later=slots.some(w=>Date.parse(w.start)>=Date.parse(active.end));return [loading?'ϟ Smart · Lade …':'⌛ Smart · Warte auf Ladebestätigung',`${later?'Ⅱ Geplante Pause':'■ Geplanter Stopp'} um ${fmt(Date.parse(active.end)-130000)}${next?' · ▶ Weiter um '+fmt(next.start):''}`];}
  if(next)return ['Ⅱ Smart · Warte auf günstigen Zeitslot',`▶ Geplanter Start um ${fmt(next.start)} · ${p.reason}`];
  return ['◷ Smart · Warte auf neue Ladegelegenheit',p.reason];
 }
 return [loading?'ϟ Lade …':'⌛ Warte auf Ladebestätigung',d.remaining_seconds!==null?`■ Geplanter Stopp um ${fmt(now+d.remaining_seconds*1000)}`:'Status wird aktualisiert'];
}
function compactPlan(d){
 const j=d.smart_preview?.joint;
 if(!j)return d.smart_preview?.windows?.length?'◷ Ladefenster geplant':'◷ Plan abwarten';
 const now=Date.now(),next=j.phases?.find(p=>Date.parse(p.end)>now);
 if(!next)return '✓ Planende';
 const time=new Date(next.end).toLocaleTimeString('de-DE',{timeZone:d.settings.timezone,hour:'2-digit',minute:'2-digit'});
 return `${next.action==='charge'?'↗ Laden':next.action==='discharge'?'↘ Frei':next.reason==='reserve'?'🔒 Schutz':'Ⅱ Pause'} bis ${time}`;
}
function phaseFacts(j,c){
 const num=n=>n.toLocaleString('de-DE',{maximumFractionDigits:2});
 const fmt=t=>new Date(t).toLocaleString('de-DE',{timeZone:c.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 const peak=Math.max(...(j.phases||[]).filter(p=>p.action==='discharge'&&p.kwh>0).map(p=>p.high_ct));
 return (j.phases||[]).map(p=>{
  const price=p.low_ct===p.high_ct?num(p.low_ct):num(p.low_ct)+'–'+num(p.high_ct);
  const action=p.action==='charge'?'↗ Laden':p.action==='discharge'?'↘ Entladung frei':'Ⅱ Gesperrt';
  const why=p.action==='charge'||p.action==='discharge'?`${num(p.kwh)} kWh · ${price} ct/kWh`:p.reason==='reserve'?'🔒 Benötigte Energie zurückhalten':p.reason==='manual'?'Manuelle Sperre':p.reason==='charge_complete'?'Lademenge für diesen Abschnitt erreicht · Entladung bleibt gesperrt':`${price} ct jetzt${Number.isFinite(peak)?' · Für spätere Entladung halten · Preisspitze '+num(peak)+' ct/kWh':''}`;
  return `${fmt(p.start)} – ${fmt(p.end)} · ${action}
${why}`;
 });
}
function renderBatteryCard(d){
 renderDischarge(d);
 const t=d.telemetry,age=t.time?(Date.now()-Date.parse(t.time))/1000:Infinity;
 const fresh=age>=0&&age<=90;
 const charging=fresh&&t.battery_power_w>100,discharging=fresh&&t.battery_power_w < -100;
 $('batterystatus').classList.toggle('charging',charging);
 $('batterystatus').classList.toggle('stale',!fresh);
 $('flowstate').textContent=!fresh?'Messwerte fehlen / veraltet':charging?'ϟ Lädt':discharging?'Entlädt':'Bereit';
 $('powerdirection').textContent=charging?'Energie fließt in den Akku':discharging?'Akku gibt Energie ab':fresh?'Kein wesentlicher Batteriefluss':'Messung abwarten';
 const target=d.mode==='planned'&&d.planned?d.planned.target_soc:d.settings.target_soc;
 $('cardtarget').textContent=Number.isFinite(target)?target.toLocaleString('de-DE',{maximumFractionDigits:1})+' %':'—';
 $('socfill').setAttribute('width',fresh?Math.min(1000,Math.max(0,t.soc*10)):0);
 $('soctarget').setAttribute('x1',target*10);$('soctarget').setAttribute('x2',target*10);
 $('socgraphic').setAttribute('aria-label',fresh?`Akkustand ${t.soc} Prozent, Ziel ${target} Prozent`:'Akkustand veraltet oder unbekannt');
 const phase=phaseInfo(d);$('cardstatus').textContent=phase[0];$('cardplan').textContent=d.mode==='smart'?compactPlan(d):phase[1];
 $('timerlabel').textContent=d.mode==='on'?'MANUELL · RESTZEIT':'RESTZEIT';
 drawCountdown();
}
setInterval(()=>{if(!document.hidden)drawCountdown();},1000);

let refreshTimer=null,watch=null;
function watchChange(name,data){
 const kind=name==='discharge'?'discharge':name==='test'||data.mode==='on'?'charge':data.mode==='off'?'stop':'state';
 watch={kind,since:Date.now(),baseline:lastStatus?.telemetry?.time,expected:name==='planned'?'planned':data.mode};
}
function trackTransition(d){
 if(!watch&&lastStatus&&(lastStatus.mode!==d.mode||lastStatus.telemetry?.eligible!==d.telemetry?.eligible)){
  watch={kind:d.telemetry.eligible?'charge':d.mode==='off'?'stop':'state',since:Date.now(),baseline:lastStatus.telemetry?.time,expected:d.mode};
 }
 if(!watch)return;
 if(watch.kind==='discharge'){
  const x=d.discharge,stamp=x?.status?.time;
  if(x&&((watch.expected==='active'&&!x.restore_pending&&!x.request.until)||(stamp&&Date.parse(stamp)>=watch.since&&x.status.locked===(watch.expected==='hold')))||d.fault)watch=null;
  else if(Date.now()-watch.since>180000){watch=null;notify('Entladeänderung noch nicht bestätigt. Verbindung und Status prüfen.','info');}
  return;
 }
 const t=d.telemetry,fresh=t.time&&Date.parse(t.time)>=watch.since&&t.time!==watch.baseline;
 const measured=fresh&&(watch.kind==='charge'?t.battery_power_w>100:watch.kind==='stop'?t.battery_power_w<=100:d.mode===watch.expected);
 if(measured||d.fault){watch=null;return;}
 if(Date.now()-watch.since>180000){watch=null;notify('Erwartete Änderung nach 3 Minuten noch nicht bestätigt. Bitte Messwerte und Gerätestatus prüfen.','info');}
}
function scheduleRefresh(){
 clearTimeout(refreshTimer);
 if(document.hidden)return;
 const pending=watch||['sample','probe','charge-test','stop','discharge-sync'].includes(lastStatus?.job);
 let delay=pending?10000:60000;
 // Refresh at a known phase boundary; the server remains authoritative.
 if(lastStatus){
  const d=lastStatus,now=Date.now(),bounds=[];
  if(d.remaining_seconds!==null&&d.remaining_seconds!==undefined)bounds.push(d.remaining_seconds*1000);
  if(d.mode==='planned'&&d.planned)bounds.push(Date.parse(d.planned.start)-now,Date.parse(d.planned.end)-now);
  if(d.mode==='smart')for(const w of d.smart_preview?.windows||[])bounds.push(Date.parse(w.start)-now,Date.parse(w.end)-130000-now);
  for(const ms of bounds)if(ms>=0)delay=Math.min(delay,Math.max(1000,ms+1000));
 }
 refreshTimer=setTimeout(refresh,delay);
}
document.addEventListener('visibilitychange',()=>{clearTimeout(refreshTimer);if(!document.hidden)refresh();});
refresh();

// Compact overview uses the same server plan; it never requests extra telemetry.
function overviewNext(d, now=Date.now()){
 const manual=d.discharge?.request?.until;
 if(d.fault)return {label:'Steuerung prüfen',reason:d.fault};
 if(manual&&Date.parse(manual)>now&&d.mode!=='smart'&&d.mode!=='planned')return {time:manual,label:'Manuelle Entladesperre endet',reason:'Freigabe durch den Server erforderlich; danach gilt der aktive Modus.'};
 if(d.mode==='off')return {label:'Kein Ladeauftrag',reason:'Die normale Entladung wird separat geregelt.'};
 if(d.mode==='planned'&&d.planned){const p=d.planned;if(Date.parse(p.end)<=now)return {label:'Stoppbestätigung abwarten',reason:'Geplantes Ende erreicht.'};return Date.parse(p.start)>now?{time:p.start,label:'Geplantes Laden starten',reason:`Ziel ${p.target_soc} % · Ende spätestens zur eingestellten Uhrzeit.`}:{time:p.end,label:'Geplantes Laden beenden',reason:`Bei ${p.target_soc} % endet der Auftrag früher.`};}
 if(d.mode==='on')return {label:'Manuelle Ladung',reason:'Restzeit in der Speicherkarte · Ziel-SOC kann früher stoppen.'};
 const phases=d.smart_preview?.joint?.phases||[];
 const phase=phases.find(p=>Date.parse(p.start)>now);
 if(manual&&Date.parse(manual)>now&&(!phase||Date.parse(manual)<Date.parse(phase.start)))return {time:manual,label:'Manuelle Entladesperre endet',reason:'Danach gilt die Smart-Regelung.'};
 if(phase){const label=phase.action==='charge'?'Netzladen starten':phase.action==='discharge'?'Entladung freigeben':'Entladung pausieren';const price=Number.isFinite(phase.low_ct)?ct(phase.low_ct)+(phase.high_ct!==phase.low_ct?' bis '+ct(phase.high_ct):''):'';return {time:phase.start,label,reason:[Number.isFinite(phase.kwh)&&phase.kwh>0?phase.kwh.toLocaleString('de-DE',{maximumFractionDigits:2})+' kWh geplant':'',price,phase.reason==='reserve'?'Energie für späteren Bedarf schützen':''].filter(Boolean).join(' · ')};}
 const slot=d.smart_preview?.windows?.find(p=>Date.parse(p.start)>now);
 if(slot)return {time:slot.start,label:'Netzladen starten',reason:ct(slot.ct)};
 return {label:'Weitere Planung abwarten',reason:d.smart_preview?.reason||'Noch keine nächste Aktion bestätigt.'};
}
function renderOverview(d){
 renderTodayPlan(d);
 const fmt={timeZone:d.settings.timezone};
 $('activity').hidden=!d.fault&&!['probe','stop','charge-test'].includes(d.job);
 $('overviewdate').textContent=new Date().toLocaleDateString('de-DE',{...fmt,weekday:'long',day:'numeric',month:'long'});
 $('timergroup').hidden=d.remaining_seconds==null;
 const next=overviewNext(d);
 $('nexttime').textContent=next.time?new Date(next.time).toLocaleString('de-DE',{...fmt,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';
 $('nextaction').textContent=next.label;$('nextreason').textContent=next.reason;
}



// Same host as this app, evcc's port; no app path or query parameters forwarded.
{const link=document.getElementById('evcclink');if(link){const url=new URL(window.location.href);url.port='7070';url.pathname='/';url.search='';url.hash='';url.username='';url.password='';link.href=url.href;}}

function renderMeterTest(d){
 const button=$('metertest'),box=$('meterresult');if(!button||!box)return;
 button.disabled=!!d.job||d.mode!=='off';button.classList.toggle('button-loading',d.job==='meter-test');
 if(d.job==='meter-test'){box.textContent='Zähler- und PV-Register werden gelesen … bis zu etwa zwei Minuten.';return;}
 const test=d.meter_test;if(!test?.rows)return;
 box.replaceChildren();const title=document.createElement('p');title.textContent='Lesetest · '+new Date(test.time).toLocaleString('de-DE',{timeZone:d.settings.timezone});box.append(title);
 for(const row of test.rows){const p=document.createElement('p');p.textContent=row.label+': '+(row.ok?row.value+' '+row.unit:'Nicht lesbar ('+row.error+')');box.append(p);}
 const hint=document.createElement('p');hint.className='muted';hint.textContent='Lesbar bedeutet noch nicht plausibel. Zählerstatus, Leistungsrichtung und Zählerstände gemeinsam prüfen; Nullwerte allein bestätigen keinen verbundenen Zähler.';box.append(hint);
}
