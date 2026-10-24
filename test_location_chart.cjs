const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync(__dirname+'/app.js','utf8');
class Node{
 constructor(){this.children=[];this.attrs={};this.value='';this.hidden=false;this.isConnected=true;this.classes=new Set();this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x)};}
 append(...nodes){this.children.push(...nodes);}replaceChildren(){this.children=[];}setAttribute(k,v){this.attrs[k]=v;}addEventListener(k,fn){this[k]=fn;}
}
const nodes={};const $=id=>nodes[id]||(nodes[id]=new Node());let message='',calls=0,success,failure;
const ctx={$,window:{isSecureContext:false},navigator:{geolocation:{getCurrentPosition:(yes,no,options)=>{calls++;success=yes;failure=no;assert.equal(options.timeout,15000);}}},notify:m=>message=m,settingsDirty:false,Date,Number};
vm.createContext(ctx);vm.runInContext(app.slice(app.indexOf('let locating='),app.indexOf('function fillSettings')),ctx);
const button=new Node();
ctx.useDeviceLocation(button);assert.equal(calls,0);assert.match(message,/HTTPS/);
ctx.window.isSecureContext=true;ctx.useDeviceLocation(button);assert.equal(calls,1);assert.equal(button.disabled,true);
ctx.useDeviceLocation(button);assert.equal(calls,1);
success({coords:{latitude:51.123456,longitude:10.123456,accuracy:25}});
assert.equal($('setting-pv_latitude').value,'51.1235');assert.equal($('setting-pv_longitude').value,'10.1235');assert.equal(ctx.settingsDirty,true);assert.equal(button.disabled,false);assert.match(message,/speichern/);
ctx.useDeviceLocation(button);failure({code:1});assert.match(message,/nicht erlaubt/);assert.equal(button.disabled,false);
ctx.useDeviceLocation(button);$('setting-pv_latitude').value='52';success({coords:{latitude:51,longitude:10}});assert.equal($('setting-pv_latitude').value,'52');assert.match(message,/bleiben erhalten/);
ctx.useDeviceLocation(button);failure({code:3});assert.match(message,/lange/);assert.equal(button.disabled,false);
ctx.useDeviceLocation(button);button.isConnected=false;success({coords:{latitude:50,longitude:9}});assert.equal($('setting-pv_latitude').value,'52');
console.log('Device location: HTTPS, consent errors, duplicate requests, dirty fields, detached form and timeout passed');

ctx.window.addEventListener=()=>{};ctx.document={addEventListener:()=>{},createElementNS:()=>new Node()};ctx.chartSignature='';ctx.ct=n=>n+' ct/kWh';
vm.runInContext(fs.readFileSync(__dirname+'/features.js','utf8'),ctx);
vm.runInContext(app.slice(app.indexOf('function renderPrices('),app.indexOf("$('compareday').onchange=")),ctx);
const at=i=>new Date(Date.UTC(2026,9,25,0,i*15)).toISOString();
const prices=Array.from({length:12},(_,i)=>({start:at(i),end:at(i+1),ct:i===0?-5:20}));
const data={mode:'off',settings:{pv_enabled:true,timezone:'Europe/Berlin'},prices,pv_forecast:{series:[{start:at(0),end:at(4),kw:1},{start:at(4),end:at(8),kw:2},{start:at(9),end:at(12),kw:0}]},comparison:{date:'2026-10-25',night_start:at(0),night_end:at(12),complete:true},price_age_seconds:10};
$('compareday').value='auto';ctx.renderPrices(data);
const svg=$('pricechart').children[0];const path=svg.children.find(x=>x.attrs.class==='pv-line');
assert.ok(path);assert.equal((path.attrs.d.match(/ M/g)||[]).length,2);assert.equal(path.attrs['pointer-events'],'none');
assert.ok(svg.children.some(x=>x.attrs.class==='pv-axis'&&x.textContent==='PV · kW'));
assert.equal($('pvlegend').hidden,false);
const bars=svg.children.filter(x=>x.attrs.role==='img');assert.equal(bars.length,12);
assert.match(bars[0].attrs['aria-label'],/-5 ct\/kWh.*1 kW/);
assert.match(bars[8].attrs['aria-label'],/keine Daten/);assert.match(bars[9].attrs['aria-label'],/0 kW/);
ctx.renderPrices(data);assert.equal($('pricechart').children[0],svg); // no redraw for identical forecast
const series=ctx.solarSeries(data);assert.equal(ctx.solarAverage(series,Date.parse(at(3)),Date.parse(at(5))),1.5);
assert.equal(ctx.solarAverage(series,Date.parse(at(7)),Date.parse(at(10))),null);
data.pv_forecast.series[0].kw=3;ctx.renderPrices(data);assert.notEqual($('pricechart').children[0],svg);
data.settings.pv_enabled=false;ctx.renderPrices(data);assert.equal($('pvlegend').hidden,true);assert.ok(!$('pricechart').children[0].children.some(x=>x.attrs.class==='pv-line'));
data.settings.pv_enabled=true;data.pv_forecast.series=[];ctx.renderPrices(data);assert.equal($('pvlegend').hidden,true);
console.log('Solar overlay: independent kW axis, gaps vs zero, DST epochs, negative prices, tooltips and redraw caching passed');
