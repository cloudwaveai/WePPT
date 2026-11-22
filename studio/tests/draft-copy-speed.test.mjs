import test from 'node:test';
import assert from 'node:assert/strict';
import {isConciseDraft,reviseConciseDraft,mergeConciseResults} from '../draft-copy-speed.mjs';

const input=(count=12)=>({action:'revise',scope:'deck',message:'请精减一下',materials:[{name:'完整材料',text:'材料全文'.repeat(5000)}],project:{stage:'draft',pages:Array.from({length:count},(_,i)=>({id:`stable-${i}`,title:`标题${i}`,body:'必须执行，不得向外披露。预算1,000元，增长10%。',role:'content'}))}});
const shortened='不得向外披露。必须执行；预算1000元，增长10%。';
const result=(id,body=shortened)=>({changes:[{pageId:id,body}]});
const ids=i=>i.project.pages.map(p=>p.id);

test('narrow grammar accepts real colloquial correction and equivalent copy requests',()=>{
 for(const message of ['精简','请精减一下','帮我精简整份文稿','整份文稿精简一下','压缩措辞','文字太多了，请精简一下','字好多啊，可以精减吗，或者有些页字多点，，你这每一页字都好多','请精简，保留关键事实和数字']){
  assert(isConciseDraft({...input(),message}),message);
 }
});
test('ambiguous, structural, factual and discussion requests stay on ordinary route',()=>{
 for(const message of ['精减到20页','精简并合并重复页','精简，新增案例','不要精简','如何精简','先讨论怎么精简','精简，换标题','精简，调整顺序','精简，删除第2页','精简，补充关键事实','按刚才的建议精简','帮我看看能否精简'])assert.equal(isConciseDraft({...input(),message}),false,message);
 assert.equal(isConciseDraft({...input(),project:{...input().project,stage:'editor'}}),false);
 assert.equal(isConciseDraft({...input(),scope:'object'}),false);
});
test('two low-effort calls retain every page, complete materials and full skill instructions',async()=>{
 const request=input(),before=structuredClone(request),skills={instructions:'规则'.repeat(9000)},calls=[];
 const merged=await reviseConciseDraft(request,{context:{pages:[request.project.pages[0]],originalBrief:'原始用途',materials:[]},skills,structuredAI:async(options)=>{
  calls.push(options);assert.equal(options.effort,'low');assert.equal(options.action,'draft-concise');
  assert(options.prompt.includes(skills.instructions));assert(options.prompt.includes(request.materials[0].text));
  for(const p of request.project.pages)assert(options.prompt.includes(p.id));
  assert(options.prompt.includes('不得从材料中增加新事实'));assert(options.prompt.includes('否定含义'));assert(options.prompt.includes('责任主体'));
  const allowed=options.schema.properties.changes.items.properties.pageId.enum;
  return result(allowed[0]);
 }});
 assert.equal(calls.length,2);assert.equal(merged.changes.length,2);assert.deepEqual(request,before);
 assert.deepEqual(merged.changes.map(c=>c.pageId),['stable-0','stable-6']);
 assert.deepEqual(merged.changes[0],{pageId:'stable-0',title:'标题0',body:shortened,objectId:'',text:null,properties:null});
 assert.deepEqual(merged.pages,[]);assert.deepEqual(merged.operations,[]);
});
test('small decks and page scope use one call while page scope still receives full deck',async()=>{
 for(const request of [input(11),{...input(40),scope:'page',pageId:'stable-23'}]){
  let count=0;await reviseConciseDraft(request,{structuredAI:async({prompt,schema})=>{
   count++;assert(prompt.includes('stable-0'));assert(prompt.includes(request.project.pages.at(-1).id));
   const allowed=schema.properties.changes.items.properties.pageId.enum;
   if(request.scope==='page')assert.deepEqual(allowed,['stable-23']);return {changes:[]};
  }});assert.equal(count,1);
 }
});
test('merge preserves original order and unchanged titles, allowing omitted pages',()=>{
 const request=input(4),batches=[ids(request).slice(0,2),ids(request).slice(2)];
 const merged=mergeConciseResults([{changes:[{pageId:'stable-1',body:shortened},{pageId:'stable-0',body:shortened}]},{changes:[]}],request,batches);
 assert.deepEqual(merged.changes.map(c=>c.pageId),['stable-0','stable-1']);assert.equal(merged.changes[0].title,'标题0');
 assert.equal(mergeConciseResults([{changes:[]}],request,[ids(request)]).changes.length,0);
});
test('cross-batch targets, duplicate IDs, structure or unexpected fields reject atomically',()=>{
 const request=input(2),batches=[['stable-0'],['stable-1']];
 for(const first of [result('stable-1'),{changes:[...result('stable-0').changes,...result('stable-0').changes]},{...result('stable-0'),operations:[]},{changes:[{pageId:'stable-0',body:shortened,title:'篡改标题'}]},{changes:[{pageId:'stable-0',body:''}]}])assert.throws(()=>mergeConciseResults([first,{changes:[]}],request,batches));
 assert.throws(()=>mergeConciseResults([{changes:[]}],request,[['stable-0']]));
});
test('numeric facts preserve comma formatting equivalence and ignore list/chapter numbering',()=>{
 const request=input(1);request.project.pages[0].body='## 第1章\n1. 预算1,000元。\n2、增长10％，2026年完成。';
 assert(mergeConciseResults([result('stable-0','预算1000元；增长10%，2026年完成。')],request,[ids(request)]));
 for(const body of ['预算1000元，2026年完成。','预算1000元，增长11%，2026年完成。','预算1000元，增长10%，2027年完成。'])assert.throws(()=>mergeConciseResults([result('stable-0',body)],request,[ids(request)]));
});
test('invalid batch immediately aborts sibling and waits for its cleanup',async()=>{
 let released=false,secondStarted;
 const gate=new Promise(resolve=>secondStarted=resolve);let calls=0;
 await assert.rejects(reviseConciseDraft(input(),{structuredAI:async(_,{signal})=>{
  if(++calls===1){await gate;return result('stable-11');}
  secondStarted();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>setTimeout(()=>{released=true;reject(signal.reason);},20),{once:true}));
 }}),/越界/);
 assert.equal(calls,2);assert.equal(released,true);
});
test('caller cancellation waits for both child processes and returns no partial result',async()=>{
 const controller=new AbortController();let started=0,cleaned=0;
 await assert.rejects(reviseConciseDraft(input(),{signal:controller.signal,structuredAI:async(_,{signal})=>new Promise((resolve,reject)=>{
  signal.addEventListener('abort',()=>setTimeout(()=>{cleaned++;reject(signal.reason);},10),{once:true});
  if(++started===2)controller.abort();
 })}));assert.equal(cleaned,2);
});
test('child timeout cancels its sibling, and already cancelled input starts no calls',async()=>{
 let count=0;const controller=new AbortController();controller.abort();
 await assert.rejects(reviseConciseDraft(input(),{signal:controller.signal,structuredAI:async()=>{count++;return {changes:[]};}}));assert.equal(count,0);
 let release;const started=new Promise(r=>release=r);let cleaned=false;
 await assert.rejects(reviseConciseDraft(input(),{structuredAI:async(_,{signal})=>{
  if(++count===1){await started;throw new DOMException('deadline','TimeoutError');}
  release();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{cleaned=true;reject(signal.reason);},{once:true}));
 }}),{name:'TimeoutError'});assert(cleaned);
});
