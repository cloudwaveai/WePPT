import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runPlannedPagePipeline} from '../planned-page-pipeline.mjs';
import {createReferenceJobs} from '../reference-design-jobs.mjs';
import {planCompositions,compositionContext} from '../composition-planner.mjs';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const until=async fn=>{const end=Date.now()+10000;while(!await fn()){if(Date.now()>end)throw Error('condition timeout');await new Promise(r=>setTimeout(r,5));}};
const snap=ids=>({pages:ids.map(pageId=>({pageId})),targetPageIds:ids});
test('overlap, anchor gate, bounded workers, snapshots and dedup',async()=>{
 const anchor=deferred(),tail=deferred(),two=deferred();let anchored=false,active=0,max=0;const seen=[];
 const task=runPlannedPagePipeline({hasAnchor:()=>anchored,produce:async publish=>{publish(snap(['a','b','c']));await tail.promise;return snap(['a','b','c','d']);},draw:async(id,plan)=>{seen.push(id);active++;max=Math.max(max,active);assert(plan.targetPageIds.includes(id));if(id==='a'){await anchor.promise;anchored=true;}else await two.promise;active--;}});
 await until(()=>seen.length===1);assert.deepEqual(seen,['a']);anchor.resolve();await until(()=>seen.length===3);assert.equal(max,2);tail.resolve();two.resolve();await task;assert.deepEqual(seen,['a','b','c','d']);
});
for(const cancel of [false,true])test((cancel?'user cancel':'producer failure')+' drains blocked draw before settling',async()=>{
 const controller=new AbortController(),started=deferred(),abortSeen=deferred(),drain=deferred(),fail=deferred();let settled=false;
 const task=runPlannedPagePipeline({signal:controller.signal,hasAnchor:()=>false,produce:async publish=>{publish(snap(['a']));await fail.promise;if(!cancel)throw Error('producer broke');return snap(['a']);},draw:async(id,p,signal)=>{started.resolve();signal.addEventListener('abort',()=>abortSeen.resolve(),{once:true});await drain.promise;}}).finally(()=>{settled=true;});
 const outcome=assert.rejects(task,cancel?/cancelled/:/producer broke/);await started.promise;if(cancel)controller.abort(Error('cancelled'));fail.resolve();await abortSeen.promise;assert.equal(settled,false);drain.resolve();await outcome;
});
test('fatal consumer failure aborts producer and drains it',async()=>{
 const drained=deferred(),aborted=deferred();let settled=false;
 const task=runPlannedPagePipeline({hasAnchor:()=>true,produce:async(publish,signal)=>{publish(snap(['a']));signal.addEventListener('abort',()=>aborted.resolve(),{once:true});await drained.promise;signal.throwIfAborted();},draw:async()=>{throw Error('disk failure');}}).finally(()=>{settled=true;});
 const outcome=assert.rejects(task,/disk failure/);await aborted.promise;assert.equal(settled,false);drained.resolve();await outcome;
});
const project=()=>({id:'validator',themeId:'midnight',pages:Array.from({length:6},(_,i)=>({id:'p'+i,title:'Chapter '+i,body:'Source '+i,role:'chapter',objects:[]}))});
const ai=({prompt})=>({pages:JSON.parse(prompt.split('INPUT_JSON:\n')[1]).targetPageIds.map(pageId=>({pageId,pageJob:'Explain',relation:'section',composition:'chapter',geometrySignature:'same',readingPath:'top down',zones:[{purpose:'title',x:.1,y:.1,w:.8,h:.2}]}))});
const terminal=async(jobs,id)=>{let last;await until(async()=>{last=await jobs.get(id);return !['queued','running','cancelling'].includes(last.status);});return last;};
test('complete validated checkpoint with no publish callbacks draws only pending',async()=>{
 const drawn=[];await runPlannedPagePipeline({completedIds:['a'],hasAnchor:()=>true,produce:async()=>snap(['a','b','c']),draw:async id=>drawn.push(id)});assert.deepEqual(drawn,['b','c']);
});
for(const pipelined of [false,true])test((pipelined?'v3':'legacy')+' waits for full planning before review and full repair planning before redraw',async()=>{
 const dataDir=await mkdtemp(join(tmpdir(),'validator-pipeline-order-')),initialReady=deferred(),initialRelease=deferred(),repairReady=deferred(),repairRelease=deferred();let draws=0,reviews=0;
 const input={project:project()};
 const jobs=createReferenceJobs({dataDir,pipelined,plan:async(input,opts)=>{const result=await planCompositions(input,{...opts,structuredAI:async arg=>ai(arg)});if(input.repairFeedback){repairReady.resolve();await repairRelease.promise;}else{initialReady.resolve();await initialRelease.promise;}return result;},generate:async input=>{draws++;return {pages:[{...input.project.pages.find(p=>p.id===input.targetPageIds[0]),themeId:'midnight',objects:[{id:'shape',type:'rect'}]}]};},review:async({project})=>{reviews++;return reviews===1?{issues:[{pageId:'p0',severity:'error',kind:'layout',message:'repair one'}],summary:'fix',reviewEvidence:{status:'fail',checkedPageIds:project.pages.map(p=>p.id)}}:{issues:[],summary:'pass',reviewEvidence:{status:'pass',checkedPageIds:project.pages.map(p=>p.id)}};}});
 try{const started=await jobs.start(input);await initialReady.promise;if(pipelined)await until(()=>draws===6);else assert.equal(draws,0);assert.equal(reviews,0);initialRelease.resolve();await repairReady.promise;assert.equal(draws,6);assert.equal(reviews,1);repairRelease.resolve();const final=await terminal(jobs,started.id);assert.equal(final.status,'completed');assert.equal(final.pipelineVersion,pipelined?3:1);assert.equal(draws,7);assert.equal(reviews,2);}finally{initialRelease.resolve();repairRelease.resolve();await rm(dataDir,{recursive:true,force:true});}
});
test('real planner partial context, persisted-before-draw, restart resumes frozen checkpoint',async()=>{
 const dataDir=await mkdtemp(join(tmpdir(),'validator-pipeline-'));let id,drawn=[],calls=0,reviews=0;const first=deferred();const input={project:project()};const before=structuredClone(input);
 const generate=async input=>{const pageId=input.targetPageIds[0];const context=JSON.parse(compositionContext(input.project,[pageId]));assert(context.deckCompositions.some(p=>p.pageId===pageId));if(id){const saved=JSON.parse(await readFile(join(dataDir,'reference-jobs',id+'.json'),'utf8'));assert(saved.compositionCheckpoint.plan.pages.some(p=>p.pageId===pageId));}drawn.push(pageId);first.resolve();return {pages:[{...input.project.pages.find(p=>p.id===pageId),themeId:'midnight',objects:[{id:'shape',type:'rect'}]}]};};
 const review=async({project})=>{reviews++;return {issues:[],summary:'pass',reviewEvidence:{status:'pass',checkedPageIds:project.pages.map(p=>p.id)}};};
 try{
 const jobs=createReferenceJobs({dataDir,generate,review,plan:(input,opts)=>planCompositions(input,{...opts,structuredAI:async arg=>{calls++;if(calls===2){await first.promise;throw Object.assign(Error('forced planning failure'),{status:403});}return ai(arg);}})});
 id=(await jobs.start(input)).id;const failed=await terminal(jobs,id);assert.equal(failed.status,'failed');assert.equal(reviews,0);assert(failed.completed>0);assert.equal(failed.pipelineVersion,3);assert.deepEqual(input,before);
 const saved=JSON.parse(await readFile(join(dataDir,'reference-jobs',id+'.json'),'utf8'));assert.equal(saved.compositionPlan,undefined);const oldDrawn=[...drawn],oldCompleted=failed.pages.map(p=>p.id);let resumedCalls=0;
 const restarted=createReferenceJobs({dataDir,generate,review,plan:(input,opts)=>planCompositions(input,{...opts,structuredAI:async arg=>{resumedCalls++;return ai(arg);}})});
 await restarted.resume(id);const completed=await terminal(restarted,id);assert.equal(completed.status,'completed',JSON.stringify(completed));assert.equal(completed.completed,6);assert.equal(resumedCalls,1);assert.equal(reviews,1);for(const pageId of oldCompleted)assert.equal(drawn.filter(x=>x===pageId).length,oldDrawn.filter(x=>x===pageId).length);assert.deepEqual(input,before);
 }finally{await rm(dataDir,{recursive:true,force:true});}
});

