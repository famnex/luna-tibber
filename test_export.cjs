const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const timers=new Map();let counter=0,clicked=0,signal;
class El{constructor(){this.value='24';this.disabled=false;this.children=[];this.classList={add(){},remove(){}};}setAttribute(k,v){this[k]=v;}replaceChildren(...x){this.children=x;}click(){clicked++;}remove(){this.removed=true;}removeAttribute(k){delete this[k];}}
const els={};const get=id=>els[id]??=new El();
const ctx={Date,JSON,AbortController,Blob,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout:(f,ms)=>{timers.set(++counter,{f,ms});return counter;},clearTimeout:id=>timers.delete(id),setInterval(){},document:{getElementById:get,createElement:()=>new El(),createTextNode:t=>({textContent:t}),addEventListener(){}},fetch:async(url,opts)=>{signal=opts.signal;return {ok:true,blob:async()=>({})};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/journal.js','utf8'),ctx);
(async()=>{
 const progress=[];const original=ctx.exportProgress;ctx.exportProgress=(n,t)=>progress.push(n);let count=0;const data=await ctx.downloadBody({headers:{get:k=>k==='Content-Length'?'4':'text/plain'},body:{getReader:()=>({read:async()=>++count<=2?{done:false,value:new Uint8Array([65,66])}:{done:true}})}});assert.equal(data.size,4);assert.deepEqual(progress,[50,100]);ctx.exportProgress=original;
 const button=new El();await ctx.exportJournal('txt',button);
 assert.equal(button.disabled,false);assert.equal(button['aria-busy'],'false');assert.equal(clicked,1);
 const link=get('journalstatus').children[1];assert.match(link.download,/\.txt$/);assert.equal(link.href,'blob:test');assert.ok(!link.removed);
 assert.ok(![...timers.values()].some(t=>t.ms===240000));
 ctx.fetch=async()=>({ok:false,status:401});await ctx.exportJournal('json',button);assert.match(get('journalstatus').textContent,/anmelden/);assert.equal(button.disabled,false);
 ctx.fetch=async(u,o)=>new Promise((resolve,reject)=>o.signal.addEventListener('abort',()=>reject(Object.assign(Error(),{name:'AbortError'}))));
 const pending=ctx.exportJournal('json',button);assert.equal(button.disabled,true);[...timers.values()].find(t=>t.ms===240000).f();await pending;
 assert.match(get('journalstatus').textContent,/6 Stunden/);assert.equal(button.disabled,false);
 console.log('Export: persistent Safari link, correct TXT suffix, auth errors, timeout and spinner cleanup passed');
})().catch(e=>{console.error(e);process.exitCode=1});
