import test from 'node:test';
import assert from 'node:assert/strict';
import {generationProgressSummary,mountGenerationProgress,createGenerationDraftRow} from '../public/generation-progress.js';
import {generationTasks} from '../public/generation-tasks.js';
const task=(overrides={})=>({id:'ref',kind:'reference',state:'running',phase:'planning',total:8,planned:5,completed:0,...overrides});
test('reference planning uses actual planned count without changing completed semantics',()=>{
 const s=generationProgressSummary(task({message:'已经规划8页'}));assert.equal(s.count,'已规划 5 / 8 页');assert.equal(s.completed,0);assert.equal(s.displayCompleted,5);assert.equal(s.ratio,5/8);assert.equal(s.phaseCounts.designing,'绘制 0 / 8');
 assert.equal(generationProgressSummary(task({planned:undefined,message:'已经规划8页'})).displayCompleted,0);
});
test('generation phase is authoritative and complete drawings still await review',()=>{
 const drawing=generationProgressSummary(task({phase:'planning',generationPhase:'designing',planned:8,completed:3}));assert.equal(drawing.count,'已生成 3 / 8 页');assert.equal(drawing.ratio,3/8);
 const reviewing=generationProgressSummary(task({generationPhase:'reviewing',planned:8,completed:8}));assert.equal(reviewing.status,'整稿检查中');assert.equal(reviewing.reviewStatus,'进行中');assert(reviewing.running);
 assert.equal(generationProgressSummary(task({state:'complete',generationPhase:'reviewing'})).reviewStatus,'通过');
});
test('terminal states retain exact counts and stop running state, invalid numbers are clamped',()=>{
 for(const state of ['failed','stopped','interrupted']){const s=generationProgressSummary(task({state,planned:3,completed:1}));assert.equal(s.count,'已规划 3 / 8 页');assert.equal(s.completed,1);assert.equal(s.running,false);}
 assert.equal(generationProgressSummary(task({planned:Infinity})).planned,0);assert.equal(generationProgressSummary(task({planned:99})).planned,8);assert.equal(generationProgressSummary(task({planned:-5})).planned,0);
});
// Minimal DOM exercises rendered surfaces without a browser/server or third-party dependency.
class Node {
 constructor(tag=''){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.style={setProperty(){}};this.className='';this._text='';this.hidden=false;this.classList={add:n=>{if(!this.className.split(' ').includes(n))this.className+=' '+n;},toggle:(n,on)=>{this.className=this.className.split(' ').filter(c=>c!==n).join(' ');if(on)this.className+=' '+n;}};}
 get childNodes(){return this.children;}get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(v){this._text=String(v);this.children=[];}
 setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}addEventListener(){}remove(){}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this._text='';this.children=nodes;}
}
const nativeSetInterval=globalThis.setInterval;globalThis.setInterval=(...args)=>{const timer=nativeSetInterval(...args);timer.unref?.();return timer;};
const find=(n,c)=>n.className.split(' ').includes(c)?n:n.children.map(x=>find(x,c)).find(Boolean);

test('rebuilding recovery rows preserves planning counts and actual phase without duplicate tasks',()=>{
 const previousDocument=globalThis.document,previousObserver=globalThis.ResizeObserver;
 globalThis.ResizeObserver=class{observe(){}disconnect(){}};
 globalThis.document={documentElement:{style:{setProperty(){}}},createElement:t=>new Node(t),createElementNS:(_,t)=>new Node(t),createTextNode:t=>{const n=new Node();n.textContent=t;return n;},querySelector:s=>s==='#app'?{before(){}}:null};
 try{
  for(const phase of ['planning','designing','repairing','reviewing']){
   const store={project:{id:'source',pages:[],generationDrafts:[]},past:[],future:[],subscribe(){},mark(){}};
   const generation=generationTasks({store});
   try{
    const job={id:'saved-job',planned:5,completed:phase==='planning'?0:3,total:8,phase,status:'cancelled',targetPageIds:[]};
    generation.showRecovery(job);generation.showRecovery(job);
    assert.equal(store.project.generationDrafts.length,1);
    const recovered=store.project.generationDrafts[0];
    assert.equal(recovered.planned,5);assert.equal(recovered.completed,job.completed);assert.equal(recovered.state,'stopped');
    assert.equal(recovered.phase,phase==='repairing'?'designing':phase);
    if(phase==='planning')assert.equal(generationProgressSummary(recovered).count,'已规划 5 / 8 页');
    assert.notEqual(generationProgressSummary(recovered).reviewStatus,'通过');
   }finally{store.project.generationDrafts=[];generation.refresh();}
  }
 }finally{globalThis.document=previousDocument;globalThis.ResizeObserver=previousObserver;}
});
test('expanded, collapsed and draft views share phase counts, accessible bar and stopped indicator',()=>{
 const previous=globalThis.document;globalThis.document={createElement:t=>new Node(t),createElementNS:(_,t)=>new Node(t),createTextNode:t=>{const n=new Node();n.textContent=t;return n;}};
 const host=new Node();let mounted;
 try{
  mounted=mountGenerationProgress(host);mounted.update(task());
  assert.equal(find(host,'gp-count').textContent,'已规划 5 / 8 页');assert.equal(find(host,'gp-segments').attributes['aria-valuenow'],'5');assert.equal(find(host,'gp-segments').attributes['aria-label'],'已规划页面');assert(find(host,'gp-phase-counts').textContent.includes('检查 待开始'));assert(find(host,'gp-steps').textContent.includes('布局规划'));assert(find(host,'is-current'));
  mounted.update(task({collapsed:true,state:'stopped'}));assert.equal(find(host,'gp-compact-count').textContent,'已规划 5 / 8 页');assert.equal(find(host,'is-current'),undefined);
  const draft=createGenerationDraftRow(task());assert(find(draft,'gp-draft-state').textContent.includes('已规划 5 / 8 页'));assert.equal(find(draft,'gp-segments').attributes['aria-valuenow'],'5');
  mounted.update(task({generationPhase:'reviewing',planned:8,completed:8}));assert.equal(find(host,'gp-status').textContent,'整稿检查中');assert(find(host,'gp-phase-counts').textContent.includes('检查 进行中'));assert(!find(host,'gp-steps').children[2].className.includes('is-done'));
  mounted.update({state:'running',phase:'designing',total:8,completed:3});assert(find(host,'gp-phase-counts').hidden);assert(find(host,'gp-steps').textContent.includes('文案已确认'));assert.equal(find(host,'gp-count').textContent,'3 / 8 页');
 }finally{mounted?.destroy();globalThis.document=previous;}
});
