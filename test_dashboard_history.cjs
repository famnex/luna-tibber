const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
class El{constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.attrs={};this.style={};this.hidden=false;this.value='';this.classList={toggle(){}};}append(...v){for(const n of v){this.children.push(n);n.parent=this;}}remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}replaceChildren(...v){this.children=v;}setAttribute(k,v){this.attrs[k]=v;}addEventListener(k,v){this[k]=v;}get options(){return this.children;}}
const nodes={},node=id=>nodes[id]||(nodes[id]=new El());let requests=[];
const now=Date.now(),fixture={day:'',timezone:'Europe/Berlin',start:now/1000-3600,end:now/1000,samples:2,prices:[],pv:[],soc:[],phases:[{start:now/1000-3600,end:now/1000,action:'hold',locked:true}],switches:[{time:now/1000-3600,label:'Entladesperre bestätigt'}]};
const d={settings:{timezone:'Europe/Berlin'}},ctx={Date,Number,Set,Map,Intl,AbortController,setTimeout,clearTimeout,setInterval(){},document:{hidden:false,createElement:t=>new El(t),createElementNS:(_,t)=>new El(t),getElementById:node,addEventListener(){}},window:{addEventListener(){}},lastStatus:d,fixture,selectedPlanDay:0,renderPrices(){},renderTodayPlan(){},fetch:async url=>{requests.push(url);return {ok:true,json:async()=>fixture};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('features.js','utf8'),ctx);vm.runInContext(fs.readFileSync('journal.js','utf8'),ctx);
ctx.renderDashboardHistory(d);assert.equal(requests.length,0);assert.equal(node('day-history-day').options.length,7);
vm.runInContext('dashboardHistory.cache.set(dashboardHistory.date,{at:Date.now(),data:fixture})',ctx);
node('day-history').onclick();assert.equal(node('day-plan-view').hidden,true);assert.equal(node('day-history-view').hidden,false);assert.equal(node('dayplantitle').textContent,'Tagesverlauf');
node('price-history').onclick();assert.equal(node('price-plan-view').hidden,true);assert.ok(node('price-history-content').children.some(n=>n.className==='history-chart'));
node('day-plan').onclick();assert.equal(node('dayplantitle').textContent,'Heute geplant');assert.equal(node('price-history-view').hidden,false);
assert.equal(requests.length,0); // Switching cached panels does not read the inverter or API.
// Thousands of raw observations stay out of the initial DOM. Details are paged.
const raw=Array.from({length:3000},(_,i)=>({start:i*10,end:(i+1)*10,action:'charge',locked:true}));
const compact={...fixture,phases:raw,summary:[{start:0,end:30000,action:'charge',locked:true}],switches:raw.map(p=>({time:p.start,label:'Ladebefehl gesendet'})),switch_groups:[{time:0,end:29990,count:3000,label:'Ladebefehl gesendet'}]};
const root=new El();ctx.drawHistoryPhases(root,compact);
const count=n=>1+n.children.reduce((v,c)=>v+count(c),0);
assert.ok(count(root)<40);
const details=root.children.filter(n=>n.tag==='details');assert.equal(details.length,2);
details[0].open=true;details[0].ontoggle();assert.ok(JSON.stringify(details[0].children.map(n=>n.textContent)).includes('Befehle'));
const groupList=details[0].children.find(n=>n.tag==='ol');assert.equal(groupList.children.length,1);assert.equal(groupList.children[0].children[1].textContent,'↻ Ladeauftrag · 3000 befristete Befehle');
details[1].open=true;details[1].ontoggle();const rawList=details[1].children.find(n=>n.tag==='ol');assert.equal(rawList.children.length,13);
rawList.children.at(-1).children[0].onclick();assert.equal(rawList.children.length,25);
const warning=ctx.historyPhaseItem({start:0,end:600,action:'discharge',locked:true},fixture);assert.equal(warning.className,'history-warning');
console.log('History grouping: bounded initial DOM, lazy exact observations, paging and lock-discharge warnings passed');
(async()=>{await ctx.loadDashboardHistory(d,true);assert.equal(requests.length,1);assert.match(requests[0],/^\/api\/journal\/timeline\?day=/);ctx.document.hidden=true;await ctx.loadDashboardHistory(d,true);assert.equal(requests.length,1);console.log('Dashboard history: separate toggles, seven-day picker, cached data, title restoration, read-only fetch and hidden-page guard passed');})();

assert.equal(vm.runInContext("historyColor({action:'charge',source:'grid'})",ctx),'#2f8d62');
assert.equal(vm.runInContext("historyColor({action:'charge',source:'pv'})",ctx),'#b18a24');
assert.equal(vm.runInContext("historyColor({action:'charge'})",ctx),'#939da5');
assert.match(fs.readFileSync('style.css','utf8'),/\.history-strip\{gap:0\}/);
assert.match(fs.readFileSync('style.css','utf8'),/\.history-strip span\{min-width:0;flex-basis:0\}/);
const pvPlan={mode:'smart',smart_preview:{joint:{trace:[{start:'2026-10-28T10:00:00Z',end:'2026-10-28T11:00:00Z',grid_charge_kwh:0,start_kwh:2,end_kwh:3}]},windows:[]}};
assert.equal(ctx.chartPhases(pvPlan)[0].action,'pv_charge');
pvPlan.smart_preview.joint.trace[0].end_kwh=2;assert.equal(ctx.chartPhases(pvPlan).length,0);
assert.match(vm.runInContext("historyLabel({action:'charge',source:'pv',source_estimated:true})",ctx),/PV-Ladung.*geschätzt/);
assert.match(fs.readFileSync('journal.js','utf8'),/const phase=\(data.summary\|\|data.phases\).find/);
