const PREFIX='/api/design/reference-jobs/';
const STATES=new Set(['queued','running','completed','partial','failed','cancelling','cancelled','interrupted']);
const clone=value=>structuredClone(value);

function pause(ms,signal){
 return new Promise((resolve,reject)=>{
  signal?.throwIfAborted();
  const done=()=>{signal?.removeEventListener('abort',abort);resolve();};
  const timer=setTimeout(done,ms);
  const abort=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);reject(signal.reason||new DOMException('已停止生成。','AbortError'));};
  signal?.addEventListener('abort',abort,{once:true});
 });
}
function checkStatus(state,total){
 if(!state||!STATES.has(state.status)||state.total!==total||!Number.isInteger(state.completed)||state.completed<0||state.completed>total)throw Error('生成任务返回的状态或页数不正确，原稿未修改。');
}
function completedPages(state,source,ids,themeId){
 if(state.completed!==ids.length||!Array.isArray(state.pages)||state.pages.length!==ids.length||new Set(state.pages.map(p=>p?.id)).size!==ids.length)throw Error('生成页面不完整或标识重复，原稿未修改。');
 const byId=new Map(source.pages.map(p=>[p.id,p]));
 for(const page of state.pages){
  const original=byId.get(page?.id);
  if(!original||!ids.includes(page.id)||page.themeId!==themeId||page.title!==original.title||page.body!==original.body||!Array.isArray(page.objects)||!page.objects.length)throw Error('生成结果的页面、模板或文案校验未通过，原稿未修改。');
 }
 const results=new Map(state.pages.map(page=>{const value=clone(page);delete value.designPending;return [value.id,value];}));
 return ids.map(id=>results.get(id));
}

export function completedReferenceResult(source,state,{themeId=source.themeId,targetPageIds=source.pages.map(p=>p.id)}={}){
 checkStatus(state,targetPageIds.length);
 if(state.status!=='completed')throw Error('生成任务尚未完成。');
 const pages=completedPages(state,source,targetPageIds,themeId),byId=new Map(pages.map(p=>[p.id,p])),review=state.designReview;
 if(review?.status!=='checked'||review.reviewEvidence?.status!=='pass'||source.pages.some(p=>!review.reviewEvidence.checkedPageIds?.includes(p.id))||review.issues?.some(i=>i.severity==='error'))throw Error('整稿视觉检查尚未通过，已有结果已保留。');
 return {...clone(source),themeId,stage:'editor',pages:source.pages.map(p=>byId.get(p.id)||p),designReview:clone(review),referenceResultIdentity:{jobId:state.id,projectId:source.id,sourceFingerprint:state.sourceFingerprint||null,themeId,targetPageIds:[...targetPageIds]}};
}

/** Keep completed server pages separate from the document until every target is valid. */
export async function designReferenceProject(project,{themeId=project?.themeId,targetPageIds,instruction='',request,onBatchReady=()=>{},onProgress=()=>{},signal,jobId,onJobStarted=()=>{},pollIntervalMs=2000,requestTimeoutMs=20000,resumeFailed=true}={}){
 const source=clone(project),ids=targetPageIds?[...targetPageIds]:(source?.pages||[]).map(p=>p.id);
 if(!source?.pages?.length||!ids.length||new Set(ids).size!==ids.length||ids.some(id=>!source.pages.some(p=>p.id===id))||!themeId||typeof request!=='function')throw Error('生成任务缺少有效页面、模板或请求接口。');
 if(!Number.isFinite(pollIntervalMs)||pollIntervalMs<0)throw Error('轮询间隔无效。');
 if(!Number.isFinite(requestTimeoutMs)||requestTimeoutMs<=0)throw Error('请求超时时间无效。');
 let id=jobId,cancelSent=false,starting=false,announced=false,planned=0,lastCompleted=0,lastPhase='planning';
 const transient=error=>[408,429,500,502,503,504].includes(error?.status)||error?.name==='TimeoutError'||(error instanceof TypeError&&!error.status);
 async function once(action,body,deferAbort=false){
  const deadline=new AbortController(),timer=setTimeout(()=>deadline.abort(new DOMException('生成进度请求超时。','TimeoutError')),requestTimeoutMs);
  const combined=signal&&!deferAbort?AbortSignal.any([signal,deadline.signal]):deadline.signal;
  try{return await request(PREFIX+action,body,combined);}
  catch(error){if(deadline.signal.aborted&&(!signal?.aborted||deferAbort))throw deadline.signal.reason;throw error;}
  finally{clearTimeout(timer);}
 }
 async function connected(action,body,{deferAbort=false,reconcile=false}={}){
  let failure;const initialAction=action,initialBody=body;
  for(let attempt=0;attempt<4;attempt++){
   signal?.throwIfAborted();
   try{return await once(action,body,deferAbort);}
   catch(error){
    signal?.throwIfAborted();
    const missingCreation=initialAction==='start'&&action==='status'&&error?.status===404;
    if(missingCreation){action='start';body=initialBody;reconcile=true;}
    else if(!transient(error))throw error;
    failure=error;
    // Start is idempotent by clientRequestId. Resume is not: after a lost
    // response, inspect the existing task instead of launching another run.
    if(reconcile&&!missingCreation){
     try{return await once('status',{id});}
     catch(statusError){
      signal?.throwIfAborted();
      if(statusError?.status===404&&action==='start'){/* replay the identical creation below */}
      else if(!transient(statusError))throw statusError;
      else{failure=statusError;if(action==='start'){action='status';body={id};reconcile=false;}}
     }
    }
    if(attempt===3)break;
    onProgress({phase:'plan',completed:lastCompleted,planned,generationPhase:lastPhase,total:ids.length,message:`连接暂时中断，正在重新获取生成进度（${attempt+1} / 3）；后台结果会保留。`});
    await pause(Math.min(pollIntervalMs,1000)*2**attempt,signal);
    // A resume response may have been lost after it was accepted. Poll only;
    // a terminal result must remain terminal, never silently resume it again.
    if(action==='resume'){action='status';body={id};reconcile=false;}
   }
  }
  throw Object.assign(Error('暂时无法获取生成进度，后台任务可能仍在运行。请从草稿箱查看原任务，原稿和已有结果已保留。'),{code:'REFERENCE_CONNECTION_LOST',cause:failure,...(failure?.status?{status:failure.status}:{})});
 }
 const cancel=()=>{
  if(!id||cancelSent||starting)return;cancelSent=true;
  // The polling signal is already aborted; cancellation needs its own request.
  try{Promise.resolve(request(PREFIX+'cancel',{id})).catch(()=>{});}catch{}
 };
 const create=async()=>{
  starting=true;
  await onJobStarted(id);announced=true;signal?.throwIfAborted();
  // Persist a client-owned identifier before creation. External cancellation
  // cannot discard the start response and orphan the durable server task.
  let started;
  try{started=await connected('start',{clientRequestId:id,project:source,themeId,targetPageIds:ids,instruction},{deferAbort:true,reconcile:true});}
  finally{starting=false;}
  if(started?.id!==id)throw Error('生成任务返回的标识与创建请求不一致，原稿未修改。');
  if(signal?.aborted){cancel();signal.throwIfAborted();}
  checkStatus(started,ids.length);
 };
 try{
  signal?.throwIfAborted();signal?.addEventListener('abort',cancel,{once:true});
  let state;
  if(id){
   try{state=await connected('status',{id});}
   catch(error){signal?.throwIfAborted();if(error?.status!==404)throw error;await create();}
   signal?.throwIfAborted();if(state){checkStatus(state,ids.length);if(Array.isArray(state.sourcePages)){if(state.sourcePages.length!==source.pages.length||state.sourcePages.some((p,i)=>p.id!==source.pages[i].id))throw Error('任务页面来源不匹配。');source.pages=clone(state.sourcePages);}}
   if(resumeFailed&&state&&['partial','failed','cancelled','interrupted'].includes(state.status)){
    await connected('resume',{id,resumeRequestId:crypto.randomUUID()},{reconcile:true});signal?.throwIfAborted();
    state=await connected('status',{id});
   }
  }else{
   id=crypto.randomUUID();await create();
  }
  if(!announced)await onJobStarted(id);signal?.throwIfAborted();
  while(true){
   if(!state)state=await connected('status',{id});
   signal?.throwIfAborted();checkStatus(state,ids.length);
   // Compatibility with a running pre-upgrade worker: use its exact, bounded
   // checkpoint message; never estimate progress from elapsed time.
   const checkpointMessage=/^已规划 (\d+) \/ (\d+) 页(?:[，。]|$)/.exec(state.message||'');
   if(Number.isInteger(state.planned)&&state.planned>=0&&state.planned<=state.total)planned=state.planned;
   else if(checkpointMessage&&Number(checkpointMessage[2])===state.total&&Number(checkpointMessage[1])<=state.total)planned=Number(checkpointMessage[1]);
   else if(['designing','reviewing','repairing'].includes(state.phase)||state.status==='completed')planned=state.total; // These phases start only after the full plan is validated.
   lastCompleted=state.completed;lastPhase=state.status==='completed'?'complete':state.phase||'planning';
   onProgress({phase:state.status==='completed'?'render':state.phase==='reviewing'?'review':'plan',completed:state.completed,planned,generationPhase:state.status==='completed'?'complete':state.phase||'planning',total:state.total,message:state.message||`逐页设计已完成 ${state.completed} / ${state.total} 页，整份完成后进入编辑。`});
   signal?.throwIfAborted();
   if(state.status==='completed'){
    const result=completedReferenceResult(source,state,{themeId,targetPageIds:ids}),pages=ids.map(id=>result.pages.find(p=>p.id===id));
    signal?.throwIfAborted();
    await onBatchReady({pages:clone(pages),sources:clone(source.pages),targetPageIds:[...ids],completed:ids.length,total:ids.length});
    return result;
   }
   if(['partial','failed','cancelled','interrupted'].includes(state.status)){
    const reason=typeof state.message==='string'?state.message.trim().slice(0,1000):'';
    const error=Error(state.status==='cancelled'?'生成任务已取消，原稿已保留。':`${state.phase==='planning'?'全稿规划未完成':state.status==='interrupted'?'生成任务已中断':'生成任务未完成'}（${state.completed} / ${state.total} 页）。${reason?reason+' ':''}原稿和已有结果已保留。`);
    error.failures=clone(state.failures||[]);throw error;
   }
   await pause(pollIntervalMs,signal);state=null;
  }
 }catch(cause){
  if(signal?.aborted)cancel();
  const error=cause instanceof Error?cause:Error(String(cause));
  if(id)error.jobId=id;
  throw error;
 }finally{signal?.removeEventListener('abort',cancel);}
}
