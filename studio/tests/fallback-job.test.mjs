import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';
import {createReferenceJobs} from '/app/reference-design-jobs.mjs';
const input=()=>({project:{id:'test-project',title:'测试',themeId:'curated-006',pages:[{id:'p1',title:'原文',body:'完整正文',objects:[],role:'content'}]},themeId:'curated-006',targetPageIds:['p1'],instruction:''});
async function fixture(t,generate,enabled=true){const dataDir=await mkdtemp(join(tmpdir(),'fallback-job-'));t.after(()=>rm(dataDir,{recursive:true,force:true}));return createReferenceJobs({dataDir,artworkFallbackEnabled:enabled,stagePipeline:false,sharedStyleFirst:false,pipelined:false,plan:async()=>({targetPageIds:['p1'],pages:[{pageId:'p1'}]}),generate,review:async({project})=>({issues:[],summary:'通过',reviewEvidence:{status:'pass',checkedPageIds:project.pages.map(p=>p.id)}})});}
async function finished(jobs,id){for(let i=0;i<400;i++){const j=await jobs.get(id);if(!['queued','running','cancelling'].includes(j.status))return j;await new Promise(r=>setTimeout(r,5));}throw Error('job did not finish');}
const success=inp=>({pages:inp.project.pages.map(p=>({...p,themeId:'curated-006',objects:[{id:'t',type:'text',text:p.title}],imageDesign:{artworkFallback:{mode:'raster-artwork'},editableText:true}}))});
test('quality failure falls back once and a transient failure resumes in persistent fallback mode',async t=>{
 const calls=[];const jobs=await fixture(t,async(inp,opts)=>{calls.push(!!opts.artworkFallback);if(calls.length===1)throw Object.assign(Error('图形拆分失败'),{code:'EDITABLE_ARTWORK_INVALID'});if(calls.length===2)throw Object.assign(Error('temporary'),{code:'ETIMEDOUT'});return success(inp);});
 const started=await jobs.start(input());const done=await finished(jobs,started.id);assert.equal(done.status,'completed');assert.deepEqual(calls,[false,true,true]);assert.equal(done.pageStatus[0].budget.used.pageRun,3);assert.equal(done.pages[0].body,'完整正文');assert.equal(done.pageStatus[0].budget.terminal,null);
});
for(const code of ['REFERENCE_SOURCE_INVALID','REFERENCE_BACKGROUND_TEXT','REFERENCE_PERSIST_FAILED'])test(`unsafe failure ${code} cannot enter fallback`,async t=>{
 const modes=[];const jobs=await fixture(t,async(_inp,opts)=>{modes.push(!!opts.artworkFallback);throw Object.assign(Error('controlled failure'),{code});});const started=await jobs.start(input());await finished(jobs,started.id);assert(modes.every(x=>!x));
});
test('fallback feature disabled preserves original quality failure',async t=>{const modes=[];const jobs=await fixture(t,async(_inp,opts)=>{modes.push(!!opts.artworkFallback);throw Object.assign(Error('图形拆分失败'),{code:'EDITABLE_ARTWORK_INVALID'});},false);const s=await jobs.start(input());const done=await finished(jobs,s.id);assert.equal(done.status,'failed');assert.deepEqual(modes,[false]);});
