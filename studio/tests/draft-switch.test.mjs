import test from 'node:test';
import assert from 'node:assert/strict';
import {generationTasks} from '../public/generation-tasks.js';

class Node {
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={setProperty(){}};this.classList={add(){},toggle(){}};this.handlers={};this.attributes={};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(key,value){this.attributes[key]=value;}
 removeAttribute(key){delete this.attributes[key];}
 addEventListener(name,fn){this.handlers[name]=fn;}
 before(node){this.sibling=node;}
 remove(){}
 get lastElementChild(){return this.children.at(-1);}
}
const find=(node,className)=>node?.className===className?node:node?.children?.map(child=>find(child,className)).find(Boolean);

const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const tick=()=>new Promise(r=>setImmediate(r));
function setup(t,open){
 const originals=Object.fromEntries(['document','ResizeObserver','setInterval','clearInterval','confirm'].map(k=>[k,globalThis[k]]));t.after(()=>Object.assign(globalThis,originals));
 const app=new Node('main'),rows=new Node('section');globalThis.document={documentElement:new Node('html'),createElement:tag=>new Node(tag),createElementNS:(_,tag)=>new Node(tag),createTextNode:text=>({textContent:text}),querySelector:s=>s==='#app'?app:s==='#generation-draft-rows'?rows:null};globalThis.ResizeObserver=class{observe(){}disconnect(){}};globalThis.setInterval=()=>0;globalThis.clearInterval=()=>{};globalThis.confirm=()=>true;
 const store={project:{id:'A',title:'A',pages:[],generationDrafts:[]},past:[],future:[],mark(){},subscribe(){}};
 const tasks=generationTasks({store,onStop(){},onOpenDrafts(){},onShowPage(){},onOpenProject:async id=>open?open(id,store):store.project={id,title:id,pages:[],generationDrafts:[]}});
 const errors=[];tasks.syncReferenceJobs(['A','B','C'].map(id=>({id:'job-'+id,projectId:id,projectTitle:id,status:'partial',completed:0,total:1})));
 const click=(id,label)=>{tasks.fillRows(rows);const row=rows.children.find(r=>r.dataset.taskId==='reference-job-'+id);const actions=find(row,'gp-draft-actions');const button=actions.children.find(b=>b.children.at(-1).textContent===label);return button.handlers.click();};
 return {store,tasks,click,errors,handler:extra=>tasks.setResumeHandler({canResume:()=>true,onError:e=>errors.push(e.message),...extra})};
}
test('retry continues in background while another project View navigates without cancelling',async t=>{
 const f=setup(t),pending=deferred();let retries=0;f.handler({retry:()=>{retries++;return pending.promise;}});
 const running=f.click('B','重新生成');await tick();assert.equal(retries,1);assert.equal(f.store.project.id,'B');
 await f.click('C','查看');assert.equal(f.store.project.id,'C');assert.deepEqual(f.errors,[]);
 pending.resolve();await running;assert.equal(f.store.project.id,'C');
});
test('ending the detached retry does not clear a newer pending action lock',async t=>{
 const f=setup(t),retry=deferred(),view=deferred();f.handler({retry:()=>retry.promise,viewCompleted:()=>view.promise});
 const running=f.click('B','重新生成');await tick();
 // The real completed-page action holds the lock until its save/navigation finishes.
 f.tasks.syncReferenceJobs([{id:'job-C',projectId:'C',status:'partial',completed:1,total:1}]);
 const viewing=f.click('C','查看已完成页');await tick();retry.resolve();await running;
 await f.click('A','查看');assert.equal(f.store.project.id,'B');
 view.resolve();await viewing;await f.click('A','查看');assert.equal(f.store.project.id,'A');
});
test('failed navigation releases the lock and never starts retry in another project',async t=>{
 let failed=true;const f=setup(t,async(id,store)=>{if(failed)throw Error('读取失败');store.project={id,title:id,pages:[],generationDrafts:[]};});let retries=0;f.handler({retry:async()=>retries++});
 await f.click('B','重新生成');assert.equal(retries,0);assert.equal(f.store.project.id,'A');assert.deepEqual(f.errors,['读取失败']);
 failed=false;await f.click('C','查看');assert.equal(f.store.project.id,'C');
});
test('navigation returning without switching prevents wrong-project retry and unlocks next View',async t=>{
 let skip=true;const f=setup(t,async(id,store)=>{if(!skip)store.project={id,title:id,pages:[],generationDrafts:[]};});let retries=0;f.handler({retry:async()=>retries++});
 await f.click('B','重新生成');assert.equal(retries,0);assert.equal(f.store.project.id,'A');assert.equal(f.errors.length,1);
 skip=false;await f.click('C','查看');assert.equal(f.store.project.id,'C');
});
