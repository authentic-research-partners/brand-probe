'use strict';
const $ = id => document.getElementById(id);
let config, token, plan, pollTimer, catalogPromise, catalogLoaded = false;
let modelOptions = [], evaluatorOptions = [];
let selectedModelIds = new Set();
const text = (tag, value, className) => { const e=document.createElement(tag);e.textContent=value;if(className)e.className=className;return e; };
const notify = value => { $('message').textContent=value; };
const isLive = () => document.querySelector('[name=mode]:checked').value==='live';
async function api(path, body) {
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Brandprobe-Token':token},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
  return data;
}
function invalidate(){plan=null;$('preview-panel').hidden=true;}
function addPrompt(p){
 const row=text('div','','prompt');row.dataset.id=p.id;
 const kind=document.createElement('select');kind.setAttribute('aria-label','Question type');
 for(const k of ['recognition','discovery','alternatives']){const o=text('option',k[0].toUpperCase()+k.slice(1));o.value=k;kind.append(o);}kind.value=p.kind;
 const q=document.createElement('textarea');q.value=p.text;q.required=true;q.setAttribute('aria-label','Audit question');
 const remove=text('button','×','remove');remove.type='button';remove.setAttribute('aria-label','Remove question');remove.onclick=()=>{row.remove();invalidate();};
 row.append(kind,q,remove);$('prompts').append(row);
}
function addReference(kind, value={}) {
 const row=text('div','','reference-row');row.dataset.id=value.id||crypto.randomUUID();
 const fields=text('div','','fields');
 const specs=kind==='facts'?[['statement','Reference statement','textarea'],['source_url','Source URL','url'],['reviewed_at','Date reviewed','date']]:[['name','Brand name','text'],['domain','Website domain','text'],['aliases','Aliases, comma separated','text']];
 for(const [key,label,type] of specs){const l=text('label',label),input=document.createElement(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.dataset.key=key;input.value=key==='aliases'?(value[key]||[]).join(', '):value[key]||'';input.required=key!=='aliases';l.append(input);fields.append(l);}
 const remove=text('button','Remove','quiet');remove.type='button';remove.onclick=()=>{row.remove();invalidate();};row.append(fields,remove);$(kind).append(row);invalidate();
}
function references(kind){return [...$(kind).children].map(row=>{const value={};for(const input of row.querySelectorAll('[data-key]'))value[input.dataset.key]=input.dataset.key==='aliases'?input.value.split(',').map(v=>v.trim()).filter(Boolean):input.value;if(kind==='facts')value.id=row.dataset.id;return value;});}
function collect(){return {...config,brand:{...config.brand,name:$('brand').value,domain:$('domain').value,audience:$('audience').value,market:$('market').value,language:$('language').value},competitors:references('competitors'),facts:references('facts'),facts_approved:$('facts-approved').checked,search:{queries:isLive()?$('search-queries').value.split('\n').map(v=>v.trim()).filter(Boolean):[],country:$('search-country').value.toUpperCase(),language:$('search-language').value,count:Number($('search-count').value),price_per_request_usd:String(Number($('search-price').value)/1000),rate_confirmed:$('search-rate-confirmed').checked},models:[...selectedModelIds],evaluator_model:$('evaluator').value||null,reasoning_effort:$('reasoning').value||null,max_tokens:Number($('max-tokens').value),repetitions:Number($('repetitions').value),budget_usd:$('budget').value,prompts:[...$('prompts').children].map(row=>({id:row.dataset.id,kind:row.querySelector('select').value,text:row.querySelector('textarea').value}))};}
function applyConfig(value){
 config=value;selectedModelIds=new Set(config.models);for(const id of ['brand','domain','audience','market','language'])$(id).value=id==='brand'?config.brand.name:config.brand[id];
 $('prompts').replaceChildren();config.prompts.forEach(addPrompt);
 for(const kind of ['competitors','facts']){$(kind).replaceChildren();(config[kind]||[]).forEach(v=>addReference(kind,v));}
 $('facts-approved').checked=config.facts_approved||false;
 $('budget').value=config.budget_usd;$('repetitions').value=config.repetitions;$('max-tokens').value=config.max_tokens;$('reasoning').value=config.reasoning_effort||'';
 const search=config.search||{};$('search-queries').value=(search.queries||[]).join('\n');$('search-country').value=search.country||'US';$('search-language').value=search.language||'en';$('search-count').value=search.count||10;$('search-price').value=Number(search.price_per_request_usd??0.005)*1000;$('search-rate-confirmed').checked=search.rate_confirmed||false;
 if(catalogLoaded){$('model-search').value='';$('evaluator-search').value='';filterModels('models');filterModels('evaluator');selectedModelIds=new Set(config.models);renderModelPicker();$('evaluator').value=config.evaluator_model||'';}
 invalidate();
}
async function loadModels(force=false){
 if(catalogPromise)return catalogPromise;
 if(catalogLoaded&&!force)return;
 invalidate();if(!catalogLoaded)selectedModelIds=new Set(config.models);
 const evaluator=catalogLoaded?$('evaluator').value:config.evaluator_model;
 $('load-models').disabled=true;$('load-models').textContent='Loading…';$('catalog-status').textContent='Fetching available models and current prices…';$('model-picker').setAttribute('aria-busy','true');
 catalogPromise=(async()=>{try{
  const models=await api('/api/models');if(!models.length)throw new Error('No eligible models returned.');
  $('evaluator').replaceChildren(text('option','Mention counts only (no semantic scoring)'));$('evaluator').firstChild.value='';
  modelOptions=models;
  for(const m of models){const judge=text('option',m.name);judge.value=m.id;$('evaluator').append(judge);}
  $('evaluator').value=evaluator||'';evaluatorOptions=[...$('evaluator').options];filterModels('models');filterModels('evaluator');catalogLoaded=true;$('model-picker').hidden=false;$('catalog-status').textContent=`${models.length} models available. Select up to six to compare. Loading this list is free.`;$('load-models').textContent='Refresh models';
 }catch(e){$('catalog-status').textContent=`Could not load models. ${e.message} ${catalogLoaded?'Your previous selection is retained.':''}`;$('load-models').textContent='Retry loading models';}
 finally{$('load-models').disabled=false;$('model-picker').setAttribute('aria-busy','false');catalogPromise=null;}})();return catalogPromise;
}
function filterModels(id){
 if(id==='models'){renderModelPicker();return;}
 const multiple=id==='models', select=$(id), pool=multiple?modelOptions:evaluatorOptions;
 const query=$(multiple?'model-search':'evaluator-search').value.trim().toLowerCase();
 const selected=new Set(multiple?[...select.selectedOptions].map(o=>o.value):[select.value]);
 const matches=pool.filter(o=>o.value && `${o.textContent} ${o.value}`.toLowerCase().includes(query));
 const retained=pool.filter(o=>o.value && selected.has(o.value) && !matches.includes(o));
 // Selected options stay visible even when the query changes.
 select.replaceChildren(...pool.filter(o=>!o.value||matches.includes(o)||selected.has(o.value)));
 for(const o of select.options)o.selected=selected.has(o.value);
 if(!multiple)select.value=[...selected][0]||'';
 $(multiple?'model-search-status':'evaluator-search-status').textContent=`${matches.length} matching models${retained.length?`; ${retained.length} selected model${retained.length===1?'':'s'} also shown`:''}.${matches.length?'':' Try another name or provider.'}`;
}
function changeModel(id, add){
 if(add){if(selectedModelIds.size>=6||selectedModelIds.has(id))return;selectedModelIds.add(id);}
 else selectedModelIds.delete(id);
 invalidate();renderModelPicker();
}
function renderModelPicker(){
 const query=$('model-search').value.trim().toLowerCase();
 const matches=modelOptions.filter(m=>`${m.name} ${m.id}`.toLowerCase().includes(query));
 const chosen=$('selected-models'), results=$('models');chosen.replaceChildren();results.replaceChildren();
 $('selected-model-count').textContent=`${selectedModelIds.size} / 6 selected`;
 if(!selectedModelIds.size)chosen.append(text('p','No models selected. Add models from the list below.','help'));
 for(const id of selectedModelIds){
  const m=modelOptions.find(m=>m.id===id),row=text('div','','model-row selected-model'),info=text('div','','model-info');
  info.append(text('strong',m?.name||id),text('p',m?id:'Unavailable in the current catalog. Remove it or refresh models.','help'));
  const remove=text('button','Remove','secondary');remove.type='button';remove.setAttribute('aria-label',`Remove ${m?.name||id}`);remove.onclick=()=>changeModel(id,false);row.append(info,remove);chosen.append(row);
 }
 for(const m of matches){
  const row=text('div','','model-row'),info=text('div','','model-info');
  info.append(text('strong',m.name),text('p',`${m.id} · $${(Number(m.input_per_token)*1e6).toFixed(2)} input / $${(Number(m.output_per_token)*1e6).toFixed(2)} output per million tokens`,'help'));
  const selected=selectedModelIds.has(m.id),button=text('button',selected?'Added':'＋ Add','secondary');button.type='button';button.disabled=selected||selectedModelIds.size>=6;button.setAttribute('aria-label',selected?`${m.name} added`:`Add ${m.name}`);button.onclick=()=>changeModel(m.id,true);row.append(info,button);results.append(row);
 }
 $('model-search-status').textContent=`${matches.length} matching models.${selectedModelIds.size>=6?' Six-model limit reached. Remove a model to add another.':''}`;
 if(!matches.length)results.append(text('p','No matching models. Try another name or provider.','help'));
}
function modeChanged(){const live=isLive();$('live-settings').hidden=!live;$('mode-notice').textContent=live?'Live mode: real API requests run only after you approve the cost preview.':'Demo mode: synthetic examples only. No real models are being tested.';if(live)loadModels();invalidate();}
$('audit-form').addEventListener('input',invalidate);
$('audit-form').addEventListener('change',event=>{invalidate();if(event.target.name==='mode')modeChanged();});
$('add-prompt').onclick=()=>{addPrompt({id:crypto.randomUUID(),kind:'discovery',text:''});invalidate();};
$('add-competitor').onclick=()=>addReference('competitors');$('add-fact').onclick=()=>addReference('facts');
$('load-models').onclick=()=>loadModels(true);
$('model-search').oninput=()=>filterModels('models');
$('evaluator-search').oninput=()=>filterModels('evaluator');
function showPlan(value){plan=value;$('preview-copy').textContent=`${plan.parent_audit_id?'Continuation: only never-dispatched answers. Original evidence and uncertain requests are preserved. ':''}${plan.requests} model responses, ${plan.evaluation_requests||0} scoring requests, and ${plan.search_requests||0} separate Brave searches. ${plan.mode==='demo'?'Synthetic demo only.':'Model answers use no search or brand fact sheet.'} Output limit: ${plan.config.max_tokens} tokens; reasoning: ${plan.config.reasoning_effort||'provider defaults'}.`;$('preview-cost').textContent=`Estimated $${Number(plan.estimated_usd).toFixed(4)} · Reserved $${Number(plan.reserved_usd).toFixed(4)} · Budget $${Number(plan.config.budget_usd).toFixed(2)}. Search portion: $${Number(plan.search_reserved_usd||0).toFixed(4)} at your entered subscription rate.`;$('run').textContent=plan.mode==='demo'?'Run synthetic demo':'Approve cost and run live audit';$('preview-panel').hidden=false;$('preview-panel').scrollIntoView({block:'nearest',behavior:'auto'});}
$('audit-form').onsubmit=async event=>{event.preventDefault();$('preview').disabled=true;notify('');try{showPlan(await api('/api/plans',{config:collect(),demo:!isLive()}));}catch(e){notify(e.message);}finally{$('preview').disabled=false;}};
$('run').onclick=async()=>{if(!plan)return;$('run').disabled=true;try{const run=await api('/api/runs',{plan_id:plan.id,approved:plan.mode==='live'});invalidate();await watch(run.id);}catch(e){notify(e.message);}finally{$('run').disabled=false;}};
async function watch(id){clearTimeout(pollTimer);try{const data=await api(`/api/runs/${id}`);render(data);if(data.audit.status==='running')pollTimer=setTimeout(()=>watch(id),1200);else await history();}catch(e){notify(e.message);}}
function sourceLink(url,label){try{const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol))return text('span',label);const a=text('a',label,'source-link');a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return text('span',label);}}
function table(headers,rows){const wrap=text('div','','table-wrap'),t=document.createElement('table'),head=document.createElement('thead'),hr=document.createElement('tr');headers.forEach(v=>hr.append(text('th',v)));head.append(hr);t.append(head);const body=document.createElement('tbody');rows.forEach(values=>{const row=document.createElement('tr');values.forEach(v=>row.append(text('td',String(v))));body.append(row);});t.append(body);wrap.append(t);return wrap;}
function render(data){
 const a=data.audit;$('results').hidden=false;$('run-status').textContent=a.status;
 $('result-label').textContent=[a.plan.mode==='demo'?'Synthetic demo. These answers are fixtures, not findings about your brand.':'Live API responses. Recognition is a model judgment, not factual verification.',...(data.warnings||[]),a.recovery_note||''].filter(Boolean).join(' ');
 $('progress').textContent=`${a.observations.filter(o=>o.status!=='interrupted'||a.status!=='running').length} of ${a.plan.requests} answers recorded; ${a.observations.filter(o=>o.status==='ok').length} usable. Scored ${a.observations.filter(o=>o.evaluation?.status==='complete').length}. Known model cost: $${Number(data.known_cost_usd).toFixed(4)}. Unknown model costs: ${data.unknown_cost_responses} generation, ${data.unknown_evaluation_costs||0} scoring. Search estimated cost: $${Number(data.search_estimated_cost_usd||0).toFixed(4)} (${data.unknown_search_costs||0} requests with uncertain billing).`;
 $('summary').replaceChildren();for(const r of data.semantic_summary||data.summary){const row=document.createElement('tr');for(const v of [r.model,r.kind,r.successful?`${r.mentions} / ${r.successful}`:'Unmeasured',r.kind==='recognition'?(r.assessed?`${r.recognized} / ${r.assessed}`:'Not assessed'):'Not applicable',r.kind==='recognition'?'Not applicable':r.assessed?`${r.recommended} / ${r.assessed}`:'Not assessed',r.excluded])row.append(text('td',String(v)));$('summary').append(row);}
 $('exports').replaceChildren();for(const kind of ['html','json','csv']){const link=text('a',`Export ${kind.toUpperCase()}`);link.href=`/api/runs/${a.id}/export/${kind}`;link.target='_blank';link.rel='noopener';$('exports').append(link);}
 const extras=$('extra-results');extras.replaceChildren();
 if((a.plan.config.competitors||[]).length){extras.append(text('h3','Comparison brands'),text('p','Exact mentions on successful questions that name none of the compared brands. Mentions are not recommendations.','help'),table(['Model','Brand','Mentions / eligible answers','Excluded'],(data.competitor_summary||[]).map(r=>[r.model,r.brand,r.successful?`${r.mentions} / ${r.successful}`:'Unmeasured',r.excluded])));}
 if((a.plan.config.facts||[]).length){extras.append(text('h3','Approved reference facts'));for(const f of a.plan.config.facts)extras.append(text('p',`${f.id}: ${f.statement} (reviewed ${f.reviewed_at})`),sourceLink(f.source_url,'Reference source'));extras.append(text('p','Checks below compare against these statements. They do not verify every claim in an answer.','help'));}
 if((a.search_observations||[]).length){extras.append(text('h3','Brave Search baseline'),table(['Query','Brand','Domain rank / returned results'],(data.search_summary||[]).map(r=>[r.query,r.brand,r.status==='ok'?(r.first_domain_rank?`${r.first_domain_rank} / ${r.returned_results}`:`Not found in ${r.returned_results} results`):r.status])));for(const result of a.search_observations){const d=document.createElement('details');d.append(text('summary',`${result.query} / ${result.status}`));if(result.error)d.append(text('p',result.error));for(const hit of result.results)d.append(sourceLink(hit.url,`${hit.rank}. ${hit.title}`),text('p',hit.description));extras.append(d);}}
 if($('evidence').dataset.run!==a.id){$('evidence').replaceChildren();$('evidence').dataset.run=a.id;}
 const existing=new Map([...$('evidence').children].map(e=>[e.dataset.id,e]));
 for(const o of a.observations){const signature=JSON.stringify([o.status,o.evaluation]),old=existing.get(o.id);if(old?.dataset.signature===signature)continue;const d=document.createElement('details');d.open=old?.open||false;d.dataset.signature=signature;d.dataset.id=o.id;d.append(text('summary',`${o.model} / ${o.prompt.kind} / repetition ${o.repetition} / ${o.status}${o.mention?' / brand mentioned':''}`),text('h3',o.prompt.text),text('pre',o.text||o.error));if(o.evaluation?.assessment){const v=o.evaluation.assessment;d.append(text('p',`Recognition: ${v.recognition}. Recommendation: ${v.recommendation}. ${v.rationale}`,'assessment'),text('blockquote',[v.recognition_quote,v.recommendation_quote].filter(Boolean).join(' / ')));for(const c of v.fact_checks||[])d.append(text('p',`Fact ${c.fact_id}: ${c.verdict}. ${c.rationale}`),text('blockquote',`Answer: ${c.answer_quote||'(not addressed)'}\nReference: ${c.reference_quote||'(none)'}`));}else if(o.evaluation)d.append(text('p',`Scoring: ${o.evaluation.status}. ${o.evaluation.error}`,'help'));if(old)old.replaceWith(d);else $('evidence').append(d);}
}
async function history(){const rows=await api('/api/runs');$('history-list').replaceChildren();if(!rows.length){$('history-list').append(text('p','No runs yet. Start with the synthetic demo.','help'));return;}for(const r of rows){const row=text('div','','history-row'),info=document.createElement('div'),actions=text('div','','history-actions');info.append(text('strong',r.brand),text('p',`${r.mode} / ${r.status} / ${new Date(r.started_at).toLocaleString()}${r.parent_audit_id?' / continuation':''}`));const b=text('button','Inspect','quiet');b.onclick=()=>watch(r.id);actions.append(b);if(r.can_continue){const c=text('button','Preview remaining work','secondary');c.onclick=async()=>{c.disabled=true;try{showPlan(await api(`/api/runs/${r.id}/continuation`,{}));}catch(e){notify(e.message);}finally{c.disabled=false;}};actions.append(c);}row.append(info,actions);$('history-list').append(row);}}
$('refresh-history').onclick=()=>history().catch(e=>notify(e.message));
$('load-pilot').onclick=async()=>{try{applyConfig(await api('/api/pilot'));document.querySelector('[name=mode][value=live]').checked=true;modeChanged();await loadModels();selectedModelIds=new Set(config.models);renderModelPicker();$('evaluator').value=config.evaluator_model||'';notify('Pilot loaded. Review the questions and models, then preview the combined cost.');}catch(e){notify(e.message);}};
(async()=>{try{const setup=await api('/api/setup');token=setup.token;applyConfig(setup.config);$('key-status').textContent=setup.key_configured?'OpenRouter key configured':'Demo ready; API key not configured';$('search-key-status').textContent=setup.search_key_configured?'Brave key configured.':'Add BRAVE_SEARCH_API_KEY to .env or .env.local to run searches.';await history();}catch(e){notify(e.message);}})();
