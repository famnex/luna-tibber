const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c={Date,Intl,window:{addEventListener(){}},document:{addEventListener(){}}};vm.createContext(c);vm.runInContext(fs.readFileSync('features.js','utf8'),c);
const now=Date.parse('2026-10-25T12:00:00Z');
const d={mode:'smart',settings:{battery_capacity_kwh:10,battery_floor_soc:5},telemetry:{time:new Date(now).toISOString(),soc:50},battery_history:[{time:new Date(now-60000).toISOString(),soc:49}],smart_preview:{joint:{trace:[{start:new Date(now).toISOString(),end:new Date(now+900000).toISOString(),start_kwh:4.5,end_kwh:5}]}}};
let r=c.batterySeries(d,now);assert.equal(r.measured.length,2);assert.equal(r.forecast[0].soc,50);assert.equal(r.forecast[1].soc,55);
d.mode='off';assert.equal(c.batterySeries(d,now).forecast.length,0);
d.mode='smart';d.telemetry.time=new Date(now-180000).toISOString();assert.equal(c.batterySeries(d,now).forecast.length,0);
const path=c.socPath([{time:now,soc:50},{time:now+60000,soc:51},{time:now+7200000,soc:52}],now,now+7200000,Date.parse,v=>v);assert.equal((path.match(/ M/g)||[]).length,2);
console.log('Battery chart: actual history, floor-aware Smart projection, inactive/stale exclusion and gaps passed');

assert.ok(path.includes(' C'));
const hourly=c.socPath([{time:now,soc:40},{time:now+3600000,soc:60}],now,now+3600000,Date.parse,v=>v);assert.equal((hourly.match(/ M/g)||[]).length,1);assert.ok(hourly.includes(' C'));
