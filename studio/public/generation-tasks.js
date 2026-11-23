import {recoveryKey} from './account-session.js';
import {mountGenerationProgress,createGenerationDraftRow} from './generation-progress.js';

export function generationTasks({store,renderMini,onStop,onOpenDrafts,onShowPage,onOpenProject}){
 let active=null,selected=null,component=null,host=null,resumeHandler=null,resuming=null;
 const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--generation-height',`${host?.getBoundingClientRect().height||0}px`));
 const remoteTasks=new Map(),deletedReferences=new Set(),deletedTasks=new Set();
 const removed=task=>deletedTasks.has(task.id)||deletedReferences.has(task.referenceJobId);
 function localTasks(){return store.project?.generationDrafts||[];}
 function tasks(){
  const all=new Map([...remoteTasks.values()].map(t=>[t.referenceJobId||t.id,t]));
  for(const task of localTasks()){
   const key=task.referenceJobId||task.id,remote=all.get(key);
   all.set(key,remote&&task.id!==active?.id&&!(task.state==='complete'&&task.applied)?{...task,...remote,id:task.id}:task);
  }
  return [...all.values()].filter(t=>!removed(t)).sort((a,b)=>Number(new Date(b.updatedAt))-Number(new Date(a.updatedAt)));
 }
 function pagesFor(task){return task.projectId===store.project?.id?store.project.pages:[];}
 async function viewTask(id){
  const task=tasks().find(t=>t.id===id);if(!task)return;
  if(task.kind==='reference'&&task.id!==active?.id){await resumeTask(id,true);return;}
  selected=id;task.collapsed=false;write(task);document.querySelector('#modal')?.close();refresh();host?.scrollIntoView({block:'nearest'});
 }
 async function viewCompletedTask(id){
  const task=tasks().find(t=>t.id===id);if(!task||resuming)return;resuming=id;refresh();
  try{document.querySelector('#modal')?.close();await resumeHandler?.viewCompleted?.(task);}finally{resuming=null;refresh();}
 }
 function stopTask(id){const task=tasks().find(t=>t.id===id);if(!task)return;Promise.resolve().then(()=>active?.id===id?onStop():resumeHandler?.stop?.(task)).catch(e=>resumeHandler?.onError?.(e));}
 function write(task){
  if(removed(task))return;
  for(const [key,value]of remoteTasks)if(value.id===task.id&&key!==(task.referenceJobId||task.id))remoteTasks.delete(key);
  remoteTasks.set(task.referenceJobId||task.id,structuredClone(task));
  if(store.project?.id!==task.projectId)return;
  if(active?.id===task.id)Object.assign(active,task);
  const rows=[task,...localTasks().filter(t=>t.id!==task.id&&(!task.referenceJobId||t.referenceJobId!==task.referenceJobId))].slice(0,12);
  store.project.generationDrafts=structuredClone(rows);
  // Task status is not an editable slide operation; undo must not resurrect running jobs.
  for(const entry of [...store.past,...store.future])if(entry.project.id===task.projectId)entry.project.generationDrafts=structuredClone(rows);
  store.mark(true);
 }
 function display(task){const shown=task.state==='running'&&task.kind!=='reference'&&task.id!==active?.id?{...task,state:'interrupted',message:'生成已中断，已完成页面已保留。'}:task;const applyReady=task.kind==='reference'&&task.state==='complete'&&!task.applied&&task.projectId===store.project?.id&&task.referenceJobId===store.project?.referenceJob?.id;return {...shown,applyReady,resumable:!!resumeHandler?.canResume(task)&&(shown.state!=='complete'||applyReady),resumePending:resuming===task.id};}
 async function resumeTask(id,view=false){
  const task=tasks().find(t=>t.id===id);if(!task||resuming||(!view&&!display(task).resumable))return;
  resuming=id;document.querySelector('#modal')?.close();
  try{
   if(task.kind==='reference'&&store.project?.id!==task.projectId&&onOpenProject)await onOpenProject(task.projectId);
   if(store.project?.id!==task.projectId)return;
   selected=id;task.collapsed=false;write(task);refresh();resuming=null;
   if(task.kind==='reference'&&(!view||['running','complete'].includes(task.state)))await resumeHandler?.resume(task,{manual:!view});
  }finally{resuming=null;refresh();}
 }
 function forgetReferences(ids){
  for(const id of ids)deletedReferences.add(id);
  for(const [key,task]of remoteTasks)if(removed(task))remoteTasks.delete(key);
  const clean=project=>{if(!project)return false;const before=JSON.stringify([project.generationDrafts,project.referenceJob]);if(project.generationDrafts)project.generationDrafts=project.generationDrafts.filter(t=>!removed(t));if(deletedReferences.has(project.referenceJob?.id))delete project.referenceJob;return before!==JSON.stringify([project.generationDrafts,project.referenceJob]);};
  const changed=clean(store.project);for(const entry of [...store.past,...store.future])clean(entry.project);
  if(active&&removed(active))active=null;
  if(changed)store.mark(true);refresh();
 }
 async function retryTask(id){
  const task=tasks().find(t=>t.id===id);if(!task||resuming)return;
  if(!confirm('沿用这份演示稿的文案和模板重新生成？新结果通过检查后才会应用。'))return;
  resuming=id;refresh();
  let released=false;
  try{
   if(store.project?.id!==task.projectId)await onOpenProject?.(task.projectId);
   if(store.project?.id!==task.projectId)throw Error('请先打开对应演示稿。');
   // The handler owns the long-running generation session. The draft action
   // lock only covers navigation; retaining it would block every View click.
   resuming=null;released=true;
   await resumeHandler?.retry?.(task);
  }finally{if(!released)resuming=null;refresh();}
 }
 async function deleteTask(id){
  const task=tasks().find(t=>t.id===id);if(!task||resuming)return;
  if(!confirm(task.state==='running'?'停止生成并删除这条草稿？文案和已保存页面会保留。':'删除这条草稿？文案、模板和已保存页面会保留。'))return;
  resuming=id;refresh();
  try{
   if(task.kind==='reference')await resumeHandler.remove(task);
   else{if(store.project?.id!==task.projectId)await onOpenProject?.(task.projectId);if(store.project?.id!==task.projectId)throw Error('请先打开对应演示稿。');if(active?.id===id){await onStop();active=null;}deletedTasks.add(id);}
   forgetReferences(task.referenceJobId?[task.referenceJobId]:[]);await store.flush();
  }finally{resuming=null;refresh();}
 }
 function refresh(){
  const rows=document.querySelector('#generation-draft-rows');if(rows)fillRows(rows);
  const task=tasks().find(t=>t.projectId===store.project?.id&&t.id===(selected||active?.id));
  if(!task){component?.destroy();component=null;observer.disconnect();host?.remove();host=null;document.documentElement.style.setProperty('--generation-height','0px');return;}
  if(!host){host=document.createElement('div');host.id='generation-task-host';document.querySelector('#app').before(host);component=mountGenerationProgress(host,{renderMini,onResume:id=>resumeTask(id).catch(e=>resumeHandler?.onError?.(e)),onStop:stopTask,onViewCompleted:id=>viewCompletedTask(id).catch(e=>resumeHandler?.onError?.(e)),onOpenDrafts,onShowPage,onCollapse:collapsed=>{const current=tasks().find(t=>t.id===(selected||active?.id));if(current){current.collapsed=collapsed;write(current);refresh();}}});observer.observe(host);}
  component.update(display(task),pagesFor(task));
 }
 function fillRows(container){container.replaceChildren(...tasks().map(task=>createGenerationDraftRow(display(task),pagesFor(task),{renderMini,onViewCompleted:id=>viewCompletedTask(id).catch(e=>resumeHandler?.onError?.(e)),onRetry:id=>retryTask(id).catch(e=>resumeHandler?.onError?.(e)),onDelete:id=>deleteTask(id).catch(e=>resumeHandler?.onError?.(e)),onResume:id=>resumeTask(id).catch(e=>resumeHandler?.onError?.(e)),onStop:stopTask,onView:id=>viewTask(id).catch(e=>resumeHandler?.onError?.(e))})));}
 store.subscribe(type=>{
  if(type==='change')for(const task of tasks())if(task.state==='running'&&task.kind!=='reference'&&task.id!==active?.id){task.state='interrupted';task.message='生成已中断，已完成页面已保留。';write(task);}
  if(type==='load'){
   selected=null;forgetReferences([]);
   const owner=store.project?.id;let hasRecovery=false;try{hasRecovery=!!localStorage.getItem(recoveryKey(owner));}catch{}
   queueMicrotask(()=>{if(store.project?.id!==owner)return;for(const task of tasks())if(task.state==='running'&&task.kind!=='reference'&&task.id!==active?.id){task.state='interrupted';task.message='网页已重新打开，生成已中断；已完成页面已保留。';if(!hasRecovery)write(task);}refresh();});
  }
  refresh();
 });
 return {
  showRecovery(job){
   if(active||!job||deletedReferences.has(job.id))return;
   let task=tasks().find(t=>t.referenceJobId===job.id||t.id===job.generationTaskId);
   if(!task){
    const now=Date.now();task={id:job.generationTaskId||crypto.randomUUID(),projectId:store.project.id,title:store.project.title,kind:'reference',referenceJobId:job.id,state:job.status==='cancelled'?'stopped':'interrupted',phase:job.phase==='repairing'?'designing':job.phase||'planning',planned:job.planned||0,completed:job.completed||0,total:job.total,startedAt:now,updatedAt:now,message:'文案和已完成页面已保留，点击继续生成同步任务进度。',completedPageIds:[],targetPageIds:job.targetPageIds||[],collapsed:false};store.project.generationDrafts=[task,...localTasks()].slice(0,12);
   }
   if(!selected){selected=task.id;task.collapsed=false;remoteTasks.set(task.referenceJobId||task.id,structuredClone(task));const local=localTasks().find(t=>t.id===task.id);if(local)local.collapsed=false;}
   refresh();
  },
  setResumeHandler(handler){resumeHandler=handler;refresh();},
  get active(){return active;},
  start(ids,options={}){const now=Date.now();active={id:options.id||crypto.randomUUID(),projectId:store.project.id,title:store.project.title,state:'running',phase:'planning',completed:0,total:ids.length,startedAt:now,updatedAt:now,message:'正在准备逐页排版，请保持此网页打开。',completedPageIds:[],targetPageIds:ids,collapsed:false,...options};selected=active.id;write(active);refresh();return active.id;},
  update(patch){if(!active)return;Object.assign(active,patch,{updatedAt:Date.now()});write(active);refresh();},
  progress(event){if(!active)return false;this.update({message:event.message||active.message,phase:active.kind==='reference'?active.phase:/review|repair|audit/.test(event.phase||'')?'reviewing':active.completed?'designing':'planning'});return true;},
  batch(pages,total){if(!active)return;const ids=[...new Set([...active.completedPageIds,...pages.map(p=>p.id)])];this.update({completedPageIds:ids,completed:ids.length,total:total||active.total,phase:'designing'});},
  finish(state,message){if(!active)return;this.update({state,applied:state==='complete',message:message||active.message,phase:state==='complete'?'complete':active.phase,collapsed:true});active=null;refresh();},
  detach(){if(active){this.update({state:'running',message:'正在后台生成，可切换到其他演示稿。'});active=null;}selected=null;refresh();},
  retainProjects(ids){
   const allowed=new Set(ids);
   for(const [key,task] of remoteTasks)if(!allowed.has(task.projectId)&&task.id!==active?.id)remoteTasks.delete(key);
   refresh();
  },
  removeProject(id){
   for(const [key,task] of remoteTasks)if(task.projectId===id)remoteTasks.delete(key);
   if(active?.projectId===id)active=null;
   selected=null;refresh();
  },
  syncReferenceJobs(jobs){
   for(const job of jobs){
    if(!job?.id||!job.projectId||deletedReferences.has(job.id))continue;
    const known=tasks().find(t=>t.referenceJobId===job.id);
    if((known&&active&&known.id===active.id)||known?.applied&&job.status==='completed')continue;
    const state=['queued','running','cancelling'].includes(job.status)?'running':job.status==='completed'?'complete':job.status==='cancelled'?'stopped':job.status==='interrupted'?'interrupted':'failed';
    const partialIds=store.project?.id===job.projectId&&store.project.referenceJob?.id===job.id?store.project.referenceJob.appliedPageIds||[]:[];
    remoteTasks.set(job.id,{...known,id:known?.id||'reference-'+job.id,referenceJobId:job.id,projectId:job.projectId,title:job.projectTitle||known?.title||'演示稿',kind:'reference',themeId:job.themeId,instruction:job.instruction,targetPageIds:job.targetPageIds,canResume:job.canResume,resumeReason:job.resumeReason,state,phase:job.phase||'planning',planned:job.planned||0,completed:job.completed||0,total:job.total,startedAt:job.createdAt,updatedAt:job.updatedAt,message:job.status==='completed'?'生成已完成，点击查看后校验并应用到对应演示稿。':job.message||'后台生成任务',completedPageIds:known?.applied?known.completedPageIds:partialIds,collapsed:known?.collapsed??true});
   }
   refresh();
   const rows=document.querySelector('#generation-draft-rows');if(rows)fillRows(rows);
  },
  forgetReferences,fillRows,refresh
 };
}
