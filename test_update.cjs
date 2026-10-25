const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const callbacks=[],timers=new Map(),nodes={};let timer=0,reloads=0,requests=[];
for(const id of ['updateapp','updateversion','updatestatus','updateprogresswrap','updateprogress','updatestep','updatesteps']){
 const classes=new Set();nodes[id]={textContent:'',disabled:false,children:[],removeAttribute(k){delete this[k];},replaceChildren(){this.children=[];},append(x){this.children.push(x);},classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name),add:name=>classes.add(name),remove:name=>classes.delete(name),contains:name=>classes.has(name)}};
}
const ctx={window:{addEventListener:()=>{},location:{reload:()=>reloads++}},document:{createElement:()=>({}),hidden:false,addEventListener:(event,fn)=>{if(event==='DOMContentLoaded')callbacks.push(fn);},getElementById:id=>nodes[id]},Date,AbortController,
 setTimeout:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clearTimeout:id=>timers.delete(id),lastStatus:{mode:'off'},
 fetch:async url=>{requests.push(url);return {ok:true,status:200,json:async()=>({state:'current',message:'Aktuell'})};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/features.js','utf8'),ctx);
(async()=>{
 const button=nodes.updateapp;
 ctx.renderUpdate({state:'idle',revision:'1234567890'},ctx.lastStatus);assert.equal(button.disabled,false);
 ctx.renderUpdate({state:'idle'},{mode:'smart'});assert.equal(button.disabled,false);
 ctx.renderUpdate({state:'done',message:'Update erfolgreich'},{mode:'off',job:'sample'});assert.equal(button.disabled,false);
 assert.match(nodes.updatestatus.textContent,/Update erfolgreich/);
 ctx.renderUpdate({state:'done'},{mode:'off',discharge:{restore_pending:true}});assert.equal(button.disabled,false);
 ctx.renderUpdate({state:'preparing',message:'Stoppen'},ctx.lastStatus);assert.equal(button.disabled,true);
 ctx.renderUpdate({state:'testing',message:'Prüfe'},ctx.lastStatus);
 assert.equal(button.disabled,true);assert.equal(button.classList.contains('button-loading'),true);assert.equal(nodes.updateprogress.value,5);assert.match(nodes.updatestep.textContent,/Schritt 6 von 9/);
 assert.equal([...timers.values()][0].ms,2000);
 await ctx.pollUpdate();assert.deepEqual(requests,['/api/update']);assert.equal(timers.size,0);assert.equal(button.disabled,false);
 ctx.document.hidden=true;ctx.renderUpdate({state:'checking'},ctx.lastStatus);assert.equal(timers.size,0);
 await ctx.pollUpdate();assert.equal(requests.length,1);
 ctx.document.hidden=false;ctx.renderUpdate({state:'done'},ctx.lastStatus);assert.equal(reloads,1);
 // The button submits once, reports loading immediately and recovers after a rejected request.
 callbacks.at(-1)();let reject;
 ctx.api=(name,data)=>{assert.equal(name,'update');return new Promise((_,no)=>reject=no);};
 const click=button.onclick();assert.equal(button.disabled,true);assert.equal(button.classList.contains('button-loading'),true);
 reject(Error('Lokale Änderungen'));await click;
 assert.equal(button.disabled,false);assert.equal(button.classList.contains('button-loading'),false);
 assert.equal(nodes.updatestatus.textContent,'Lokale Änderungen');
 console.log('Update UI: state guard, spinner, visible-only status polling, reload and failure feedback passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
