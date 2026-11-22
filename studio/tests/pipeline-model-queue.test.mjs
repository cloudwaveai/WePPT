import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createPipelineModelQueue,runPipelineAI} from '../pipeline-model-queue.mjs';
import {createReferenceJobs} from '../reference-design-jobs.mjs';

const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const until=async fn=>{const end=Date.now()+5000;while(!await fn()){if(Date.now()>end)throw Error('condition timeout');await new Promise(r=>setTimeout(r,5));}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('shared two-slot FIFO orders calls from multiple decks without starving restoration behind new planning',async()=>{
 const gates=new Map(['a-plan','b-plan','a-restore','b-review','a-plan-next'].map(id=>[id,deferred()]));
 const starts=[];let active=0,max=0;
 const queue=createPipelineModelQueue(async input=>{starts.push(input.id);active++;max=Math.max(max,active);try{await gates.get(input.id).promise;return input.id;}finally{active--;}});
 const deckA=id=>queue({id,deck:'a'}),deckB=id=>queue({id,deck:'b'});
 const tasks=[deckA('a-plan'),deckB('b-plan'),deckA('a-restore'),deckB('b-review'),deckA('a-plan-next')];
 try{
  await until(()=>starts.length===2);assert.deepEqual(starts,['a-plan','b-plan']);assert.equal(max,2);
  gates.get('b-plan').resolve();await until(()=>starts.length===3);assert.equal(starts[2],'a-restore');
  gates.get('a-plan').resolve();await until(()=>starts.length===4);assert.equal(starts[3],'b-review');
  gates.get('a-restore').resolve();await until(()=>starts.length===5);assert.equal(starts[4],'a-plan-next');assert.equal(max,2);
 }finally{for(const gate of gates.values())gate.resolve();}
 assert.deepEqual(await Promise.all(tasks),[...gates.keys()]);assert.equal(active,0);
});

test('cancelling a queued call removes it immediately, never invokes provider, and preserves FIFO for remaining calls',async()=>{
 const drain=deferred(),controller=new AbortController(),starts=[];
 const queue=createPipelineModelQueue(async id=>{starts.push(id);if(id==='running')await drain.promise;return id;},1);
 const first=queue('running');await until(()=>starts.length===1);
 const abandoned=queue('queued-cancel',{signal:controller.signal}),rejection=assert.rejects(abandoned,/queued cancelled/);
 const last=queue('next');controller.abort(Error('queued cancelled'));await rejection;assert.deepEqual(starts,['running']);
 drain.resolve();assert.deepEqual(await Promise.all([first,last]),['running','next']);assert.deepEqual(starts,['running','next']);
});

test('running cancellation retains occupied slot until provider drains and then admits next request',async()=>{
 const drain=deferred(),abortSeen=deferred(),controller=new AbortController(),starts=[];let settled=false;
 const queue=createPipelineModelQueue(async(id,{signal})=>{starts.push(id);if(id==='running'){signal.addEventListener('abort',()=>abortSeen.resolve(),{once:true});await drain.promise;signal.throwIfAborted();}return id;},1);
 const first=queue('running',{signal:controller.signal}).finally(()=>settled=true),rejection=assert.rejects(first,/running cancelled/);
 await until(()=>starts.length===1);const next=queue('next');controller.abort(Error('running cancelled'));await abortSeen.promise;await tick();
 assert.equal(settled,false);assert.deepEqual(starts,['running']);drain.resolve();await rejection;assert.equal(await next,'next');assert.deepEqual(starts,['running','next']);
});

test('already-cancelled and cancelled-before-start calls never reach provider and release capacity',async()=>{
 let calls=0;const queue=createPipelineModelQueue(async()=>++calls,1);
 const before=new AbortController();before.abort(Error('before queue'));await assert.rejects(queue('before',{signal:before.signal}),/before queue/);
 const immediate=new AbortController(),pending=queue('microtask',{signal:immediate.signal});immediate.abort(Error('before provider'));
 await assert.rejects(pending,/before provider/);assert.equal(calls,0);assert.equal(await queue('healthy'),1);
});

test('sync throws and async provider rejections release slots without unhandled promise rejections',async()=>{
 const unhandled=[];const onUnhandled=reason=>unhandled.push(reason);process.on('unhandledRejection',onUnhandled);
 try{
  const queue=createPipelineModelQueue(id=>{if(id==='sync')throw Error('sync failure');if(id==='async')return Promise.reject(Error('async failure'));return Promise.resolve(id);},1);
  const outcomes=await Promise.allSettled([queue('sync'),queue('async'),queue('success')]);await tick();await tick();
  assert.deepEqual(outcomes.map(o=>o.status),['rejected','rejected','fulfilled']);assert.equal(outcomes[2].value,'success');assert.deepEqual(unhandled,[]);
 }finally{process.removeListener('unhandledRejection',onUnhandled);}
});

test('mixed v4 and legacy job managers share one model queue while only v4 enables image-stage slots',async()=>{
 const root=await mkdtemp(join(tmpdir(),'weppt-model-queue-')),observed=[];
 const run=async(name,pageWorkers)=>{
  const jobs=createReferenceJobs({dataDir:join(root,name),pageWorkers,
   plan:async(input,opts)=>{observed.push({name,stage:'plan',model:opts.structuredAI});const plan={targetPageIds:['p0'],pages:[{pageId:'p0'}]};await opts.onCheckpoint({plan});return plan;},
   generate:async(input,opts)=>{observed.push({name,stage:'page',model:opts.structuredAI,stageImageSlots:opts.stageImageSlots});return {pages:[{...input.project.pages[0],themeId:input.themeId,objects:[{id:'rect',type:'rect'}]}]};},
   review:async(_input,opts)=>{observed.push({name,stage:'review',model:opts.structuredAI});return {issues:[],reviewEvidence:{status:'pass',checkedPageIds:['p0']}};}
  });
  const start=await jobs.start({project:{id:name,themeId:'midnight',pages:[{id:'p0',title:'Title',body:'Copy',role:'cover',objects:[]}]}});
  await until(async()=>{const job=await jobs.get(start.id);if(['completed','failed','partial'].includes(job.status)){assert.equal(job.status,'completed');return true;}return false;});
 };
 try{
  await Promise.all([run('deck-a',2),run('deck-b',2),run('legacy',0)]);
  for(const name of ['deck-a','deck-b','legacy']){const rows=observed.filter(o=>o.name===name);assert.equal(rows.length,3);for(const row of rows)assert.equal(row.model,runPipelineAI,`${name}/${row.stage} must share queue`);}
  for(const row of observed.filter(o=>o.stage==='page'))assert.equal(!!row.stageImageSlots,row.name!=='legacy');
 }finally{await rm(root,{recursive:true,force:true,maxRetries:5,retryDelay:20});}
});
