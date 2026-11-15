'use strict';
const el=id=>document.getElementById(id);
const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
async function api(action,data={}){
 const response=await fetch('/api/vehicles'+(action?'/'+action:''),action?{method:'POST',headers:{'Content-Type':'application/json','X-Luna':'1'},body:JSON.stringify(data)}:{});
 const result=await response.json();
 if(!response.ok)throw Error(response.status===401?'Bitte zuerst auf der LUNA-Hauptseite anmelden.':result.error||'Abruf fehlgeschlagen');
 return result;
}
function fields(value,parent,prefix=''){
 if(value&&typeof value==='object'){
  for(const [key,entry] of Object.entries(value))fields(entry,parent,prefix?prefix+' › '+key:key);
 }else{
  const row=node('div','');row.className='manual-order';row.append(node('strong',prefix),node('p',value===null?'Nicht geliefert':String(value)));parent.append(row);
 }
}
function render(result){
 if(!result)return;
 const root=el('results');root.replaceChildren();
 root.append(node('p','Abgerufen: '+new Date(result.fetched_at*1000).toLocaleString('de-DE')));
 for(const warning of result.warnings||[])root.append(node('p',warning));
 if(!result.devices.length)root.append(node('p','Keine Geräte geliefert. Fahrzeugverknüpfung in Tibber und Fahrzeug-Leserecht prüfen.'));
 for(const item of result.devices){
  const d=item.device||{};const card=node('article','');card.className='card';
  card.append(node('h2',d.info?.name||d.name||d.info?.model||d.id||'Fahrzeug'));
  if(item.error)card.append(node('p',item.error));
  const values=item.details||d;
  // Preserve vendor names and timestamps rather than guessing field semantics or missing statuses.
  const caps=Array.isArray(values.capabilities)?values.capabilities:[];
  const labels={'storage.stateOfCharge':'🔋 Ladestand','storage.targetStateOfCharge':'🎯 Ladeziel','range.remaining':'↔ Reichweite','connector.status':'🔌 Anschluss','charging.status':'⚡ Ladestatus'};
  const statuses={connected:'Angesteckt',disconnected:'Nicht angesteckt',charging:'Lädt',idle:'Keine aktive Ladung',unknown:'Unbekannt'};
  for(const [id,label] of Object.entries(labels)){
   const c=caps.find(c=>c.id===id);const row=node('div','');row.className='manual-order';
   row.append(node('strong',label),node('p',!c||c.value==null?'Nicht geliefert':(statuses[c.value]||String(c.value))+(c.unit?' '+c.unit:'')));
   const stamp=c?.updatedAt||c?.timestamp||c?.lastUpdated;
   row.append(node('small',stamp?'Datenzeit: '+stamp:'Messzeitpunkt nicht geliefert'));card.append(row);
  }
  const all=node('details','');all.append(node('summary','Alle gelieferten Felder'));const list=node('div','');fields(values,list);all.append(list);card.append(all);
  const raw=node('details','');raw.append(node('summary','Originalantwort (JSON)'),node('pre',JSON.stringify(item,null,2)));card.append(raw);root.append(card);
 }
}
async function run(button,fn){button.disabled=true;el('message').textContent='Bitte warten …';try{await fn();}catch(e){el('message').textContent=e.message;}finally{button.disabled=false;}}
el('connect').onsubmit=e=>{e.preventDefault();run(e.submitter,async()=>{const r=await api('begin',{client_id:el('client').value,client_secret:el('secret').value});el('secret').value='';el('authorize').href=r.url;el('authorize').hidden=false;el('message').textContent='Anmeldelink bereit. Bitte innerhalb von zehn Minuten abschließen.';});};
el('finish').onsubmit=e=>{e.preventDefault();run(e.submitter,async()=>{await api('finish',{callback_url:el('callback').value});el('callback').value='';el('authorize').hidden=true;el('read').disabled=false;el('message').textContent='Verbunden. Jetzt Fahrzeugdaten abrufen.';});};
el('read').onclick=()=>run(el('read'),async()=>{render(await api('read'));el('message').textContent='Tibber-Daten geladen. Messzeitpunkte stehen bei den gelieferten Feldern.';});
el('disconnect').onclick=()=>run(el('disconnect'),async()=>{await api('disconnect');el('read').disabled=true;el('results').replaceChildren();el('message').textContent='Lokaler Zugang entfernt.';});
api().then(r=>{el('read').disabled=!r.connected;el('setup').open=!r.connected;el('message').textContent=r.connected?'Mit Tibber verbunden.':'Noch nicht mit der Tibber Data API verbunden.';render(r.result);}).catch(e=>{el('message').textContent=e.message;});
