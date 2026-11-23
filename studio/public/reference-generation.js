import {sameSavedProject} from './project-version-recovery.js';
import {referenceFingerprint, matchesReferenceBaseline, applyReferencePartial, mergeReferenceCompletion, completeReferenceApplication, reconcileAppliedReference} from './reference-delivery.js';
import {designReferenceProject,completedReferenceResult} from './reference-design-pipeline.js';
const fingerprint=referenceFingerprint;
export function createReferenceGeneration({store,request,contentProject,isBusy,setBusy,setController,onProgress,onApplied,notify,generation,onOpenProject,onApplicationConflict,onOpenGeneratedCopy}){
 let session=null,draftsHost=null,listPending=null;
 async function syncDrafts(){
  if(listPending)return listPending;
  listPending=(async()=>{const [result,projects]=await Promise.all([request('/api/design/reference-jobs/list',{},AbortSignal.timeout(10000)),request('/api/projects',undefined,AbortSignal.timeout(10000))]);if(!Array.isArray(result?.jobs)||!Array.isArray(projects?.projects))throw Error('生成任务列表无效。');const ids=projects.projects.map(p=>p.id);generation?.retainProjects?.(ids);generation?.forgetReferences?.(result.deletedJobIds||[]);generation?.syncReferenceJobs?.(result.jobs.filter(j=>ids.includes(j.projectId)));if(draftsHost?.isConnected)generation?.fillRows(draftsHost);return result.jobs;})();
  try{return await listPending;}finally{listPending=null;}
 }
 const listTimer=setInterval(()=>{const dialog=draftsHost?.closest?.('dialog');if(draftsHost?.isConnected&&(!dialog||dialog.open)||store.project?.referenceJob&&!session)void syncDrafts().catch(()=>{});},2000);
 listTimer.unref?.();
 async function fillDrafts(host){draftsHost=host;generation?.fillRows(host);try{await syncDrafts();}catch(error){if(host.isConnected&&!host.childNodes.length){const message=document.createElement('p');message.textContent='任务列表暂时无法同步，请重新打开草稿箱。';host.append(message);}}}
 async function detach(){
  const old=session;if(!old)return;
  old.detached=true;session=null;
  generation?.detach?.();setBusy(false);setController(null);
  // Let a pre-saved creation request reach the server before dropping its watcher.
  if(old.starting)await old.creationDone;
  old.controller.abort(new DOMException('已转到后台生成。','AbortError'));
  // Save only the currently bound project's checkpoint; no background page writes.
  if(store.project?.id===old.owner)await store.flush();
 }

 function remember(value){
  store.project.referenceJob=value;
  for(const item of [...store.past,...store.future])if(item.project.id===store.project.id)item.project.referenceJob=structuredClone(value);
  store.mark(true);
 }
 function commitApplication(next,label){
  store.commit(p=>{for(const key of Object.keys(p))delete p[key];Object.assign(p,next);},label);
 }
 function sealApplicationHistory(jobId){
  for(const entry of [...store.past,...store.future]){
   const p=entry.project;if(p.id!==store.project.id)continue;
   p.referenceApplications=structuredClone(store.project.referenceApplications);
   if(p.referenceJob?.id===jobId)delete p.referenceJob;
   for(const task of p.generationDrafts||[])if(task.referenceJobId===jobId){task.applied=true;task.state='complete';task.phase='complete';}
  }
 }
 async function offerGeneratedCopy(result,jobId,cause){
  if(!onApplicationConflict||!onOpenGeneratedCopy)throw Object.assign(Error('生成已完成，当前稿有修改或保存冲突；可保留当前稿并打开生成结果副本。'),{code:'REFERENCE_APPLICATION_CONFLICT',cause});
  const copy=structuredClone(result);copy.id=crypto.randomUUID();copy.revision=0;copy.title=`${result.title||'演示文稿'}（生成结果副本）`;
  for(const key of ['referenceJob','referenceApplications','generationDrafts','referenceResultIdentity','updatedAt','previewDrafts'])delete copy[key];
  copy.generatedFrom={projectId:result.id,jobId};
  return onApplicationConflict({message:'生成结果已经完成。当前稿有修改或保存冲突，可以保留当前稿并打开生成结果副本。',openCopy:async()=>{
   let saved;
   try{const response=await request('/api/projects/'+encodeURIComponent(copy.id),copy,AbortSignal.timeout(20000),'PUT');saved={...copy,revision:response.revision,updatedAt:response.updatedAt};}
   catch(error){const remote=await request('/api/projects/'+encodeURIComponent(copy.id),undefined,AbortSignal.timeout(10000)).catch(()=>null);if(!remote||!sameSavedProject(copy,remote))throw error;saved=remote;}
   await onOpenGeneratedCopy(saved);notify('已打开生成结果副本，原稿和未保存修改已保留。');return saved;
  }});
 }
 const pendingApplications=new Map();
 function deliverCompleted(state){
  if(pendingApplications.has(state.id))return pendingApplications.get(state.id);
  const pending=deliverCompletedOnce(state).finally(()=>pendingApplications.delete(state.id));pendingApplications.set(state.id,pending);return pending;
 }
 async function deliverCompletedOnce(state){
  const project=store.project,jobId=state.id;
  if(state.projectId!==project?.id||!Array.isArray(state.sourcePages)||!Array.isArray(state.targetPageIds))throw Error('生成结果的项目或来源不匹配。');
  const result=completedReferenceResult({...structuredClone(project),pages:structuredClone(state.sourcePages)},state,{themeId:state.themeId,targetPageIds:state.targetPageIds});
  const reconciled=reconcileAppliedReference(project,result,jobId);
  if(!reconciled&&(!project.referenceJob||project.referenceJob.id!==jobId||!matchesReferenceBaseline(project,project.referenceJob)))return offerGeneratedCopy(result,jobId);
  try{await store.flush();}catch(error){return offerGeneratedCopy(result,jobId,error);}
  // flush may have adopted a newer server version; decide again against that exact document.
  const before=structuredClone(store.project),already=reconcileAppliedReference(before,result,jobId);
  if(!already&&(!before.referenceJob||before.referenceJob.id!==jobId||!matchesReferenceBaseline(before,before.referenceJob)))return offerGeneratedCopy(result,jobId);
  const next=already||completeReferenceApplication(before,mergeReferenceCompletion(before,result),jobId);
  commitApplication(next,'应用已完成的生成结果');
  try{await store.flush();}
  catch(error){
   if(store.project.id===before.id&&sameSavedProject({...store.project,generationDrafts:next.generationDrafts},next)){store.project=before;store.dirty=true;store.backup?.();}
   return offerGeneratedCopy(result,jobId,error);
  }
  sealApplicationHistory(jobId);generation?.syncReferenceJobs?.([{...state,projectTitle:store.project.title}]);onApplied(store.project.pages[0]?.id);notify(already?'已打开保存的生成结果，保留当前编辑。':'生成结果已应用，可以编辑或导出。');return next;
 }
 async function run({mode='reference',themeId=store.project?.themeId,targetPageIds,jobId,instruction='',resumeFailed=true}={}){
  if(!['reference','image'].includes(mode))throw Error('未知的整稿生成方式。');
  if(isBusy()||session)throw Error('当前生成还在进行，请完成或停止后再开始。');
  if(!store.project?.pages?.length)throw Error('请先确认文案。');
  const owner=store.project.id,baseline=fingerprint(store.project),source=contentProject(),saved=store.project.referenceJob;
  delete source.referenceJob;
  if(jobId&&(!saved||saved.id!==jobId||!matchesReferenceBaseline(store.project,saved)))throw Error('文稿已有修改，旧任务不会覆盖新内容。请重新确认模板生成。');
  const controller=new AbortController();let creationFinished;const creationDone=new Promise(resolve=>creationFinished=resolve),current={owner,controller,detached:false,starting:!jobId,creationDone};session=current;setController(controller);setBusy(true);
  const scopedRequest=async(path,body,signal)=>{if(current.detached&&path==='/api/design/reference-jobs/cancel')return {status:'running'};try{return await request(path,body,signal);}finally{if(path==='/api/design/reference-jobs/start'){current.starting=false;creationFinished();}}};
  let taskId,completedResult;
  const updateTask=patch=>{if(taskId&&generation?.active?.id===taskId)generation.update(patch);};
  const finishTask=(state,message)=>{if(taskId&&generation?.active?.id===taskId)generation.finish(state,message);};
  const own=()=>{if(current.detached)throw new DOMException('已转到后台生成。','AbortError');if(store.project?.id!==owner||!matchesReferenceBaseline(store.project,store.project.referenceJob||{baseline})){controller.abort();throw Error('文稿已发生变化，生成结果未覆盖你的修改。');}};
  try{
   taskId=generation?.start(targetPageIds||source.pages.map(p=>p.id),{...(jobId&&saved?.id===jobId&&saved.generationTaskId?{id:saved.generationTaskId}:{}),kind:'reference',designMode:mode,themeId,instruction});
   updateTask({kind:'reference',designMode:mode,planned:saved?.planned||0,message:mode==='image'?'Image 正在按所选风格设计整稿；完成规划、逐页生成和整稿检查后应用。':'正在依照所选模板逐页重绘；整份完成并校验后进入编辑。',completedPageIds:[]});
   const result=await designReferenceProject(source,{themeId,targetPageIds,instruction,jobId,resumeFailed,request:scopedRequest,signal:controller.signal,
    onJobStarted:async id=>{own();const completed=saved?.id===id?saved.completed||0:0;remember({...saved,id,mode,generationTaskId:taskId,themeId,instruction,targetPageIds:targetPageIds||source.pages.map(p=>p.id),baseline,status:'running',completed,planned:saved?.id===id?saved.planned||0:0,phase:saved?.id===id?saved.phase||'planning':'planning',total:targetPageIds?.length||source.pages.length});updateTask({referenceJobId:id,completed,completedPageIds:[]});await store.flush();},
    onProgress:event=>{own();const old=store.project.referenceJob;if(old&&(old.completed!==event.completed||old.total!==event.total||old.planned!==event.planned||old.phase!==event.generationPhase))remember({...old,completed:event.completed,planned:event.planned,phase:event.generationPhase,total:event.total});updateTask({completed:event.completed,planned:event.planned,total:event.total,completedPageIds:[],phase:event.generationPhase==='repairing'?'designing':event.generationPhase,message:event.message});onProgress({...event,message:mode==='image'?`Image 整稿设计：${event.message||`${event.completed} / ${event.total} 页`}`:event.message||`按模板绘制：${event.completed} / ${event.total} 页`});const host=document.querySelector('#design-progress');if(host){host.dataset.background='true';host.title=event.message;}}
   });
   completedResult=result;own();const merged=mergeReferenceCompletion(store.project,result);commitApplication(completeReferenceApplication(store.project,merged,store.project.referenceJob.id),'应用按模板重绘的整份演示稿');
   await store.flush();sealApplicationHistory(result.referenceResultIdentity?.jobId||saved?.id||store.project.generationDrafts?.find(t=>t.id===taskId)?.referenceJobId);if(current.detached||store.project?.id!==owner)return null;const completedPageIds=targetPageIds||source.pages.map(p=>p.id);updateTask({completed:completedPageIds.length,total:completedPageIds.length,completedPageIds});finishTask('complete',result.pages.every(p=>p.imageDesign?.editableArtwork)?'整份页面已完成并应用，文字、线条和图片可分别编辑。':'整份页面已完成并应用。');await store.flush();if(current.detached||store.project?.id!==owner)return null;onApplied(result.pages[0]?.id);notify(merged.designReview?.status==='needs-attention'?'生成已完成，已保留你的手动修改，可重新检查编辑页。':result.pages.every(p=>p.imageDesign?.editableArtwork)?'整份页面已生成，文字、线条和图片可分别编辑。':'整份页面已生成并通过检查。');
  }catch(error){
   if(current.detached)return null;
   if(completedResult){finishTask('complete','生成已完成，结果已保留；可查看应用或打开副本。');return offerGeneratedCopy(completedResult,completedResult.referenceResultIdentity?.jobId||saved?.id,error);}
   if(store.project?.id===owner&&store.project.referenceJob)remember({...store.project.referenceJob,status:controller.signal.aborted?'cancelled':'paused',message:error.message});
   finishTask(controller.signal.aborted?'stopped':'failed',error.message||'任务未完成，原稿已保留，可继续生成。');
   throw error;
  }finally{creationFinished();if(session===current){finishTask('interrupted','生成已中断，原稿已保留，可继续生成。');session=null;setBusy(false);renderRecovery();}}
 }
 function renderRecovery(){
  const old=document.querySelector('#design-recovery');if(old?.dataset.reference==='true')old.remove();
  const job=store.project?.referenceJob;if(!job||session)return false;
  generation?.showRecovery?.(job);return true;
 }
 generation?.setResumeHandler?.({
  canResume:task=>!!task.referenceJobId&&task.canResume!==false,
  onError:error=>notify(error.message),
  stop:async task=>{await request('/api/design/reference-jobs/cancel',{id:task.referenceJobId},AbortSignal.timeout(20000));await syncDrafts();},
  remove:async task=>{
   if(session&&generation?.active?.referenceJobId===task.referenceJobId)await detach();
   await request('/api/design/reference-jobs/delete',{id:task.referenceJobId,stop:true},AbortSignal.timeout(120000));
  },
  viewCompleted:async task=>{
   if(session)await detach();
   if(store.project?.id!==task.projectId&&onOpenProject)await onOpenProject(task.projectId);
   if(store.project?.id!==task.projectId)throw Error('请先打开对应演示稿。');
   const state=await request('/api/design/reference-jobs/status',{id:task.referenceJobId},AbortSignal.timeout(20000));
   const partial=applyReferencePartial(store.project,state);
   store.commit(p=>{p.pages=partial.pages;p.stage=partial.stage;p.designReview=partial.designReview;p.referenceJob=partial.referenceJob;},'编辑已完成的生成页面');
   remember(partial.referenceJob);await store.flush();onApplied(partial.referenceJob.appliedPageIds[0]);
   notify(`已打开 ${partial.referenceJob.appliedPageIds.length} 个完成页，可编辑或导出；未完成页仍保留原文。`);
  },
  retry:async task=>{
   if(store.project?.id!==task.projectId)throw Error('请先打开对应演示稿。');
   const saved=store.project.referenceJob?.id===task.referenceJobId?store.project.referenceJob:null;
   document.querySelector('#modal')?.close();
   return run({mode:saved?.mode||task.designMode||'reference',themeId:saved?.themeId||task.themeId||store.project.themeId,instruction:saved?.instruction??task.instruction??''});
  },
  resume:async (task,{manual=true}={})=>{
   if(store.project?.id!==task.projectId&&onOpenProject)await onOpenProject(task.projectId);
   if(store.project?.id!==task.projectId)throw Error('请先打开对应演示稿。');
   const state=await request('/api/design/reference-jobs/status',{id:task.referenceJobId},AbortSignal.timeout(20000));
   if(state.status==='completed')return deliverCompleted(state);
   const job=store.project?.referenceJob;
   if(!job){notify('此演示稿没有待应用的生成任务，已打开当前保存版本。');return;}
   if(job.id!==task.referenceJobId)throw Error('该演示稿已有更新的生成任务，旧结果不会覆盖当前内容。');
   return run({mode:job.mode||'reference',themeId:job.themeId,targetPageIds:job.targetPageIds,jobId:job.id,resumeFailed:manual,instruction:job.instruction||''});
  }
 });
 store.subscribe(type=>{if(type!=='load')return;if(session&&store.project?.id!==session.owner)void detach().catch(e=>notify(e.message));if((store.project?.referenceJob||store.project?.generationDrafts?.length)&&!session)void syncDrafts().catch(()=>{});});
 return {run,detach,fillDrafts,syncDrafts,renderRecovery,destroy(){clearInterval(listTimer);},get active(){return !!session;}};
}
