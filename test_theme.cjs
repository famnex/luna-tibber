const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('theme.js','utf8');
function run(saved,blocked=false){
 const nodes=Object.fromEntries(['startup','startupspinner','startupretry','startuptext','appearance'].map(k=>[k,{hidden:false}]));
 const root={dataset:{}},media={matches:true,addEventListener:(e,f)=>media.changed=f};let ready,timeout,stored;
 const document={documentElement:root,querySelector:()=>({setAttribute(){}}),getElementById:k=>nodes[k],addEventListener:(e,f)=>ready=f};
 const window={matchMedia:()=>media};vm.runInNewContext(source,{window,document,localStorage:{getItem(){if(blocked)throw Error();return saved;},setItem(k,v){stored=v;}},setTimeout:f=>(timeout=f,1),clearTimeout(){},location:{reload(){}}});
 assert.equal(root.dataset.theme,saved==='light'?'light':'dark');ready();nodes.appearance.value='light';nodes.appearance.onchange();assert.equal(root.dataset.theme,'light');assert.equal(stored,'light');
 window.startupState('error');assert.equal(nodes.startupretry.hidden,false);assert.equal(nodes.startupspinner.hidden,true);
 window.startupState('ready');assert.equal(nodes.startup.hidden,true);
 return nodes;
}
run(null);run('dark');run('light');run(null,true);
const html=fs.readFileSync('web.html','utf8');assert.match(html,/id="login" hidden/);assert(html.indexOf('/theme.js')<html.indexOf('/style.css'));
const app=fs.readFileSync('app.js','utf8');assert.match(app,/abort\.abort\(\),20000/);assert.match(app,/startupState\?\.\('error',/);assert.match(app,/clearTimeout\(timeout\)/);
console.log('Appearance: system/manual preference, unavailable storage, startup success/error and hidden initial login passed');
