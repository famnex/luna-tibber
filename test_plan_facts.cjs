const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/app.js','utf8');
const els={};const element=()=>({textContent:'',attrs:{},classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v;}});
const ctx={Date,Number,Math,$:id=>els[id]??=(element()),renderDischarge(){},phaseInfo:()=>['Smart','long generic reason'],drawCountdown(){}};
vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('function displayPlanPhases'),source.indexOf('setInterval(()=>{if(!document.hidden)drawCountdown()')),ctx);
const start=new Date(Date.now()-1000).toISOString(),end=new Date(Date.now()+3600000).toISOString();
const joint={phases:[{start,end,action:'hold',reason:'reserve',kwh:0,low_ct:12,high_ct:13}]};
const d={mode:'smart',settings:{target_soc:80,timezone:'Europe/Berlin'},telemetry:{time:new Date().toISOString(),soc:60,battery_power_w:0},smart_preview:{effective_target_soc:18.831684638633398,joint}};
ctx.renderBatteryCard(d);
assert.equal(els.cardtarget.textContent,'80 %');
assert.match(els.cardplan.textContent,/🔒 Schutz bis/);
assert.ok(els.cardplan.textContent.length<35);
assert.equal(els.soctarget.attrs.x1,800);
assert.match(ctx.phaseFacts(joint,d.settings)[0],/Benötigte Energie/);
joint.phases[0]={start,end,action:'charge',reason:'price',kwh:2.345,low_ct:12,high_ct:13};
assert.match(ctx.phaseFacts(joint,d.settings)[0],/2,35 kWh · 12–13 ct/);
console.log('Plan facts: configured SOC ceiling, rounded numbers, short card and concrete slot data passed');

const pause={settings:{timezone:'Europe/Berlin'},server_time:'2026-10-31T10:59:00Z',smart_preview:{joint:{phases:[
 {start:'2026-10-31T10:58:00Z',end:'2026-10-31T11:00:00Z',action:'hold',reason:'reserve'},
 {start:'2026-10-31T11:00:00Z',end:'2026-10-31T14:45:00Z',action:'hold',reason:'price'}]}}};
assert.match(ctx.compactPlan(pause),/15:45/);
