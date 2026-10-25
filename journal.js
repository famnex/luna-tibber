'use strict';
let journalBusy=false,journalBefore=null,journalAt=0,journalKey='';
function journalVisible(){return !document.hidden&&!document.getElementById('dashboard').hidden&&!document.getElementById('journal').hidden;}
function journalQuery(){return 'hours='+document.getElementById('journalhours').value+'&all='+(document.getElementById('journalall').checked?'1':'0');}
function journalTime(stamp){
 const zone=typeof lastStatus!=='undefined'?lastStatus?.settings?.timezone||'Europe/Berlin':'Europe/Berlin';
 return new Date(stamp*1000).toLocaleString('de-DE',{timeZone:zone,day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'shortOffset'});
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
   const li=document.createElement('li'),time=document.createElement('time'),p=document.createElement('p');
   time.dateTime=new Date(event.timestamp*1000).toISOString();time.textContent=journalTime(event.timestamp)+' · '+event.mode;
   p.textContent=event.text;li.append(time,p);
   const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
   summary.textContent='Messwerte & Entscheidungsdaten · Plan #'+(event.plan_id??'—');
   pre.textContent=JSON.stringify(event.data,null,2);details.append(summary,pre);
   if(event.plan_id){
    const button=document.createElement('button');button.textContent='Vollständigen Plan anzeigen';
    button.onclick=async()=>{button.disabled=true;button.classList.add('button-loading');
     try{const r=await fetch('/api/journal/plan?id='+event.plan_id);if(!r.ok)throw Error('Plan nicht mehr verfügbar.');
      const plan=await r.json(),output=document.createElement('pre');output.textContent=JSON.stringify(plan,null,2);details.append(output);button.remove();
     }catch(e){button.textContent=e.message;button.disabled=false;}finally{button.classList.remove('button-loading');}};
    details.append(button);
   }
   li.append(details);list.append(li);
  }
  journalBefore=d.before;journalKey=key;journalAt=Date.now();
  document.getElementById('journalmore').hidden=!journalBefore;
  document.getElementById('journalstatus').textContent=d.error||(!list.children.length?'Noch keine Einträge in diesem Zeitraum. Aufzeichnung beginnt mit diesem Update.':'Neueste Einträge zuerst · vollständige Planstände im Export.');
 }catch(e){document.getElementById('journalstatus').textContent=e.message;}
 finally{journalBusy=false;button.disabled=false;button.classList.remove('button-loading');button.setAttribute('aria-busy','false');}
}
async function exportJournal(kind,button){
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),90000);
 const status=document.getElementById('journalstatus');
 button.disabled=true;button.classList.add('button-loading');button.setAttribute('aria-busy','true');
 status.textContent='Export wird erstellt … bei vielen Planständen kann das bis zu einer Minute dauern.';
 try{
  const r=await fetch('/api/journal/'+(kind==='json'?'export':'text')+'?hours='+document.getElementById('journalhours').value,{signal:controller.signal});
  if(!r.ok)throw Error(r.status===401?'Bitte erneut anmelden.':'Export fehlgeschlagen. Bitte 6 Stunden wählen und erneut versuchen.');
  const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='luna-diagnose-'+new Date().toISOString().slice(0,10)+'.'+(kind==='json'?'json.gz':'txt');
  a.textContent='Datei speichern / öffnen';a.className='download-link';
  status.replaceChildren(document.createTextNode('Export bereit. Falls der Download nicht startet: '),a);
  a.click();
  // Keep a real, tappable link for Safari/PWA user-activation requirements.
  setTimeout(()=>{URL.revokeObjectURL(url);a.remove();},300000);
 }catch(e){status.textContent=e.name==='AbortError'?'Export dauert zu lange. Bitte 6 Stunden wählen und erneut versuchen.':e.message;}
 finally{clearTimeout(timeout);button.disabled=false;button.classList.remove('button-loading');button.setAttribute('aria-busy','false');}
}
document.addEventListener('DOMContentLoaded',()=>{
 document.getElementById('journalrefresh').onclick=()=>loadJournal();
 document.getElementById('journalmore').onclick=()=>loadJournal(true);
 for(const id of ['journalhours','journalall'])document.getElementById(id).onchange=()=>{journalAt=0;loadJournal();};
 for(const kind of ['json','text'])document.getElementById('journal'+kind).onclick=e=>exportJournal(kind==='text'?'txt':'json',e.currentTarget);
 document.querySelector('[data-tab="journal"]').addEventListener('click',()=>setTimeout(()=>loadJournal(),0));
 document.addEventListener('visibilitychange',()=>{if(journalVisible())loadJournal();});
});
setInterval(()=>{if(journalVisible()&&Date.now()-journalAt>=60000)loadJournal();},1000);
