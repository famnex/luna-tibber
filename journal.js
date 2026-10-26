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

function diagnosisElement(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function diagnosisChart(container,title,rows,lines,unit,maxGap){
 const panel=diagnosisElement('section',undefined,'diag-chart');panel.append(diagnosisElement('h3',title));container.append(panel);
 const data=rows.filter(r=>lines.some(l=>Number.isFinite(r[l.key])));
 if(data.length<2){panel.append(diagnosisElement('p','Noch nicht genügend Messpunkte.','muted'));return;}
 const controls=diagnosisElement('div',undefined,'diag-legend'),plot=diagnosisElement('div'),detail=diagnosisElement('p','Punkte antippen oder mit Tab auswählen.','muted diag-detail');panel.append(controls,plot,detail);
 const active=new Set(lines.map(l=>l.key));
 const time=t=>new Date(t*1000).toLocaleString('de-DE',{timeZone:typeof lastStatus!=='undefined'?lastStatus?.settings?.timezone||'Europe/Berlin':'Europe/Berlin',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 function draw(){
  plot.replaceChildren();const ns='http://www.w3.org/2000/svg';
  const el=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;};
  const svg=el('svg',{viewBox:'0 0 760 250',role:'img','aria-label':title+' · '+unit});plot.append(svg);
  const lo=data[0].time,hi=data[data.length-1].time;
  const ymax=Math.max(unit==='%'?100:1,...data.flatMap(r=>lines.filter(l=>active.has(l.key)).map(l=>Number.isFinite(r[l.key])?r[l.key]/(unit==='kW'?1000:1):0)))* (unit==='%'?1:1.1);
  const x=t=>60+(t-lo)/Math.max(1,hi-lo)*680,y=v=>210-v/ymax*180;
  for(let i=0;i<=4;i++){const v=ymax*i/4;svg.append(el('line',{x1:60,x2:740,y1:y(v),y2:y(v),stroke:'#dbe5de'}));svg.append(el('text',{x:52,y:y(v)+4,'text-anchor':'end',fill:'#61746b','font-size':12},v.toLocaleString('de-DE',{maximumFractionDigits:1})));}
  svg.append(el('text',{x:60,y:17,fill:'#61746b','font-size':12},unit));
  for(let i=0;i<3;i++){const t=lo+(hi-lo)*i/2;svg.append(el('text',{x:x(t),y:238,'text-anchor':i===0?'start':i===2?'end':'middle',fill:'#61746b','font-size':12},time(t)));}
  for(const l of lines){if(!active.has(l.key))continue;let path='',previous=null;
   for(const r of rows){const v=r[l.key];if(!Number.isFinite(v)){previous=null;continue;}const val=v/(unit==='kW'?1000:1);path+=(previous&&r.time-previous.time<=maxGap?' L':' M')+x(r.time)+' '+y(val);previous=r;}
   svg.append(el('path',{d:path,fill:'none',stroke:l.color,'stroke-width':2.5,'stroke-dasharray':l.dashed?'6 4':'none','stroke-linejoin':'round'}));
  }
  for(const r of data){
   const label=time(r.time)+' · '+lines.filter(l=>active.has(l.key)&&Number.isFinite(r[l.key])).map(l=>l.name+': '+journalNumber(r[l.key]/(unit==='kW'?1000:1),' '+unit)).join(' · ');
   const hit=el('rect',{x:x(r.time)-3,y:28,width:6,height:184,fill:'transparent',tabindex:0,role:'img','aria-label':label});hit.append(el('title',{},label));for(const type of ['click','focus','pointerenter'])hit.addEventListener(type,()=>detail.textContent=label);svg.append(hit);
  }
 }
 for(const l of lines){const b=diagnosisElement('button',l.name);b.style.borderColor=l.color;b.setAttribute('aria-pressed','true');b.onclick=()=>{active.has(l.key)?active.delete(l.key):active.add(l.key);b.setAttribute('aria-pressed',String(active.has(l.key)));draw();};controls.append(b);}draw();
}
function renderDiagnosis(box,d){
 box.replaceChildren();const el=diagnosisElement;
 box.append(el('p',`${d.valid_samples} Messungen · ${d.invalid_samples} ungültig · Toleranz ±${d.tolerance_pct} %`,'diag-quality'));
 const cards=el('div',undefined,'diag-grid');box.append(cards);
 for(const [key,title] of [['house','⌂ Hausverbrauch'],['evening','◷ Abendfenster'],['pv','☀ PV-Erzeugung']]){
  const v=d.totals[key],card=el('article',undefined,'diag-metric');card.append(el('h3',title));cards.append(card);
  if(!v.hours){card.append(el('p','Noch keine Vergleichsdaten','muted'));continue;}
  card.append(el('strong',journalNumber(v.actual_kwh,' kWh'),'diag-value'),el('p','≈ Messung · '+journalNumber(v.planned_kwh,' kWh Prognose')));
  const pct=v.difference_pct,badge=el('span',(pct===null?'Δ '+journalNumber(v.difference_kwh,' kWh'):(pct>0?'+':'')+journalNumber(pct,' %')),'diag-badge '+(key==='pv'?'neutral':pct!==null&&Math.abs(pct)<=d.tolerance_pct?'ok':'review'));card.append(badge);
  card.append(el('p',journalNumber(v.hours,' h vergleichbar')+(key==='pv'?' · DC / AC':' · Ø '+journalNumber(v.actual_mean_w,' W')),'muted'));
 }
 diagnosisChart(box,'Hausverbrauch · Messung & Planung',d.series,[{key:'house_w',name:'Gemessen',color:'#245d46'},{key:'load_w',name:'Geplant',color:'#94704c',dashed:true}],'kW',600);
 diagnosisChart(box,'PV · Messung & Prognose',d.series,[{key:'pv_dc_w',name:'Gemessen (DC)',color:'#bd801b'},{key:'pv_forecast_w',name:'Prognose (AC)',color:'#7567ac',dashed:true}],'kW',600);
 const details=el('details'),summary=el('summary','◴ Akku & Entladesperren');details.append(summary);box.append(details);
 diagnosisChart(details,'Akkustand · gemessener Verlauf',d.soc_series,[{key:'soc',name:'SOC',color:'#7567ac'}],'%',120);
 if(!d.hold_spans.length)details.append(el('p','Keine ausreichend dokumentierte Sperrphase.','muted'));
 for(const s of d.hold_spans){const row=el('div',undefined,'diag-hold');row.append(el('strong',journalNumber(s.start_soc,' %')+' → '+journalNumber(s.end_soc,' %')),el('p',journalTime(s.start)+' – '+journalTime(s.end)),el('small','Abnahme '+journalNumber(s.soc_drop,' Prozentpunkte')+' · max. gemeldete Entladung '+journalNumber(s.max_discharge_w,' W')));details.append(row);}
 for(const s of d.limit_mismatches)details.append(el('p','⚠ '+journalTime(s.time)+': Entladegrenze '+journalNumber(s.limit_w,' W')+' trotz zuvor bestätigter Sperre.','diag-alert'));
 const advice=el('section',undefined,'diag-advice');advice.append(el('h3','↗ Einstellungen prüfen'),el('p','Letzte 7 Tage · nur passende Einstellungen · keine automatische Änderung.','muted'));box.append(advice);
 for(const r of d.recommendations){const card=el('article',undefined,'diag-recommendation '+r.level);card.append(el('strong',(r.level==='ok'?'✓ ':r.level==='review'?'↗ ':'ⓘ ')+r.title),el('p',r.text));const progress=el('progress');progress.max=100;progress.value=r.progress_pct;progress.setAttribute('aria-label',r.progress);card.append(progress,el('small',r.progress));if(!r.ready){advice.append(card);continue;}const b=el('button','Einstellung öffnen');b.onclick=()=>{document.querySelector('[data-tab="settings"]').click();const input=document.querySelector('input[name="'+r.setting+'"]');if(input){const group=input.closest('details');if(group)group.open=true;input.scrollIntoView({behavior:'smooth',block:'center'});input.focus({preventScroll:true});}};card.append(b);advice.append(card);}
 const notes=el('details');notes.append(el('summary','ⓘ Aussagekraft & Messverfahren'),el('p','Verglichen werden dieselben erfassten Zeiträume mit der jeweiligen Prognose zum Messzeitpunkt. Lücken bleiben offen. Zwischenwerte sind angenähert; kurze Lastspitzen können fehlen. DC-PV und AC-Prognose sind nur orientierend vergleichbar. Hausverbrauch enthält auch Auto und andere Sonderlasten. SOC-Verlust bei 0 W beweist weder Eigenbedarf noch einen Defekt.'));box.append(notes);
}
async function loadDiagnosis(){
 const button=document.getElementById('diagnosisrefresh'),box=document.getElementById('diagnosisresult');
 if(button.disabled)return;const hours=document.getElementById('journalhours').value;button.disabled=true;button.classList.add('button-loading');button.setAttribute('aria-busy','true');
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),30000);
 try{const response=await fetch('/api/journal/diagnosis?hours='+hours,{signal:controller.signal});if(!response.ok)throw Error('Diagnose nicht erreichbar.');const d=await response.json();if(hours===document.getElementById('journalhours').value)renderDiagnosis(box,d);}
 catch(e){box.append(diagnosisElement('p',e.name==='AbortError'?'Diagnose dauert zu lange. Erneut versuchen.':e.message,'diag-alert'));}
 finally{clearTimeout(timeout);button.disabled=false;button.classList.remove('button-loading');button.setAttribute('aria-busy','false');if(hours!==document.getElementById('journalhours').value)loadDiagnosis();}
}
document.addEventListener('DOMContentLoaded',()=>{
 const panel=document.getElementById('diagnosispanel');
 panel.addEventListener('toggle',()=>{if(panel.open)loadDiagnosis();});
 document.getElementById('diagnosisrefresh').onclick=loadDiagnosis;
 document.getElementById('journalhours').addEventListener('change',()=>{if(panel.open)loadDiagnosis();});
});
