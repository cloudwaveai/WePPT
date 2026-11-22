import test from 'node:test';
import assert from 'node:assert/strict';
import {designReferenceProject} from '../public/reference-design-pipeline.js';

const source=count=>({id:'reference-isolated',themeId:'old',designEngine:'svg',pages:Array.from({length:count},(_,i)=>({id:'p'+i,title:'第'+i+'页',body:'完整原文 '+i,objects:[],role:'content'}))});
const review=project=>({status:'checked',visionRan:true,repairRounds:0,issues:[],summary:'whole-deck reviewed',reviewEvidence:{status:'pass',checkedPageIds:project.pages.map(p=>p.id)}});
const completed=(project,ids=project.pages.map(p=>p.id))=>({designReview:review(project),status:'completed',total:ids.length,completed:ids.length,pages:project.pages.filter(p=>ids.includes(p.id)).map(p=>({...structuredClone(p),themeId:'chosen',designPending:true,objects:[{id:'t-'+p.id,type:'text',text:p.title,x:64,y:64,w:500,h:80,fontSize:40}]})),failures:[]});
const base={themeId:'chosen',pollIntervalMs:0};

for(const count of [10,30])test(`${count}-page generation applies exactly once after every page completes`,async()=>{
 const project=source(count),before=structuredClone(project),batches=[],progress=[],jobs=[];let polls=0;
 const result=await designReferenceProject(project,{...base,onJobStarted:id=>jobs.push(id),onBatchReady:batch=>batches.push(batch),onProgress:event=>progress.push(event.completed),request:async(path,input)=>{
  if(path.endsWith('/start')){assert.equal(input.project.pages.length,count);assert.equal(input.themeId,'chosen');assert.deepEqual(jobs,[input.clientRequestId]);return {id:input.clientRequestId,status:'queued',total:count,completed:0};}
  assert(path.endsWith('/status'));assert.equal(batches.length,0,'partial pages must never reach document commit');polls++;
  return polls<3?{status:'running',total:count,completed:polls,pages:completed(project).pages.slice(0,polls)}:completed(project);
 }});
 assert.deepEqual(project,before);assert.equal(jobs.length,1);assert.match(jobs[0],/^[a-f0-9-]{36}$/);assert.deepEqual(progress,[1,2,count]);assert.equal(batches.length,1);assert.equal(batches[0].pages.length,count);assert.deepEqual(batches[0].sources,before.pages);assert.deepEqual(batches[0].targetPageIds,before.pages.map(p=>p.id));assert(result.pages.every(p=>p.objects.length&&!p.designPending));assert.equal(result.designReview.visionRan,true);assert.equal(result.designReview.status,'checked');
});

test('subset completion preserves all unselected pages and original ordering',async()=>{
 const project=source(4),ids=['p3','p1'];let batch;
 const result=await designReferenceProject(project,{...base,jobId:'existing',targetPageIds:ids,onBatchReady:value=>batch=value,request:async()=>completed(project,ids)});
 assert.deepEqual(result.pages.map(p=>p.id),['p0','p1','p2','p3']);assert.deepEqual(result.pages[0],project.pages[0]);assert.deepEqual(result.pages[2],project.pages[2]);assert.deepEqual(batch.pages.map(p=>p.id),ids);
});

test('invalid completed responses never commit and retain the recovery job identifier',async()=>{
 const project=source(3);
 const mutations=[s=>s.pages.pop(),s=>s.pages[1].id='p0',s=>s.pages[0].id='other',s=>s.pages[0].themeId='wrong',s=>delete s.pages[0].themeId,s=>s.pages[0].title='改写',s=>s.pages[0].body+='丢失原文',s=>s.pages[0].objects=[],s=>s.total=4,s=>s.completed=2,s=>s.status='unknown'];
 for(const mutate of mutations){const state=completed(project);mutate(state);let commits=0;
  await assert.rejects(designReferenceProject(project,{...base,jobId:'recoverable',onBatchReady:()=>commits++,request:async()=>state}),error=>error.jobId==='recoverable');
  assert.equal(commits,0);
 }
});

for(const status of ['partial','failed','cancelled','interrupted'])test(`resuming a ${status} job keeps completed work on the server`,async()=>{
 const project=source(3),calls=[];let polls=0;
 const result=await designReferenceProject(project,{...base,jobId:'saved',request:async(path,input)=>{calls.push(path.split('/').at(-1));assert.equal(input.id,'saved');if(path.endsWith('/resume'))assert.match(input.resumeRequestId,/^[0-9a-f-]{36}$/);else assert.deepEqual(input,{id:'saved'});if(path.endsWith('/resume'))return {id:'saved',status:'queued',total:3,completed:1};return ++polls===1?{status,total:3,completed:1,pages:completed(project).pages.slice(0,1),failures:[]}:completed(project);}});
 assert.deepEqual(calls,['status','resume','status']);assert.equal(result.pages.length,3);
});

test('new job failure keeps partial pages out of the document and exposes actual failures',async()=>{
 const project=source(3),before=structuredClone(project);let commits=0,id;
 await assert.rejects(designReferenceProject(project,{...base,onJobStarted:value=>id=value,onBatchReady:()=>commits++,request:async(path,input)=>path.endsWith('/start')?{id:input.clientRequestId,status:'queued',total:3,completed:0}:{status:'failed',total:3,completed:1,pages:completed(project).pages.slice(0,1),failures:[{pageId:'p1',message:'timeout'}]}}),error=>error.jobId===id&&error.failures[0].message==='timeout');
 assert.equal(commits,0);assert.deepEqual(project,before);
});

test('aborting polling sends one cancellation request without the aborted signal',async()=>{
 const project=source(3),before=structuredClone(project),controller=new AbortController(),calls=[];let commits=0,id;
 await assert.rejects(designReferenceProject(project,{...base,signal:controller.signal,onJobStarted:value=>id=value,onProgress:()=>controller.abort(),onBatchReady:()=>commits++,request:async(path,input,signal)=>{calls.push(path.split('/').at(-1));if(path.endsWith('/cancel')){assert.equal(signal,undefined);assert.deepEqual(input,{id});return {};}
  return path.endsWith('/start')?{id:input.clientRequestId,status:'queued',total:3,completed:0}:{status:'running',total:3,completed:1,pages:completed(project).pages.slice(0,1)};
 }}),error=>error.name==='AbortError'&&error.jobId===id);
 assert.deepEqual(calls,['start','status','cancel']);assert.equal(commits,0);assert.deepEqual(project,before);
});

test('cancellation during creation waits for the known job and cancels it without orphaning',async()=>{
 const controller=new AbortController(),calls=[];let savedId,commits=0;
 await assert.rejects(designReferenceProject(source(2),{...base,signal:controller.signal,onJobStarted:id=>savedId=id,onBatchReady:()=>commits++,request:async(path,input,signal)=>{
  calls.push(path.split('/').at(-1));
  if(path.endsWith('/start')){
   assert.equal(input.clientRequestId,savedId);assert.notEqual(signal,controller.signal);assert(signal instanceof AbortSignal);
   controller.abort();await Promise.resolve();assert.equal(signal.aborted,false);assert.deepEqual(calls,['start']);
   return {id:input.clientRequestId,status:'queued',total:2,completed:0};
  }
  assert(path.endsWith('/cancel'));assert.deepEqual(input,{id:savedId});assert.equal(signal,undefined);return {};
 }}),error=>error.name==='AbortError'&&error.jobId===savedId);
 assert.deepEqual(calls,['start','cancel']);assert.equal(commits,0);
});

test('lost creation response retains a pre-saved recovery identifier',async()=>{
 let savedId;
 await assert.rejects(designReferenceProject(source(2),{...base,onJobStarted:id=>savedId=id,request:async(path,input)=>{assert.equal(input.clientRequestId,savedId);throw Error('network response lost');}}),error=>error.jobId===savedId&&/network response lost/.test(error.message));
 assert.match(savedId,/^[a-f0-9-]{36}$/);
});

test('a creation response cannot silently replace the client-owned job identifier',async()=>{
 let savedId,commits=0;
 await assert.rejects(designReferenceProject(source(2),{...base,onJobStarted:id=>savedId=id,onBatchReady:()=>commits++,request:async()=>({id:'unexpected-job',status:'queued',total:2,completed:0})}),error=>error.jobId===savedId&&/标识/.test(error.message));
 assert.equal(commits,0);
});

test('explicit recovery 404 recreates the exact original request using the same client identifier',async()=>{
 const project=source(3),calls=[],announced=[],ids=['p1','p2'],controller=new AbortController();let polls=0;
 const result=await designReferenceProject(project,{...base,jobId:'pre-saved-id',targetPageIds:ids,instruction:'参考原模板重新绘制',signal:controller.signal,onJobStarted:id=>announced.push(id),request:async(path,input,signal)=>{
  calls.push(path.split('/').at(-1));
  if(path.endsWith('/status')){assert.deepEqual(input,{id:'pre-saved-id'});if(++polls===1)throw Object.assign(Error('missing'),{status:404});return completed(project,ids);}
  assert(path.endsWith('/start'));assert.deepEqual(input,{clientRequestId:'pre-saved-id',project,themeId:'chosen',targetPageIds:ids,instruction:'参考原模板重新绘制'});assert.notEqual(signal,controller.signal);
  return {id:input.clientRequestId,status:'queued',completed:0,total:2};
 }});
 assert.deepEqual(calls,['status','start','status']);assert.deepEqual(announced,['pre-saved-id']);assert.equal(result.pages[1].themeId,'chosen');assert.deepEqual(result.pages[0],project.pages[0]);
});

test('persistent 503 and untyped failures retain the saved task without recreation',async()=>{
 for(const failure of [Object.assign(Error('service unavailable'),{status:503}),Error('connection lost')]){
  const calls=[];
  await assert.rejects(designReferenceProject(source(2),{...base,jobId:'known-id',request:async path=>{calls.push(path.split('/').at(-1));throw failure;}}),error=>error.jobId==='known-id'&&(failure.status===503?error.code==='REFERENCE_CONNECTION_LOST'&&error.cause===failure:error===failure));
  assert.deepEqual(calls,Array(failure.status===503?4:1).fill('status'));
 }
});

test('already aborted invocation does not create a remote job',async()=>{
 const controller=new AbortController();controller.abort();let calls=0;
 await assert.rejects(designReferenceProject(source(1),{...base,signal:controller.signal,request:async()=>calls++}),{name:'AbortError'});assert.equal(calls,0);
});

test('cancelling status is polled until cancellation completes without applying partial pages',async()=>{
 const project=source(3),calls=[];let commits=0,polls=0;
 await assert.rejects(designReferenceProject(project,{...base,jobId:'stopping',onBatchReady:()=>commits++,onProgress:event=>calls.push(event.message),request:async()=>({status:++polls===1?'cancelling':'cancelled',message:'正在停止任务',total:3,completed:1,pages:completed(project).pages.slice(0,1)})}),error=>error.jobId==='stopping'&&/已取消/.test(error.message));
 assert.equal(polls,2);assert.equal(commits,0);assert.match(calls[0],/正在停止任务/);
});

test('whole-deck review is retained independently of per-page style metadata',async()=>{
 const project=source(3);
 for(const checked of [0,1,3]){
  const state=completed(project);state.pages.forEach((page,index)=>page.referenceDesign={visualChecked:index<checked});
  const result=await designReferenceProject(project,{...base,jobId:'visual',request:async()=>state});
  assert.deepEqual(result.designReview,state.designReview);assert.equal(result.designReview.visionRan,true);
  result.designReview.summary='mutated';assert.equal(state.designReview.summary,'whole-deck reviewed');
 }
});

test('missing, failed, incomplete or error-bearing whole-deck review never applies completed pages',async()=>{
 const project=source(3);
 for(const change of [s=>delete s.designReview,s=>s.designReview.status='pending',s=>s.designReview.reviewEvidence.status='fail',s=>s.designReview.reviewEvidence.checkedPageIds=['p0','p1'],s=>s.designReview.issues=[{severity:'error',message:'repeat'}]]){
  const state=completed(project);change(state);let commits=0;
  await assert.rejects(designReferenceProject(project,{...base,jobId:'visual',onBatchReady:()=>commits++,request:async()=>state}),/视觉检查/);
  assert.equal(commits,0);
 }
});

test('structured planning counts and real phases reach UI without counting planned pages as generated',async()=>{
 const project=source(15),events=[];let calls=0;
 const states=[{status:'running',phase:'planning',planned:5,completed:0},{status:'running',phase:'designing',planned:15,completed:0},{status:'running',phase:'reviewing',planned:15,completed:15},{status:'failed',phase:'reviewing',planned:15,completed:15,message:'整稿检查未通过'}];
 await assert.rejects(designReferenceProject(project,{...base,jobId:'saved',onProgress:e=>events.push(e),request:async()=>({...states[Math.min(calls++,3)],total:15,pages:[],failures:[]})}),/整稿检查未通过/);
 assert.deepEqual(events.map(e=>[e.planned,e.completed,e.generationPhase]),[[5,0,'planning'],[15,0,'designing'],[15,15,'reviewing'],[15,15,'reviewing']]);
});

test('running pre-upgrade workers expose only validated checkpoint progress without a restart',async()=>{
 const project=source(15),events=[];let calls=0;
 const states=[{phase:'planning',message:'已规划 5 / 15 页，正在规划接下来的 5 页'}, {phase:'planning',message:'已规划 99 / 15 页'}, {phase:'planning',message:'已规划 10 / 25 页'}, {phase:'designing',message:'正在按共享构图计划逐页设计'}, {status:'failed',phase:'designing',message:'页面检查失败'}];
 await assert.rejects(designReferenceProject(project,{...base,jobId:'saved',onProgress:e=>events.push(e),request:async()=>({status:'running',...states[Math.min(calls++,4)],total:15,completed:0,pages:[],failures:[]})}),/页面检查失败/);
 assert.deepEqual(events.map(e=>e.planned),[5,5,5,15,15]);assert(events.every(e=>e.completed===0));
});
