const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class El{constructor(){this.value='';this.hidden=false;this.children=[];this.dataset={};this.open=false;this.options=[];}replaceChildren(){this.children=[];}append(...x){this.children.push(...x);}}
const nodes={},$=id=>nodes[id]??=new El();
let now=Date.parse('2026-10-30T14:00:30Z');
class ClockDate extends Date{static now(){return now;}}
const document={hidden:false,activeElement:null,createElement:()=>new El()};
const ctx={$,document,Date:ClockDate,Intl,Number,setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,lastStatus:{settings:{timezone:'Europe/Berlin'}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('manual-ui.js','utf8'),ctx);
$('orderdialog').open=true;$('orderkind').value='consumption';$('orderrepeat').value='once';$('orderduration').value='60';$('orderdurationunit').value='1';$('orderkwh').value='1.5';
const revision=vm.runInContext('tipRevision',ctx);
$('ordertipchoices').append(new El());const card=$('ordertipchoices').children[0];
$('orderstart').value='2026-10-30T14:50';ctx.updateConsumptionClock();
assert.equal($('orderstart').value,'2026-10-30T15:00');
now+=120000;ctx.updateConsumptionClock();assert.equal($('orderstart').value,'2026-10-30T15:02');
$('orderstart').value='2026-10-30T17:00';ctx.updateConsumptionClock();assert.equal($('orderstart').value,'2026-10-30T17:00');
now=Date.parse('2026-10-30T16:01:00Z');ctx.updateConsumptionClock();assert.equal($('orderstart').value,'2026-10-30T17:01');
document.activeElement=$('orderstart');now+=60000;ctx.updateConsumptionClock();assert.equal($('orderstart').value,'2026-10-30T17:01');
$('orderstart').onblur();assert.equal($('orderstart').value,'2026-10-30T17:02');
$('orderdialog').open=false;now+=60000;ctx.updateConsumptionClock();assert.equal($('orderstart').value,'2026-10-30T17:02');
assert.equal(vm.runInContext('tipRevision',ctx),revision);
assert.equal($('ordertipchoices').children[0],card);
$('ordertiprefresh').onclick();assert.equal(vm.runInContext('tipRevision',ctx),revision+1);
console.log('Draft clock: past catches up, future fixed until reached, typing protected, closed dialog untouched');
