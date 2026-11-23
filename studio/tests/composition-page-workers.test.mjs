import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {planCompositions} from '../composition-planner.mjs';

const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const project=()=>({themeId:'midnight',pages:['a','b','c','d'].map(id=>({id,title:id,body:'Full source '+id,role:'content'}))});
const inputOf=prompt=>JSON.parse(prompt.split('INPUT_JSON:\n')[1]);
const page=(pageId,x=['a','b','c','d'].indexOf(pageId)*.2)=>({pageId,pageJob:'Explain',relation:'sequence',composition:'Distinct arrangement',geometrySignature:'geometry',readingPath:'top down',zones:[{purpose:'body',x,y:.1,w:.15,h:.7}]});
async function fixture(fn){const dataDir=await mkdtemp(join(tmpdir(),'page-workers-'));try{await fn(dataDir);}finally{await rm(dataDir,{recursive:true,force:true});}}

test('two single-page workers start concurrently, publish first page without waiting for second, and persist source order',()=>fixture(async dataDir=>{
 const firstTwo=deferred(),releaseSecond=deferred(),firstSaved=deferred();let active=0,max=0,calls=0;const saved=[];
 const task=planCompositions({project:project()},{dataDir,pageWorkers:2,structuredAI:async({prompt,schema})=>{
  const input=inputOf(prompt),id=input.targetPageIds[0];assert.equal(input.targetPageIds.length,1);assert.equal(input.pages.length,4);assert.equal(schema.properties.pages.maxItems,1);
  active++;max=Math.max(max,active);if(++calls===2)firstTwo.resolve();await firstTwo.promise;if(id==='b')await releaseSecond.promise;active--;return {pages:[page(id)]};
 },onCheckpoint:async checkpoint=>{saved.push(checkpoint.plan.pages.map(p=>p.pageId));if(saved.length===1)firstSaved.resolve();}});
 await firstSaved.promise;assert.deepEqual(saved,[['a']]);releaseSecond.resolve();const result=await task;
 assert.equal(max,2);assert.equal(calls,4);assert.deepEqual(saved,[['a'],['a','b'],['a','b','c'],['a','b','c','d']]);assert.equal(result.pages.length,4);
}));

test('out-of-order response remains speculative; only conflicting page retries against frozen confirmed layouts',()=>fixture(async dataDir=>{
 const secondReturned=deferred(),counts={};const saved=[];
 const result=await planCompositions({project:project(),targetPageIds:['a','b']},{dataDir,pageWorkers:2,structuredAI:async({prompt})=>{
  const input=inputOf(prompt),id=input.targetPageIds[0];counts[id]=(counts[id]||0)+1;
  if(id==='a')await secondReturned.promise;
  if(id==='b'&&counts[id]===1){secondReturned.resolve();return {pages:[page(id,0)]};}
  if(id==='b'){assert.deepEqual(input.confirmedPlans.map(p=>p.pageId),['a']);assert.match(input.correction,/构图重复/);assert.match(input.correction,/仅修复/);}
  return {pages:[page(id)]};
 },onCheckpoint:async checkpoint=>saved.push(checkpoint.plan.pages.map(p=>p.pageId))});
 assert.deepEqual(counts,{a:1,b:2});assert.deepEqual(saved,[['a'],['a','b']]);assert.equal(result.pages[0].zones[0].x,0);
}));

test('chapter pairs may share geometry but mixed and content pairs still fail',()=>fixture(async dataDir=>{
 for(const roles of [['chapter','chapter'],['chapter','content'],['content','content']]){
  const p=project();p.pages=p.pages.slice(0,2);p.pages.forEach((x,i)=>x.role=roles[i]);let calls=0;
  const task=planCompositions({project:p},{dataDir,pageWorkers:2,structuredAI:async({prompt})=>{calls++;return {pages:[page(inputOf(prompt).targetPageIds[0],0)]};}});
  if(roles.every(r=>r==='chapter')){assert.equal((await task).pages.length,2);assert.equal(calls,2);}else{await assert.rejects(task,/构图重复/);assert.equal(calls,3);}
 }
}));

test('checkpoint write failure aborts and drains speculative provider work without model retry',()=>fixture(async dataDir=>{
 const secondStarted=deferred(),abortSeen=deferred(),drain=deferred();let settled=false,calls=0;
 const task=planCompositions({project:project()},{dataDir,pageWorkers:2,structuredAI:async({prompt},{signal})=>{
  calls++;const id=inputOf(prompt).targetPageIds[0];if(id==='a'){await secondStarted.promise;return {pages:[page(id)]};}
  signal.addEventListener('abort',()=>abortSeen.resolve(),{once:true});secondStarted.resolve();await drain.promise;signal.throwIfAborted();
 },onCheckpoint:async()=>{throw Error('disk failure');}}).finally(()=>settled=true);
 const outcome=assert.rejects(task,/disk failure/);await abortSeen.promise;assert.equal(settled,false);assert.equal(calls,2);drain.resolve();await outcome;
}));

test('user cancellation drains both active planning workers before returning',()=>fixture(async dataDir=>{
 const controller=new AbortController(),bothStarted=deferred(),drain=deferred();let calls=0,settled=false;
 const task=planCompositions({project:project()},{dataDir,pageWorkers:2,signal:controller.signal,structuredAI:async(_,{signal})=>{if(++calls===2)bothStarted.resolve();await drain.promise;signal.throwIfAborted();}}).finally(()=>settled=true);
 const outcome=assert.rejects(task,/cancel test/);await bothStarted.promise;controller.abort(Error('cancel test'));await Promise.resolve();assert.equal(settled,false);drain.resolve();await outcome;assert.equal(calls,2);
}));

test('same-mode resume reuses persisted prefix; legacy and different worker settings reject checkpoint',()=>fixture(async dataDir=>{
 let checkpoint;
 await assert.rejects(planCompositions({project:project()},{dataDir,pageWorkers:2,structuredAI:async({prompt})=>({pages:[page(inputOf(prompt).targetPageIds[0])]}),onCheckpoint:async value=>{checkpoint=structuredClone(value);throw Error('stop after persisted page');}}),/stop after persisted page/);
 const ids=[];const result=await planCompositions({project:project()},{dataDir,pageWorkers:2,checkpoint,structuredAI:async({prompt})=>{const id=inputOf(prompt).targetPageIds[0];ids.push(id);return {pages:[page(id)]};}});
 assert.deepEqual(ids,['b','c','d']);assert.deepEqual(result.pages[0],checkpoint.plan.pages[0]);
 for(const pageWorkers of [0,1])await assert.rejects(planCompositions({project:project()},{dataDir,pageWorkers,checkpoint,structuredAI:async()=>assert.fail('stale checkpoint called provider')}),/断点已过期/);
}));
