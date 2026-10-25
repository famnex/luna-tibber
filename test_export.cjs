const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const timers=new Map();let counter=0,clicked=0,signal;
class El{constructor(){this.value='24';this.disabled=false;this.children=[];this.classList={add(){},remove(){}};}setAttribute(k,v){this[k]=v;}replaceChildren(...x){this.children=x;}click(){clicked++;}remove(){this.removed=true;}}
const els={};const get=id=>els[id]??=new El();
const ctx={Date,JSON,AbortController,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout:(f,ms)=>{timers.set(++counter,{f,ms});return counter;},clearTimeout:id=>timers.delete(id),setInterval(){},document:{getElementById:get,createElement:()=>new El(),createTextNode:t=>({textContent:t}),addEventListener(){}},fetch:async(url,opts)=>{signal=opts.signal;return {ok:true,blob:async()=>({})};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/journal.js','utf8'),ctx);
(async()=>{
 const button=new El();await ctx.exportJournal('txt',button);
 assert.equal(button.disabled,false);assert.equal(button['aria-busy'],'false');assert.equal(clicked,1);
 const link=get('journalstatus').children[1];assert.match(link.download,/\.txt$/);assert.equal(link.href,'blob:test');assert.ok(!link.removed);
 assert.ok(![...timers.values()].some(t=>t.ms===90000));
 ctx.fetch=async()=>({ok:false,status:401});await ctx.exportJournal('json',button);assert.match(get('journalstatus').textContent,/anmelden/);assert.equal(button.disabled,false);
 ctx.fetch=async(u,o)=>new Promise((resolve,reject)=>o.signal.addEventListener('abort',()=>reject(Object.assign(Error(),{name:'AbortError'}))));
 const pending=ctx.exportJournal('json',button);assert.equal(button.disabled,true);[...timers.values()].find(t=>t.ms===90000).f();await pending;
 assert.match(get('journalstatus').textContent,/6 Stunden/);assert.equal(button.disabled,false);
 console.log('Export: persistent Safari link, correct TXT suffix, auth errors, timeout and spinner cleanup passed');
})().catch(e=>{console.error(e);process.exitCode=1});
