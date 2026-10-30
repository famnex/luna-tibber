/* Manual interventions are independent of the automatic mode. */
let editingOrder=null;
function orderLocal(iso){
 const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:lastStatus?.settings.timezone||'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(iso));
 return parts.replace(' ','T');
}
function orderFields(){
 const type=$('orderkind').value,hold=type==='hold',extra=type==='consumption'||type==='holiday',kind=$('orderendkind');
 if(extra)kind.value='time';
 $('ordernamewrap').hidden=!extra;$('consumptionfields').hidden=type!=='consumption';
 $('orderendkindwrap').hidden=extra;$('orderstart').required=extra;
 $('orderkwh').required=type==='consumption';
 $('orderweekdays').hidden=type!=='consumption'||$('orderrepeat').value!=='weekly';
 [...kind.options].forEach(o=>o.hidden=(o.value==='forever'&&!hold)||(o.value==='soc'&&hold));
 if((hold&&kind.value==='soc')||(!hold&&kind.value==='forever'))kind.value='time';
 $('orderendwrap').hidden=kind.value!=='time';$('orderend').required=kind.value==='time';
 $('ordersocwrap').hidden=kind.value!=='soc';$('ordersoc').required=kind.value==='soc';
 $('orderhelp').textContent=type==='holiday'?'☷ In diesem Zeitraum nur Grundlast einplanen. Zusatzverbräuche werden ausgesetzt, auch einmalige. Explizite Ladeaufträge und Sperren bleiben gültig.':type==='consumption'?'⌂ Zusätzlich zur Grundlast · kWh werden gleichmäßig auf das Zeitfenster verteilt. Überschneidende Verbräuche addieren sich. Wiederholungen gelten ab dem Startdatum.':hold?'🔒 Entladung gesperrt · Laden weiterhin möglich':`↗ Netzladen ohne Preisprüfung · mindestens 3 Minuten · bis ${lastStatus?.settings.charge_power_w||'—'} W · höchstens ${lastStatus?.settings.max_session_minutes||'—'} Minuten · SOC-Grenze ${kind.value==='soc'?$('ordersoc').value:lastStatus?.settings.target_soc||80} %`;
}
function editOrder(order=null){
 editingOrder=order?.id||null;$('ordernotice').textContent='';
 $('ordername').value=order?.name||'';$('orderrepeat').value=order?.repeat||'once';$('orderkwh').value=order?.kwh||1.5;
 for(let i=0;i<7;i++)$('orderday'+i).checked=(order?.weekdays||[]).includes(i);
 $('orderkind').value=order?.kind||'hold';$('orderstart').value=order?orderLocal(order.start):'';
 $('orderendkind').value=order?.end_kind||'time';$('orderend').value=order?.end?orderLocal(order.end):orderLocal(Date.now()+3600000);
 $('ordersoc').value=order?.target_soc||lastStatus?.settings.target_soc||80;
 $('ordertitle').textContent=order?'Eingriff bearbeiten':'Eingriff hinzufügen';orderFields();$('orderdialog').showModal();
}
$('orderadd').onclick=()=>editOrder();$('ordercancel').onclick=()=>$('orderdialog').close();
$('orderkind').onchange=()=>{if(['consumption','holiday'].includes($('orderkind').value)&&!$('orderstart').value)$('orderstart').value=orderLocal(Date.now());orderFields();};$('orderendkind').onchange=orderFields;$('orderrepeat').onchange=orderFields;
$('orderform').onsubmit=async e=>{
 e.preventDefault();
 const data={id:editingOrder,kind:$('orderkind').value,start:$('orderstart').value,end_kind:$('orderendkind').value,end:$('orderend').value,target_soc:Number($('ordersoc').value),name:$('ordername').value,kwh:Number($('orderkwh').value),repeat:$('orderrepeat').value,weekdays:Array.from({length:7},(_,i)=>i).filter(i=>$('orderday'+i).checked)};
 if(await perform('manual-save',data,e.submitter))$('orderdialog').close();
 else $('ordernotice').textContent=$('notice').textContent||'Speichern fehlgeschlagen; bitte erneut versuchen.';
};
function renderManualOrders(d){
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
