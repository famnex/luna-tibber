const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={Date,window:{addEventListener(){}},document:{addEventListener(){}}};vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/features.js','utf8'),ctx);
const rows=[{start:0,end:10,kw:0},{start:10,end:20,kw:4},{start:20,end:30,kw:0},{start:40,end:50,kw:2}];
const path=ctx.smoothSolarPath(rows,0,50,x=>x,y=>y);
assert.equal((path.match(/ M/g)||[]).length,2);assert.ok(path.includes(' C'));assert.ok(!path.includes('NaN'));
// Cubic control values are endpoint values, so convex hull cannot overshoot.
for(const match of path.matchAll(/ C([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)/g)){
 for(const i of [2,4,6])assert.ok(Number(match[i])>=0&&Number(match[i])<=4);
}
assert.equal(rows[1].kw,4);assert.equal(ctx.smoothSolarPath([],0,50,x=>x,y=>y),'');
const now=Date.parse('2026-10-25T06:00:00Z'),at=h=>new Date(now+h*3600000).toISOString();
const d={mode:'smart',settings:{timezone:'Europe/Berlin'},prices:[{start:at(0),end:at(17)}],dispatch_preview:{windows:[{start:at(-1),end:at(2),action:'hold'},{start:at(2),end:at(17),action:'discharge'}]},smart_preview:{windows:[{start:at(0),end:at(1)}]}};
const phases=ctx.todayPhases(d,now);assert.equal(phases[0].action,'charge');assert.equal(phases[0].start,now);assert.equal(phases.at(-1).end,Date.parse(at(17)));assert.ok(phases.some(p=>p.action==='hold'));assert.ok(phases.some(p=>p.action==='discharge'));
d.mode='off';assert.equal(ctx.todayPhases(d,now).length,0);
d.mode='planned';d.planned={start:at(1),end:at(2)};assert.equal(ctx.todayPhases(d,now)[0].action,'unknown');assert.equal(ctx.todayPhases(d,now)[1].action,'charge');
console.log('PV smoothing: bounded cubics, zero values and gaps; daily plan: clipping, precedence and inactive modes passed');
// Tomorrow is a local calendar day, not now + 24 hours (DST fallback).
const dstNow=Date.parse('2026-10-24T22:30:00Z');
assert.equal(ctx.planDayKey(d,dstNow,1),'2026-10-26');
const tomorrow={...d,mode:'smart',prices:[{start:'2026-10-25T23:00:00Z',end:'2026-10-26T23:00:00Z'}],dispatch_preview:{windows:[{start:'2026-10-25T23:00:00Z',end:'2026-10-26T23:00:00Z',action:'hold'}]},smart_preview:{windows:[]}};
assert.equal(ctx.todayPhases(tomorrow,dstNow,1)[0].start,Date.parse('2026-10-25T23:00:00Z'));
assert.equal(ctx.todayPhases(tomorrow,dstNow,0).length,0);
assert.equal(ctx.todayPhases({...tomorrow,prices:[]},dstNow,1).length,0);
