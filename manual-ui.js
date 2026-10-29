/* Manual interventions are independent of the automatic mode. */
let editingOrder=null;
function orderLocal(iso){
 const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:lastStatus?.settings.timezone||'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(iso));
 return parts.replace(' ','T');
}
function orderFields(){
 const hold=$('orderkind').value==='hold',kind=$('orderendkind');
 [...kind.options].forEach(o=>o.hidden=(o.value==='forever'&&!hold)||(o.value==='soc'&&hold));
 if((hold&&kind.value==='soc')||(!hold&&kind.value==='forever'))kind.value='time';
 $('orderendwrap').hidden=kind.value!=='time';$('orderend').required=kind.value==='time';
 $('ordersocwrap').hidden=kind.value!=='soc';$('ordersoc').required=kind.value==='soc';
 $('orderhelp').textContent=hold?'🔒 Entladung gesperrt · Laden weiterhin möglich':`↗ Netzladen ohne Preisprüfung · mindestens 3 Minuten · bis ${lastStatus?.settings.charge_power_w||'—'} W · höchstens ${lastStatus?.settings.max_session_minutes||'—'} Minuten · SOC-Grenze ${kind.value==='soc'?$('ordersoc').value:lastStatus?.settings.target_soc||80} %`;
}
function editOrder(order=null){
 editingOrder=order?.id||null;$('ordernotice').textContent='';
 $('orderkind').value=order?.kind||'hold';$('orderstart').value=order?orderLocal(order.start):'';
 $('orderendkind').value=order?.end_kind||'time';$('orderend').value=order?.end?orderLocal(order.end):orderLocal(Date.now()+3600000);
 $('ordersoc').value=order?.target_soc||lastStatus?.settings.target_soc||80;
 $('ordertitle').textContent=order?'Eingriff bearbeiten':'Eingriff hinzufügen';orderFields();$('orderdialog').showModal();
}
$('orderadd').onclick=()=>editOrder();$('ordercancel').onclick=()=>$('orderdialog').close();
$('orderkind').onchange=orderFields;$('orderendkind').onchange=orderFields;
$('orderform').onsubmit=async e=>{
 e.preventDefault();
 const data={id:editingOrder,kind:$('orderkind').value,start:$('orderstart').value,end_kind:$('orderendkind').value,end:$('orderend').value,target_soc:Number($('ordersoc').value)};
 if(await perform('manual-save',data,e.submitter))$('orderdialog').close();
 else $('ordernotice').textContent=$('notice').textContent||'Speichern fehlgeschlagen; bitte erneut versuchen.';
};
function renderManualOrders(d){
 const root=$('orderlist');if(!root)return;
 const now=Date.parse(d.server_time||new Date().toISOString());
 const rows=d.manual_orders||[];
 const key=JSON.stringify(rows.map(o=>({...o,active:Date.parse(o.start)<=now})));
 if(root.dataset.key===key)return;root.dataset.key=key;root.replaceChildren();
 const fmt=x=>new Date(x).toLocaleString('de-DE',{timeZone:d.settings.timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
 if(!rows.length){const p=document.createElement('p');p.className='muted';p.textContent='Keine manuellen Eingriffe geplant.';root.append(p);return;}
 for(const o of rows){
  const card=document.createElement('article');card.className='manual-order';
  const title=document.createElement('strong');title.textContent=(o.kind==='hold'?'🔒 Entladesperre':'↗ Ladeauftrag')+(Date.parse(o.start)<=now?' · aktiv':' · geplant');
  const time=document.createElement('p');time.textContent='◷ '+fmt(o.start)+' → '+(o.end_kind==='forever'?'bis auf Widerruf':o.end_kind==='soc'?o.target_soc+' % · spätestens '+fmt(o.end):fmt(o.end));
  const actions=document.createElement('div');actions.className='actions';
  const edit=document.createElement('button');edit.textContent='✎ Bearbeiten';edit.onclick=()=>editOrder(o);
  const remove=document.createElement('button');remove.textContent='× Entfernen';remove.onclick=async()=>{if(confirm('Diesen manuellen Eingriff entfernen? Ein aktiver Eingriff wird beendet; Smart darf anschließend wieder entscheiden.'))await perform('manual-delete',{id:o.id},remove);};
  actions.append(edit,remove);card.append(title,time,actions);root.append(card);
 }
}
