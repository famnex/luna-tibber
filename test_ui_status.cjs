const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('app.js','utf8');const ctx={Date};vm.createContext(ctx);vm.runInContext(code.slice(code.indexOf('function uiAge('),code.indexOf('function renderBatteryCard(')),ctx);
const now=Date.now(),time=new Date(now).toISOString();
assert.match(ctx.deviceEvidence({telemetry:{time,battery_power_w:200}},now),/Ladung gemessen/);
assert.match(ctx.deviceEvidence({discharge:{status:{time,locked:true}}},now),/am Gerät bestätigt/);
assert.match(ctx.deviceEvidence({job:'discharge-sync'},now),/ausstehend/);
assert.match(ctx.deviceEvidence({discharge:{status:{time:new Date(now-100000).toISOString(),locked:true}}},now),/nicht frisch/);
assert.equal(ctx.uiAge(7200),'2 Std.');assert.equal(ctx.uiAge(70),'1 Min.');
console.log('UI evidence: confirmed / pending / stale remain distinct; concise age labels passed');
