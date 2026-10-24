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
const helps=all.filter(n=>n.className==='help-button');assert.equal(helps.length,29);
for(const help of helps){
 const desc=all.find(n=>n.id===help.attrs['aria-controls']);assert.ok(desc.textContent&&desc.textContent.length>40);
 assert.equal(help.type,'button');assert.equal(desc.hidden,true);help.onclick();assert.equal(desc.hidden,false);assert.equal(help.attrs['aria-expanded'],'true');help.onclick();assert.equal(desc.hidden,true);
}
assert.equal(all.some(n=>n.name==='reserve_soc'),false);
assert.match(all.find(n=>n.id==='help-extra_load_kwh').textContent,/zusätzlich/);
assert.equal(all.find(n=>n.name==='password').type,'password');
console.log('Settings: help on all 29 fields, touch/keyboard button semantics, no fixed reserve, hidden secrets');
