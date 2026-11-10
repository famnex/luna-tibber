const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const src=fs.readFileSync('app.js','utf8'),nodes={},calls=[];
function el(){return {hidden:true,style:{},dataset:{},attrs:{},children:[],classes:new Set(),setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},append(x){this.children.push(x)},prepend(x){this.children.unshift(x);x.remove=()=>this.children.splice(this.children.indexOf(x),1)},querySelector(){return this.children[0]},classList:{toggle(k,on){on?this.owner.classes.add(k):this.owner.classes.delete(k)},remove(k){this.owner.classes.delete(k)}}};}
function node(id){if(!nodes[id]){nodes[id]=el();nodes[id].classList.owner=nodes[id];}return nodes[id];}
const buttons=[node('modeButton')];buttons[0].disabled=false;
const ctx={$:node,document:{querySelectorAll:()=>buttons,createElement:()=>el()},window:{startupState:state=>calls.push(state)}};
vm.createContext(ctx);vm.runInContext(src.slice(src.indexOf('function setDashboardLoading'),src.indexOf('async function refresh')),ctx);
(async()=>{
 ctx.fetch=async()=>({status:401});assert.equal((await ctx.loadStartup()).status,401);assert.equal(nodes.dashboard,undefined);
 ctx.fetch=async()=>({ok:true,json:async()=>({timezone:'Europe/Berlin',measurement:{soc:57,battery_power_w:-500,time:'2026-11-02T10:00:00Z'}})});
 await ctx.loadStartup();assert.equal(nodes.dashboard.hidden,false);assert.equal(nodes.quickcard.hidden,true);
 assert.match(nodes.soc.textContent,/57/);assert.match(nodes.power.textContent,/-0,5/);assert.match(nodes.sampletime.textContent,/11:00/);
 assert.ok(nodes.pricechart.classes.has('skeleton'));assert.ok(!nodes.soc.classes.has('skeleton'));assert.equal(buttons[0].disabled,true);assert.deepEqual(calls,['ready']);
 ctx.setDashboardLoading(false);assert.equal(buttons[0].disabled,false);assert.equal(nodes.pricechart.classes.size,0);assert.equal(nodes.manual.children.length,0);
 ctx.fetch=async()=>({ok:true,json:async()=>({timezone:'Europe/Berlin',measurement:{}})});await ctx.loadStartup();assert.ok(nodes.soc.classes.has('skeleton'));
})().catch(e=>{console.error(e);process.exitCode=1;});
