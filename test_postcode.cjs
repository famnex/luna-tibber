const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Node{
 constructor(tag){this.tag=tag;this.children=[];this.value='';this.isConnected=true;this.classList={add:()=>{},remove:()=>{}};}
 append(...nodes){this.children.push(...nodes);}replaceChildren(){this.children=[];}setAttribute(){}
}
const coords={};let queries=[],resolve,notice='';
const ctx={document:{createElement:tag=>new Node(tag)},$:id=>coords[id]||(coords[id]={value:''}),api:async(name,data)=>{queries.push({name,data});return new Promise(done=>resolve=done);},notify:m=>notice=m,settingsDirty:false};
vm.createContext(ctx);const source=fs.readFileSync(__dirname+'/app.js','utf8');vm.runInContext(source.slice(source.indexOf('function postcodeField('),source.indexOf('function fillSettings(')),ctx);
(async()=>{
 const field=ctx.postcodeField(),[label,input,button,info,results]=field.children;
 assert.equal(input.type,'text');assert.equal(input.name,undefined);
 input.value='123';await button.onclick();assert.equal(queries.length,0);assert.match(info.textContent,/fünfstellige/);
 input.value='01234';const task=button.onclick();assert.equal(button.disabled,true);
 await button.onclick();assert.equal(queries.length,1);assert.equal(queries[0].data.postcode,'01234');
 resolve({results:[{name:'Ort A',latitude:51.12,longitude:10.34},{name:'Ort B',latitude:51.2,longitude:10.4}]});await task;
 assert.equal(results.children.length,2);assert.equal(ctx.settingsDirty,false);
 results.children[1].onclick();assert.equal(coords['setting-pv_latitude'].value,'51.2000');assert.equal(coords['setting-pv_longitude'].value,'10.4000');assert.equal(ctx.settingsDirty,true);assert.match(notice,/speichern/);
 input.value='12345';const second=button.onclick();input.value='54321';input.oninput();resolve({results:[{name:'Old',latitude:1,longitude:1}]});await second;assert.equal(results.children.length,0);
 const third=button.onclick();resolve({results:[]});await third;assert.match(info.textContent,/Kein Ort/);assert.equal(button.disabled,false);
 ctx.api=async()=>{throw Error('Nicht erreichbar');};await button.onclick();assert.equal(info.textContent,'Nicht erreichbar');assert.equal(button.disabled,false);
 console.log('Postcode UI: validation, preserved zero, explicit selection, draft-only, stale response and errors passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
