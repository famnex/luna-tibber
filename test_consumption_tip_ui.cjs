const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class El{constructor(){this.value='';this.hidden=false;this.options=[];this.children=[];this.dataset={};}replaceChildren(){this.children=[];}append(...x){this.children.push(...x);}}
const nodes={};const $=id=>nodes[id]??=new El();
let resolveRequest;
const ctx={document:{createElement:()=>new El()},$,Intl,Date,Number,AbortController,setInterval:()=>1,setTimeout:()=>1,clearTimeout:()=>{},lastStatus:{settings:{timezone:'Europe/Berlin'}},
fetch:()=>new Promise(resolve=>{resolveRequest=resolve;})};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('manual-ui.js','utf8'),ctx);
$('orderkind').value='consumption';$('orderrepeat').value='once';
$('orderstart').value='2026-10-30T15:00';$('orderduration').value='60';$('orderdurationunit').value='1';$('orderkwh').value='1.5';
(async()=>{
 ctx.scheduleConsumptionTip();
 const pending=ctx.loadConsumptionTip({},1);
 resolveRequest({ok:true,json:async()=>({state:'better',suggestions:[{start:'2026-10-30T16:00:00Z',end:'2026-10-30T17:00:00Z',saving_eur:.3,cost_eur:.3,extra_eur:0,cheapest:true},{start:'2026-10-30T18:00:00Z',end:'2026-10-30T19:00:00Z',saving_eur:.25,cost_eur:.35,extra_eur:.05,cheapest:false}],current_eur:.6,message:'Nur Tibber'})});
 await pending;
 assert.match($('ordertipchoices').children[0].children[0].children[0].textContent,/17:00–18:00/);
 assert.match($('ordertipchoices').children[0].children[0].children[0].textContent,/0,30/);
 assert.equal($('orderstart').value,'2026-10-30T15:00');
 assert.equal($('ordertipchoices').children.length,2);
 assert.match($('ordertipchoices').children[1].children[0].children[1].textContent,/0,05/);
 $('ordertipchoices').children[0].children[1].onclick();assert.equal($('orderstart').value,'2026-10-30T17:00');
 const stale=ctx.loadConsumptionTip({},2);
 $('orderrepeat').value='daily';ctx.scheduleConsumptionTip();
 resolveRequest({ok:true,json:async()=>({state:'better',suggestions:[{start:'2026-10-30T16:00:00Z',end:'2026-10-30T17:00:00Z',saving_eur:.3,cost_eur:.3,extra_eur:0,cheapest:true},{start:'2026-10-30T18:00:00Z',end:'2026-10-30T19:00:00Z',saving_eur:.25,cost_eur:.35,extra_eur:.05,cheapest:false}],current_eur:.6,message:'Old'})});
 await stale;assert.equal($('ordertip').hidden,true);assert.equal($('ordertipchoices').children.length,0);
 $('orderrepeat').value='once';ctx.scheduleConsumptionTip();
 const economic=ctx.loadConsumptionTip({},4);
 resolveRequest({ok:true,json:async()=>({basis:'dispatch',state:'better',horizon_end:'2026-10-31T00:00:00Z',current_eur:.6,message:'PV und Akku; ohne Einspeisevergütung',suggestions:[{start:'2026-10-30T16:00:00Z',end:'2026-10-30T17:00:00Z',saving_eur:.3,cost_eur:.3,extra_eur:0,cheapest:true,end_soc:42,horizon_soc:10,pv_direct_kwh:.8,hold_minutes:30,automatic_hold:true,later_extra_eur:.1}]})});
 await economic;
 assert.equal($('ordertipassumptions').hidden,false);
 assert.match($('ordertiptext').textContent,/Mehrkosten/);
 assert.match($('ordertipchoices').children[0].children[0].children[0].textContent,/Günstigster geprüft/);
 assert.match($('ordertipchoices').children[0].children[0].children[2].textContent,/Smart-Pause/);
 assert.match($('ordertipchoices').children[0].children[0].children[3].textContent,/Spätere Mehrkosten/);
 console.log('Price tips: local time, euros, explicit adoption and stale response suppression passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
