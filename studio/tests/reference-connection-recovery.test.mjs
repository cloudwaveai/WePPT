import test from 'node:test';
import assert from 'node:assert/strict';
import {designReferenceProject} from '../public/reference-design-pipeline.js';

const project={id:'isolated',themeId:'chosen',pages:[{id:'p1',title:'完整标题',body:'原始正文。',role:'content',objects:[]}]};
const running={id:'saved',status:'running',phase:'designing',completed:0,planned:1,total:1,pages:[]};
const done={...running,status:'completed',completed:1,pages:[{...project.pages[0],themeId:'chosen',objects:[{id:'text',type:'text',text:'完整标题'}]}],designReview:{status:'checked',issues:[],reviewEvidence:{status:'pass',checkedPageIds:['p1']}}};
const options={jobId:'saved',pollIntervalMs:0};
const http=status=>Object.assign(Error('HTTP '+status),{status});

for(const failure of [new TypeError('Failed to fetch'),new DOMException('timeout','TimeoutError'),...[408,429,500,502,503,504].map(http)]){
 test(`one transient ${failure.status||failure.name} status failure recovers the same task`,async()=>{
  let calls=0,commits=0;const progress=[];
  const result=await designReferenceProject(project,{...options,onProgress:e=>progress.push(e),onBatchReady:()=>commits++,request:async(path,body)=>{assert(path.endsWith('/status'));assert.equal(body.id,'saved');if(++calls===2)throw failure;return calls===1?running:done;}});
  assert.equal(result.pages.length,1);assert.equal(commits,1);assert.equal(calls,3);
  assert.equal(progress[1].completed,0);assert.equal(progress[1].planned,1);assert.equal(progress[1].generationPhase,'designing');
 });
}

test('four persistent network failures stop monitoring without cancelling or recreating the backend task',async()=>{
 const calls=[];let commits=0;
 await assert.rejects(designReferenceProject(project,{...options,onBatchReady:()=>commits++,request:async(path,body)=>{calls.push(path);assert.equal(body.id,'saved');throw new TypeError('Failed to fetch');}}),e=>e.code==='REFERENCE_CONNECTION_LOST'&&e.jobId==='saved'&&/后台任务可能仍在运行/.test(e.message));
 assert.equal(calls.length,4);assert(calls.every(p=>p.endsWith('/status')));assert.equal(commits,0);
});

for(const exists of [true,false])test(`lost start response reconciles before ${exists?'tracking existing task':'replaying the identical creation'}`,async()=>{
 const calls=[],creates=[];let id,first=true,commits=0;
 const result=await designReferenceProject(project,{pollIntervalMs:0,onJobStarted:value=>id=value,onBatchReady:()=>commits++,request:async(path,body)=>{
  const action=path.split('/').at(-1);calls.push(action);
  if(action==='start'){creates.push(structuredClone(body));assert.equal(body.clientRequestId,id);if(first){first=false;throw http(504);}return {...running,id,status:'queued'};}
  assert.equal(body.id,id);if(!exists&&calls.length===2)throw http(404);return {...done,id};
 }});
 assert.equal(result.pages.length,1);assert.equal(commits,1);assert.deepEqual(calls,exists?['start','status','status']:['start','status','start','status']);
 if(!exists)assert.deepEqual(creates[0],creates[1]);assert.equal(creates.length,exists?1:2);
});

for(const reconnectFails of [false,true])test(`lost resume response ${reconnectFails?'keeps polling after reconnect failure':'uses the actual backend state'} without replay`,async()=>{
 const calls=[];let statusCalls=0;
 const result=await designReferenceProject(project,{...options,request:async(path)=>{
  const action=path.split('/').at(-1);calls.push(action);
  if(action==='resume')throw http(504);
  if(++statusCalls===1)return {...running,status:'interrupted'};
  if(reconnectFails&&statusCalls===2)throw http(503);
  return done;
 }});
 assert.equal(result.pages.length,1);assert.equal(calls.filter(a=>a==='resume').length,1);assert(!calls.includes('start'));
});

for(const missing of [true,false])test(`unknown start acceptance polls until ${missing?'explicit absence permits same-id creation':'the existing task is found'}`,async()=>{
 const calls=[],creates=[];let statusCalls=0;
 await designReferenceProject(project,{pollIntervalMs:0,request:async(path,body)=>{
  const action=path.split('/').at(-1);calls.push(action);
  if(action==='start'){creates.push(structuredClone(body));if(creates.length===1)throw http(504);return {...running,id:body.clientRequestId};}
  if(++statusCalls===1)throw http(503);
  if(missing&&statusCalls===2)throw http(404);
  return {...done,id:creates[0].clientRequestId};
 }});
 assert.deepEqual(calls,missing?['start','status','status','start','status']:['start','status','status','status']);
 assert.equal(creates.length,missing?2:1);if(missing)assert.deepEqual(creates[0],creates[1]);
});

for(const status of [400,401,403,404,409,410,422])test(`HTTP ${status} during polling fails immediately`,async()=>{
 let calls=0,commits=0;
 await assert.rejects(designReferenceProject(project,{...options,onBatchReady:()=>commits++,request:async()=>{if(++calls===1)return running;throw http(status);}}),e=>e.status===status);
 assert.equal(calls,2);assert.equal(commits,0);
});

test('an individual hanging fetch times out and reconnects without a deck-wide deadline',async()=>{
 let calls=0;
 const result=await designReferenceProject(project,{...options,requestTimeoutMs:15,request:async(_path,_body,signal)=>{
  if(++calls===1)return new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));
  return done;
 }});
 assert.equal(result.pages.length,1);assert.equal(calls,2);
});

test('user cancellation during a pending status request cancels exactly once and commits nothing',async()=>{
 const controller=new AbortController(),calls=[];let commits=0;
 await assert.rejects(designReferenceProject(project,{...options,signal:controller.signal,onBatchReady:()=>commits++,request:async(path,_body,signal)=>{
  const action=path.split('/').at(-1);calls.push(action);if(action==='cancel'){assert.equal(signal,undefined);return {};}
  return new Promise((_,reject)=>{signal.addEventListener('abort',()=>reject(signal.reason),{once:true});controller.abort();});
 }}),e=>e.name==='AbortError');
 assert.deepEqual(calls,['status','cancel']);assert.equal(commits,0);
});

test('user cancellation during backoff does not resume, retry or commit',async()=>{
 const controller=new AbortController(),calls=[];
 await assert.rejects(designReferenceProject(project,{...options,signal:controller.signal,onProgress:()=>controller.abort(),request:async path=>{const action=path.split('/').at(-1);calls.push(action);if(action==='cancel')return {};throw http(503);}}),e=>e.name==='AbortError');
 assert.deepEqual(calls,['status','cancel']);
});

test('server terminal quality failure after reconnection stays failed and never applies',async()=>{
 let calls=0,commits=0;
 await assert.rejects(designReferenceProject(project,{...options,onBatchReady:()=>commits++,request:async()=>{if(++calls===1)throw http(504);return {...running,status:'partial',message:'文字检查未通过',failures:[{pageId:'p1',code:'REFERENCE_TEXT_REPAIR_EXHAUSTED'}]};}}),e=>/文字检查未通过/.test(e.message)&&e.failures.length===1);
 assert.equal(commits,0);
});
