const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const source=fs.readFileSync('brandprobe/static/app.js','utf8');
const html=fs.readFileSync('brandprobe/static/index.html','utf8');
assert.match(html, /id="model-picker" hidden/);
assert.match(source, /if\(live\)loadModels\(\)/);
assert.doesNotMatch(html, /Command\/Ctrl|select id="models"/);
class Element {
 constructor(label=''){this.options=[];this.hidden=true;this.value='';this.textContent=label;}
 replaceChildren(...items){this.options=items;}
 append(...items){this.options.push(...items);}
 setAttribute(){}
 get firstChild(){return this.options[0];}
 get selectedOptions(){return this.options.filter(o=>o.selected);}
}
const elements=Object.fromEntries(['models','selected-models','selected-model-count','evaluator','load-models','catalog-status','model-picker','model-search','evaluator-search','model-search-status','evaluator-search-status'].map(k=>[k,new Element()]));
let calls=0, invalidations=0, fail=true;
const catalog=['Alpha','Beta','Gamma','Delta','Epsilon','Zeta','Eta'].map((name,i)=>({id:String.fromCharCode(97+i),name,input_per_token:0,output_per_token:0}));
const context={$:id=>elements[id],text:(tag,label)=>new Element(label),invalidate:()=>invalidations++,api:async()=>{calls++;if(fail)throw new Error('offline');return catalog;}};
vm.createContext(context);
vm.runInContext("let catalogPromise, catalogLoaded=false, modelOptions=[], evaluatorOptions=[], selectedModelIds=new Set(); let config={models:['b'],evaluator_model:'a'};\n"+source.slice(source.indexOf('async function loadModels('),source.indexOf('function modeChanged(')),context);
const chosen=()=>Array.from(vm.runInContext('[...selectedModelIds]',context));
const addButton=name=>elements.models.options.find(row=>row.options[0]?.options[0]?.textContent===name)?.options[1];
(async()=>{
 await context.loadModels();
 assert.equal(elements['model-picker'].hidden,true);
 assert.match(elements['load-models'].textContent,/Retry/);
 fail=false;
 await Promise.all([context.loadModels(),context.loadModels()]);
 assert.equal(calls,2);
 assert.equal(elements['model-picker'].hidden,false);
 assert.deepEqual(chosen(),['b']);
 assert.equal(elements['evaluator'].value,'a');
 assert.equal(addButton('Beta').disabled,true);
 addButton('Alpha').onclick();
 assert.deepEqual(chosen(),['b','a']);
 assert.equal(elements['selected-models'].options.length,2);
 context.changeModel('a',true); // no duplicates
 assert.deepEqual(chosen(),['b','a']);
 elements['model-search'].value='  GAMMA ';context.filterModels('models');
 assert.equal(elements.models.options.length,1);
 addButton('Gamma').onclick();
 assert.deepEqual(chosen(),['b','a','c']);
 elements['selected-models'].options[1].options[1].onclick(); // remove Alpha under another filter
 assert.deepEqual(chosen(),['b','c']);
 elements['model-search'].value='missing';context.filterModels('models');
 assert.match(elements['model-search-status'].textContent,/0 matching models/);
 assert.equal(elements['selected-models'].options.length,2);
 elements['model-search'].value='';context.filterModels('models');
 for(const name of ['Alpha','Delta','Epsilon','Zeta'])addButton(name).onclick();
 assert.equal(chosen().length,6);
 assert.equal(addButton('Eta').disabled,true);
 context.changeModel('g',true);assert.equal(chosen().length,6);
 elements['selected-models'].options[0].options[1].onclick();
 assert.equal(addButton('Eta').disabled,false);
 addButton('Eta').onclick();assert.equal(chosen().length,6);
 const before=chosen();await context.loadModels(true);assert.deepEqual(chosen(),before);
 elements['evaluator-search'].value='beta';context.filterModels('evaluator');
 assert.equal(elements.evaluator.value,'a');
 fail=true;await context.loadModels(true);
 assert.equal(elements['model-picker'].hidden,false);
 assert.deepEqual(chosen(),before);
 assert.ok(invalidations>5);
 console.log('Model picker: loading, search, add/remove buttons, duplicate prevention, six-model limit and refresh preservation passed.');
})().catch(error=>{console.error(error);process.exit(1);});
