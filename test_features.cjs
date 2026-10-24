const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/features.js','utf8');
const ctx={window:{addEventListener:()=>{}},document:{addEventListener:()=>{}},Date};vm.createContext(ctx);vm.runInContext(source,ctx);
const d={mode:'smart',dispatch_preview:{windows:[{start:'2026-10-24T00:00:00Z',end:'2026-10-24T06:00:00Z',action:'hold'}]},smart_preview:{windows:[{start:'2026-10-24T01:00:00Z',end:'2026-10-24T01:15:00Z'}]}};
ctx.d=d;vm.runInContext('phases=chartPhases(d)',ctx);
assert.equal(ctx.phaseAt(ctx.phases,Date.parse('2026-10-24T01:05:00Z')),'charge');
assert.equal(ctx.phaseAt(ctx.phases,Date.parse('2026-10-24T01:14:00Z')),'hold');
d.mode='off';assert.equal(ctx.chartPhases(d).length,0);
// Service worker must never intercept or queue API writes.
const handlers={};const sw={self:{addEventListener:(name,fn)=>handlers[name]=fn,skipWaiting:()=>{}},URL,fetch:()=>{throw Error('unexpected network');}};
vm.createContext(sw);vm.runInContext(fs.readFileSync(__dirname+'/sw.js','utf8'),sw);
let intercepted=false;handlers.fetch({request:{method:'POST',mode:'cors',url:'/api/mode'},respondWith:()=>intercepted=true});
assert.equal(intercepted,false);
console.log('Chart phase precedence and service-worker control isolation passed');
// Money statistics: empty periods, missing prices and negative savings stay distinct.
function element(){return {textContent:'',children:[],append(...items){this.children.push(...items);},replaceChildren(){this.children=[];}};}
const elements={historyinfo:element(),periodstats:element(),historyrows:element(),historygroup:{value:'months'}};
ctx.document.getElementById=id=>elements[id];ctx.document.createElement=element;
const blank={valued:0,discharge:0,seconds:0,saving:0,cost:0,avoided:0};
ctx.ledger={enabled:true,started:null,periods:{today:{...blank},yesterday:{...blank},last30:{...blank},last365:{...blank}},months:[],years:[]};
vm.runInContext('historyData=ledger;renderHistory()',ctx);
assert.match(elements.periodstats.children[0].children[1].textContent,/0,00/);
assert.match(elements.historyinfo.textContent,/zukünftiger Smart-Plan/);
ctx.ledger.periods.today={...blank,seconds:120,discharge:1};
vm.runInContext('renderHistory()',ctx);
assert.equal(elements.periodstats.children[0].children[1].textContent,'—');
ctx.ledger.periods.today={valued:1,discharge:2,seconds:120,saving:-.12,cost:.50,avoided:.40};
ctx.ledger.months=[{...ctx.ledger.periods.today,period:'2026-10'}];
vm.runInContext('renderHistory()',ctx);
const card=elements.periodstats.children[0];
assert.match(card.children[1].textContent,/-0,12/);
assert.equal(card.children[2].textContent,'Mehrkosten laut Plan');
assert.match(card.children[3].textContent,/Verschleiß: 0,02/);
assert.match(card.children[3].textContent,/Teilbetrag/);
assert.equal(elements.historyrows.children[0].children.length,4);
assert.ok(elements.historyrows.children[0].children.slice(1).every(x=>x.textContent.includes('€')));
console.log('Money statistics rendering passed');
// PV card distinguishes applied plans, unavailable data and disabled settings.
for(const id of ['pvcard','pvstatus','pvday','pvsummary','pvage'])elements[id]=element();
ctx.renderPv({settings:{pv_enabled:true,target_soc:80,timezone:'UTC'},pv_forecast:{age_seconds:180,reason:'Cache'},smart_preview:{night_end:'2026-10-25T06:00:00Z',pv:{applied:true,target_soc:20,generation_kwh:12,direct_kwh:2,surplus_kwh:10,reduction_kwh:6,reason:'PV berücksichtigt'}}});
assert.match(elements.pvsummary.textContent,/20 % statt 80 %/);
assert.match(elements.pvsummary.textContent,/6 kWh weniger/);
ctx.renderPv({settings:{pv_enabled:true},pv_forecast:{reason:'Keine Prognose'},smart_preview:{}});
assert.match(elements.pvsummary.textContent,/aktuellen Akkustand/);
assert.equal(elements.pvstatus.textContent,'Keine Prognose');
ctx.renderPv({settings:{pv_enabled:false}});assert.equal(elements.pvcard.hidden,true);
console.log('PV forecast rendering passed');
