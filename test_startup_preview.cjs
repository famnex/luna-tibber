const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const src=fs.readFileSync('app.js','utf8'),nodes={},calls=[];
const ctx={$:id=>nodes[id]??={},window:{startupState:state=>calls.push(state)}};
vm.createContext(ctx);vm.runInContext(src.slice(src.indexOf('async function loadStartup'),src.indexOf('async function refresh')),ctx);
(async()=>{
 ctx.fetch=async()=>({status:401});
 assert.equal((await ctx.loadStartup()).status,401);assert.deepEqual(nodes,{});
 ctx.fetch=async()=>({ok:true,json:async()=>({timezone:'Europe/Berlin',measurement:{soc:57,battery_power_w:-500,time:'2026-11-02T10:00:00Z'}})});
 await ctx.loadStartup();assert.equal(nodes.quickcard.hidden,false);assert.match(nodes.quickvalues.textContent,/57 % · -0,5 kW/);
 assert.match(nodes.quickstamp.textContent,/11:00/);assert.deepEqual(calls,['ready']);
})().catch(e=>{console.error(e);process.exitCode=1;});
