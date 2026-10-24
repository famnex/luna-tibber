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
