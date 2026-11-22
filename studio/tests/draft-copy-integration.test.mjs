import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runAI} from '../ai.mjs';
const input=()=>({action:'revise',scope:'deck',message:'字好多啊，可以精减吗，或者有些页字多点，，你这每一页字都好多',materials:[{name:'来源',text:'完整来源不能丢弃'.repeat(1000)}],project:{id:'isolated-draft',stage:'draft',themeId:'curated-005',title:'验证文稿',messages:[{role:'user',scope:'deck',text:'原始培训需求'}],pages:Array.from({length:40},(_,i)=>({id:'id-'+i,title:'第'+i+'节',body:'必须执行，不得向外披露。当前预算1,000元。',role:'content'}))}});
async function fixture(fn){const dataDir=await mkdtemp(join(tmpdir(),'draft-copy-integration-'));try{await fn(dataDir);}finally{await rm(dataDir,{recursive:true,force:true});}}
test('runAI routes real colloquial 40-page request through two batches with trace and timing',()=>fixture(async dataDir=>{
 const request=input(),before=structuredClone(request);let calls=0;
 const result=await runAI(request,{dataDir,structuredAI:async({schema,prompt,effort,action})=>{
  calls++;assert.equal(action,'draft-concise');assert.equal(effort,'low');assert(prompt.includes(request.materials[0].text));assert(prompt.includes('原始培训需求'));
  for(const p of request.project.pages)assert(prompt.includes(p.id));
  const targets=schema.properties.changes.items.properties.pageId.enum;assert.equal(targets.length,20);
  return {changes:[{pageId:targets[0],body:'必须执行；不得向外披露。预算1000元。'}]};
 }});
 assert.equal(calls,2);assert.deepEqual(request,before);assert.equal(result.changes.length,2);assert.deepEqual(result.pages,[]);assert.deepEqual(result.operations,[]);
 assert(result.skillTrace.ids.length);assert.equal(result.skillTrace.visualEvidence,false);
 const timing=JSON.parse((await readFile(join(dataDir,'ai-timings.jsonl'),'utf8')).trim());assert.equal(timing.route,'draft-concise');assert.equal(timing.success,true);assert(timing.contextChars>request.materials[0].text.length);
}));
test('runAI page simplification retains complete materials even for spelling previously omitting them',()=>fixture(async dataDir=>{
 const request={...input(),message:'请精简一下',scope:'page',pageId:'id-23'};let calls=0;
 const result=await runAI(request,{dataDir,structuredAI:async({schema,prompt})=>{calls++;assert(prompt.includes(request.materials[0].text));assert(prompt.includes('id-39'));assert.deepEqual(schema.properties.changes.items.properties.pageId.enum,['id-23']);return {changes:[]};}});
 assert.equal(calls,1);assert.deepEqual(result.changes,[]);
}));
test('runAI never returns partial edits when a batch violates scope',()=>fixture(async dataDir=>{
 await assert.rejects(runAI(input(),{dataDir,structuredAI:async()=>({changes:[{pageId:'outside',body:'不能应用'}]})}),/越界/);
 const timing=JSON.parse((await readFile(join(dataDir,'ai-timings.jsonl'),'utf8')).trim());assert.equal(timing.success,false);
}));
