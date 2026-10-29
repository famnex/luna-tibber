const fs=require('fs'),vm=require('vm'),assert=require('assert');
class El{constructor(){this.children=[];this.handlers={};this.style={};this.attrs={};this.classList={add(){}};}append(...a){this.children.push(...a);}replaceChildren(...a){this.children=a;}setAttribute(k,v){this.attrs[k]=v;}addEventListener(k,f){this.handlers[k]=f;}}
const ctx={window:{addEventListener(){}},document:{addEventListener(){},createElement(){return new El();}},console};vm.createContext(ctx);vm.runInContext(fs.readFileSync('features.js','utf8'),ctx);
const svg=new El();let count=0;ctx.bindPlotInspection(svg,()=>count++);
svg.handlers.pointermove({pointerType:'mouse'});assert.equal(count,1);
svg.handlers.pointermove({pointerType:'touch'});assert.equal(count,1);
svg.handlers.pointerdown({pointerId:1,clientX:10,clientY:20});svg.handlers.pointerup({pointerId:1,clientX:13,clientY:20});assert.equal(count,2);
svg.handlers.pointerdown({pointerId:1,clientX:10,clientY:20});svg.handlers.pointerup({pointerId:1,clientX:90,clientY:20});assert.equal(count,2);
svg.handlers.pointerdown({pointerId:1,clientX:10,clientY:20});svg.handlers.pointercancel();svg.handlers.pointerup({pointerId:1,clientX:10,clientY:20});assert.equal(count,2);
const root=new El();ctx.renderPhaseStrip(root,[{start:0,end:10,action:'charge'},{start:10,end:40,action:'hold'}],String);
assert.equal(root.children.length,3);assert.equal(root.children[1].children.length,5);assert.equal(root.children[2].hidden,true);assert.equal(root.children[0].children[1].style.flex,'30');root.children[0].children[0].onclick();assert.equal(root.children[2].hidden,false);assert.equal(root.children[2].children.length,2);
console.log('Chart interaction: hover, tap, swipe/cancel, proportional compact plan and selected bubbles passed');
