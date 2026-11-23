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

test('current completed checkpoint offers explicit application; historical completion and running tasks do not',async()=>{
 const originals={document:globalThis.document,ResizeObserver:globalThis.ResizeObserver,setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval};
 const app=new Node('main');globalThis.document={documentElement:new Node('html'),createElement:tag=>new Node(tag),createElementNS:(_,tag)=>new Node(tag),createTextNode:text=>({textContent:text}),querySelector:selector=>selector==='#app'?app:null};globalThis.ResizeObserver=class{observe(){}disconnect(){}};globalThis.setInterval=()=>0;globalThis.clearInterval=()=>{};
 const job={id:'job-a',generationTaskId:'task-a',status:'running',total:1,targetPageIds:['p']},store={project:{id:'A',title:'稿件A',pages:[],referenceJob:job,generationDrafts:[]},past:[],future:[],mark(){},subscribe(){}};
 let resumes=0;const tasks=generationTasks({store,renderMini:()=>'',onStop(){},onOpenDrafts(){},onShowPage(){}});
 try{
  tasks.setResumeHandler({canResume:()=>true,resume:async()=>resumes++});tasks.showRecovery(job);
  tasks.syncReferenceJobs([{id:'job-a',projectId:'A',status:'running',completed:0,total:1}]);
  assert.equal(find(app.sibling,'gp-recovery-actions').hidden,true);
  tasks.syncReferenceJobs([{id:'job-a',projectId:'A',status:'completed',completed:1,total:1}]);
  const recovery=find(app.sibling,'gp-recovery-actions'),button=find(app.sibling,'gp-button gp-resume');
  assert.equal(recovery.hidden,false);assert.equal(button.lastElementChild.textContent,'查看并应用');assert.equal(resumes,0);
  await button.handlers.click();assert.equal(resumes,1);
  delete store.project.referenceJob;tasks.refresh();assert.equal(recovery.hidden,true);
  store.project.referenceJob=job;tasks.syncReferenceJobs([{id:'job-a',projectId:'A',status:'failed',completed:0,total:1}]);assert.equal(recovery.hidden,false);assert.equal(button.lastElementChild.textContent,'继续生成');assert.equal(resumes,1);
 }finally{Object.assign(globalThis,originals);}
});


test('deleted project tasks disappear from the draft list without removing other projects',()=>{
 const originals={document:globalThis.document,ResizeObserver:globalThis.ResizeObserver};
 const app=new Node('main');globalThis.document={documentElement:new Node('html'),createElement:tag=>new Node(tag),createElementNS:(_,tag)=>new Node(tag),createTextNode:text=>({textContent:text}),querySelector:selector=>selector==='#app'?app:null};globalThis.ResizeObserver=class{observe(){}disconnect(){}};
 const store={project:null,past:[],future:[],mark(){},subscribe(){}};
 const tasks=generationTasks({store,renderMini:()=>'',onStop(){},onOpenDrafts(){},onShowPage(){}}),rows=new Node('section');
 const rowIds=()=>{tasks.fillRows(rows);return rows.children.map(row=>row.dataset.taskId).sort();};
 try{
  tasks.syncReferenceJobs([{id:'job-a',projectId:'A',status:'completed',completed:1,total:1},{id:'job-b',projectId:'B',status:'cancelled',completed:0,total:1}]);
  assert.deepEqual(rowIds(),['reference-job-a','reference-job-b']);
  tasks.removeProject('A');assert.deepEqual(rowIds(),['reference-job-b']);
  tasks.syncReferenceJobs([{id:'job-c',projectId:'C',status:'failed',completed:0,total:1}]);
  tasks.retainProjects(['C']);assert.deepEqual(rowIds(),['reference-job-c']);
  tasks.retainProjects([]);assert.deepEqual(rowIds(),[]);
 }finally{Object.assign(globalThis,originals);}
});
