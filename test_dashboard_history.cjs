const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
class El{constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.attrs={};this.style={};this.hidden=false;this.value='';this.classList={toggle(){}};}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}setAttribute(k,v){this.attrs[k]=v;}addEventListener(k,v){this[k]=v;}get options(){return this.children;}}
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
(async()=>{await ctx.loadDashboardHistory(d,true);assert.equal(requests.length,1);assert.match(requests[0],/^\/api\/journal\/timeline\?day=/);ctx.document.hidden=true;await ctx.loadDashboardHistory(d,true);assert.equal(requests.length,1);console.log('Dashboard history: separate toggles, seven-day picker, cached data, title restoration, read-only fetch and hidden-page guard passed');})();
