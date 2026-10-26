const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class El{constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.style={};this.handlers={};}append(...a){this.children.push(...a);}replaceChildren(...a){this.children=a;}setAttribute(k,v){this.attrs[k]=v;}addEventListener(k,v){this.handlers[k]=v;}}
const ctx={Date,Number,Set,document:{createElement:t=>new El(t),createElementNS:(_,t)=>new El(t),addEventListener(){}},setInterval(){},lastStatus:{settings:{timezone:'Europe/Berlin'}}};vm.createContext(ctx);vm.runInContext(fs.readFileSync(__dirname+'/journal.js','utf8'),ctx);
const box=new El('div');const rows=[{time:0,house_w:500,load_w:500,pv_dc_w:0,pv_forecast_w:0},{time:300,house_w:600,load_w:500,pv_dc_w:200,pv_forecast_w:100},{time:1200,house_w:700,load_w:500,pv_dc_w:400,pv_forecast_w:200}];
ctx.diagnosisChart(box,'Haus',rows,[{key:'house_w',name:'Gemessen',color:'green'},{key:'load_w',name:'Geplant',color:'blue',dashed:true}],'kW',600);
const panel=box.children[0],controls=panel.children[1],plot=panel.children[2];
let paths=plot.children[0].children.filter(e=>e.tag==='path');assert.equal(paths.length,2);assert.equal((paths[0].attrs.d.match(/ M/g)||[]).length,2);assert.ok(paths[0].attrs.d.includes(' L'));
controls.children[0].onclick();paths=plot.children[0].children.filter(e=>e.tag==='path');assert.equal(paths.length,1);assert.equal(controls.children[0].attrs['aria-pressed'],'false');
const empty={actual_kwh:0,planned_kwh:0,hours:0,difference_pct:null};
ctx.renderDiagnosis(new El('div'),{valid_samples:0,invalid_samples:0,tolerance_pct:10,totals:{house:empty,evening:empty,pv:empty},series:[],soc_series:[],hold_spans:[],limit_mismatches:[],recommendations:[]});
console.log('Diagnosis UI: empty data, independent legends, dashed forecast and unbridged gaps passed');
