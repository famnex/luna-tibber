const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(__dirname+'/app.js','utf8');const ctx={Date,Number,ct:n=>n+' ct/kWh'};vm.createContext(ctx);vm.runInContext(src.slice(src.indexOf('function displayPlanPhases'),src.indexOf('function compactPlan')),ctx);vm.runInContext(src.slice(src.indexOf('function overviewNext'),src.indexOf('function renderOverview')),ctx);
const now=Date.parse('2026-10-25T02:00:00Z'),future='2026-10-25T04:00:00Z';
const d={mode:'off'};assert.match(ctx.overviewNext(d,now).label,/Kein/);
d.discharge={request:{until:future}};assert.equal(ctx.overviewNext(d,now).time,future);
d.fault='Fehler';assert.equal(ctx.overviewNext(d,now).reason,'Fehler');delete d.fault;delete d.discharge;
d.mode='smart';d.smart_preview={joint:{phases:[{start:future,action:'charge',kwh:1.23,low_ct:10,high_ct:12}]}};assert.match(ctx.overviewNext(d,now).reason,/1,23 kWh/);
d.mode='planned';d.planned={start:future,end:'2026-10-25T05:00:00Z',target_soc:80};assert.match(ctx.overviewNext(d,now).label,/starten/);assert.match(ctx.overviewNext(d,Date.parse(future)+1).label,/beenden/);
console.log('Overview: mode, manual hold, fault, planned start/end and concrete Smart plan passed');

const pause={mode:'smart',server_time:'2026-10-31T10:59:00Z',smart_preview:{joint:{phases:[
 {start:'2026-10-31T10:58:00Z',end:'2026-10-31T11:00:00Z',action:'hold',reason:'reserve'},
 {start:'2026-10-31T11:00:00Z',end:'2026-10-31T14:45:00Z',action:'hold',reason:'price'},
 {start:'2026-10-31T14:45:00Z',end:'2026-10-31T23:00:00Z',action:'discharge'}]}}};
const original=JSON.stringify(pause);
assert.equal(ctx.overviewNext(pause).time,'2026-10-31T14:45:00Z');
assert.equal(ctx.overviewNext(pause).label,'Entladung freigeben');
assert.equal(JSON.stringify(pause),original);
pause.smart_preview.joint.phases.pop();assert.match(ctx.overviewNext(pause).label,/noch nicht geplant/);
pause.smart_preview.joint.phases[1].action='charge';assert.equal(ctx.overviewNext(pause).time,'2026-10-31T11:00:00Z');
console.log('Next action: server clock, merged pause, actual transition and unknown release passed');
