import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readdir,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {planCompositions,compositionContext,compositionFingerprint} from '../composition-planner.mjs';
import {upstreamPackage} from '../upstream-skills.mjs';
import {buildSkillContext} from '../skill-runtime.mjs';
const project=()=>({themeId:'test-theme',pages:[{id:'a',title:'Overview',body:'Complete body A',role:'body'},{id:'b',title:'Process',body:'Complete body B',role:'body'},{id:'c',title:'Context only',body:'Non-target full text',role:'body'}]});
const page=(pageId,x=0)=>({pageId,pageJob:'Explain',relation:'order',composition:'Focal hierarchy and different reading direction',geometrySignature:'job → geometry',readingPath:'Left to right',zones:[{purpose:'content',x,y:0,w:0.5,h:0.8}]});
async function fixture(fn){const dataDir=await mkdtemp(join(tmpdir(),'composition-test-'));try{await fn(dataDir);}finally{await rm(dataDir,{recursive:true,force:true});}}
test('one planner call receives full deck and exact attributed source; scoped context survives object changes',()=>fixture(async dataDir=>{
 const p=project();let calls=0;
 const plan=await planCompositions({project:p,targetPageIds:['a','b'],instruction:'Preserve words'},{dataDir,structuredAI:async({prompt,schema},{signal})=>{
  calls++;assert(!signal.aborted);assert(prompt.includes('Non-target full text'));assert(prompt.includes('Complete body A'));
  const pkg=upstreamPackage('ppt-master');const raw=await readFile(join(pkg.directory,'references/native-shape-authoring.md'),'utf8');const start=raw.indexOf('### 2.1 Topology assembly'),end=raw.indexOf('**Boolean decision gate**',start);assert(prompt.includes(raw.slice(start,end).trim()));assert(prompt.includes(pkg.commit));assert.equal(schema.additionalProperties,false);
  assert.equal((await readdir(join(dataDir,'design-jobs'))).length,1);return {pages:[page('a'),page('b',0.5)]};
 }});
 assert.equal(calls,1);assert.deepEqual(plan.targetPageIds,['a','b']);assert.equal((await readdir(join(dataDir,'design-jobs'))).length,0);
 p.compositionPlan=plan;p.pages[0].objects=[{type:'text',text:'new object'}];assert.equal(JSON.parse(compositionContext(p,['a'])).pages.length,1);assert.equal(JSON.parse(compositionContext(p,['a'])).deckCompositions.length,2);
 assert.throws(()=>compositionContext(p,['c']),/计划内/);p.pages[2].body+=' changed';assert.throws(()=>compositionContext(p,['a']),/过期/);
}));
test('reject duplicate geometry regardless of names, small moves, or zone order; reject invalid scopes and bounds',()=>fixture(async dataDir=>{
 for(const make of [()=>[page('a'),{...page('b',0.01),composition:'Different name',geometrySignature:'Completely different'}],()=>[page('a'),page('a',0.5)],()=>[page('a'),{...page('b',0.8)}],()=>[page('a'),{...page('b',0.5),unexpected:true}]]){
  await assert.rejects(planCompositions({project:project(),targetPageIds:['a','b']},{dataDir,structuredAI:async()=>({pages:make()})}),/构图规划/);
  assert.equal((await readdir(join(dataDir,'design-jobs'))).length,0);
 }
}));
test('failures and cancellation propagate without fallback and clean deployment guard',()=>fixture(async dataDir=>{
 await assert.rejects(planCompositions({project:project(),targetPageIds:['a']},{dataDir,structuredAI:async()=>{throw Error('provider failure');}}),/provider failure/);
 const controller=new AbortController();await assert.rejects(planCompositions({project:project(),targetPageIds:['a']},{dataDir,signal:controller.signal,structuredAI:async()=>{controller.abort();return {pages:[page('a')]};}}),e=>e.name==='AbortError');
 assert.equal((await readdir(join(dataDir,'design-jobs'))).length,0);
}));
test('fingerprint binds theme and all copy, rejects truncation, and absent plans retain compatibility',()=>{
 const p=project(),hash=compositionFingerprint(p);assert.equal(compositionContext(p,['a']),null);p.pages[0].objects=[{}];assert.equal(compositionFingerprint(p),hash);p.themeId='other';assert.notEqual(compositionFingerprint(p),hash);p.pages[0].body='x'.repeat(100001);assert.throws(()=>compositionFingerprint(p),/正文/);
});

test('chapter geometry reuse passes planning and stored context using source roles',()=>fixture(async dataDir=>{
 const p=project();p.pages[0].role=p.pages[1].role='chapter';let calls=0;
 const plan=await planCompositions({project:p,targetPageIds:['a','b']},{dataDir,structuredAI:async({prompt})=>{calls++;assert.match(prompt,/同类章节页.*统一版式/);return {pages:[page('a'),page('b')]};}});
 assert.equal(calls,1);p.compositionPlan=plan;assert.equal(JSON.parse(compositionContext(p,['a','b'])).pages.length,2);
 p.pages[1].role='content';assert.throws(()=>compositionContext(p,['a','b']),/过期/);
}));

for(const roles of [['chapter','content'],['content','content'],['cover','cover']])test(`same geometry remains rejected for ${roles.join('/')}`,()=>fixture(async dataDir=>{
 const p=project();p.pages[0].role=roles[0];p.pages[1].role=roles[1];
 await assert.rejects(planCompositions({project:p,targetPageIds:['a','b']},{dataDir,structuredAI:async()=>({pages:[page('a'),page('b')]})}),/构图重复/);
}));
test('partial planning preserves long non-target copy and complete global skill instructions',()=>fixture(async dataDir=>{
 const p=project();p.pages[2].title='T'.repeat(25000);p.pages[2].body='B'.repeat(100000);
 const instruction='Keep full context';const skills=buildSkillContext({mode:'plan',project:p,message:instruction,scope:'page'});
 const plan=await planCompositions({project:p,targetPageIds:['a'],instruction},{dataDir,structuredAI:async({prompt})=>{
  assert(prompt.includes(p.pages[2].title));assert(prompt.includes(p.pages[2].body));assert(prompt.includes(skills.instructions));return {pages:[page('a')]};
 }});
 p.compositionPlan=plan;assert(compositionContext(p,['a']));const old=plan.sourceFingerprint;p.pages[2].body=p.pages[2].body.slice(0,-1)+'X';assert.notEqual(compositionFingerprint(p),old);assert.throws(()=>compositionContext(p,['a']),/过期/);
}));

const longProject=(count=25)=>({themeId:'test-theme',pages:Array.from({length:count},(_,i)=>({id:'p'+i,title:'Title '+i,body:'Entire confirmed source '+i,role:'content'}))});
const uniquePage=id=>{const i=Number(id.slice(1));return {...page(id),zones:[{purpose:'content',x:(i%5)*.18,y:Math.floor(i/5)*.18,w:.12,h:.12}]};};
const contextOf=prompt=>JSON.parse(prompt.split('INPUT_JSON:\n')[1]);

test('25-page planning emits sequential bounded batches with full copy, rules and confirmed global context',()=>fixture(async dataDir=>{
 const p=longProject(),progress=[],saved=[],signals=[];let calls=0,persisting=false;
 const skills=buildSkillContext({mode:'plan',project:p,message:'Keep it',scope:'deck'});
 const result=await planCompositions({project:p,instruction:'Keep it'},{dataDir,onProgress:e=>progress.push(e),onCheckpoint:async c=>{
  persisting=true;await new Promise(resolve=>setTimeout(resolve,2));saved.push(structuredClone(c));persisting=false;
 },structuredAI:async({prompt,schema,effort},{signal,onProgress})=>{
  assert.equal(persisting,false);assert.equal(effort,'medium');assert(prompt.includes(skills.instructions));assert.match(prompt,/不超过60字/);
  const c=contextOf(prompt);assert.equal(c.pages.length,25);assert.deepEqual(c.pages.map(p=>p.body),p.pages.map(p=>p.body));
  assert.equal(c.targetPageIds.length,5);assert.equal(c.confirmedPlans.length,calls*5);assert.equal(schema.properties.pages.maxItems,5);
  assert.deepEqual(c.allTargetPageIds,p.pages.map(p=>p.id));assert.equal(c.targetPageIds[0],'p'+calls*5);
  onProgress({phase:'requesting'});signals.push(signal);calls++;return {pages:c.targetPageIds.map(uniquePage)};
 }});
 assert.equal(calls,5);assert.equal(new Set(signals).size,5);assert.equal(result.pages.length,25);
 assert.deepEqual(saved.map(c=>c.plan.pages.length),[5,10,15,20,25]);assert.equal(saved.at(-1).version,1);
 assert(progress.every(e=>e.stage==='composition'&&e.total===25&&Number.isInteger(e.planned)&&typeof e.message==='string'));
 assert.equal(progress.at(-1).planned,25);p.compositionPlan=result;assert(compositionContext(p,['p24']));
}));

test('batch timeout splits automatically, and a timed-out singleton has at most two attempts',()=>fixture(async dataDir=>{
 const calls=[];
 const plan=await planCompositions({project:longProject(5)},{dataDir,structuredAI:async({prompt})=>{
  const c=contextOf(prompt);calls.push(c.targetPageIds.length);
  if(c.targetPageIds.length===5)throw Object.assign(Error('timeout'),{name:'TimeoutError'});
  return {pages:c.targetPageIds.map(uniquePage)};
 }});
 assert.deepEqual(calls,[5,3,2]);assert.equal(plan.pages.length,5);
 let attempts=0;await assert.rejects(planCompositions({project:longProject(1)},{dataDir,structuredAI:async()=>{attempts++;throw Object.assign(Error('timeout'),{status:408});}}),/timeout/);
 assert.equal(attempts,2);
}));

test('a cross-batch duplicate is corrected once against all earlier pages, then fails if repeated',()=>fixture(async dataDir=>{
 for(const repair of [true,false]){
  let calls=0,lastCheckpoint;
  const request=planCompositions({project:longProject(6)},{dataDir,onCheckpoint:async c=>{lastCheckpoint=c;},structuredAI:async({prompt})=>{
   const c=contextOf(prompt);calls++;
   if(calls===1)return {pages:c.targetPageIds.map(uniquePage)};
   assert.equal(c.confirmedPlans.length,5);
   if(calls===3){assert.match(c.correction,/构图重复/);if(repair)return {pages:[uniquePage('p5')]};}
   return {pages:[{...uniquePage('p0'),pageId:'p5'}]};
  }});
  if(repair)assert.equal((await request).pages.length,6);else{await assert.rejects(request,/构图重复/);assert.equal(lastCheckpoint.plan.pages.length,5);}
  assert.equal(calls,3);
 }
}));

test('checkpoint resumes only missing pages and rejects changed copy, objects, targets, instructions, feedback and sources',()=>fixture(async dataDir=>{
 const input={project:longProject(6),instruction:'original',repairFeedback:'feedback'};let saved,calls=0;
 await assert.rejects(planCompositions(input,{dataDir,onCheckpoint:async c=>{saved=c;},structuredAI:async({prompt})=>{
  if(++calls===2)throw Object.assign(Error('Unauthorized'),{status:401});return {pages:contextOf(prompt).targetPageIds.map(uniquePage)};
 }}),/Unauthorized/);
 assert.equal(saved.plan.pages.length,5);let resumed=0;
 const result=await planCompositions(input,{dataDir,checkpoint:saved,structuredAI:async({prompt})=>{
  resumed++;const c=contextOf(prompt);assert.deepEqual(c.targetPageIds,['p5']);assert.equal(c.confirmedPlans.length,5);return {pages:[uniquePage('p5')]};
 }});
 assert.equal(resumed,1);assert.equal(result.pages.length,6);
 for(const change of [x=>x.project.pages[0].body+=' changed',x=>x.project.pages[0].objects=[{id:'user',custom:true}],x=>x.targetPageIds=['p0'],x=>x.instruction='changed',x=>x.repairFeedback='changed',x=>x.themeId='another']){
  const changed=structuredClone(input);change(changed);
  await assert.rejects(planCompositions(changed,{dataDir,checkpoint:saved,structuredAI:async()=>{throw Error('must not call');}}),/断点已过期/);
 }
 const corrupted=structuredClone(saved);corrupted.plan.sources[0].commit='wrong';
 await assert.rejects(planCompositions(input,{dataDir,checkpoint:corrupted,structuredAI:async()=>{throw Error('must not call');}}),/断点内容无效/);
}));

test('cancellation and authorization never retry; checkpoint write failure never reruns model',()=>fixture(async dataDir=>{
 for(const failure of ['cancel','auth','persist']){
  let calls=0;const controller=new AbortController();
  await assert.rejects(planCompositions({project:longProject(6)},{dataDir,signal:controller.signal,onCheckpoint:async()=>{if(failure==='persist')throw Error('disk unavailable');},structuredAI:async({prompt})=>{
   calls++;if(failure==='cancel'){controller.abort();throw Object.assign(Error('timeout'),{status:408});}
   if(failure==='auth')throw Error('AI 登录或模型授权失效，请检查本机 Codex。');
   return {pages:contextOf(prompt).targetPageIds.map(uniquePage)};
  }}),failure==='cancel'?e=>e.name==='AbortError':failure==='auth'?/授权失效/:/disk unavailable/);
  assert.equal(calls,1);assert.equal((await readdir(join(dataDir,'design-jobs'))).length,0);
 }
}));
