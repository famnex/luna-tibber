'use strict';
const phaseColor=action=>({charge:'#2f8d62',discharge:'#ce732a',hold:'#8c9da2'}[action]||'#91af83');
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
function solarSeries(d){
 if(!d.settings?.pv_enabled||!d.prices?.length)return [];
 const first=Date.parse(d.prices[0].start),last=Date.parse(d.prices[d.prices.length-1].end);
 return (d.pv_forecast?.series||[]).map(r=>({start:Date.parse(r.start),end:Date.parse(r.end),kw:r.kw}))
  .filter(r=>Number.isFinite(r.start)&&Number.isFinite(r.end)&&r.end>r.start&&Number.isFinite(r.kw)&&r.kw>=0&&r.end>first&&r.start<last).sort((a,b)=>a.start-b.start);
}
function solarAverage(rows,start,end){
 if(!(end>start))return null;
 let cursor=start,energy=0;
 for(const row of rows){const a=Math.max(cursor,row.start),b=Math.min(end,row.end);if(b<=a)continue;if(a>cursor)return null;energy+=(b-a)*row.kw;cursor=b;if(cursor>=end)return energy/(end-start);}
 return null;
}
function renderExtras(d){
 renderUpdate(d.update,d);
 renderPv(d);

 const q=d.dispatch_preview;
 const j=d.smart_preview?.joint,b=j?.bridge;
 const num=n=>typeof n==='number'?n.toLocaleString('de-DE',{maximumFractionDigits:2}):'—';
 const hour=t=>t?new Date(t).toLocaleTimeString('de-DE',{timeZone:d.settings.timezone,hour:'2-digit',minute:'2-digit'}):'Tagesende';
 document.getElementById('dispatchreason').textContent=b?(j.night_complete===false?'☀ Verbleibender Bedarf bis ':'☀ Morgenversorgung bis ')+hour(b.pv_start):q?.enabled?q.reason:'Smart-Entladung nicht aktiv';
 const g=j?.guard||q?.guard;
 const protection=g?.unavailable?'🔒 Daten fehlen · Entladung vorläufig gesperrt':g?`🔒 Jetzt benötigt: ${num(g.required_kwh)} kWh Akku · Sperrgrenze ${num(g.threshold_soc)} % SOC\n${num(g.surplus_kwh)} kWh oberhalb der Schutzgrenze · ${g.hold?'Entladung gesperrt':'Entladung nach Preisplan'}${d.mode==='smart'?'':' · Vorschau, Smart nicht aktiv'}`:'Schutzberechnung noch nicht verfügbar';
 document.getElementById('dispatchsummary').textContent=b?
  `${num(b.demand_kwh)} kWh Bedarf + ${num(b.buffer_kwh)} kWh automatischer Wetterpuffer\n${j.night_complete===false?'Für verbleibenden Bedarf':'Am Nachtende benötigt'}: ${num(b.required_soc)} % SOC inkl. ${num(b.floor_soc)} % Gerätegrenze\n${b.shortfall_kwh>.02?'⚠ Planlücke '+num(b.shortfall_kwh)+' kWh · Kaufgrenze, Ladezeit und Ziel prüfen':'✓ Morgenversorgung laut Plan gedeckt'}\n${protection}${j.pv_available===false?'\n☁ PV-Daten fehlen · gerechnet ohne Solarertrag':''}`:
  protection;
 if(!window.isSecureContext)document.getElementById('pushstatus').textContent='🔒 HTTPS für Installation und Push erforderlich.';
 else if(d.push?.error)document.getElementById('pushstatus').textContent=d.push.error;
}
function renderPv(d){
 const card=document.getElementById('pvcard');if(!card)return;
 card.hidden=!d.settings.pv_enabled;if(card.hidden)return;
 const p=d.smart_preview?.pv,forecast=d.pv_forecast||{},num=n=>typeof n==='number'?n.toLocaleString('de-DE',{maximumFractionDigits:2}):'—';
 document.getElementById('pvstatus').textContent=p?.reason||forecast.reason||'Wetterprognose wird geladen …';
 const start=d.smart_preview?.joint?.bridge?.night_end||d.smart_preview?.night_end;
 document.getElementById('pvday').textContent=start?'Für den Tag ab '+new Date(start).toLocaleString('de-DE',{timeZone:d.settings.timezone}):'Nächster Tag nach dem Nachtfenster';
 const j=d.smart_preview?.joint;
 document.getElementById('pvsummary').textContent=j?`☀ ${num(j.solar?.generation_kwh)} kWh Erzeugung\n⌂ ${num(j.solar?.direct_kwh)} kWh direkt für das Haus\n↗ ${num((j.solar?.generation_kwh||0)-(j.solar?.direct_kwh||0))} kWh Überschuss vor Speicherverlusten und Kapazitätsgrenze`:p?.applied?`☀ ${num(p.generation_kwh)} kWh Erzeugung · ${num(p.direct_kwh)} kWh direkt\n☾ ${num(p.target_soc)} % statt ${num(d.settings.target_soc)} % · ${num(p.reduction_kwh)} kWh weniger Nachtladung`:'Vollständige Wetterdaten und aktuellen Akkustand abwarten.';
 document.getElementById('pvage').textContent=typeof forecast.age_seconds==='number'?`Aktualisiert vor ${Math.floor(forecast.age_seconds/60)} min`:'Noch keine gültigen Wetterdaten.';
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

const updateStates=new Set(['preparing','queued','checking','dependencies','testing','installing','restarting','rollback']);
let updateTimer=null,updateWatch=false,updateStarting=false,updateDisconnectedAt=0;
function renderUpdateProgress(u){
 const wrap=document.getElementById('updateprogresswrap');if(!wrap)return;
 const labels=['Steuerung stoppen','Ladestopp bestätigen','Entladung freigeben','Git prüfen','Abhängigkeiten prüfen','Tests ausführen','Version installieren','Dienst neu starten','Bereitschaft bestätigen'];
 const steps={queued:4,checking:4,dependencies:5,testing:6,installing:7,restarting:8,done:9,current:9};
 const n=u.state==='preparing'?(u.step||1):steps[u.state],active=updateStates.has(u.state);
 wrap.hidden=!active&&!['done','current','failed'].includes(u.state);
 const bar=document.getElementById('updateprogress');
 if(u.state==='failed')bar.value=0;else if(n)bar.value=['done','current'].includes(u.state)?9:n-1;else bar.removeAttribute('value');
 document.getElementById('updatestep').textContent=u.state==='current'?'Keine neuere Version vorhanden':u.state==='failed'?'Abgebrochen · Details unten':u.state==='rollback'?'Vorherige Version wird wiederhergestellt':n?`Schritt ${n} von 9 · ${labels[n-1]}${u.at?' · seit '+Math.max(0,Math.floor(Date.now()/1000-u.at))+' s':''}`:'Vorbereitung läuft …';
 const list=document.getElementById('updatesteps');list.replaceChildren();
 for(const item of u.steps||[]){const li=document.createElement('li');li.textContent=new Date(item.at*1000).toLocaleTimeString('de-DE')+' · '+item.message;list.append(li);}
}
async function updateStatusRequest(){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
 try{return await fetch('/api/update',{signal:controller.signal});}finally{clearTimeout(timer);}
}
function renderUpdate(u,d){
 if(!u)return;
 renderUpdateProgress(u);
 const active=updateStates.has(u.state),button=document.getElementById('updateapp');
 document.getElementById('updateversion').textContent='Installierter Stand: '+(u.revision?u.revision.slice(0,8):'kein Git-Stand erkannt');
 document.getElementById('updatestatus').textContent=active?(u.message||'Update läuft …'):updateStarting?'Stopp und Update werden vorbereitet …':u.message||'Bereit für Updates';
 button.disabled=active||updateStarting;
 button.classList.toggle('button-loading',active||updateStarting);
 if(active){updateWatch=true;scheduleUpdatePoll();}
 else if(updateWatch){updateWatch=false;clearTimeout(updateTimer);if(u.state==='done')window.location.reload();}
}
function scheduleUpdatePoll(){clearTimeout(updateTimer);if(updateWatch&&!document.hidden)updateTimer=setTimeout(pollUpdate,2000);}
async function pollUpdate(){
 if(document.hidden)return;
 try{
  const r=await updateStatusRequest();
  if(r.status===401){updateWatch=false;const b=document.getElementById('updateapp');b.disabled=false;b.classList.remove('button-loading');document.getElementById('updatestatus').textContent='Bitte nach dem Neustart erneut anmelden.';return;}
  if(!r.ok)throw Error();const status=await r.json();updateDisconnectedAt=0;renderUpdate(status,lastStatus);
 }catch{
  if(!updateDisconnectedAt)updateDisconnectedAt=Date.now();
  const seconds=Math.floor((Date.now()-updateDisconnectedAt)/1000);
  document.getElementById('updatestatus').textContent=`Server nicht erreichbar · seit ${seconds} s. Neustart wird abgewartet …`;
  if(seconds>=120){updateWatch=false;const b=document.getElementById('updateapp');b.disabled=false;b.classList.remove('button-loading');document.getElementById('updatestatus').textContent='Seit zwei Minuten keine Rückmeldung. Dienst und update.log per PuTTY prüfen; der Updateausgang ist unbekannt.';}
 }finally{scheduleUpdatePoll();}
}
document.addEventListener('DOMContentLoaded',()=>{
 document.getElementById('updateapp').onclick=async()=>{
  if(updateStarting||updateWatch)return;
  updateStarting=true;const b=document.getElementById('updateapp');b.disabled=true;b.classList.add('button-loading');
  document.getElementById('updatestatus').textContent='Update wird angefordert …';
  renderUpdateProgress({state:'preparing',step:1});
  let timer;
  try{await Promise.race([api('update',{}),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Anforderung noch unbestätigt')),20000);})]);updateWatch=true;await pollUpdate();}
  catch(e){document.getElementById('updatestatus').textContent=e.message;if(e.message==='Anforderung noch unbestätigt'){updateWatch=true;scheduleUpdatePoll();}else renderUpdateProgress({state:'failed'});}
  finally{clearTimeout(timer);updateStarting=false;if(!updateWatch){b.disabled=false;b.classList.remove('button-loading');}}
 };
 document.addEventListener('visibilitychange',()=>{clearTimeout(updateTimer);if(!document.hidden&&updateWatch)pollUpdate();});
});

// Smoothstep cubic curves stay between neighbouring samples; never bridge gaps.
// This affects only SVG geometry, not hourly averages, tooltips or scheduling.
function smoothSolarPath(rows,first,last,x,y){
 const segments=[];let segment=[],previous=null;
 for(const r of rows){
  const a=Math.max(first,r.start),b=Math.min(last,r.end);if(b<=a)continue;
  if(previous!==a&&segment.length){segments.push(segment);segment=[];}
  if(!segment.length)segment.push([a,r.kw]);
  segment.push([(a+b)/2,r.kw]);previous=b;
  const next=rows.find(q=>q.start===b);
  if(!next||b===last){segment.push([b,r.kw]);segments.push(segment);segment=[];previous=null;}
 }
 if(segment.length)segments.push(segment);
 return segments.map(points=>{
  let path=' M'+x(points[0][0])+' '+y(points[0][1]);
  for(let i=1;i<points.length;i++){
   const [a,v]=points[i-1],[b,w]=points[i],left=x(a),right=x(b),dx=(right-left)/3;
   path+=' C'+(left+dx)+' '+y(v)+' '+(right-dx)+' '+y(w)+' '+right+' '+y(w);
  }
  return path;
 }).join('');
}
// Calendar days in the installation timezone, including 23/25-hour DST days.
function planDayKey(d,now,offset=0){
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:d.settings.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(now));
 const value=type=>Number(parts.find(p=>p.type===type).value);
 return new Date(Date.UTC(value('year'),value('month')-1,value('day')+offset)).toISOString().slice(0,10);
}
function dayPrices(d,now,offset){
 const key=planDayKey(d,now,offset);
 return (d.prices||[]).filter(p=>planDayKey(d,p.start)===key).sort((a,b)=>Date.parse(a.start)-Date.parse(b.start));
}
function todayPhases(d,now=Date.now(),offset=0){
 const prices=dayPrices(d,now,offset);
 if(!prices.length)return [];
 const start=offset===0?Math.max(now,Date.parse(prices[0].start)):Date.parse(prices[0].start),end=Date.parse(prices[prices.length-1].end);
 let phases=chartPhases(d);
 if(d.mode==='planned'&&d.planned)phases=[{start:d.planned.start,end:d.planned.end,action:'charge',reason:'manual'}];
 if(d.mode==='on'&&d.remaining_seconds>0)phases=[{start:new Date(now).toISOString(),end:new Date(now+d.remaining_seconds*1000).toISOString(),action:'charge',reason:'manual'}];
 phases=phases.filter(p=>Date.parse(p.end)>start&&Date.parse(p.start)<end);
 if(!phases.length||end<=start)return [];
 const boundaries=[...new Set([start,end,...phases.flatMap(p=>[Date.parse(p.start),Date.parse(p.end)]).filter(t=>t>start&&t<end)])].sort((a,b)=>a-b);
 const result=[];
 for(let i=0;i<boundaries.length-1;i++){
  const a=boundaries[i],b=boundaries[i+1],entry=phaseEntryAt(phases,a),action=entry?.action||'unknown';
  const prev=result[result.length-1];
  if(prev&&prev.action===action)prev.end=b;
  else result.push({start:a,end:b,action});
 }
 return result;
}
let selectedPlanDay=0;
function bindPlanNavigation(card){
 if(card.dataset.navigationReady)return;
 card.dataset.navigationReady='true';
 const select=offset=>{selectedPlanDay=offset;renderTodayPlan(card.planStatus);};
 document.getElementById('plan-today').onclick=()=>select(0);
 document.getElementById('plan-tomorrow').onclick=()=>select(1);
 let origin=null;
 card.addEventListener('touchstart',e=>{
  origin=e.touches.length===1&&!e.target.closest('button')?{x:e.touches[0].clientX,y:e.touches[0].clientY,time:Date.now()}:null;
 },{passive:true});
 card.addEventListener('touchcancel',()=>{origin=null;},{passive:true});
 card.addEventListener('touchend',e=>{
  if(!origin)return;
  const start=origin;origin=null;
  const touch=e.changedTouches[0];if(!touch||e.touches.length)return;
  const dx=touch.clientX-start.x,dy=touch.clientY-start.y;
  if(Date.now()-start.time<800&&Math.abs(dx)>=60&&Math.abs(dx)>Math.abs(dy)*1.5)select(dx<0?1:0);
 },{passive:true});
}
function renderTodayPlan(d){
 const root=document.getElementById('todayphases');if(!root)return;
 const card=document.getElementById('dayplan');card.planStatus=d;bindPlanNavigation(card);
 const now=Date.now(),offset=selectedPlanDay,day=offset?'Morgen':'Heute';
 const rows=todayPhases(d,now,offset),hasPrices=dayPrices(d,now,offset).length>0;
 const signature=JSON.stringify([offset,planDayKey(d,now,offset),d.mode,hasPrices,rows.map(r=>[Math.floor(r.start/60000),r.end,r.action])]);
 if(root.dataset.signature===signature)return;root.dataset.signature=signature;root.replaceChildren();
 document.getElementById('dayplantitle').textContent=day+' geplant';
 for(const [id,value] of [['plan-today',0],['plan-tomorrow',1]]){
  const button=document.getElementById(id);button.setAttribute('aria-pressed',String(offset===value));button.classList.toggle('selected',offset===value);
 }
 const key=planDayKey(d,now,offset),date=key.slice(8)+'.'+key.slice(5,7)+'.';
 document.getElementById('todayplanhint').textContent=date+' · '+(rows.length?(offset?'Vorschau · geplante Freigaben':'Ab jetzt · geplante Freigaben'):d.mode==='off'?'Aus · kein Ladeplan aktiv':!hasPrices?'Preise noch nicht verfügbar':day+' noch keine bestätigten Planphasen');
 if(!rows.length)return;
 const bar=document.createElement('div');bar.className='plan-strip';bar.setAttribute('aria-hidden','true');
 const list=document.createElement('ol');list.className='plan-steps';
 const fmt=t=>new Date(t).toLocaleTimeString('de-DE',{timeZone:d.settings.timezone,hour:'2-digit',minute:'2-digit'});
 const labels={charge:['↑','Laden'],discharge:['↓','Entladung frei'],hold:['Ⅱ','Pause'],unknown:['·','Keine Planung']};
 for(const row of rows){
  const [icon,label]=labels[row.action],part=document.createElement('span');part.className='phase-'+row.action;part.style.flex=String(row.end-row.start);bar.append(part);
  const li=document.createElement('li');li.className='phase-'+row.action;
  const symbol=document.createElement('span');symbol.className='plan-symbol';symbol.textContent=icon;
  const time=document.createElement('strong');time.textContent=fmt(row.start)+'–'+fmt(row.end);
  const text=document.createElement('small');text.textContent=label;li.append(symbol,time,text);list.append(li);
 }
 root.append(bar,list);
}

const chartVisibility={pv:true,battery:true};
function batterySeries(d,now=Date.now()){
 const measured=(d.battery_history||[]).map(p=>({time:Date.parse(p.time),soc:p.soc})).filter(p=>Number.isFinite(p.time)&&Number.isFinite(p.soc)&&p.time<=now&&p.soc>=0&&p.soc<=100);
 const t=d.telemetry||{},stamp=Date.parse(t.time),fresh=Number.isFinite(t.soc)&&Number.isFinite(stamp)&&now-stamp<=120000&&now>=stamp;
 if(fresh)measured.push({time:stamp,soc:t.soc});
 measured.sort((a,b)=>a.time-b.time);
 const forecast=[],c=d.settings,capacity=c.battery_capacity_kwh;
 if(!fresh||!(capacity>0))return {measured,forecast};
 const trace=d.mode==='smart'?d.smart_preview?.joint?.trace:null;
 if(trace?.length){
  const floor=c.battery_floor_soc||0;
  for(const row of trace){
   forecast.push({time:Date.parse(row.start),soc:floor+row.start_kwh/capacity*100});
   forecast.push({time:Date.parse(row.end),soc:floor+row.end_kwh/capacity*100});
  }
 }else if(c.pv_enabled&&d.pv_forecast?.series?.length&&c.base_load_w>0&&d.mode==='off'){
  // Normal self-consumption estimate when Smart is off; never imply its plan is active.
  let soc=t.soc,cursor=now;const eta=Math.sqrt(c.roundtrip_efficiency),floor=c.battery_floor_soc||0;
  forecast.push({time:now,soc});
  for(const row of d.pv_forecast.series){
   const start=Math.max(now,Date.parse(row.start)),end=Date.parse(row.end);if(end<=start)continue;
   if(start>cursor+1000)break;
   for(let a=start;a<end;){
    const b=Math.min(end,a+300000),local=new Intl.DateTimeFormat('en-GB',{timeZone:c.timezone,hour:'2-digit',hourCycle:'h23'}).format(new Date(a));
    const extra=Number(local)>=c.extra_load_start_hour&&Number(local)<c.extra_load_end_hour?c.extra_load_kwh/(c.extra_load_end_hour-c.extra_load_start_hour):0;
    const net=row.kw-c.base_load_w/1000-extra,held=Date.parse(d.discharge?.request?.until)>a;
    const energy=net>=0?Math.min(net*eta,c.charge_power_w/1000):held?0:net/eta;
    soc=Math.max(floor,Math.min(100,soc+energy*(b-a)/3600000/capacity*100));forecast.push({time:b,soc});a=b;
   }
   cursor=end;
  }
 }
 return {measured,forecast:forecast.filter(p=>Number.isFinite(p.soc)&&Number.isFinite(p.time))};
}
function socPath(points,first,last,x,y){
 let path='',previous=null;
 for(const p of points){if(p.time<first||p.time>last)continue;
  const right=x(new Date(p.time).toISOString()),value=y(p.soc);
  if(previous===null||p.time-previous.time>75*60000)path+=' M'+right+' '+value;
  else{
   const left=x(new Date(previous.time).toISOString()),dx=(right-left)/3;
   // Bounded cubic: stays between measured SOCs, no invented peaks.
   path+=' C'+(left+dx)+' '+y(previous.soc)+' '+(right-dx)+' '+value+' '+right+' '+value;
  }
  previous=p;
 }
 return path;
}
