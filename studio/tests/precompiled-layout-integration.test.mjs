import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {checkPrecompiledLayout} from '../public/precompiled-layout-check.js';
import {renderBlueprintPackage} from '../public/template-blueprints.js';
import {planBlueprintDeck} from '../public/blueprint-planner.js';

// Execute the actual application function, with only its external UI/network
// dependencies replaced. No model calls, browser startup or project writes.
const app=await readFile(new URL('../public/app.js',import.meta.url),'utf8');
const functionSource=app.slice(app.indexOf('async function runDesignedLayout('),app.indexOf('async function runDeckReview('));
assert.ok(functionSource.startsWith('async function runDesignedLayout('));
const pack=JSON.parse(await readFile(new URL('../public/template-blueprint-packs/curated-001.json',import.meta.url),'utf8'));
const sourcePage=(body='原始正文')=>({id:'p1',role:'content',title:'工作安排',body,objects:[]});
const safeLayout=page=>({...structuredClone(page),objects:[
 {id:'title',type:'text',sourceField:'title',text:page.title,x:50,y:40,w:800,h:80,fontSize:40,layoutManaged:true},
 {id:'body',type:'text',sourceField:'body',sourceRange:[0,page.body.length],text:page.body,x:50,y:160,w:800,h:200,fontSize:26,layoutManaged:true}
]});
const realLayout=pages=>planBlueprintDeck(pages,pack).map(page=>renderBlueprintPackage(page,{id:pack.themeId,palette:{background:'#fff'}},pack,page.precompiledVariant||0));
function fixture({pages=[sourcePage()],layout=pages=>pages.map(safeLayout),measure=async()=>({issues:[]})}={}){
 const calls={commits:[],fallback:[],finished:[],started:0,batches:0,measure:0,layouts:0};
 const sandbox={structuredClone,AbortController,DOMException,console,JSON,Map,Set,
  busy:false,designController:null,editor:null,view:'draft',
  store:{project:{id:'project',themeId:'curated-001',stage:'draft',designEngine:'native',pages:structuredClone(pages)},commit(mutator,label){calls.commits.push(label);mutator(sandbox.store.project);}},
  contentProject:()=>structuredClone(sandbox.store.project),
  isPrecompiledTheme:()=>true,
  layoutDeck:pages=>{calls.layouts++;return layout(pages);},
  checkPrecompiledLayout:(pages,ids)=>checkPrecompiledLayout(pages,ids,{measure:async selected=>{calls.measure++;return measure(selected,sandbox);}}),
  setDesignBusy:(value,{release=true}={})=>{if(release)sandbox.busy=value;if(!value)sandbox.designController=null;},
  designProgress:()=>{},notify:()=>{},render:()=>{},
  referenceGeneration:{run:options=>{calls.fallback.push(structuredClone(options));return 'reference-result';}},
  generation:{active:false,start(){calls.started++;this.active=true;},batch(){calls.batches++;},finish(status){calls.finished.push(status);this.active=false;}},
  combinePreviewReview:(_retained,review)=>review,
 };
 vm.createContext(sandbox);vm.runInContext(functionSource,sandbox);
 return {sandbox,calls,run:options=>sandbox.runDesignedLayout({themeId:'curated-001',...options})};
}

test('actual dense pack falls back before any page commit or generation completion',async()=>{
 const body=Array.from({length:12},(_,i)=>`## 第${i+1}项检查\n这是必须完整保留的培训正文，需要按照真实文案安排阅读顺序与空间。`).join('\n');
 const f=fixture({pages:[sourcePage(body)],layout:realLayout});
 const before=structuredClone(f.sandbox.store.project);
 assert.equal(await f.run({targetPageIds:['p1'],instruction:'保留全部培训文案'}),'reference-result');
 assert.deepEqual(f.sandbox.store.project,before);
 assert.equal(f.calls.commits.length,0);assert.equal(f.calls.batches,0);assert.equal(f.calls.started,0);
 assert.deepEqual(f.calls.fallback,[{themeId:'curated-001',targetPageIds:['p1'],instruction:'保留全部培训文案'}]);
 assert.equal(f.calls.measure,0);assert.equal(f.sandbox.busy,false);assert.equal(f.sandbox.designController,null);
});

test('rendered overflow falls back without exposing otherwise source-exact pages',async()=>{
 const f=fixture({measure:async()=>({issues:[{kind:'text-overflow',severity:'error',pageId:'p1'}]})});
 await f.run();assert.equal(f.calls.measure,1);assert.equal(f.calls.commits.length,0);assert.equal(f.calls.fallback.length,1);
});

test('cancellation during measurement leaves original pages and does not start fallback',async()=>{
 const f=fixture({measure:async(_pages,sandbox)=>{sandbox.designController.abort();return {issues:[]};}});
 const before=structuredClone(f.sandbox.store.project);
 await assert.rejects(f.run(),error=>error.name==='AbortError');
 assert.deepEqual(f.sandbox.store.project,before);assert.equal(f.calls.commits.length,0);assert.equal(f.calls.fallback.length,0);
 assert.equal(f.sandbox.busy,false);assert.equal(f.sandbox.designController,null);
});

test('source edits during measurement are retained and candidate is never applied',async()=>{
 const f=fixture({measure:async(_pages,sandbox)=>{sandbox.store.project.pages[0].body='用户刚修改的正文';return {issues:[]};}});
 await assert.rejects(f.run(),/文稿已有变化/);
 assert.equal(f.sandbox.store.project.pages[0].body,'用户刚修改的正文');
 assert.equal(f.calls.commits.length,0);assert.equal(f.calls.fallback.length,0);assert.equal(f.sandbox.busy,false);
});

test('measurement errors preserve original project instead of bypassing the gate',async()=>{
 const f=fixture({measure:async()=>{throw Error('DOM measurement failed');}});
 const before=structuredClone(f.sandbox.store.project);
 await assert.rejects(f.run(),/DOM measurement failed/);
 assert.deepEqual(f.sandbox.store.project,before);assert.equal(f.calls.commits.length,0);assert.equal(f.calls.fallback.length,0);
 assert.equal(f.sandbox.busy,false);assert.equal(f.sandbox.designController,null);
});

test('safe candidates reuse measured pages and preserve the fast path',async()=>{
 const untouched={...sourcePage('另一页原文'),id:'p2',objects:[{id:'user-object',custom:true,type:'text',text:'用户对象'}]};
 const f=fixture({pages:[sourcePage(),untouched]});
 await f.run({targetPageIds:['p1']});
 assert.equal(f.calls.fallback.length,0);assert.equal(f.calls.layouts,1);assert.equal(f.calls.measure,1);
 assert.equal(f.calls.started,1);assert.equal(f.calls.batches,1);assert.equal(f.calls.commits.length,2);
 assert.deepEqual(f.calls.finished,['complete']);assert.equal(f.sandbox.store.project.stage,'editor');
 assert.equal(f.sandbox.store.project.designReview.status,'checked');assert.equal(f.sandbox.store.project.designReview.visionRan,false);
 assert.equal(f.sandbox.store.project.pages[0].objects[1].text,'原始正文');
 assert.deepEqual(f.sandbox.store.project.pages[1],untouched);
 assert.equal(f.sandbox.busy,false);assert.equal(f.sandbox.designController,null);
});
