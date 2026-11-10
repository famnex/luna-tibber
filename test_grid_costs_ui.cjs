const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),els={gridperiod:{value:'today'},gridaverage:{},gridamount:{},gridcoverage:{}};
const src=fs.readFileSync('features.js','utf8'),ctx={document:{getElementById:id=>els[id]}};vm.createContext(ctx);vm.runInContext(src.slice(src.indexOf('let gridCostData=null;')),ctx);
vm.runInContext("gridCostData={periods:{today:{ct_kwh:40,kwh:3,eur:1.2,hours:1,coverage_pct:50}}};renderGridCosts()",ctx);
assert.equal(els.gridaverage.textContent,'≈ 40 ct/kWh');assert.match(els.gridamount.textContent,/3 kWh/);assert.match(els.gridcoverage.textContent,/Teilzeitraum/);
vm.runInContext("gridCostData.periods.today={ct_kwh:null,kwh:0,eur:0,hours:0,coverage_pct:0};renderGridCosts()",ctx);assert.equal(els.gridaverage.textContent,'—');
