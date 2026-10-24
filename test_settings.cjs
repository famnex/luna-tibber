const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.hidden=false;}
 append(...els){this.children.push(...els);}
 replaceChildren(...els){this.children=[...els];}
 setAttribute(key,value){this.attrs[key]=value;}
}
const fields=new Element('div');
const ctx={document:{createElement:tag=>new Element(tag)},$:id=>{assert.equal(id,'fields');return fields;},types:{}};
vm.createContext(ctx);const s=fs.readFileSync(__dirname+'/app.js','utf8');
vm.runInContext(s.slice(s.indexOf('const labels='),s.indexOf('const types='))+s.slice(s.indexOf('const settingHelp='),s.indexOf('async function refresh()')),ctx);
vm.runInContext("fillSettings(Object.fromEntries(Object.keys(labels).map(k=>[k,k==='smart_discharge_enabled'?true:0])),{password:true,tibber_token:true})",ctx);
const all=[];function visit(node){all.push(node);for(const child of node.children)visit(child);}visit(fields);
const helps=all.filter(n=>n.className==='help-button');assert.equal(helps.length,37);
for(const help of helps){
 const desc=all.find(n=>n.id===help.attrs['aria-controls']);assert.ok(desc.textContent&&desc.textContent.length>40);
 assert.equal(help.type,'button');assert.equal(desc.hidden,true);help.onclick();assert.equal(desc.hidden,false);assert.equal(help.attrs['aria-expanded'],'true');help.onclick();assert.equal(desc.hidden,true);
}
assert.equal(all.some(n=>n.name==='reserve_soc'),false);
assert.match(all.find(n=>n.id==='help-extra_load_kwh').textContent,/zusätzlich/);
assert.equal(all.find(n=>n.name==='password').type,'password');
console.log('Settings: help on all 37 fields, touch/keyboard button semantics, no fixed reserve, hidden secrets');
// Saving submits only edited fields; unchanged connection data and blank secrets stay out.
const form={},inputs=[{name:'base_load_w',type:'number',value:'700'},{name:'host',type:'text',value:'192.0.2.1'},{name:'password',type:'password',value:''}];
ctx.$=id=>id==='settingsform'?form:{querySelectorAll:()=>inputs};
ctx.settingsBaseline={base_load_w:500,host:'192.0.2.1'};ctx.types={base_load_w:'number',host:'string',password:'string'};
ctx.perform=async(name,data)=>{assert.equal(name,'settings');assert.equal(JSON.stringify(data),JSON.stringify({base_load_w:700}));};
vm.runInContext(s.slice(s.indexOf("$('settingsform').onsubmit="),s.indexOf("$('plannedkind').onchange=")),ctx);
form.onsubmit({preventDefault:()=>{},submitter:{}}).then(()=>console.log('Settings submit: changed fields only, no blank credentials or unchanged connection fields')).catch(e=>{console.error(e);process.exitCode=1;});
