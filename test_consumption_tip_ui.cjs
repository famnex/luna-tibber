const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const nodes={};const $=id=>nodes[id]??={value:'',hidden:false,options:[]};
let resolveRequest;
const ctx={$,Intl,Date,Number,AbortController,setTimeout:()=>1,clearTimeout:()=>{},lastStatus:{settings:{timezone:'Europe/Berlin'}},
fetch:()=>new Promise(resolve=>{resolveRequest=resolve;})};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('manual-ui.js','utf8'),ctx);
$('orderkind').value='consumption';$('orderrepeat').value='once';
$('orderstart').value='2026-10-30T15:00';$('orderend').value='2026-10-30T16:00';$('orderkwh').value='1.5';
(async()=>{
 ctx.scheduleConsumptionTip();
 const pending=ctx.loadConsumptionTip({},1);
 resolveRequest({ok:true,json:async()=>({state:'better',start:'2026-10-30T16:00:00Z',end:'2026-10-30T17:00:00Z',saving_eur:.3,current_eur:.6,alternative_eur:.3,message:'Nur Tibber'})});
 await pending;
 assert.match($('ordertiptitle').textContent,/17:00–18:00/);
 assert.match($('ordertiptitle').textContent,/0,30/);
 assert.equal($('orderstart').value,'2026-10-30T15:00');
 assert.equal($('ordertipapply').hidden,false);
 $('ordertipapply').onclick();assert.equal($('orderstart').value,'2026-10-30T17:00');
 const stale=ctx.loadConsumptionTip({},2);
 $('orderrepeat').value='daily';ctx.scheduleConsumptionTip();
 resolveRequest({ok:true,json:async()=>({state:'better',start:'2026-10-30T16:00:00Z',end:'2026-10-30T17:00:00Z',saving_eur:.3,current_eur:.6,alternative_eur:.3,message:'Old'})});
 await stale;assert.equal($('ordertip').hidden,true);assert.equal($('ordertipapply').hidden,true);
 console.log('Price tips: local time, euros, explicit adoption and stale response suppression passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
