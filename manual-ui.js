/* Manual interventions are independent of the automatic mode. */
let editingOrder=null,manualClockOffset=0;
function orderLocal(iso){
 const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:lastStatus?.settings.timezone||'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(iso));
 return parts.replace(' ','T');
}
function orderFields(){
 const type=$('orderkind').value,hold=type==='hold',extra=type==='consumption'||type==='holiday',kind=$('orderendkind');
 $('orderdialog').dataset.kind=type;
 $('orderenergywrap').hidden=type!=='consumption';$('orderrepeatwrap').hidden=type!=='consumption';
 if(extra)kind.value='time';
 $('ordernamewrap').hidden=!extra;$('consumptionfields').hidden=type!=='consumption';
 $('orderendkindwrap').hidden=extra;$('orderstart').required=extra;
 $('orderkwh').required=type==='consumption';
 $('orderweekdays').hidden=type!=='consumption'||$('orderrepeat').value!=='weekly';
 [...kind.options].forEach(o=>o.hidden=(o.value==='forever'&&!hold)||(o.value==='soc'&&hold));
 if((hold&&kind.value==='soc')||(!hold&&kind.value==='forever'))kind.value='time';
 $('orderendwrap').hidden=kind.value!=='time';$('orderduration').required=kind.value==='time';
 const labels={hold:['Sperre ab','Sperrdauer'],charge:['Laden ab','Ladedauer'],consumption:['Verbrauch ab','Verbrauchsdauer'],holiday:['Abwesenheit ab','Dauer der Abwesenheit']};
 const label=labels[type]||labels.hold;$('orderstartlabel').textContent=label[0];$('orderdurationlabel').textContent=label[1];
 $('ordersocwrap').hidden=kind.value!=='soc';$('ordersoc').required=kind.value==='soc';
 $('orderhelp').textContent=type==='holiday'?'☷ In diesem Zeitraum nur Grundlast einplanen. Zusatzverbräuche werden ausgesetzt, auch einmalige. Explizite Ladeaufträge und Sperren bleiben gültig.':type==='consumption'?'⌂ Zusätzlich zur Grundlast · kWh werden gleichmäßig auf das Zeitfenster verteilt. Überschneidende Verbräuche addieren sich. Wiederholungen gelten ab dem Startdatum.':hold?'🔒 Entladung gesperrt · Laden weiterhin möglich':`↗ Netzladen ohne Preisprüfung · mindestens 3 Minuten · bis ${lastStatus?.settings.charge_power_w||'—'} W · höchstens ${lastStatus?.settings.max_session_minutes||'—'} Minuten · SOC-Grenze ${kind.value==='soc'?$('ordersoc').value:lastStatus?.settings.target_soc||80} %`;
 scheduleConsumptionTip();
}
function editOrder(order=null){
 editingOrder=order?.id||null;$('ordertemplate').value='';$('templatenotice').textContent='';renderConsumptionTemplates(lastStatus);$('ordernotice').textContent='';
 $('ordername').value=order?.name||'';$('orderrepeat').value=order?.repeat||'once';$('orderkwh').value=order?.kwh||1.5;
 for(let i=0;i<7;i++)$('orderday'+i).checked=(order?.weekdays||[]).includes(i);
 $('orderkind').value=order?.kind||'hold';$('orderstart').value=order?orderLocal(order.start):orderLocal(Date.now()+manualClockOffset);
 setOrderDuration(order?.end?Math.max(1,Math.round((Date.parse(order.end)-Date.parse(order.start))/60000)):60);
 $('orderendkind').value=order?.end_kind||'time';$('orderend').value=order?.end?orderLocal(order.end):orderLocal(Date.now()+manualClockOffset+3600000);
 $('ordersoc').value=order?.target_soc||lastStatus?.settings.target_soc||80;
 $('ordertitle').textContent=order?'Eingriff bearbeiten':'Eingriff hinzufügen';orderFields();$('orderdialog').showModal();updateConsumptionClock();
}
$('orderadd').onclick=()=>editOrder();$('ordercancel').onclick=()=>{clearTimeout(tipTimer);tipRevision++;$('orderdialog').close();};
$('orderkind').onchange=()=>{if(['consumption','holiday'].includes($('orderkind').value)&&!$('orderstart').value)$('orderstart').value=orderLocal(Date.now()+manualClockOffset);orderFields();};$('orderendkind').onchange=orderFields;$('orderrepeat').onchange=orderFields;
$('orderform').onsubmit=async e=>{
 e.preventDefault();
 syncConsumptionStart(true);
 const data={id:editingOrder,kind:$('orderkind').value,start:$('orderstart').value,end_kind:$('orderendkind').value,end:$('orderend').value,duration_minutes:orderDuration(),target_soc:Number($('ordersoc').value),name:$('ordername').value,kwh:Number($('orderkwh').value),repeat:$('orderrepeat').value,weekdays:Array.from({length:7},(_,i)=>i).filter(i=>$('orderday'+i).checked)};
 if(await perform('manual-save',data,e.submitter))$('orderdialog').close();
 else $('ordernotice').textContent=$('notice').textContent||'Speichern fehlgeschlagen; bitte erneut versuchen.';
};
function renderManualOrders(d){
 if(d.server_time)manualClockOffset=Date.parse(d.server_time)-Date.now();
 renderConsumptionTemplates(d);
 const root=$('orderlist');if(!root)return;
 const now=Date.parse(d.server_time||new Date().toISOString());
 const rows=d.manual_occurrences||d.manual_orders||[];
 const key=JSON.stringify(rows.map(o=>({...o,active:Date.parse(o.start)<=now})));
 if(root.dataset.key===key)return;root.dataset.key=key;root.replaceChildren();
 const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:d.settings.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 if(!rows.length){const p=document.createElement('p');p.className='muted';p.textContent='Keine manuellen Eingriffe geplant.';root.append(p);return;}
 for(const o of rows){
  const card=document.createElement('article');card.className='manual-order';
  const title=document.createElement('strong');title.textContent=(o.kind==='hold'?'🔒 Entladesperre':o.kind==='charge'?'↗ Ladeauftrag':(o.kind==='holiday'?'☷ ':'⌂ ')+(o.name||'Zusatzverbrauch'))+(Date.parse(o.start)<=now?' · aktiv':' · geplant');
  const time=document.createElement('p');time.textContent='◷ '+fmt(o.start)+' → '+(o.end_kind==='forever'?'bis auf Widerruf':o.end_kind==='soc'?o.target_soc+' % · spätestens '+fmt(o.end):fmt(o.end));
  const actions=document.createElement('div');actions.className='actions';
  const edit=document.createElement('button');edit.textContent=o.recurring?'✎ Routine bearbeiten':'✎ Bearbeiten';edit.onclick=()=>editOrder((d.manual_orders||[]).find(r=>r.id===o.id)||o);
  const remove=document.createElement('button');remove.textContent=o.recurring?'× Routine entfernen':'× Entfernen';remove.onclick=async()=>{if(confirm(o.recurring?'Die gesamte Routine einschließlich aller Wiederholungen entfernen?':'Diesen Eintrag entfernen? Die Planung wird danach angepasst.'))await perform('manual-delete',{id:o.id},remove);};
  actions.append(edit,remove);card.append(title,time);
  if(o.kind==='consumption'){const info=document.createElement('p');info.className='muted';info.textContent=o.kwh.toLocaleString('de-DE')+' kWh zusätzlich'+(o.holiday_overlap?' · ☷ im Urlaub ganz/teilweise pausiert':'')+(o.recurring?' · ↻ '+(o.repeat==='daily'?'täglich':o.weekdays.map(i=>['Mo','Di','Mi','Do','Fr','Sa','So'][i]).join(', '))+' · weitere Wiederholungen folgen':'');card.append(info);}
  card.append(actions);root.append(card);
 }
}


function orderDuration(){return Number($('orderduration').value)*Number($('orderdurationunit').value||1);}
function setOrderDuration(minutes){
 const unit=minutes%1440===0?1440:minutes%60===0?60:1;
 $('orderdurationunit').value=String(unit);$('orderduration').value=String(minutes/unit);
}
function renderConsumptionTemplates(d){
 const select=$('ordertemplate'),rows=d?.consumption_templates||[],key=JSON.stringify(rows);
 if(select.dataset.key!==key){
  const selected=select.value;select.replaceChildren();
  for(const row of [{id:'',name:'Ohne Vorlage'},...rows]){
   const option=document.createElement('option');option.value=row.id;option.textContent=row.name;select.append(option);
  }
  select.value=rows.some(r=>r.id===selected)?selected:'';select.dataset.key=key;
 }
 $('templateupdate').hidden=!select.value;$('templatedelete').hidden=!select.value;
}
$('ordertemplate').onchange=()=>{
 const row=(lastStatus?.consumption_templates||[]).find(r=>r.id===$('ordertemplate').value);
 if(row){$('ordername').value=row.name;$('orderkwh').value=row.kwh;setOrderDuration(row.duration_minutes);}
 renderConsumptionTemplates(lastStatus);scheduleConsumptionTip();
};
async function changeTemplate(action,existing,button){
 const data={id:existing?$('ordertemplate').value:null,name:$('ordername').value,duration_minutes:orderDuration(),kwh:Number($('orderkwh').value)};
 if(action==='template-delete'&&!confirm('Diese Vorlage löschen? Bereits angelegte Eingriffe bleiben bestehen.'))return;
 $('templatenotice').textContent='';
 if(await perform(action,data,button)){$('templatenotice').textContent=action==='template-delete'?'Vorlage gelöscht.':'Vorlage gespeichert.';renderConsumptionTemplates(lastStatus);}
 else $('templatenotice').textContent=$('notice').textContent||'Vorlage konnte nicht gespeichert werden.';
}
$('templatesave').onclick=e=>changeTemplate('template-save',false,e.currentTarget);
$('templateupdate').onclick=e=>changeTemplate('template-save',true,e.currentTarget);
$('templatedelete').onclick=e=>changeTemplate('template-delete',true,e.currentTarget);

// Suggestions edit the draft only. Saving remains explicit.
let tipTimer=null,tipRevision=0,tipPendingRevision=null,tipRenderedSignature='';
function scheduleConsumptionTip(){
 clearTimeout(tipTimer);tipRenderedSignature='';const revision=++tipRevision;
 $('ordertipchoices').replaceChildren();$('ordertipassumptions').hidden=true;
 const visible=$('orderkind').value==='consumption'&&$('orderrepeat').value==='once';
 $('ordertip').hidden=!visible;if(!visible)return;
 const data={id:editingOrder,start:$('orderstart').value,duration_minutes:orderDuration(),kwh:Number($('orderkwh').value)};
 if(!data.start||!(data.duration_minutes>0)||!(data.kwh>0)){
  $('ordertiptitle').textContent='◷ Zeitfenster vergleichen';$('ordertiptext').textContent='Beginn, Dauer und kWh eintragen.';return;
 }
 $('ordertiptitle').textContent='◷ Preisvergleich …';$('ordertiptext').textContent='';
 tipTimer=setTimeout(()=>loadConsumptionTip(data,revision),700);
}
async function loadConsumptionTip(data,revision){
 tipPendingRevision=revision;
 const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),45000);
 try{
  const response=await fetch('/api/consumption-tip',{method:'POST',headers:{'Content-Type':'application/json','X-Luna':'1'},body:JSON.stringify(data),signal:abort.signal});
  const tip=await response.json();if(revision!==tipRevision)return;
  if(!response.ok)throw new Error(tip.error||'Preisvergleich nicht verfügbar');
  if(tip.state==='pending'||tip.state==='busy'){
   $('ordertiptitle').textContent='◷ Vergleich läuft …';
   $('ordertiptext').textContent=(tip.message||'Bitte warten …')+(tip.elapsed_seconds?' · '+tip.elapsed_seconds+' s':'');
   tipTimer=setTimeout(()=>{if(revision===tipRevision)loadConsumptionTip(tip.job?{_advice_job:tip.job}:data,revision);},500);
   if(!tip.suggestions?.length)return;
  }else tipPendingRevision=null;
  const signature=JSON.stringify([tip.suggestions,tip.message,tip.basis,tip.current_eur,tip.estimate]);
  if(signature===tipRenderedSignature)return;tipRenderedSignature=signature;
  $('ordertipchoices').replaceChildren();
  const money=n=>n.toLocaleString('de-DE',{style:'currency',currency:'EUR'});
  const fmt=x=>new Date(x).toLocaleTimeString('de-DE',{timeZone:lastStatus?.settings.timezone||'Europe/Berlin',hour:'2-digit',minute:'2-digit'});
  $('ordertiptitle').textContent=tip.suggestions?.length?(tip.estimate?'≈ Geschätzte Zeitfenster':'💡 Zeitfenster zur Auswahl'):'ⓘ Zeitvergleich';
  const economic=tip.basis==='dispatch'&&tip.suggestions?.length;
  $('ordertipassumptions').hidden=!economic;$('ordertipbasis').textContent=tip.message||'';
  $('ordertiptext').textContent=economic?'Dein Termin: ≈ '+money(tip.current_eur)+' Mehrkosten · Vergleich bis '+new Date(tip.horizon_end).toLocaleString('de-DE',{timeZone:lastStatus?.settings.timezone||'Europe/Berlin',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):(tip.message||'');
  if(tip.estimate&&economic)$('ordertiptext').textContent='≈ Stundenschätzung · '+$('ordertiptext').textContent;
  for(const option of tip.suggestions||[]){
   const row=document.createElement('div');row.className='tip-choice';
   const info=document.createElement('div'),heading=document.createElement('strong'),detail=document.createElement('p');
   heading.textContent=({now:'Jetzt · ',earliest:'Frühester Start · ',between:'Dazwischen · ',later:'Später · '}[option.role]||'')+fmt(option.start)+'–'+fmt(option.end)+' · '+money(option.cost_eur)+(option.cheapest?(economic?' ★ Günstigster geprüft':' ★ Günstigstes'):'');
   detail.className='muted';detail.textContent=(option.saving_eur>=0?'− '+money(option.saving_eur):'+ '+money(-option.saving_eur))+' gegenüber deiner Eingabe'+(!option.cheapest?' · + '+money(option.extra_eur)+' zum günstigsten Termin':'');
   info.append(heading,detail);
   if(economic){
    const facts=document.createElement('p');facts.className='muted';
    const number=n=>Number(n).toLocaleString('de-DE',{maximumFractionDigits:1});
    facts.textContent='🔋 Danach '+number(option.end_soc)+' % · ☀ '+number(option.pv_direct_kwh)+' kWh zusätzlich direkt'+(option.hold_minutes?' · 🔒 '+option.hold_minutes+' Min. '+(option.automatic_hold?'Smart-Pause':'Sperre'):'');
    const later=document.createElement('small');later.textContent='Spätere Mehrkosten: '+money(option.later_extra_eur)+' · Akku am Horizontende: '+number(option.horizon_soc)+' %';
    info.append(facts,later);
   }
   const button=document.createElement('button');button.type='button';button.textContent='Übernehmen';
   button.onclick=()=>{if(revision!==tipRevision)return;$('orderstart').value=orderLocal(option.start);setOrderDuration(Math.round((Date.parse(option.end)-Date.parse(option.start))/60000));scheduleConsumptionTip();};
   row.append(info,button);$('ordertipchoices').append(row);
  }
 }catch(e){if(revision===tipRevision)tipPendingRevision=null;if(revision===tipRevision){$('ordertiptitle').textContent='ⓘ Kein Preisvorschlag';$('ordertiptext').textContent=e.name==='AbortError'?'Zeitlimit erreicht. Eingabe ändern, um erneut zu prüfen.':e.message;}}
 finally{clearTimeout(timeout);}
}
for(const id of ['orderstart','orderduration','orderdurationunit','orderkwh'])$(id).oninput=scheduleConsumptionTip;


// Only the open draft follows the clock; saved orders/routines are never moved.
function syncConsumptionStart(force=false){
 if($('orderkind').value!=='consumption'||(!$('orderdialog').open&&!force))return false;
 const input=$('orderstart'),now=orderLocal(Date.now()+manualClockOffset);
 if(!force&&document.activeElement===input)return false;
 if(input.value&&input.value<now){input.value=now;return true;}
 return false;
}
let lastTipMinute='';
function updateConsumptionClock(){
 if(document.hidden||!$('orderdialog').open)return;
 const changed=syncConsumptionStart();
 const minute=orderLocal(Date.now()+manualClockOffset);
 if(changed||minute!==lastTipMinute){
  lastTipMinute=minute;
  if(tipPendingRevision!==tipRevision&&$('orderkind').value==='consumption'&&$('orderrepeat').value==='once')scheduleConsumptionTip();
 }
}
$('orderstart').onblur=()=>{syncConsumptionStart(true);scheduleConsumptionTip();};
setInterval(updateConsumptionClock,1000);
document.addEventListener?.('visibilitychange',()=>{if(!document.hidden)updateConsumptionClock();});
