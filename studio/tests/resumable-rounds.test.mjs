import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';import {createHash,randomUUID} from 'node:crypto';
import {createReferenceJobs} from '/app/reference-design-jobs.mjs';
import {pageLimit,pageRemaining,deckLimit} from '/app/reference-retry-rounds.mjs';
const input=(n=1)=>({project:{id:'round-test',title:'40页测试',themeId:'curated-091',pages:Array.from({length:n},(_,i)=>({id:'p'+i,title:'标题'+i,body:'完整正文'+i,role:'content',objects:[]}))}});
const result=inp=>({pages:inp.project.pages.filter(p=>inp.targetPageIds.includes(p.id)).map(p=>({...p,themeId:'curated-091',objects:[{id:'t-'+p.id,type:'text',text:p.body}]}))});
const goodReview=async({project})=>({summary:'checked',issues:[],reviewEvidence:{status:'pass',checkedPageIds:project.pages.map(p=>p.id)}});
async function cache(opts,id){const dir=join(opts.checkpointDir,'image-background-'+createHash('sha256').update(id).digest('hex'));await mkdir(dir,{recursive:true});const bytes=Buffer.from('controlled-same-source');await writeFile(join(dir,'background.png'),bytes);await writeFile(join(dir,'checkpoint.json'),JSON.stringify({version:1,fingerprint:'a'.repeat(64),imageHash:createHash('sha256').update(bytes).digest('hex')}));await writeFile(join(dir,'layout.json'),JSON.stringify({version:1,fingerprint:'a'.repeat(64),layout:{boxes:[]}}));}
async function fixture(t,generate,review=goodReview,overrides={}){const dataDir=await mkdtemp(join(tmpdir(),'rounds-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));const config={dataDir,generate,review,plan:async inp=>({targetPageIds:inp.targetPageIds,pages:inp.targetPageIds.map(pageId=>({pageId}))}),stagePipeline:false,sharedStyleFirst:false,pipelined:false,retryDelayMs:0,...overrides};return {jobs:createReferenceJobs(config),config,dataDir};}
async function finished(jobs,id){for(let i=0;i<1000;i++){const j=await jobs.get(id);if(!['queued','running','cancelling'].includes(j.status))return j;await new Promise(r=>setTimeout(r,2));}throw Error('bounded fixture timed out');}
test('three explicit rounds keep monotonic cumulative usage, duplicate IDs and reads grant nothing',async t=>{
 const f=await fixture(t,async(inp,opts)=>{await cache(opts,inp.targetPageIds[0]);for(let i=0;i<7;i++)await opts.beforeStage('text');return result(inp);});
 const started=await f.jobs.start(input());let j=await finished(f.jobs,started.id);assert.equal(j.pageStatus[0].budget.used.text,6);assert.equal(j.canResume,true);
 for(let round=2;round<=3;round++){
  const before=await readFile(join(f.dataDir,'reference-jobs',j.id+'.json'),'utf8');await f.jobs.resume(j.id);assert.equal(await readFile(join(f.dataDir,'reference-jobs',j.id+'.json'),'utf8'),before);
  const rid=randomUUID();await f.jobs.resume(j.id,{resumeRequestId:rid});j=await finished(f.jobs,j.id);assert.equal(j.pageStatus[0].budget.used.text,round*6);assert.equal(pageRemaining(j.pageStatus[0].budget,'text'),0);
  const bytes=await readFile(join(f.dataDir,'reference-jobs',j.id+'.json'),'utf8');await Promise.all([f.jobs.get(j.id),f.jobs.list(),f.jobs.resume(j.id,{resumeRequestId:rid})]);assert.equal(await readFile(join(f.dataDir,'reference-jobs',j.id+'.json'),'utf8'),bytes);
 }
 const restarted=createReferenceJobs(f.config);j=await restarted.get(j.id);assert.equal(j.pageStatus[0].budget.used.text,18);assert.equal(j.canResume,true);assert.equal(pageLimit(j.pageStatus[0].budget,'text'),18);
});
test('40 pages: resume calls only the missing page and retains all 39 original results',async t=>{
 const calls=new Map();const f=await fixture(t,async(inp,opts)=>{const id=inp.targetPageIds[0],n=(calls.get(id)||0)+1;calls.set(id,n);if(id==='p17'&&n===1){await cache(opts,id);for(let i=0;i<7;i++)await opts.beforeStage('text');}return result(inp);});
 const started=await f.jobs.start(input(40)),before=await finished(f.jobs,started.id);assert.equal(before.completed,39);
 const rid=randomUUID();await Promise.all([f.jobs.resume(before.id,{resumeRequestId:rid}),f.jobs.resume(before.id,{resumeRequestId:rid})]);const after=await finished(f.jobs,before.id);assert.equal(after.completed,40);assert.equal(after.status,'completed');assert.equal(calls.get('p17'),2);assert.equal([...calls.values()].filter(n=>n===1).length,39);for(const p of before.pages)assert.deepEqual(after.pages.find(n=>n.id===p.id),p);
});
test('whole-deck exhausted budget opens a review round without regenerating any page',async t=>{
 let gen=0,reviews=0;const f=await fixture(t,async inp=>{gen++;return result(inp);},async inp=>{reviews++;if(reviews<4)throw Error('temporary review failure');return goodReview(inp);});
 const started=await f.jobs.start(input());let j=await finished(f.jobs,started.id);for(let i=0;i<3;i++){await f.jobs.resume(j.id,{resumeRequestId:randomUUID()});j=await finished(f.jobs,j.id);}assert.equal(j.status,'completed');assert.equal(reviews,4);assert.equal(j.deckReviewUsed,4);assert.equal(gen,1);
});
test('deleted task rejects replayed resume command',async t=>{const f=await fixture(t,async inp=>result(inp));const x=await f.jobs.start(input());await finished(f.jobs,x.id);await f.jobs.remove(x.id);await assert.rejects(f.jobs.resume(x.id,{resumeRequestId:randomUUID()}),e=>e.status===410);});
test('failed image request can be retried after service recovery without cache regeneration of successful pages',async t=>{
 let calls=0;const f=await fixture(t,async(inp,opts)=>{if(++calls===1){await opts.beforeStage('image');throw Object.assign(Error('provider auth unavailable'),{code:'PROVIDER_AUTH',imageCallFailed:true});}await opts.beforeStage('image');return result(inp);});const x=await f.jobs.start(input());await finished(f.jobs,x.id);await f.jobs.resume(x.id,{resumeRequestId:randomUUID()});const j=await finished(f.jobs,x.id);assert.equal(j.status,'completed');assert.equal(j.pageStatus[0].budget.used.image,2);
});

test('malformed round records cannot authorize work or overflow counters',()=>{
 const used={image:1,text:6,styleReview:1,pageRun:1},startedWith={...used},ceiling={image:3,text:12,styleReview:9,pageRun:7};
 for(const round of [{number:2,startedWith,ceiling},{number:2,requestId:randomUUID(),openedAt:new Date().toISOString(),startedWith,ceiling:{pageRun:7}}])assert.equal(pageLimit({used,round},'pageRun'),0);
 for(const extra of [{deckReviewUsed:-1},{deckReviewUsed:0,reviewRound:{number:2,requestId:randomUUID(),openedAt:new Date().toISOString(),startedWith:9,ceiling:12}},{deckReviewUsed:Number.MAX_SAFE_INTEGER,reviewRound:{number:2,requestId:randomUUID(),openedAt:new Date().toISOString(),startedWith:Number.MAX_SAFE_INTEGER,ceiling:Number.MAX_SAFE_INTEGER+3}}])assert.equal(deckLimit(extra),0);
});

test('modern shared-style stage pipeline preserves completed pages across an explicit round',async t=>{
 const calls=new Map();const f=await fixture(t,async(inp,opts)=>{const id=inp.targetPageIds[0],n=(calls.get(id)||0)+1;calls.set(id,n);if(id==='p17'&&n===1){await cache(opts,id);for(let i=0;i<7;i++)await opts.beforeStage('text');}return result(inp);},goodReview,{pipelined:true,sharedStyleFirst:true,stagePipeline:true,prepareStyle:async()=>({version:1})});
 const started=await f.jobs.start(input(40)),before=await finished(f.jobs,started.id);assert.equal(before.pipelineVersion,6);assert.equal(before.completed,39);await f.jobs.resume(before.id,{resumeRequestId:randomUUID()});const after=await finished(f.jobs,before.id);assert.equal(after.status,'completed');assert.equal(after.completed,40);assert.equal(calls.get('p17'),2);for(const p of before.pages)assert.deepEqual(after.pages.find(n=>n.id===p.id),p);
});
