const fs=require('fs'),vm=require('vm'),assert=require('assert');
class El{constructor(){this.children=[];this.dataset={};this.value='';this.hidden=false;this.options=[];}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}showModal(){this.open=true;}close(){this.open=false;}}
const nodes={},$=id=>nodes[id]??=new El();
$('orderendkind').options=['time','soc','forever'].map(value=>({value}));
const calls=[],d={mode:'off',settings:{timezone:'Europe/Berlin',target_soc:80,charge_power_w:5000,max_session_minutes:120},server_time:'2026-10-29T12:00:00Z',manual_orders:[{id:'1',kind:'hold',start:'2026-10-29T11:00:00Z',end:null,end_kind:'forever'}]};
const ctx={$,lastStatus:d,Intl,Date,Number,console,document:{createElement:()=>new El()},confirm:()=>true,perform:async(...v)=>{calls.push(v);return true;}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('manual-ui.js','utf8'),ctx);
ctx.renderManualOrders(d);assert.equal($('orderlist').children.length,1);assert.match($('orderlist').children[0].children[0].textContent,/aktiv/);
ctx.editOrder(d.manual_orders[0]);assert.equal($('orderdialog').open,true);assert.equal($('orderendwrap').hidden,true);
$('orderkind').value='charge';ctx.orderFields();assert.equal($('orderendkind').value,'time');assert.equal($('orderend').required,true);
$('orderendkind').value='soc';ctx.orderFields();assert.equal($('ordersocwrap').hidden,false);assert.equal($('orderend').required,false);
const html=fs.readFileSync('web.html','utf8');assert.deepEqual([...html.matchAll(/data-mode="([^"]+)"/g)].map(x=>x[1]),['off','smart']);
(async()=>{await $('orderform').onsubmit({preventDefault(){},submitter:new El()});assert.equal(calls[0][0],'manual-save');assert.equal($('orderdialog').open,false);console.log('Manual UI: persistent list, editor, end conditions, save, two-mode selector passed');})();
