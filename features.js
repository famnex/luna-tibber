'use strict';
const phaseColor=action=>({charge:'#2f8d62',discharge:'#ce732a',hold:'#6875bb'}[action]||'#91af83');
const phaseLabel=action=>({charge:'↗ Laden',discharge:'↘ Entladung frei',hold:'Ⅱ Entladung pausiert'}[action]||'');
function chartPhases(d){
 if(d.mode!=='smart')return [];
 const rows=(d.dispatch_preview?.windows||[]).map(w=>({...w}));
 const until=d.discharge?.request?.until;
 if(until&&Date.parse(until)>Date.now())rows.push({start:new Date(Date.now()).toISOString(),end:until,action:'hold'});
 // Charge rows are drawn last and take precedence over hold rows.
 for(const w of d.smart_preview?.windows||[]){const end=Date.parse(w.end)-130000;if(end>Date.parse(w.start))rows.push({...w,end:new Date(end).toISOString(),action:'charge'});}
 return rows;
}
function phaseEntryAt(phases,time){return [...phases].reverse().find(w=>Date.parse(w.start)<=time&&time<Date.parse(w.end));}
function phaseAt(phases,time){return phaseEntryAt(phases,time)?.action;}
function phaseDescription(w){return (w.projected?'Vorschau · ':'')+(w.surplus_only?'↘ Restenergie frei · Gerätegrenzen gelten':phaseLabel(w.action));}
function renderExtras(d){
 renderUpdate(d.update,d);
 document.getElementById('referencelabel').textContent=d.settings.smart_discharge_enabled?'Erwarteter Preis bei Entladung':'Durchschnittspreis im Verbrauchsfenster';
 const q=d.dispatch_preview;
 document.getElementById('dispatchreason').textContent=q?.enabled?'✧ '+q.reason:'ⓘ Smart-Entladen in den Einstellungen aktivierbar';
 const num=n=>typeof n==='number'?n.toLocaleString('de-DE',{maximumFractionDigits:2}):'—';
 document.getElementById('dispatchsummary').textContent=q?.enabled?`${num(q.stored_kwh)} kWh im Akku · keine feste App-Reserve\n≈ ${num(q.available_kwh)} kWh nach Entladeverlusten (Gerätegrenzen gelten)\nDavon ${num(q.reserved_later_kwh)} kWh für spätere Planstunden zurückgehalten\n⌁ ${q.base_load_w} W Grundverbrauch${q.extra_load_kwh?' + '+num(q.extra_load_kwh)+' kWh Zusatzbedarf täglich':''}${q.future_complete?'\nVorschau ab Nachtende: ca. '+num(q.future_soc)+' % SOC':q.future_reason?'\nTagesvorschau: '+q.future_reason:''}`:'';
 if(!window.isSecureContext)document.getElementById('pushstatus').textContent='🔒 HTTPS für Installation und Push erforderlich.';
 else if(d.push?.error)document.getElementById('pushstatus').textContent=d.push.error;
}
let historyData=null,historyLoading=false,historyAt=0;
async function loadHistory(force=false){
 if(document.hidden||document.getElementById('statistics').hidden||historyLoading||(!force&&Date.now()-historyAt<60000))return;
 historyLoading=true;const info=document.getElementById('historyinfo');info.textContent='◌ Statistik wird geladen …';
 try{const r=await fetch('/api/history');if(!r.ok)throw Error('Statistik nicht erreichbar');historyData=await r.json();historyAt=Date.now();if(!document.hidden)renderHistory();}
 catch(e){info.textContent='⚠ '+e.message;}
 finally{historyLoading=false;}
}
function renderHistory(){
 if(!historyData)return;
 const d=historyData,eur=n=>n.toLocaleString('de-DE',{style:'currency',currency:'EUR'});
 const valued=v=>v.valued>0,empty=v=>!(v.seconds>0);
 const money=(v,key)=>valued(v)?'≈ '+eur(v[key]):empty(v)?eur(0):'—';
 const partial=v=>valued(v)&&v.discharge-v.valued>0.000001;
 document.getElementById('historyinfo').textContent=(d.started?'≈ Geschätzte Ersparnis aus ausgeführten Ladeaufträgen · seit '+d.started:'Noch keine Ladeaufträge erfasst. Ein zukünftiger Smart-Plan zählt erst, sobald die App lädt.')+(d.enabled?'':' · Erfassung deaktiviert: in den Einstellungen einschalten.');
 const box=document.getElementById('periodstats');box.replaceChildren();
 for(const [key,title] of [['today','Heute'],['yesterday','Gestern'],['last30','Letzte 30 Tage'],['last365','Letzte 365 Tage']]){
  const v=d.periods[key],card=document.createElement('article');card.className='card statcard';
  const h=document.createElement('p');h.className='eyebrow';h.textContent=title;
  const amount=document.createElement('strong');amount.className='big';amount.textContent=money(v,'saving');
  const label=document.createElement('p');label.textContent=valued(v)&&v.saving<0?'Mehrkosten laut Plan':'Ersparnis laut Plan';
  const detail=document.createElement('p');detail.className='muted';
  detail.textContent=empty(v)?'Keine Ladeaufträge in diesem Zeitraum.':!valued(v)?'Ladeaufträge vorhanden, aber Preise fehlen für die Geldberechnung.':`Vermiedene Stromkosten: ${eur(v.avoided)} · Ladekosten: ${eur(v.cost)} · Verschleiß: ${eur(Math.max(0,v.avoided-v.cost-v.saving))}${partial(v)?' · Teilbetrag: Für weitere Ladeaufträge fehlen Preise.':''}`;
  card.append(h,amount,label,detail);box.append(card);
 }
 const tbody=document.getElementById('historyrows');tbody.replaceChildren();
 const rows=d[document.getElementById('historygroup').value];
 for(const v of rows){const tr=document.createElement('tr');for(const text of [v.period,money(v,'saving')+(partial(v)?' (Teilbetrag)':''),money(v,'cost'),money(v,'avoided')]){const td=document.createElement('td');td.textContent=text;tr.append(td);}tbody.append(tr);}
 if(!rows.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=4;cell.textContent='Noch keine Ladeaufträge erfasst. Frühere Ladungen werden nicht rückwirkend übernommen.';row.append(cell);tbody.append(row);}
}
let installPrompt=null,pwaRegistration=null;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;});
function setPushButtons(active){document.getElementById('pushenable').hidden=active;document.getElementById('pushdisable').hidden=!active;document.getElementById('pushtest').hidden=!active;}
async function initializePwa(){
 const status=document.getElementById('pwastatus');
 if(!window.isSecureContext||!('serviceWorker' in navigator)){status.textContent='🔒 Eine vertrauenswürdige HTTPS-Adresse ist erforderlich.';return;}
 try{
  pwaRegistration=await navigator.serviceWorker.register('/sw.js');
  const standalone=window.matchMedia('(display-mode: standalone)').matches||navigator.standalone;
  status.textContent=standalone?'✓ LUNA ist als App geöffnet':'⊕ Installieren oder auf dem iPhone: Teilen → Zum Home-Bildschirm';
  if('PushManager' in window){const sub=await pwaRegistration.pushManager.getSubscription();setPushButtons(!!sub);}
  else document.getElementById('pushstatus').textContent='Push hier nicht verfügbar. Auf dem iPhone die installierte App öffnen.';
 }catch(e){status.textContent='⚠ App-Registrierung fehlgeschlagen. HTTPS und Browser prüfen.';}
}
async function pushAction(button,callback){
 button.disabled=true;button.classList.add('button-loading');
 try{await callback();}catch(e){document.getElementById('pushstatus').textContent='⚠ '+e.message;}
 finally{button.disabled=false;button.classList.remove('button-loading');}
}
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelector('[data-tab="statistics"]').addEventListener('click',()=>loadHistory());
 document.getElementById('historygroup').onchange=renderHistory;
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadHistory();});
 setInterval(()=>loadHistory(),60000);
 document.getElementById('installapp').onclick=async()=>{
  if(installPrompt){await installPrompt.prompt();installPrompt=null;}
  else document.getElementById('pwastatus').textContent=window.isSecureContext?'Auf dem iPhone: Teilen → Zum Home-Bildschirm. Sonst das Installationssymbol im Browser verwenden.':'Zuerst HTTPS einrichten; Anleitung im Repository unter PWA.';
 };
 document.getElementById('pushenable').onclick=e=>pushAction(e.currentTarget,async()=>{
  if(!pwaRegistration||!('PushManager' in window)||!window.isSecureContext)throw Error('HTTPS und einen Push-fähigen Browser bzw. die installierte iPhone-App verwenden.');
  if(!lastStatus?.push?.available)throw Error('Zuerst das Push-Paket auf dem Server installieren.');
  if(!lastStatus.settings.push_contact)throw Error('Zuerst Kontakt-E-Mail für Push speichern.');
  const permission=await Notification.requestPermission();
  if(permission!=='granted')throw Error('Benachrichtigungen wurden nicht erlaubt.');
  await Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(Error('App noch nicht bereit; erneut versuchen.')),10000))]);
  const key=lastStatus.push.public_key;const bytes=Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-key.length%4)%4)),x=>x.charCodeAt(0));
  const sub=await pwaRegistration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
  try{await api('push-subscribe',{subscription:sub.toJSON()});}catch(e){await sub.unsubscribe();throw e;}
  setPushButtons(true);document.getElementById('pushstatus').textContent='✓ Wichtige Meldungen aktiviert.';
 });
 document.getElementById('pushdisable').onclick=e=>pushAction(e.currentTarget,async()=>{
  const sub=await pwaRegistration?.pushManager.getSubscription();
  if(sub){await api('push-unsubscribe',{endpoint:sub.endpoint});await sub.unsubscribe();}
  setPushButtons(false);document.getElementById('pushstatus').textContent='Benachrichtigungen für dieses Gerät ausgeschaltet.';
 });
 document.getElementById('pushtest').onclick=e=>pushAction(e.currentTarget,async()=>{await api('push-test',{});document.getElementById('pushstatus').textContent='Testnachricht angefordert.';});
 initializePwa();
});

const updateStates=new Set(['queued','checking','dependencies','testing','installing','restarting','rollback']);
let updateTimer=null,updateWatch=false,updateStarting=false;
function renderUpdate(u,d){
 if(!u)return;
 const active=updateStates.has(u.state),button=document.getElementById('updateapp');
 document.getElementById('updateversion').textContent='Installierter Stand: '+(u.revision?u.revision.slice(0,8):'kein Git-Stand erkannt');
 const hold=d?.discharge?.request?.until&&Date.parse(d.discharge.request.until)>Date.now();
 const reason=d?.mode&&d.mode!=='off'?'Zum Update Steuerung auf Aus stellen.':hold?'Manuelle Entladesperre aufheben.':d?.discharge?.restore_pending?'Bestätigung der Entladefreigabe wird abgewartet.':d?.job&&d.job!=='sample'?'Gerätevorgang läuft noch: '+d.job:'';
 document.getElementById('updatestatus').textContent=active?(u.message||'Update läuft …'):updateStarting?'Update wird angefordert; eine laufende Messwertabfrage wird abgewartet …':reason||((u.message||'Bereit für Updates')+(d?.job==='sample'?' · Update kann angefordert werden; Messwertabfrage wird abgewartet.':''));
 button.disabled=active||updateStarting||!!reason;
 button.classList.toggle('button-loading',active||updateStarting);
 if(active){updateWatch=true;scheduleUpdatePoll();}
 else if(updateWatch){updateWatch=false;clearTimeout(updateTimer);if(u.state==='done')window.location.reload();}
}
function scheduleUpdatePoll(){clearTimeout(updateTimer);if(updateWatch&&!document.hidden)updateTimer=setTimeout(pollUpdate,2000);}
async function pollUpdate(){
 if(document.hidden)return;
 try{const r=await fetch('/api/update');if(r.status===401){updateWatch=false;document.getElementById('updatestatus').textContent='Bitte nach dem Neustart erneut anmelden.';return;}if(!r.ok)throw Error();renderUpdate(await r.json(),lastStatus);}
 catch{document.getElementById('updatestatus').textContent='Verbindung unterbrochen · Neustart wird abgewartet …';}
 finally{scheduleUpdatePoll();}
}
document.addEventListener('DOMContentLoaded',()=>{
 document.getElementById('updateapp').onclick=async()=>{
  if(updateStarting||updateWatch)return;
  updateStarting=true;const b=document.getElementById('updateapp');b.disabled=true;b.classList.add('button-loading');
  document.getElementById('updatestatus').textContent='Update wird angefordert …';
  try{await api('update',{});updateWatch=true;await pollUpdate();}
  catch(e){document.getElementById('updatestatus').textContent=e.message;}
  finally{updateStarting=false;if(!updateWatch){b.disabled=false;b.classList.remove('button-loading');}}
 };
 document.addEventListener('visibilitychange',()=>{clearTimeout(updateTimer);if(!document.hidden&&updateWatch)pollUpdate();});
});
