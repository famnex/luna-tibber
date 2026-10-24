const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class El{constructor(){this.children=[];this.hidden=false;this.value='24';this.checked=false;this.dataset={};this.classList={add(){},remove(){}};}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}setAttribute(){}remove(){}}
const els={};const get=id=>els[id]??=new El();let calls=[];
const ctx={Date,JSON,URL,setTimeout,document:{hidden:false,getElementById:get,createElement:()=>new El(),addEventListener(){},body:new El()},setInterval(){},fetch:async url=>{calls.push(url);return {ok:true,json:async()=>({events:[{timestamp:1792888200,mode:'smart',text:'Akku entlädt <script>',data:{soc:40},plan_id:7}],before:5})};}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/journal.js','utf8'),ctx);
(async()=>{
 await ctx.loadJournal();assert.equal(calls.length,1);assert.match(calls[0],/^\/api\/journal\?/);
 const entry=get('journalentries').children[0];assert.equal(entry.children[1].textContent,'Akku entlädt <script>');
 assert.match(entry.children[0].textContent,/GMT/);assert.equal(get('journalmore').hidden,false);
 await ctx.loadJournal(true);assert.match(calls[1],/before=5/);assert.equal(get('journalentries').children.length,2);
 ctx.document.hidden=true;await ctx.loadJournal();assert.equal(calls.length,2);
 ctx.document.hidden=false;get('journal').hidden=true;await ctx.loadJournal();assert.equal(calls.length,2);
 assert.ok(!calls.some(x=>x.includes('/api/status')));
 console.log('Journal UI: text-only rendering, timezone offset, pagination, visibility and no measurement requests passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
