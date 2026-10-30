const fs=require('fs'),vm=require('vm'),assert=require('assert');
class El{constructor(){this.children=[];this.dataset={};this.value='';this.hidden=false;this.options=[];}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}showModal(){this.open=true;}close(){this.open=false;}}
const nodes={},$=id=>nodes[id]??=new El();
$('orderendkind').options=['time','soc','forever'].map(value=>({value}));
const calls=[],d={mode:'off',settings:{timezone:'Europe/Berlin',target_soc:80,charge_power_w:5000,max_session_minutes:120},server_time:'2026-10-29T12:00:00Z',manual_orders:[{id:'1',kind:'hold',start:'2026-10-29T11:00:00Z',end:null,end_kind:'forever'}]};
const ctx={setTimeout:()=>1,clearTimeout:()=>{},$,lastStatus:d,Intl,Date,Number,console,document:{createElement:()=>new El()},confirm:()=>true,perform:async(...v)=>{calls.push(v);return true;}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('manual-ui.js','utf8'),ctx);
ctx.renderManualOrders(d);assert.equal($('orderlist').children.length,1);assert.match($('orderlist').children[0].children[0].textContent,/aktiv/);
ctx.editOrder(d.manual_orders[0]);assert.equal($('orderdialog').open,true);assert.equal($('orderendwrap').hidden,true);
$('orderkind').value='charge';ctx.orderFields();assert.equal($('orderendkind').value,'time');assert.equal($('orderduration').required,true);
$('orderendkind').value='soc';ctx.orderFields();assert.equal($('ordersocwrap').hidden,false);assert.equal($('orderduration').required,false);
const html=fs.readFileSync('web.html','utf8');assert.deepEqual([...html.matchAll(/data-mode="([^"]+)"/g)].map(x=>x[1]),['off','smart']);
(async()=>{await $('orderform').onsubmit({preventDefault(){},submitter:new El()});assert.equal(calls[0][0],'manual-save');assert.equal($('orderdialog').open,false);console.log('Manual UI: persistent list, editor, end conditions, save, two-mode selector passed');})();

$('orderkind').value='consumption';$('orderrepeat').value='weekly';ctx.orderFields();
assert.equal($('consumptionfields').hidden,false);assert.equal($('orderweekdays').hidden,false);
assert.equal($('orderstart').required,true);assert.equal($('orderendkindwrap').hidden,true);
$('orderkind').value='holiday';ctx.orderFields();assert.equal($('consumptionfields').hidden,true);
assert.match($('orderhelp').textContent,/Ladeaufträge und Sperren bleiben gültig/);
const routine={id:'routine',kind:'consumption',name:'Kochen',start:'2026-10-29T17:00:00Z',end:'2026-10-29T19:00:00Z',kwh:2,repeat:'weekly',weekdays:[0,4],end_kind:'time'};
const occurrences=[0].map(i=>({...routine,start:'2026-11-0'+(2+i*4)+'T17:00:00Z',recurring:true}));
ctx.renderManualOrders({...d,manual_orders:[routine],manual_occurrences:occurrences});
assert.equal($('orderlist').children.length,1);
assert.match($('orderlist').children[0].children[2].textContent,/weitere Wiederholungen/);
$('orderlist').children[0].children[3].children[0].onclick();
assert.equal($('orderstart').value,'2026-10-29T18:00');assert.equal($('orderday4').checked,true);
console.log('Consumption UI: recurrence, holiday semantics, one occurrence and master editing passed');

const template={id:'wash',name:'Waschmaschine',duration_minutes:90,kwh:1.5};
ctx.lastStatus={...d,consumption_templates:[template]};
ctx.renderConsumptionTemplates(ctx.lastStatus);$('ordertemplate').value='wash';$('ordertemplate').onchange();
assert.equal($('ordername').value,'Waschmaschine');assert.equal(ctx.orderDuration(),90);assert.equal($('orderkwh').value,1.5);
assert.equal($('templateupdate').hidden,false);
console.log('Templates: saved choice fills independent draft name, duration and energy');
