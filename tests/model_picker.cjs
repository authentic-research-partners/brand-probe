const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('brandprobe/static/app.js','utf8');
const html=fs.readFileSync('brandprobe/static/index.html','utf8');
assert.match(html, /id="model-picker" hidden/);
assert.match(source, /if\(live\)loadModels\(\)/);
class Element {
 constructor(){this.options=[];this.hidden=true;this.value='';this.textContent='';}
 replaceChildren(...items){this.options=items;}
 append(item){this.options.push(item);}
 setAttribute(){}
 get firstChild(){return this.options[0];}
 get selectedOptions(){return this.options.filter(o=>o.selected);}
}
const elements=Object.fromEntries(['models','evaluator','load-models','catalog-status','model-picker'].map(k=>[k,new Element()]));
let calls=0, invalidations=0, fail=true;
const context={$:id=>elements[id],text:(tag,label)=>({textContent:label}),invalidate:()=>invalidations++,api:async()=>{calls++;if(fail)throw new Error('offline');return [{id:'a',name:'Alpha',input_per_token:0,output_per_token:0},{id:'b',name:'Beta',input_per_token:0,output_per_token:0}];}};
vm.createContext(context);
vm.runInContext("let catalogPromise, catalogLoaded=false; let config={models:['b'],evaluator_model:'a'};\n"+source.slice(source.indexOf('async function loadModels('),source.indexOf('function modeChanged(')),context);
(async()=>{
 await context.loadModels();
 assert.equal(elements['model-picker'].hidden,true);
 assert.match(elements['load-models'].textContent,/Retry/);
 assert.match(elements['catalog-status'].textContent,/offline/);
 fail=false;
 await Promise.all([context.loadModels(),context.loadModels()]);
 assert.equal(calls,2);
 assert.equal(elements['model-picker'].hidden,false);
 assert.equal(elements['models'].selectedOptions[0].value,'b');
 assert.equal(elements['evaluator'].value,'a');
 assert.equal(elements['load-models'].disabled,false);
 assert.equal(elements['load-models'].textContent,'Refresh models');
 elements.models.options[0].selected=true;elements.models.options[1].selected=false;
 await context.loadModels(true);
 assert.equal(elements.models.selectedOptions[0].value,'a');
 fail=true;await context.loadModels(true);
 assert.equal(elements['model-picker'].hidden,false);
 assert.equal(elements.models.selectedOptions[0].value,'a');
 assert.equal(invalidations,4);
 console.log('Model picker: automatic entry, failure, retry, deduplication and selection preservation passed.');
})().catch(error=>{console.error(error);process.exit(1);});
