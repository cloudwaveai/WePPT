import test from 'node:test';import assert from 'node:assert/strict';
import {createReferenceGeneration} from '/app/public/reference-generation.js';
import {referenceFingerprint,completedReferenceExport} from '/app/public/reference-delivery.js';

test('actual controller views partial pages, retains edits and resumes once after a lost response',async t=>{
 const old=globalThis.document;globalThis.document={querySelector:()=>null};t.after(()=>globalThis.document=old);
 const source={id:'source',title:'部分稿',themeId:'theme',designEngine:'svg',stage:'draft',pages:[0,1].map(i=>({id:'p'+i,title:'标题'+i,body:'原文'+i,role:'content',objects:[]}))};
 const generated=source.pages.map(p=>({...p,themeId:'theme',objects:[{id:'text-'+p.id,type:'text',text:p.body}]}));
 let status='partial',busy=false,handler;const requests=[];
 const store={project:structuredClone(source),past:[],future:[],mark(){},subscribe(){},async flush(){},commit(fn){fn(this.project);}};
 store.project.referenceJob={id:'job',themeId:'theme',targetPageIds:['p0','p1'],baseline:referenceFingerprint(source)};
 const request=async(path,body)=>{requests.push({path,body:structuredClone(body)});
  if(path.endsWith('/resume')){assert.match(body.resumeRequestId,/^[0-9a-f-]{36}$/);status='completed';throw new TypeError('lost accepted response');}
  if(path.endsWith('/status'))return {id:'job',projectId:'source',themeId:'theme',status,completed:status==='completed'?2:1,total:2,planned:2,sourcePages:structuredClone(source.pages),pages:structuredClone(status==='completed'?generated:generated.slice(0,1)),failures:[],designReview:{status:'checked',reviewEvidence:{status:'pass',checkedPageIds:['p0','p1']},issues:[]}};
  throw Error('Unexpected request '+path);
 };
 const generation={setResumeHandler(h){handler=h;},detach(){},start(){return 'generation';},update(){},finish(){},get active(){return null;}};
 const controller=createReferenceGeneration({store,request,contentProject:()=>structuredClone(store.project),isBusy:()=>busy,setBusy:v=>busy=v,setController(){},onProgress(){},onApplied(){},notify(){},generation});t.after(()=>controller.destroy());
 const task={projectId:'source',referenceJobId:'job'};await handler.viewCompleted(task);assert.equal(store.project.stage,'editor');assert.equal(completedReferenceExport(store.project).pages.length,1);
 store.project.pages[0].title='人工标题';store.project.pages[0].body='人工正文';store.project.pages[0].objects[0].text='人工排版';
 await handler.viewCompleted(task);assert.equal(store.project.pages[0].title,'人工标题');
 await handler.resume(task);assert.equal(busy,false);assert.equal(store.project.pages[0].objects[0].text,'人工排版');assert.equal(store.project.pages[0].body,'人工正文');assert.equal(store.project.pages[1].objects[0].text,source.pages[1].body);assert.equal(store.project.referenceJob,undefined);assert.equal(store.project.designReview.status,'needs-attention');
 assert.equal(requests.filter(r=>r.path.endsWith('/resume')).length,1);assert.equal(requests.filter(r=>r.path.endsWith('/start')).length,0);
});
