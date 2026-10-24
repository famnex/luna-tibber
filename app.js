'use strict';
const $=id=>document.getElementById(id);
let initialized=false,busy=false,refreshing=false,settingsDirty=false,chartSignature="",lastStatus=null,chosenMode=null,modeDirty=false,pendingButton=null;
const labels={smart_discharge_enabled:'Smart: Entladung optimieren',base_load_w:'Erwarteter Grundverbrauch (W)',reserve_soc:'Mindestreserve (%)',statistics_enabled:'Planersparnis speichern (ohne Messabfragen)',push_contact:'Kontakt-E-Mail für Push',battery_capacity_kwh:'Nutzbare Akkukapazität gesamt (kWh, erforderlich für Smart)',host:'Wechselrichter-IP',port:'Port',unit_id:'Unit-ID',expected_serial:'Wechselrichter-Seriennummer',username:'Huawei-Benutzername',password:'Huawei-Installateurpasswort',tibber_token:'Tibber Personal Access Token',tibber_home_id:'Tibber Zuhause-ID (bei mehreren Zuhause)',max_buy_ct_kwh:'Maximaler Kaufpreis (ct/kWh)',target_soc:'Ziel-Akkustand (%)',charge_power_w:'Angeforderte Ladeleistung (W)',max_session_minutes:'Maximale Ladesitzung (Minuten)',roundtrip_efficiency:'Gesamtwirkungsgrad (z. B. 0.85)',wear_ct_kwh:'Verschleißreserve (ct/kWh)',min_saving_ct_kwh:'Mindestvorteil (ct/kWh)',use_start_hour:'Verbrauchsfenster ab Stunde',use_end_hour:'Verbrauchsfenster bis Stunde',night_start_hour:'Nachtvergleich ab Stunde (0–23)',night_end_hour:'Nachtvergleich bis Stunde (1–24)',timezone:'Zeitzone',wifi_enabled:'WLAN-Profil vor Laden prüfen'};
const types={};
const modes={off:'Aus',smart:'Smart',on:'An',schedule:'Zeitplan',planned:'Geplant'};
const ct=n=>typeof n==='number'?n.toLocaleString('de-DE',{maximumFractionDigits:2})+' ct/kWh':'—';
async function api(action,data){const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Luna':'1'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw new Error(d.error);return d;}
function showBusy(active,text='Bitte warten …',button=null){$('progressbar').hidden=!active;$('progresstext').textContent=text;if(button){button.classList.toggle('button-loading',active);button.setAttribute('aria-busy',String(active));}}
function notify(s,kind='success'){$('notice').textContent=s;$('notice').dataset.kind=kind;}
const actionLabels={discharge:'Entladung ändern','push-test':'Testnachricht senden',settings:'Einstellungen speichern',schedules:'Zeitpläne speichern',planned:'Ladeauftrag planen',probe:'Gerät auslesen',test:'Ladetest starten','adopt-serial':'Seriennummer übernehmen',mode:'Steuerung umschalten'};
async function perform(name,data={},button=null){if(busy)return false;busy=true;pendingButton=button;showBusy(true,(actionLabels[name]||'Aktion')+' …',button);document.body.classList.add('working');const buttons=[...document.querySelectorAll('#dashboard button')];buttons.forEach(b=>b.disabled=true);$('dashboard').setAttribute('aria-busy','true');notify('');try{await api(name,data);if(['mode','planned','test','discharge'].includes(name))watchChange(name,data);if(name==='mode'||name==='planned'){modeDirty=false;chosenMode=name==='planned'?'planned':data.mode;}notify(name==='probe'||name==='test'?'':name==='settings'?'Einstellungen gespeichert.':name==='planned'?'Ladeauftrag eingeplant. Start und Ende stehen unten.':name==='mode'&&data.mode==='off'?'Stopp angefordert. Bestätigung im Gerätestatus abwarten.':'Änderung übernommen.');if(name==='settings')settingsDirty=false;await refresh();return true;}catch(e){notify(e.message,'error');return false;}finally{showBusy(false,'',pendingButton);pendingButton=null;busy=false;buttons.forEach(b=>b.disabled=false);document.body.classList.remove('working');$('dashboard').setAttribute('aria-busy','false');}}

function fillSettings(s,secrets){const box=$('fields');box.replaceChildren();const sections={};const group=k=>['host','port','unit_id','expected_serial','username','password','wifi_enabled'].includes(k)?'Wechselrichter & Verbindung':k.startsWith('tibber')?'Tibber-Zugang':['target_soc','charge_power_w','max_session_minutes','battery_capacity_kwh'].includes(k)?'Ladegrenzen':'Preise, Vergleich & Zeitzone';for(const [key,label] of Object.entries(labels)){const l=document.createElement('label');l.textContent=label;const i=document.createElement('input');i.name=key;types[key]=typeof s[key];i.type=typeof s[key]==='boolean'?'checkbox':typeof s[key]==='number'?'number':'text';if(i.type==='number')i.step='any';if(key==='password'||key==='tibber_token')i.type='password';i.autocomplete='off';if(i.type==='checkbox')i.checked=s[key];else i.value=s[key]??'';if(key==='password'||key==='tibber_token')i.placeholder=secrets[key]?'Gespeichert – leer lassen zum Behalten':'Noch nicht gespeichert';l.append(i);if(key==='password'||key==='tibber_token'){const b=document.createElement('button');b.type='button';b.textContent='Anzeigen / verbergen';b.onclick=()=>i.type=i.type==='password'?'text':'password';l.append(b);}const g=group(key);if(!sections[g]){const section=document.createElement('section');section.className='card';const h=document.createElement('h2');h.textContent=g;const grid=document.createElement('div');grid.className='fields';section.append(h,grid);box.append(section);sections[g]=grid;}sections[g].append(l);}}
async function refresh(){if(document.hidden||refreshing)return;refreshing=true;try{const r=await fetch('/api/status'+(watch?'?fast=1':''));if(r.status===401){$('connection').textContent='Webinterface erreichbar · bitte anmelden';$('login').hidden=false;$('dashboard').hidden=true;$('logout').hidden=true;return;}if(!r.ok)throw new Error('Status nicht erreichbar');const d=await r.json();if(document.hidden)return;trackTransition(d);lastStatus=d;countdownAnchor=performance.now();renderBatteryCard(d);renderControl(d);renderExtras(d);$('connection').textContent='● Verbunden · aktualisiert '+new Date().toLocaleTimeString('de-DE');$('connection').classList.remove('offline');renderPrices(d);$('login').hidden=true;$('dashboard').hidden=false;$('logout').hidden=false;if(!initialized){fillSettings(d.settings,d.secrets_set);initialized=true;}const p=d.planned;$('plannedstatus').textContent=p?`${p.phase==='waiting'?'Wartet':p.phase==='charging'?'Lädt':p.phase==='completed'?'Beendet':'Fehler'} · ${new Date(p.start).toLocaleString('de-DE',{timeZone:d.settings.timezone})} bis spätestens ${new Date(p.end).toLocaleString('de-DE',{timeZone:d.settings.timezone})} · Ziel ${p.target_soc} %`:'Kein einmaliger Auftrag.';const t=d.telemetry;const age=t.time?(Date.now()-Date.parse(t.time))/1000:null;$('soc').textContent=typeof t.soc==='number'?t.soc.toFixed(1)+' %':'—';$('battery').value=t.soc??0;$('power').textContent=typeof t.battery_power_w==='number'?(t.battery_power_w/1000).toFixed(2)+' kW':'—';$('sampletime').textContent=age===null?'Noch keine Messung':`Letzte Messung vor ${Math.max(0,Math.floor(age))} s${age>90?' · veraltet':''}`;$('price').textContent=ct(d.current_price);$('modebadge').textContent=modes[d.mode];$('activity').classList.toggle('spinning',!!d.job);$('activity').textContent=d.fault?'Steuerung meldet einen Fehler – Details unten.':d.job==='sample'?'Messwerte werden aktualisiert …':d.job==='probe'?'Gerät wird ausgelesen …':d.job==='stop'?'Stopp wird an den Wechselrichter gesendet …':d.job==='charge-test'?'Beaufsichtigter Ladetest läuft …':d.job?(t.eligible?'Ladeauftrag aktiv · '+(t.reason||'Ladung freigegeben'):'Steuerung aktiv · '+(t.reason||'Warte auf Messwerte')):d.mode==='planned'?'Geplant: wartet auf Startzeit.':d.mode==='off'?'Aus: keine automatische oder geplante Ladung durch diese App.':'Wartet auf das nächste Zeitfenster.';if(!busy){for(const [id,job] of [['probe','probe'],['test','charge-test']])$(id).classList.toggle('button-loading',d.job===job);}$('fault').hidden=!d.fault;$('fault').textContent=d.fault;$('missing').hidden=!d.missing.length;$('missing').textContent='Noch einzurichten: '+d.missing.join(', ');const e=d.economics;$('saving').textContent=typeof e.saving_ct_kwh==='number'?ct(e.saving_ct_kwh)+' Vorteil':'—';$('planreason').textContent=d.price_error||e.reason;$('effective').textContent=ct(e.effective_ct_kwh);$('reference').textContent=ct(e.reference_ct_kwh);$('window').textContent=e.window_start?new Date(e.window_start).toLocaleString('de-DE',{timeZone:d.settings.timezone})+' – '+new Date(e.window_end).toLocaleTimeString('de-DE',{timeZone:d.settings.timezone,hour:'2-digit',minute:'2-digit'}):'—';$('device').textContent=d.device.serial?`${d.device.model||'Huawei'} · Seriennummer ${d.device.serial}`:'Gerät noch nicht ausgelesen';$('wifi').textContent=d.wifi.interface?`WLAN-Profil: ${d.wifi.interface} · ${d.wifi.ssid} · ${d.wifi.host} (Systemdienst)`:'WLAN-Connector noch nicht eingerichtet';$('commissioned').hidden=d.job==='charge-test';$('commissioned').textContent=d.commissioned?'Ladetest bestätigt.':'Ladetest noch nicht bestätigt.';$('events').textContent=d.events.map(x=>JSON.stringify(x)).join('\n');}catch(e){$('connection').textContent='Verbindung unterbrochen · angezeigte Werte können veraltet sein';$('connection').classList.add('offline');}finally{refreshing=false;scheduleRefresh();}}
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
$('probe').onclick=e=>perform('probe',{},e.currentTarget);
$('adopt').onclick=async e=>{await perform('adopt-serial',{},e.currentTarget);initialized=false;await refresh();};
$('test').onclick=e=>{if(confirm('Beaufsichtigten Test starten? Maximal 1 kW für zwei Minuten. Netzbezug vor Ort prüfen.'))perform('test',{},e.currentTarget);};
$('settingsform').onsubmit=async e=>{e.preventDefault();const data={};for(const i of $('fields').querySelectorAll('input'))data[i.name]=i.type==='checkbox'?i.checked:types[i.name]==='number'?Number(i.value):i.value;await perform('settings',data,e.submitter);};
$('plannedkind').onchange=()=>{$('endtimelabel').hidden=$('plannedkind').value!=='time';$('endsoclabel').hidden=$('plannedkind').value!=='soc';$('plannedend').required=$('plannedkind').value==='time';};
$('plannedform').onsubmit=e=>{e.preventDefault();};

$('settingsform').addEventListener('input',()=>{settingsDirty=true;notify('Ungespeicherte Einstellungen. Zum Speichern zuerst auf Aus schalten.','info');});
window.addEventListener('beforeunload',e=>{if(settingsDirty){e.preventDefault();e.returnValue='';}});
function renderPrices(d){
 const comp=$('compareday').value==='auto'?d.comparison:d.comparisons[$('compareday').value];const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:d.settings.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 $('comparedate').textContent='Vergleichstag: '+comp.date+' · Nachtfenster '+fmt(comp.night_start)+' bis '+fmt(comp.night_end);
 $('dayaverage').textContent=ct(comp.day_ct);$('nightaverage').textContent=ct(comp.night_ct);$('nightsaving').textContent=ct(comp.saving_ct);
 $('comparereason').textContent=!comp.complete?'Für den ausgewählten Vergleichstag fehlen vollständige Preise. Anderen Tag auswählen oder Veröffentlichung abwarten.':`Effektiver Speicherstrompreis: ${ct(comp.effective_ct)}. ${comp.saving_ct>0?'Rechnerisch günstiger als der Tagesdurchschnitt.':'Gegenüber dem Tagesdurchschnitt kein Preisvorteil.'}`;
 const rows=d.prices||[];const chart=$('pricechart');$('chartinfo').textContent=d.price_error||(!rows.length?'Noch keine Preise verfügbar. Tibber-Zugang in den Einstellungen prüfen.':`${rows.length} Preisintervalle · ${d.settings.timezone} · ct/kWh · Stand vor ${d.price_age_seconds??0} s. Markierung: aktueller Preis.`);const phases=chartPhases(d);const signature=JSON.stringify([rows,phases,d.settings.timezone,Math.floor(Date.now()/900000)]);if(signature===chartSignature)return;chartSignature=signature;chart.replaceChildren();if(!rows.length)return;
 const ns='http://www.w3.org/2000/svg';const el=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
 const svg=el('svg',{viewBox:'0 0 1000 280',role:'group','aria-label':'Tibber-Preise, einzelne Balken auswählbar'});const min=Math.min(0,...rows.map(p=>p.ct)),max=Math.max(1,...rows.map(p=>p.ct)),span=max-min||1;const first=Date.parse(rows[0].start),last=Date.parse(rows[rows.length-1].end);const x=t=>55+(Date.parse(t)-first)/(last-first)*925;const y=v=>235-(v-min)/span*205;
 for(let i=0;i<=4;i++){const v=min+span*i/4;svg.append(el('line',{x1:55,x2:980,y1:y(v),y2:y(v),stroke:'#dce5dd'}),el('text',{x:46,y:y(v)+4,'text-anchor':'end'},v.toFixed(1)));}
 svg.append(el('line',{x1:55,x2:980,y1:y(0),y2:y(0),stroke:'#728779'}));
 rows.forEach((p,i)=>{const current=Date.parse(p.start)<=Date.now()&&Date.now()<Date.parse(p.end);const phase=phaseAt(phases,Date.parse(p.start));const label=(phase?phaseLabel(phase)+' · ':'')+fmt(p.start)+' – '+fmt(p.end)+': '+ct(p.ct);const bar=el('rect',{x:x(p.start),y:Math.min(y(0),y(p.ct)),width:Math.max(1,x(p.end)-x(p.start)-1),height:Math.max(2,Math.abs(y(p.ct)-y(0))),fill:phase?phaseColor(phase):'#91af83',stroke:current?'#172b25':'none','stroke-width':current?2:0,tabindex:0,role:'img','aria-label':label});bar.append(el('title',{},label));for(const event of ['pointerenter','focus','click'])bar.addEventListener(event,()=>{$('chartdetail').textContent=label;});svg.append(bar);if(i%Math.ceil(rows.length/6)===0)svg.append(el('text',{x:x(p.start),y:263,'text-anchor':'start'},fmt(p.start)));});
 for(const phase of phases){const left=Math.max(first,Date.parse(phase.start)),right=Math.min(last,Date.parse(phase.end));if(right<=left)continue;const band=el('rect',{x:x(new Date(left).toISOString()),y:239,width:Math.max(1,x(new Date(right).toISOString())-x(new Date(left).toISOString())),height:7,fill:phaseColor(phase.action)});band.append(el('title',{},phaseLabel(phase.action)+' · '+fmt(left)+' – '+fmt(right)));svg.append(band);}
 chart.append(svg);
}

$('compareday').onchange=()=>{if(lastStatus)renderPrices(lastStatus);};
function renderControl(d){
 if(!d)return;
 if(!modeDirty)chosenMode=d.mode;
 for(const [id,mode] of [['manualcontrols','on'],['plannedcontrols','planned'],['smartcontrols','smart']])$(id).hidden=chosenMode!==mode;
 document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('active',b.dataset.mode===chosenMode);b.setAttribute('aria-pressed',String(b.dataset.mode===chosenMode));});
 $('modedraft').textContent=modeDirty?'Auswahl: '+modes[chosenMode]+' · Erst mit der Schaltfläche unten aktivieren. Aktuell: '+modes[d.mode]:chosenMode==='off'?'Aus: kein Ladeauftrag durch diese App.':'Aktueller Modus: '+modes[d.mode];
 $('plannedform').hidden=d.mode==='planned'&&!modeDirty;
 $('modeconfirmation').hidden=!modeDirty;
 const c=d.settings;
 const preview=d.smart_preview;
 const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:c.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 $('smarttiming').textContent=preview.reason;
 const number=n=>typeof n==='number'?n.toLocaleString('de-DE',{maximumFractionDigits:2}):'—';
 $('smarttarget').textContent=`SOC ${number(preview.soc)} → ${preview.target_soc} % · Kapazität ${number(preview.capacity_kwh)} kWh · Bedarf ${number(preview.needed_kwh)} kWh · Ladeleistung bis ${preview.power_w} W · reine Ladedauer ca. ${number(preview.duration_minutes)} Minuten.`;
 if(preview.soc===null&&$('smartslots').children.length){
  $('smarttiming').textContent='Messung wird aktualisiert · bisheriger Plan, derzeit nicht bestätigt';
 }else{
  const texts=preview.windows.map(slot=>`${fmt(slot.start)} – ${fmt(slot.end)} · ${ct(slot.ct)}`);
  const signature=JSON.stringify(texts);
  if($('smartslots').dataset.signature!==signature){
   $('smartslots').replaceChildren(...texts.map(text=>{const row=document.createElement('li');row.textContent=text;return row;}));
   $('smartslots').dataset.signature=signature;
  }
 }

 const info=chosenMode==='off'?'Die erzwungene Ladung und aktive Zeitplanung dieser App werden beendet.':chosenMode==='smart'?`Ziel ${c.target_soc} % · Leistung bis ${c.charge_power_w} W · Kaufgrenze ${ct(c.max_buy_ct_kwh)} · Mindestvorteil ${ct(c.min_saving_ct_kwh)}.`:chosenMode==='on'?`Ziel ${c.target_soc} % · Leistung bis ${c.charge_power_w} W · maximale Sitzung ${c.max_session_minutes} Minuten. Kein Preisvergleich.`:`Leistung bis ${c.charge_power_w} W · maximale Sitzung ${c.max_session_minutes} Minuten. Start und Ende wie oben eingegeben.`;
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
 $('cardtarget').textContent=target+' %';
 $('socfill').setAttribute('width',fresh?Math.min(1000,Math.max(0,t.soc*10)):0);
 $('soctarget').setAttribute('x1',target*10);$('soctarget').setAttribute('x2',target*10);
 $('socgraphic').setAttribute('aria-label',fresh?`Akkustand ${t.soc} Prozent, Ziel ${target} Prozent`:'Akkustand veraltet oder unbekannt');
 const phase=phaseInfo(d);$('cardstatus').textContent=phase[0];$('cardplan').textContent=phase[1];
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
