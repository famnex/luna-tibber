/* Local appearance and startup UI only; no device or control requests. */
(()=>{
 const root=document.documentElement,media=window.matchMedia('(prefers-color-scheme: dark)');
 let preference='system';try{preference=localStorage.getItem('luna-theme')||'system';}catch(_){}
 if(!['system','light','dark'].includes(preference))preference='system';
 function apply(){const dark=preference==='dark'||(preference==='system'&&media.matches);root.dataset.theme=dark?'dark':'light';document.querySelector('meta[name="theme-color"]')?.setAttribute('content',dark?'#101a17':'#f4f6f2');}
 apply();media.addEventListener('change',apply);
 let timer;
 window.startupState=(state,detail)=>{
  const panel=document.getElementById('startup');if(!panel)return;
  clearTimeout(timer);panel.hidden=state==='ready';
  document.getElementById('startupspinner').hidden=state==='error';
  document.getElementById('startupretry').hidden=state!=='error';
  document.getElementById('startuptext').textContent=state==='error'?(detail||'Die App ist noch nicht erreichbar. Bitte erneut versuchen.'):'Anmeldung und Status werden geladen …';
 };
 document.addEventListener('DOMContentLoaded',()=>{
  const select=document.getElementById('appearance');select.value=preference;
  select.onchange=()=>{preference=select.value;try{localStorage.setItem('luna-theme',preference);}catch(_){}apply();};
  document.getElementById('startupretry').onclick=()=>location.reload();
  if(!document.getElementById('startup').hidden)timer=setTimeout(()=>window.startupState('error'),25000);
 });
})();
