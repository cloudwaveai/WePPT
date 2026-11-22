import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile,writeFile,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';
import {createReferenceJobs} from '../reference-design-jobs.mjs';
import {planCompositions} from '../composition-planner.mjs';
const planner=async input=>({version:1,targetPageIds:[...input.targetPageIds],pages:input.targetPageIds.map(pageId=>({pageId,composition:'planned '+pageId}))});
const reviewer=async({project})=>({issues:[],summary:'controlled whole-deck review',reviewEvidence:{status:'pass',checkedPageIds:project.pages.map(p=>p.id)}});
const jobsFor=options=>createReferenceJobs({plan:planner,review:reviewer,prepareStyle:async()=>({}),retryDelayMs:0,pipelined:false,sharedStyleFirst:false,stagePipeline:false,...options});
const project=()=>({id:'source',revision:4,themeId:'curated-006',pages:Array.from({length:4},(_,i)=>({id:'p'+i,title:'标题'+i,body:'原文'+i,role:i?'content':'cover',objects:[]}))});
const output=input=>({pages:input.project.pages.filter(p=>input.targetPageIds.includes(p.id)).map(p=>({...p,themeId:input.themeId,objects:[{id:'t-'+p.id,type:'text',text:p.title}],referenceDesign:{templateId:input.themeId}}))});
async function fixture(fn){const dataDir=await mkdtemp(join(tmpdir(),'reference-job-'));try{await fn(dataDir);}finally{await rm(dataDir,{recursive:true,force:true});}}
async function finish(jobs,id){for(let n=0;n<300;n++){const job=await jobs.get(id);if(!['queued','running','cancelling'].includes(job.status))return job;await delay(5);}throw Error('job did not finish');}
test('first page anchors later parallel work; immutable source and ordered complete result',()=>fixture(async dataDir=>{
 const source=project(),before=structuredClone(source),seen=[];let active=0,max=0;
 const jobs=jobsFor({dataDir,generate:async(input,{onProgress})=>{active++;max=Math.max(active,max);seen.push(structuredClone(input));onProgress('image','drawing');await delay(input.targetPageIds[0]==='p1'?20:5);active--;return output(input);}});
 const started=await jobs.start({project:source});source.pages[0].body='concurrent edit';const result=await finish(jobs,started.id);
 assert.equal(result.status,'completed');assert.equal(result.completed,4);assert.equal(max,2);assert.deepEqual(result.pages.map(p=>p.id),['p0','p1','p2','p3']);assert.equal(result.pages[0].body,before.pages[0].body);assert.deepEqual(seen[0].styleAnchorIds,[]);
 for(const call of seen.slice(1)){assert(call.styleAnchorIds.includes('p0'));assert(call.project.pages[0].objects.length);assert.equal(call.referenceMode,true);assert.equal(call.singlePass,true);}
 assert.equal(result.sourceRevision,4);assert.equal('input'in result,false);assert.deepEqual((await readdir(dataDir)).sort(),['reference-jobs']);
 result.pages[0].title='mutated response';assert.notEqual((await jobs.get(result.id)).pages[0].title,'mutated response');
}));
test('two failures do not block other pages; resume only missing pages and preserves completed ones',()=>fixture(async dataDir=>{
 let fail=true;const calls=[];const jobs=jobsFor({dataDir,generate:async input=>{const id=input.targetPageIds[0];calls.push(id);if(id==='p1'&&fail)throw new DOMException('bad /app/private/model.json','TimeoutError');return output(input);}});
 const started=await jobs.start({project:project()}),partial=await finish(jobs,started.id);assert.equal(partial.status,'partial');assert.equal(partial.completed,3);assert.equal(calls.filter(id=>id==='p1').length,2);assert.equal(partial.failures.length,1);assert(!JSON.stringify(partial).includes('/app/private'));
 const completed=structuredClone(partial.pages);calls.length=0;fail=false;await jobs.resume(started.id);const full=await finish(jobs,started.id);assert.equal(full.status,'completed');assert.deepEqual(calls,['p1']);assert.equal(full.failures.length,0);for(const page of completed)assert.deepEqual(full.pages.find(p=>p.id===page.id),page);
}));
test('cancel waits for active generation to unwind, never accepts late result, releases slot',()=>fixture(async dataDir=>{
 let entered,cleaned=false;const began=new Promise(resolve=>entered=resolve);
 const jobs=jobsFor({dataDir,generate:async(input,{signal})=>{entered();await new Promise(resolve=>signal.addEventListener('abort',()=>setTimeout(()=>{cleaned=true;resolve();},20),{once:true}));return output(input);}});
 const first=await jobs.start({project:project()});await began;await assert.rejects(jobs.start({project:project()}),e=>e.status===409);const stopped=await jobs.cancel(first.id);assert(cleaned);assert.equal(stopped.status,'cancelled');assert.equal(stopped.completed,0);assert.equal(stopped.pageStatus[0].status,'pending');
 const next=await jobs.start({project:project()});await delay(5);await jobs.cancel(next.id);
}));
test('startup recovers running checkpoint as interrupted; resumes remaining original snapshot',()=>fixture(async dataDir=>{
 const jobs=jobsFor({dataDir,generate:async input=>output(input)}),first=await jobs.start({project:project()}),done=await finish(jobs,first.id),path=join(dataDir,'reference-jobs',first.id+'.json');
 const stored=JSON.parse(await readFile(path,'utf8'));stored.status='running';stored.pages=stored.pages.slice(0,1);stored.pageStatus.slice(1).forEach(s=>s.status='running');await writeFile(path,JSON.stringify(stored));const calls=[];
 const restored=jobsFor({dataDir,generate:async input=>{calls.push(input.targetPageIds[0]);return output(input);}});assert.equal((await restored.get(first.id)).status,'interrupted');await restored.resume(first.id);const recovered=await finish(restored,first.id);assert.equal(recovered.status,'completed');assert.deepEqual(calls.sort(),['p1','p2','p3']);assert.deepEqual(recovered.pages,done.pages);
}));
test('strict IDs, page bounds and source changes rejected',()=>fixture(async dataDir=>{
 const jobs=jobsFor({dataDir,generate:async input=>{const result=output(input);result.pages[0].body='changed';return result;}});
 for(const id of ['../escape','a','00000000-0000-0000-0000-000000000000'])await assert.rejects(jobs.get(id),e=>e.status===400);
 await assert.rejects(jobs.start({project:{...project(),pages:Array(101).fill(project().pages[0])}}));await assert.rejects(jobs.start({project:project(),targetPageIds:['missing']}));await assert.rejects(jobs.start({project:project(),targetPageIds:['p0','p0']}));
 const first=await jobs.start({project:project(),targetPageIds:['p0']});const failed=await finish(jobs,first.id);assert.equal(failed.status,'failed');assert.equal(failed.pages.length,0);assert.equal(failed.failures[0].attempts,1);
}));
test('failed first page does not stop deck; first successful page becomes the anchor',()=>fixture(async dataDir=>{
 const calls=[];const jobs=jobsFor({dataDir,generate:async input=>{calls.push(structuredClone(input));if(input.targetPageIds[0]==='p0')throw new DOMException('first page failed','TimeoutError');return output(input);}});
 const first=await jobs.start({project:project()}),result=await finish(jobs,first.id);assert.equal(result.status,'partial');assert.equal(result.completed,3);assert.deepEqual(calls.slice(0,3).map(c=>c.targetPageIds[0]),['p0','p0','p1']);for(const call of calls.slice(3))assert.deepEqual(call.styleAnchorIds,['p1']);
}));
test('custom object removal is rejected without mutating input or publishing a page',()=>fixture(async dataDir=>{
 const source=project();source.pages[0].objects=[{id:'logo',type:'rect',custom:true,x:1,y:2,w:3,h:4}];const before=structuredClone(source);
 const jobs=jobsFor({dataDir,generate:async input=>output(input)});const first=await jobs.start({project:source,targetPageIds:['p0']});const result=await finish(jobs,first.id);assert.equal(result.status,'failed');assert.equal(result.completed,0);assert.match(result.failures[0].message,/自定义对象/);assert.deepEqual(source,before);
}));
test('client request IDs make concurrent starts idempotent and reject changed payloads',()=>fixture(async dataDir=>{
 let calls=0;const jobs=jobsFor({dataDir,generate:async input=>{calls++;await delay(10);return output(input);}});
 const input={project:project(),targetPageIds:['p0'],instruction:'原要求',clientRequestId:randomUUID()};
 const [first,second]=await Promise.all([jobs.start(input),jobs.start(structuredClone(input))]);assert.equal(first.id,input.clientRequestId);assert.equal(second.id,first.id);
 for(const update of [{instruction:'新要求'},{themeId:'curated-007'},{targetPageIds:['p1']},{project:{...input.project,title:'different'}}])await assert.rejects(jobs.start({...input,...update}),e=>e.status===409);
 const done=await finish(jobs,first.id);assert.equal(done.status,'completed');assert.equal(calls,1);
 const restored=jobsFor({dataDir,generate:async()=>{throw Error('must not regenerate');}});const again=await restored.start(input);assert.equal(again.id,first.id);assert.equal(again.status,'completed');assert.deepEqual(again.pages,done.pages);
 for(const clientRequestId of ['../escape','not-uuid',null,123])await assert.rejects(jobs.start({project:project(),clientRequestId}),e=>e.status===400);
}));
test('wrong theme result is rejected and never checkpointed as completed',()=>fixture(async dataDir=>{
 const jobs=jobsFor({dataDir,generate:async input=>{const result=output(input);result.pages[0].themeId='curated-007';return result;}});
 const first=await jobs.start({project:project(),targetPageIds:['p0']}),failed=await finish(jobs,first.id);assert.equal(failed.status,'failed');assert.equal(failed.completed,0);assert.equal(failed.failures[0].attempts,1);assert.match(failed.failures[0].message,/参考风格/);
}));

test('planning runs once before generation and each worker receives its own shared plan snapshot',()=>fixture(async dataDir=>{
 const events=[],plans=[],received=[];let saved;
 const jobs=jobsFor({dataDir,plan:async input=>{events.push('plan');plans.push(structuredClone(input));saved=await planner(input);return saved;},generate:async input=>{events.push(input.targetPageIds[0]);received.push(structuredClone(input.project.compositionPlan));input.project.compositionPlan.pages[0].composition='mutated worker copy';return output(input);}});
 const started=await jobs.start({project:project()}),result=await finish(jobs,started.id);
 assert.equal(result.status,'completed');assert.equal(plans.length,1);assert.equal(events[0],'plan');assert.deepEqual(plans[0].targetPageIds,['p0','p1','p2','p3']);
 for(const value of received)assert.deepEqual(value,saved);
 assert.equal(result.designReview.status,'checked');assert.equal(result.designReview.repairRounds,0);
}));

test('planning failure prevents generation and retains retryable job without false completion',()=>fixture(async dataDir=>{
 let generated=0,reviewed=0;const jobs=jobsFor({dataDir,plan:async()=>{throw Error('planning failed');},generate:async()=>generated++,review:async()=>reviewed++});
 const started=await jobs.start({project:project()}),result=await finish(jobs,started.id);
 assert.equal(result.status,'failed');assert.equal(result.completed,0);assert.equal(generated,0);assert.equal(reviewed,0);assert.match(result.message,/planning failed/);
}));

for(const mode of ['failed','incomplete'])test(`${mode} whole-deck review cannot mark generated pages completed`,()=>fixture(async dataDir=>{
 let count=0;const jobs=jobsFor({dataDir,generate:async input=>output(input),review:async({project})=>{count++;return {issues:[],summary:'not accepted',reviewEvidence:{status:mode==='failed'?'fail':'pass',checkedPageIds:project.pages.slice(0,mode==='incomplete'?1:4).map(p=>p.id)}};}});
 const started=await jobs.start({project:project()}),result=await finish(jobs,started.id);
 assert.equal(result.status,'partial');assert.equal(result.completed,4);assert.equal(result.designReview.status,'needs-attention');assert.equal(count,1);
}));

test('only flagged target pages repair, at most twice, and every repair is reviewed again',()=>fixture(async dataDir=>{
 const generated=[],planned=[],reviews=[],repairInputs=[];
 const jobs=jobsFor({dataDir,plan:async input=>{planned.push(structuredClone(input));return planner(input);},generate:async input=>{generated.push(input.targetPageIds[0]);repairInputs.push(structuredClone(input));return output(input);},review:async input=>{reviews.push(structuredClone(input.project));return {issues:[{pageId:'p1',severity:'error',kind:'text-overflow',message:'Clipped body text on p1'}],summary:'repeat',reviewEvidence:{status:'fail',checkedPageIds:input.project.pages.map(p=>p.id)}};}});
 const started=await jobs.start({project:project()}),result=await finish(jobs,started.id);
 assert.equal(result.status,'partial');assert.equal(result.designReview.repairRounds,2);assert.equal(reviews.length,3);assert.deepEqual(planned.map(p=>p.targetPageIds),[['p0','p1','p2','p3']]);
 assert.equal(generated.filter(id=>id==='p1').length,3);for(const id of ['p0','p2','p3'])assert.equal(generated.filter(p=>p===id).length,1);
 for(const p of repairInputs.slice(4))assert.match(p.textRepairFeedback,/Clipped body text/);
 assert.equal(result.pages.length,4);assert.equal(new Set(result.pages.map(p=>p.id)).size,4);
}));

test('successful repair becomes completed only after a subsequent passing full review',()=>fixture(async dataDir=>{
 let calls=0;const jobs=jobsFor({dataDir,generate:async input=>output(input),review:async input=>++calls===1?{issues:[{pageId:'p2',severity:'error',kind:'readability',message:'Clipped text'}],summary:'repair required',reviewEvidence:{status:'fail',checkedPageIds:input.project.pages.map(p=>p.id)}}:reviewer(input)});
 const started=await jobs.start({project:project()}),result=await finish(jobs,started.id);
 assert.equal(result.status,'completed');assert.equal(calls,2);assert.equal(result.designReview.repairRounds,1);assert.equal(result.pageStatus.find(p=>p.pageId==='p2').attempts,2);
 assert.equal(result.planned,4,'a one-page repair must not replace the full-deck planned count');
 const restored=jobsFor({dataDir,generate:async()=>{throw Error('read-only recovery must not generate');}});
 assert.equal((await restored.get(started.id)).planned,4,'planned count survives a fresh manager after repair');
}));

test('cancelling review preserves all pages and resume reruns review without regenerating healthy pages',()=>fixture(async dataDir=>{
 let entered,reviewCalls=0,generateCalls=0,planCalls=0;const began=new Promise(resolve=>entered=resolve);
 const jobs=jobsFor({dataDir,plan:async input=>{planCalls++;return planner(input);},generate:async input=>{generateCalls++;return output(input);},review:async(input,{signal})=>{reviewCalls++;if(reviewCalls===1){entered();await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));}return reviewer(input);}});
 const started=await jobs.start({project:project()});await began;const stopped=await jobs.cancel(started.id);
 assert.equal(stopped.status,'cancelled');assert.equal(stopped.completed,4);assert.notEqual(stopped.designReview?.status,'checked');
 await jobs.resume(started.id,{resumeRequestId:randomUUID()});const result=await finish(jobs,started.id);assert.equal(result.status,'completed');assert.equal(generateCalls,4);assert.equal(planCalls,1);assert.equal(reviewCalls,2);assert.deepEqual(result.pages,stopped.pages);
}));

test('subset repair cannot change unselected pages or custom objects and review sees the full ordered deck',()=>fixture(async dataDir=>{
 const source=project();source.pages.forEach(p=>p.objects=[{id:'custom-'+p.id,type:'rect',custom:true,x:100,y:100,w:50,h:50}]);const before=structuredClone(source),seen=[];let reviewCalls=0;
 const jobs=jobsFor({dataDir,generate:async input=>{seen.push(input.targetPageIds[0]);const result=output(input);result.pages[0].objects.push(...structuredClone(input.project.pages.find(p=>p.id===input.targetPageIds[0]).objects.filter(o=>o.custom)));return result;},review:async input=>{
  assert.deepEqual(input.project.pages.map(p=>p.id),before.pages.map(p=>p.id));for(const i of [0,2,3])assert.deepEqual(input.project.pages[i],before.pages[i]);
  assert.deepEqual(input.project.pages[1].objects.find(o=>o.custom),before.pages[1].objects[0]);reviewCalls++;
  return {issues:[{pageId:'p3',severity:'error',kind:'repetition',message:'Unselected page must not be changed'}],summary:'outside scope',reviewEvidence:{status:'fail',checkedPageIds:before.pages.map(p=>p.id)}};
 }});
 const started=await jobs.start({project:source,targetPageIds:['p1']}),result=await finish(jobs,started.id);
 assert.equal(result.status,'partial');assert.deepEqual(seen,['p1']);assert.equal(reviewCalls,1);assert.deepEqual(source,before);assert.deepEqual(result.pages[0].objects.find(o=>o.custom),before.pages[1].objects[0]);
}));

for(const legacyReview of ['absent','incomplete'])test(`legacy completed checkpoint with ${legacyReview} full-deck review resumes verification without regenerating pages`,()=>fixture(async dataDir=>{
 const original=jobsFor({dataDir,generate:async input=>output(input)}),first=await original.start({project:project()}),done=await finish(original,first.id),path=join(dataDir,'reference-jobs',first.id+'.json');
 const stored=JSON.parse(await readFile(path,'utf8'));delete stored.compositionPlan;
 if(legacyReview==='absent')delete stored.designReview;else stored.designReview.reviewEvidence.checkedPageIds=['p0'];
 await writeFile(path,JSON.stringify(stored));let planCalls=0,reviewCalls=0,generateCalls=0;
 const restored=jobsFor({dataDir,plan:async input=>{planCalls++;return planner(input);},generate:async()=>{generateCalls++;throw Error('must not regenerate saved pages');},review:async input=>{reviewCalls++;return reviewer(input);}});
 const recoverable=await restored.get(first.id);assert.equal(recoverable.status,'interrupted');assert.equal(recoverable.completed,4);assert.match(recoverable.message,/补做整稿视觉复核/);
 await restored.resume(first.id);const checked=await finish(restored,first.id);
 assert.equal(checked.status,'completed');assert.equal(checked.designReview.status,'checked');assert.equal(planCalls,1);assert.equal(reviewCalls,1);assert.equal(generateCalls,0);assert.deepEqual(checked.pages,done.pages);
}));

test('6000-character user instruction and repair findings remain complete in independent fields through planning and generation',()=>fixture(async dataDir=>{
 const instruction='完整要求'.repeat(1499)+'末尾保留',feedback='必须调整第二页的中央分区并保留最终标记',planned=[],generated=[];assert.equal(instruction.length,6000);let reviews=0;
 const jobs=jobsFor({dataDir,plan:async input=>{planned.push(structuredClone(input));return planner(input);},generate:async input=>{generated.push(structuredClone(input));return output(input);},review:async input=>++reviews===1?{issues:[{pageId:'p1',kind:'readability',severity:'error',message:feedback}],summary:'repair',reviewEvidence:{status:'fail',checkedPageIds:input.project.pages.map(p=>p.id)}}:reviewer(input)});
 const started=await jobs.start({project:project(),instruction}),result=await finish(jobs,started.id);assert.equal(result.status,'completed');assert.equal(planned.length,1);assert.equal(generated.length,5);
 for(const input of [...planned,...generated])assert.equal(input.instruction,instruction);
 assert.equal(planned[0].repairFeedback,'');assert(generated.at(-1).textRepairFeedback.includes(feedback));
}));

const sixPageProject=()=>({...project(),pages:Array.from({length:6},(_,i)=>({id:'p'+i,title:'标题'+i,body:'完整内容'+i,role:'content',objects:[]}))});
const batchInput=prompt=>JSON.parse(prompt.split('INPUT_JSON:\n')[1]);
const uniqueComposition=pageId=>({pageId,pageJob:'Explain',relation:'sequence',composition:'Content focal zone '+pageId,geometrySignature:'unique '+pageId,readingPath:'top to bottom',zones:[{purpose:'content',x:Number(pageId.slice(1))*.14,y:.1,w:.1,h:.7}]});

test('persisted planning batch and real progress survive failure and fresh-manager resume without discarding confirmed plans',()=>fixture(async dataDir=>{
 let release,entered;const gate=new Promise(r=>release=r),began=new Promise(r=>entered=r),calls=[];let generationCalls=0;
 const first=jobsFor({dataDir,plan:(input,options)=>planCompositions(input,{...options,structuredAI:async({prompt})=>{const context=batchInput(prompt);calls.push(context.targetPageIds);if(calls.length===2){entered();await gate;throw Error('provider temporarily unavailable');}return {pages:context.targetPageIds.map(uniqueComposition)};}}),generate:async input=>{generationCalls++;return output(input);}});
 const started=await first.start({project:sixPageProject()});await began;
 const running=await first.get(started.id);assert.equal(running.phase,'planning');assert.equal(running.completed,0);assert.equal(running.planned,5);assert.match(running.message,/已规划 5 \/ 6 页/);assert.equal(generationCalls,0);
 const file=join(dataDir,'reference-jobs',started.id+'.json'),saved=JSON.parse(await readFile(file,'utf8'));assert.equal(saved.compositionCheckpoint.plan.pages.length,5);assert.deepEqual(saved.compositionCheckpoint.plan.pages.map(p=>p.pageId),['p0','p1','p2','p3','p4']);
 release();const failed=await finish(first,started.id);assert.equal(failed.status,'failed');assert.equal(failed.completed,0);assert.equal(failed.planned,5);
 let received;const resumedCalls=[];
 const restored=jobsFor({dataDir,plan:(input,options)=>{received=structuredClone(options.checkpoint);return planCompositions(input,{...options,structuredAI:async({prompt})=>{const c=batchInput(prompt);resumedCalls.push(c.targetPageIds);assert.equal(c.confirmedPlans.length,5);return {pages:c.targetPageIds.map(uniqueComposition)};}});},generate:async input=>{generationCalls++;return output(input);}});
 await restored.resume(started.id);const completed=await finish(restored,started.id);assert.equal(completed.status,'completed');assert.equal(completed.planned,6);assert.deepEqual(received,saved.compositionCheckpoint);assert.deepEqual(resumedCalls,[['p5']]);assert.equal(generationCalls,6);
}));

test('cancelling planning retains durable completed batch and never starts image generation',()=>fixture(async dataDir=>{
 let entered;const began=new Promise(r=>entered=r);let modelCalls=0,generationCalls=0;
 const jobs=jobsFor({dataDir,plan:(input,options)=>planCompositions(input,{...options,structuredAI:async({prompt},{signal})=>{const c=batchInput(prompt);if(++modelCalls===2){entered();await new Promise(r=>signal.addEventListener('abort',r,{once:true}));signal.throwIfAborted();}return {pages:c.targetPageIds.map(uniqueComposition)};}}),generate:async input=>{generationCalls++;return output(input);}});
 const started=await jobs.start({project:sixPageProject()});await began;const cancelled=await jobs.cancel(started.id);assert.equal(cancelled.status,'cancelled');assert.equal(cancelled.completed,0);assert.equal(generationCalls,0);assert.equal(modelCalls,2);
 const saved=JSON.parse(await readFile(join(dataDir,'reference-jobs',started.id+'.json'),'utf8'));assert.equal(saved.compositionCheckpoint.plan.pages.length,5);assert.equal(saved.compositionPlan,undefined);
}));

test('new text repair targets retain original composition and receive their own findings',()=>fixture(async dataDir=>{
 const received=[],repairInputs=[];let reviewCalls=0;
 const jobs=jobsFor({dataDir,plan:async(input,options)=>{received.push({input:structuredClone(input),checkpoint:options.checkpoint});const value=await planner(input);await options.onCheckpoint({marker:input.targetPageIds.join(','),feedback:input.repairFeedback});return value;},generate:async input=>{repairInputs.push(structuredClone(input));return output(input);},review:async input=>{reviewCalls++;return reviewCalls<=2?{issues:[{pageId:reviewCalls===1?'p1':'p2',severity:'error',kind:'readability',message:'修复原因'+reviewCalls}],summary:'needs repair',reviewEvidence:{status:'fail',checkedPageIds:input.project.pages.map(p=>p.id)}}:reviewer(input);}});
 const started=await jobs.start({project:project()}),result=await finish(jobs,started.id);assert.equal(result.status,'completed');assert.equal(received.length,1);assert.equal(received[0].checkpoint,undefined);assert.deepEqual(repairInputs.slice(4).map(x=>x.targetPageIds),[['p1'],['p2']]);assert.match(repairInputs[4].textRepairFeedback,/修复原因1/);assert.match(repairInputs[5].textRepairFeedback,/修复原因2/);
}));

test('repeated text findings preserve composition and re-review each bounded repair',()=>fixture(async dataDir=>{
 let plans=0,generated=0,reviews=0;
 const jobs=jobsFor({dataDir,plan:(input,options)=>planCompositions(input,{...options,structuredAI:async({prompt})=>{plans++;return {pages:batchInput(prompt).targetPageIds.map(uniqueComposition)};}}),generate:async input=>{const result=output(input);result.pages[0].objects[0].x=++generated;return result;},review:async input=>{reviews++;return {issues:[{pageId:'p1',severity:'error',kind:'readability',message:'相同反馈仍未解决'}],summary:'needs repair',reviewEvidence:{status:'fail',checkedPageIds:input.project.pages.map(p=>p.id)}};}});
 const started=await jobs.start({project:project()}),result=await finish(jobs,started.id);assert.equal(result.status,'partial');assert.equal(result.designReview.repairRounds,2);assert.equal(plans,1);assert.equal(reviews,3);assert.equal(generated,6);assert.doesNotMatch(result.message,/断点已过期/);
}));

test('staged jobs expedite the first target and cached fallback drawing, then perform the full review', async t => fixture(async dataDir => {
  const {stageScheduler} = await import('../stage-pipeline.mjs');
  const observed = [];
  const firstInspection = Promise.withResolvers();
  const run = stageScheduler.run;
  t.mock.method(stageScheduler, 'run', async (stage, work, options) => {
    const result = await run(stage, work, options);
    if (result?.testPage) observed.push([result.testPage, stage, options.prefer]);
    return result;
  });

  const source = project();
  source.pages = source.pages.slice(0, 2);
  const jobs = jobsFor({
    dataDir, sharedStyleFirst: true, stagePipeline: true, artworkFallbackEnabled: true,
    generate: async (input, options) => {
      const id = input.targetPageIds[0];
      if (id === 'p0') await firstInspection.promise;
      if (id === 'p0' && !options.artworkFallback) {
        throw Object.assign(Error('fixture requests source-image fallback'), {code: 'EDITABLE_ARTWORK_INVALID'});
      }
      await options.runStage('drawing', () => ({testPage: id}), options.signal);
      await options.runStage('inspection', () => ({testPage: id}), options.signal);
      if (id === 'p1') firstInspection.resolve();
      return output(input);
    },
  });
  // A selected range can start with a page other than the first in the document.
  const started = await jobs.start({project: source, targetPageIds: ['p1', 'p0']});
  const result = await finish(jobs, started.id);
  assert.equal(result.status, 'completed');
  assert.equal(result.designReview.reviewEvidence.status, 'pass');
  assert.deepEqual(result.pages.map(p => p.id), ['p1', 'p0']);
  assert.deepEqual(observed.filter(x => x[0] === 'p1'), [['p1','drawing',true], ['p1','inspection',true]]);
  assert.deepEqual(observed.filter(x => x[0] === 'p0'), [['p0','drawing',true], ['p0','inspection',false]]);
}));
