'use strict';
let journalBusy=false,journalBefore=null,journalAt=0,journalKey='';
function journalVisible(){return !document.hidden&&!document.getElementById('dashboard').hidden&&!document.getElementById('journal').hidden;}
function journalQuery(){return 'hours='+document.getElementById('journalhours').value+'&all='+(document.getElementById('journalall').checked?'1':'0');}
function journalTime(stamp){
 const zone=typeof lastStatus!=='undefined'?lastStatus?.settings?.timezone||'Europe/Berlin':'Europe/Berlin';
 return new Date(stamp*1000).toLocaleString('de-DE',{timeZone:zone,day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'shortOffset'});
}
let journalExportBusy=false;
let journalFilter='all';
const journalNumber=(n,unit='')=>Number.isFinite(n)?n.toLocaleString('de-DE',{maximumFractionDigits:2})+unit:null;
function journalCard(event){
 const d=event.data||{},kind=event.event,power=d.battery_power_w;
 let type='info',symbol='·',title='Ereignis';
 if(['snapshot','test_sample','decision'].includes(kind)){
  if(Number.isFinite(power)&&power>100){type='charge';symbol='↑';title='Ladung gemessen';}
  else if(Number.isFinite(power)&&power< -100){type='discharge';symbol='↓';title='Entladung gemessen';}
  else {type='hold';symbol='Ⅱ';title=Number.isFinite(power)?'Akku ruht':'Messwert fehlt';}
 }else if(kind==='charge_command'){type='charge';symbol='↑';title='Ladebefehl gesendet';}
 else if(['stopped','stopped_on_exit','target_reached'].includes(kind)){type='hold';symbol='■';title=kind==='target_reached'?'Ladeziel erreicht':'Stopp bestätigt';}
 else if(kind==='discharge_synced'){type=d.discharge_confirmation?.locked?'hold':'discharge';symbol=type==='hold'?'Ⅱ':'↓';title=type==='hold'?'Entladesperre bestätigt':'Entladesteuerung abgeglichen';}
 else if(['error','price_error','stop_unconfirmed'].includes(kind)){type='error';symbol='!';title=kind==='stop_unconfirmed'?'Stopp unbestätigt':'Störung';}
 else if(kind==='service_started'){symbol='↻';title='Dienst gestartet';}
 else if(kind==='user_action'){symbol='⚙';title='Einstellung übernommen';}
 else if(kind==='controller_exit'){symbol='■';title='Geräteprozess beendet';}
 if(d.live===false)title+=' · Simulation';
 const metrics=[journalNumber(d.soc,' % SOC'),Number.isFinite(power)?journalNumber(power/1000,' kW gemessen'):null,
  kind==='charge_command'?journalNumber(d.watts/1000,' kW angefordert'):null,
  journalNumber(d.price_ct_kwh,' ct/kWh'),journalNumber(d.minutes,' min'),
  journalNumber(d.guard?.threshold_soc,' % Schutzgrenze'),journalNumber(d.guard?.required_kwh,' kWh später benötigt')].filter(Boolean);
 const reasons=[d.reason,d.dispatch?.reason].filter(Boolean);
 let reason=d.plan_change||(reasons.length?[...new Set(reasons)].join(' · '):event.text);
 if(kind==='charge_command')reason='Befehl gesendet. Tatsächlichen Ladebeginn zeigen die folgenden Messwerte.';
 return {type,symbol,title,metrics,reason};
}
function filterJournal(){
 const list=document.getElementById('journalentries');let shown=0;
 for(const row of list.children){row.hidden=journalFilter!=='all'&&row.dataset.kind!==journalFilter;if(!row.hidden)shown++;}
 const status=document.getElementById('journalfilterstatus');if(status)status.textContent=journalFilter==='all'?'':shown+' passende Einträge geladen · für weitere Einträge unten nachladen.';
}
function appendJournalPlan(details,plan){
 const box=document.createElement('div');box.className='journal-plan';
 const title=document.createElement('strong');title.textContent='Planstand';box.append(title);
 const facts=[journalNumber(plan.config?.target_soc,' % SOC-Obergrenze'),journalNumber(plan.charging?.planned_kwh,' kWh Netzladung'),journalNumber(plan.charging?.effective_target_soc,' % SOC am Nachtende ≈')].filter(Boolean);
 const p=document.createElement('p');p.textContent=facts.join(' · ');box.append(p);
 for(const phase of plan.joint?.phases||[]){const row=document.createElement('p');row.textContent=(phase.action==='charge'?'↑ Laden':phase.action==='discharge'?'↓ Entladung frei':'Ⅱ Pause')+' · '+journalTime(Date.parse(phase.start)/1000)+' – '+journalTime(Date.parse(phase.end)/1000)+' · '+(journalNumber(phase.kwh,' kWh')||'')+' · '+(journalNumber(phase.low_ct,' ct/kWh')||'')+(phase.high_ct!==phase.low_ct?' bis '+journalNumber(phase.high_ct,' ct/kWh'):'');box.append(row);}
 const raw=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='Vollständige Plandaten';pre.textContent=JSON.stringify(plan,null,2);raw.append(summary,pre);box.append(raw);details.append(box);
}
async function loadJournal(more=false){
 if(journalBusy||!journalVisible())return;
 journalBusy=true;const key=journalQuery(),button=document.getElementById(more?'journalmore':'journalrefresh');
 button.disabled=true;button.classList.add('button-loading');button.setAttribute('aria-busy','true');
 try{
  const r=await fetch('/api/journal?'+key+(more&&journalBefore?'&before='+journalBefore:''));
  if(!r.ok)throw Error('Verlauf nicht erreichbar – Anmeldung und Verbindung prüfen.');
  const d=await r.json();if(key!==journalQuery()||!journalVisible())return;
  const list=document.getElementById('journalentries');if(!more)list.replaceChildren();
  for(const event of d.events){
   const card=journalCard(event),li=document.createElement('li'),time=document.createElement('time'),p=document.createElement('p');
   li.className='journal-event event-'+card.type;li.dataset.kind=card.type;
   time.dateTime=new Date(event.timestamp*1000).toISOString();time.textContent=journalTime(event.timestamp)+' · '+event.mode;
   const head=document.createElement('div');head.className='event-heading';
   const icon=document.createElement('span');icon.className='event-icon';icon.setAttribute('aria-hidden','true');icon.textContent=card.symbol;
   const title=document.createElement('h3');title.textContent=card.title;head.append(icon,title);
   const metrics=document.createElement('div');metrics.className='event-metrics';
   for(const text of card.metrics){const chip=document.createElement('span');chip.textContent=text;metrics.append(chip);}
   const label=document.createElement('small');label.textContent='Grund / Beobachtung';
   p.textContent=card.reason;li.append(time,head,metrics,label,p);
   const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
   summary.textContent='Messwerte & Entscheidungsdaten · Plan #'+(event.plan_id??'—');
   pre.textContent=event.text+'\n\n'+JSON.stringify(event.data,null,2);details.append(summary,pre);
   if(event.plan_id){
    const button=document.createElement('button');button.textContent='◷ Plan #'+event.plan_id+' ansehen';button.className='plan-link';
    button.onclick=async()=>{button.disabled=true;button.classList.add('button-loading');
     try{const r=await fetch('/api/journal/plan?id='+event.plan_id);if(!r.ok)throw Error('Plan nicht mehr verfügbar.');
      const plan=await r.json();appendJournalPlan(li,plan);button.remove();
     }catch(e){button.textContent=e.message;button.disabled=false;}finally{button.classList.remove('button-loading');}};
    li.append(button);
   }
   li.append(details);list.append(li);
  }
  filterJournal();journalBefore=d.before;journalKey=key;journalAt=Date.now();
  document.getElementById('journalmore').hidden=!journalBefore;
  document.getElementById('journalstatus').textContent=d.error||(!list.children.length?'Noch keine Einträge in diesem Zeitraum. Aufzeichnung beginnt mit diesem Update.':'Neueste Einträge zuerst · vollständige Planstände im Export.');
 }catch(e){document.getElementById('journalstatus').textContent=e.message;}
 finally{journalBusy=false;button.disabled=false;button.classList.remove('button-loading');button.setAttribute('aria-busy','false');}
}
function exportProgress(value,text){
 const wrap=document.getElementById('exportprogresswrap');if(!wrap)return;wrap.hidden=false;
 const bar=document.getElementById('exportprogress');
 if(value===null)bar.removeAttribute('value');else bar.value=value;
 document.getElementById('exportstep').textContent=text;
}
async function downloadBody(response){
 const total=Number(response.headers?.get('Content-Length'))||0;
 if(!response.body?.getReader)return response.blob();
 const reader=response.body.getReader(),chunks=[];let received=0;
 while(true){const {done,value}=await reader.read();if(done)break;chunks.push(value);received+=value.byteLength;
  const percent=total?Math.min(100,received/total*100):null;
  exportProgress(percent,`Download: ${percent===null?'':Math.floor(percent)+' % · '}${(received/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})} MB${total?' / '+(total/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})+' MB':''}`);
 }
 return new Blob(chunks,{type:response.headers.get('Content-Type')||'application/octet-stream'});
}
async function exportJournal(kind,button){
 if(journalExportBusy)return; journalExportBusy=true;
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),240000);
 const status=document.getElementById('journalstatus');
 button.disabled=true;button.classList.add('button-loading');button.setAttribute('aria-busy','true');
 exportProgress(null,'1/2 · Protokoll wird zusammengestellt …');
 status.textContent='Export wird erstellt … bei vielen Planständen kann das bis zu drei Minuten dauern.';
 try{
  const r=await fetch('/api/journal/'+(kind==='json'?'export':'text')+'?hours='+document.getElementById('journalhours').value,{signal:controller.signal});
  if(!r.ok)throw Error(r.status===401?'Bitte erneut anmelden.':'Export fehlgeschlagen. Bitte 6 Stunden wählen und erneut versuchen.');
  exportProgress(null,'2/2 · Datei wird übertragen …');
  const blob=await downloadBody(r),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='luna-diagnose-'+new Date().toISOString().slice(0,10)+'.'+(kind==='json'?'json.gz':'txt');
  a.textContent='Datei speichern / öffnen';a.className='download-link';
  status.replaceChildren(document.createTextNode('Export bereit. Falls der Download nicht startet: '),a);
  exportProgress(100,'Datei vollständig übertragen · bereit zum Speichern');
  a.click();
  // Keep a real, tappable link for Safari/PWA user-activation requirements.
  setTimeout(()=>{URL.revokeObjectURL(url);a.remove();},300000);
 }catch(e){exportProgress(0,'Export nicht abgeschlossen');status.textContent=e.name==='AbortError'?'Export dauert zu lange. Bitte 6 Stunden wählen und erneut versuchen.':e.message;}
 finally{journalExportBusy=false;clearTimeout(timeout);button.disabled=false;button.classList.remove('button-loading');button.setAttribute('aria-busy','false');}
}
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-journal-filter]').forEach(button=>button.onclick=()=>{journalFilter=button.dataset.journalFilter;document.querySelectorAll('[data-journal-filter]').forEach(b=>{b.classList.toggle('selected',b===button);b.setAttribute('aria-pressed',String(b===button));});filterJournal();});
 document.getElementById('journalrefresh').onclick=()=>loadJournal();
 document.getElementById('journalmore').onclick=()=>loadJournal(true);
 for(const id of ['journalhours','journalall'])document.getElementById(id).onchange=()=>{journalAt=0;loadJournal();};
 for(const kind of ['json','text'])document.getElementById('journal'+kind).onclick=e=>exportJournal(kind==='text'?'txt':'json',e.currentTarget);
 document.querySelector('[data-tab="journal"]').addEventListener('click',()=>setTimeout(()=>loadJournal(),0));
 document.addEventListener('visibilitychange',()=>{if(journalVisible())loadJournal();});
});
setInterval(()=>{if(journalVisible()&&Date.now()-journalAt>=60000)loadJournal();},1000);

async function loadDiagnosis(){
 const button=document.getElementById('diagnosisrefresh'),box=document.getElementById('diagnosisresult');
 if(button.disabled)return;button.disabled=true;button.classList.add('button-loading');box.textContent='Messwerte werden ausgewertet …';
 try{
  const response=await fetch('/api/journal/diagnosis?hours='+document.getElementById('journalhours').value);
  if(!response.ok)throw Error('Diagnose nicht erreichbar.');const d=await response.json();box.replaceChildren();
  const line=text=>{const p=document.createElement('p');p.textContent=text;box.append(p);};
  line(d.valid_samples+' gültige Zählermessungen · '+d.invalid_samples+' fehlgeschlagene / unplausible Messungen');
  const labels={house:'Hausverbrauch gesamt',outside_evening:'Verbrauch außerhalb Abendfenster',evening:'Verbrauch im Abendfenster',pv:'PV: DC-Messung / AC-Prognose (nur Orientierung)'};
  for(const [key,v] of Object.entries(d.totals)){
   if(!v.hours){line(labels[key]+': noch keine vergleichbaren Messpaare.');continue;}
   line(labels[key]+': '+journalNumber(v.actual_kwh,' kWh gemessen ≈')+' / '+journalNumber(v.planned_kwh,' kWh geplant')+' · Δ '+journalNumber(v.difference_kwh,' kWh')+' · '+journalNumber(v.hours,' h erfasst'));
   if(key!=='pv')line('Ø '+journalNumber(v.actual_mean_w,' W gemessen')+' / '+journalNumber(v.planned_mean_w,' W geplant'));
  }
  line('Vergleich mit der Prognose zum jeweiligen Messzeitpunkt. Nur gemeinsame Messzeiträume, Lücken über 10 Minuten ausgelassen. Leistungswerte werden zwischen Messpunkten angenähert. PV-Eingangsleistung ist DC, die Prognose AC: keine exakte Wirkungsgradbewertung.');
  line('Grundlast und Kochen sind nicht separat messbar. Auto und andere Verbraucher zählen mit. Einstellungen werden nicht automatisch verändert.');
  const title=document.createElement('h3');title.textContent='SOC während bestätigter Entladesperren';box.append(title);
  if(!d.hold_spans.length)line('Keine ausreichend dokumentierte Sperrphase im Zeitraum.');
  for(const s of d.hold_spans){line(journalTime(s.start)+' – '+journalTime(s.end)+' · '+journalNumber(s.start_soc,' %')+' → '+journalNumber(s.end_soc,' %')+' · Abnahme '+journalNumber(s.soc_drop,' Prozentpunkte')+' · höchste gemeldete Entladung '+journalNumber(s.max_discharge_w,' W'));}
  line('SOC-Abnahme bei 0 W ist ein Befund, kein Nachweis für Hausverbrauch oder einen Defekt. Eigenbedarf, SOC-Korrekturen und nicht erfasste Vorgänge lassen sich daraus nicht trennen.');
  for(const s of d.limit_mismatches)line('⚠ '+journalTime(s.time)+': Sperre zuletzt bestätigt, ausgelesene Entladegrenze aber '+journalNumber(s.limit_w,' W')+'. Zeitpunkt einer möglichen externen Änderung unbekannt.');
 }catch(e){box.textContent=e.message;}finally{button.disabled=false;button.classList.remove('button-loading');}
}
document.addEventListener('DOMContentLoaded',()=>{
 const panel=document.getElementById('diagnosispanel');
 panel.addEventListener('toggle',()=>{if(panel.open)loadDiagnosis();});
 document.getElementById('diagnosisrefresh').onclick=loadDiagnosis;
 document.getElementById('journalhours').addEventListener('change',()=>{if(panel.open)loadDiagnosis();});
});
