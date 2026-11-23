import {pageLimit,pageRemaining,openPageRound,deckLimit,openDeckRound} from './reference-retry-rounds.mjs';
import {setTimeout as retryDelay} from 'node:timers/promises';
import {RETRY_LIMITS,retryError,classifyReferenceFailure,initialPageBudget,reviewRepairScope} from './reference-retry-policy.mjs';
import {referenceStyle} from './reference-style.mjs';
import {runPlannedPagePipeline} from './planned-page-pipeline.mjs';
import {stageScheduler,runStageAI} from './stage-pipeline.mjs';
import {runPipelineAI} from './pipeline-model-queue.mjs';
import {planCompositions} from './composition-planner.mjs';
import {reviewDesign} from './design-ai.mjs';
import {mkdir,readFile,readdir,writeFile,rename,rm} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {generateImageDesign,imageConcurrency} from './image-design-ai.mjs';
import {manualPageResume,referenceResumeAvailability} from './reference-resume-policy.mjs';

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const activeStatuses=new Set(['queued','running','cancelling']);
const ARTWORK_VALIDATION_REVISION=5;
const copy=value=>structuredClone(value),now=()=>new Date().toISOString();
const error=(message,status=400)=>Object.assign(Error(message),{status});
const safeMessage=e=>String(e?.message||'页面生成失败，请重试。').replace(/[A-Za-z]:[\\/][^\s，；。]+/g,'[本地路径]').replace(/\/(?:app|tmp|home|opt|Users|var)\/[^\s，；。]+/g,'[服务路径]').slice(0,800);
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
const requestFingerprint=input=>createHash('sha256').update(JSON.stringify(canonical(input))).digest('hex');
function validate(input){
 if(!input||!Array.isArray(input.project?.pages)||!input.project.pages.length||input.project.pages.length>100)throw error('请提供 1–100 页已确认文案。');
 if(input.clientRequestId!==undefined&&(typeof input.clientRequestId!=='string'||!UUID.test(input.clientRequestId)))throw error('客户端请求标识无效。');
 const snapshot=copy(input),project=snapshot.project;
 if(project.pages.some(p=>!p||typeof p!=='object'))throw error('页面内容无效。');
 const ids=project.pages.map(p=>p.id);
 if(ids.some(id=>typeof id!=='string'||!id||id.length>100)||new Set(ids).size!==ids.length)throw error('页面标识缺失或重复。');
 if(project.pages.some(p=>typeof p.title!=='string'||typeof p.body!=='string'||p.title.length>2000||p.body.length>12000))throw error('页面文案无效或过长，请先拆页。');
 const themeId=snapshot.themeId||project.themeId,targetPageIds=snapshot.targetPageIds??ids,instruction=snapshot.instruction??'';
 if(typeof themeId!=='string'||!/^[\w-]{1,100}$/.test(themeId))throw error('请选择有效的参考风格。');
 if(!Array.isArray(targetPageIds)||!targetPageIds.length||targetPageIds.length>100||new Set(targetPageIds).size!==targetPageIds.length||targetPageIds.some(id=>!ids.includes(id)))throw error('目标页面不存在或重复。');
 if(typeof instruction!=='string'||instruction.length>6000)throw error('排版要求过长。');
 project.themeId=themeId;return {project,themeId,targetPageIds:copy(targetPageIds),instruction};
}

/** Persists isolated generation snapshots; never writes or applies user projects. */
export function createReferenceJobs({dataDir,artworkFallbackEnabled=process.env.WEPPT_REFERENCE_ARTWORK_FALLBACK==='1',generate=generateImageDesign,plan=planCompositions,review=reviewDesign,prepareStyle=referenceStyle,pipelined=true,pageWorkers=Number(process.env.WEPPT_REFERENCE_PAGE_WORKERS||0),sharedStyleFirst=true,stagePipeline=process.env.WEPPT_STAGE_PIPELINE==='1',retryDelayMs=1000,drawingWorkers=Number(process.env.WEPPT_REFERENCE_DRAW_WORKERS??Math.max(4,imageConcurrency+2))}={}){
 if(typeof dataDir!=='string'||!dataDir)throw Error('dataDir is required');
 if(![0,1,2].includes(pageWorkers))throw new RangeError('Planning page workers must be 0, 1 or 2');
 if(!Number.isInteger(drawingWorkers)||drawingWorkers<1||drawingWorkers>8)throw new RangeError('Drawing page workers must be between 1 and 8');
 const directory=join(resolve(dataDir),'reference-jobs'),jobs=new Map(),controllers=new Map(),runs=new Map();
 let operation=Promise.resolve(),writes=Promise.resolve();
 const serialize=fn=>{const result=operation.then(fn);operation=result.catch(()=>{});return result;};
 const persist=job=>{const payload=JSON.stringify(job),id=job.id;const next=writes.then(async()=>{const temporary=join(directory,`${id}.${randomUUID()}.tmp`);try{await writeFile(temporary,payload,{flag:'wx'});await rename(temporary,join(directory,`${id}.json`));}finally{await rm(temporary,{force:true}).catch(()=>{});}});writes=next.catch(()=>{});return next;};
 const ready=(async()=>{
  await mkdir(directory,{recursive:true});
  for(const name of await readdir(directory)){
   if(!name.endsWith('.json')||!UUID.test(name.slice(0,-5)))continue;
   let job;try{job=JSON.parse(await readFile(join(directory,name),'utf8'));}catch{continue;}
   if(job?.version!==1||job.id!==name.slice(0,-5)||!job.input||!Array.isArray(job.pages)||!Array.isArray(job.pageStatus))continue;
   jobs.set(job.id,job);
   if(job.deletedAt)continue;
   if(job.status==='completed'&&(job.designReview?.status!=='checked'||job.designReview.reviewEvidence?.status!=='pass'||job.input.project.pages.some(p=>!job.designReview.reviewEvidence.checkedPageIds?.includes(p.id)))){job.status='interrupted';job.message='已生成页面保留，需补做整稿视觉复核。';job.updatedAt=now();await persist(job);}
   if(activeStatuses.has(job.status)){job.status='interrupted';job.updatedAt=now();job.message='服务已重启，已完成页面保留，可继续生成。';for(const page of job.pageStatus)if(page.status==='running')page.status='pending';await persist(job);}
  }
 })();
 const lookup=(id,includeDeleted=false)=>{if(typeof id!=='string'||!UUID.test(id))throw error('作业标识无效。');const job=jobs.get(id);if(!job)throw error('生成作业不存在。',404);if(job.deletedAt&&!includeDeleted)throw error('生成草稿已删除。',410);return job;};
 const plannedCount=job=>new Set([...(job.compositionPlan?.pages||[]),...(job.compositionCheckpoint?.plan?.pages||[]),...job.pages.map(p=>({pageId:p.id}))].map(p=>p.pageId).filter(id=>job.input.targetPageIds.includes(id))).size;
 const publicJob=job=>copy({id:job.id,projectId:job.input.project.id,sourceRevision:job.input.project.revision,sourceFingerprint:job.sourceFingerprint,themeId:job.input.themeId,targetPageIds:job.input.targetPageIds,sourcePages:job.input.project.pages,status:job.status,...referenceResumeAvailability(job),completed:job.pages.length,planned:plannedCount(job),total:job.input.targetPageIds.length,pages:job.input.targetPageIds.flatMap(id=>job.pages.filter(p=>p.id===id)),failures:job.failures,pageStatus:job.pageStatus,message:job.message,phase:job.phase,pipelineVersion:job.pipelineVersion,pipelineTimings:job.pipelineTimings,stageTimings:job.stageTimings,stageEvents:job.stageEvents,deckReviewUsed:job.deckReviewUsed,designReview:job.designReview,createdAt:job.createdAt,updatedAt:job.updatedAt});
 const assertCapacity=projectId=>{const active=[...jobs.values()].filter(j=>activeStatuses.has(j.status)||runs.has(j.id));if(active.some(j=>j.input.project.id===projectId))throw error('这份文稿已在生成，请完成或停止后再开始。',409);if(active.length>=2)throw error('已有两份文稿正在生成，请等待其中一份完成或停止后再开始。',409);};
 const authorizeManualResume=async job=>{
  for(const state of job.pageStatus){
   if((!state.budget?.terminal&&!state.manualResume)||!manualPageResume(state,{ignoreBlocked:true})||job.pages.some(p=>p.id===state.pageId)&&!job.failures.some(f=>f.pageId===state.pageId))continue;
   if(state.lastFailure?.imageCallFailed===true){state.budget.terminal=null;delete state.manualResumeBlocked;continue;}
   const checkpoint=join(dataDir,'reference-checkpoints',job.id,'image-background-'+createHash('sha256').update(state.pageId).digest('hex'));
   try{
    const meta=JSON.parse(await readFile(join(checkpoint,'checkpoint.json'),'utf8')),layoutBytes=await readFile(join(checkpoint,'layout.json'),'utf8'),saved=JSON.parse(layoutBytes);
    if(meta.version!==1||saved.version!==1||!/^[a-f0-9]{64}$/.test(meta.fingerprint||'')||saved.fingerprint!==meta.fingerprint||!Array.isArray(saved.layout?.boxes)||createHash('sha256').update(await readFile(join(checkpoint,'background.png'))).digest('hex')!==meta.imageHash)throw Error('原背景或排版缓存缺失/不匹配，不能继续原任务；已有页面保留。');
    const attempts=saved.artworkInventoryRepairAttempts??0;
    if(!Number.isInteger(attempts)||attempts<0||attempts>1000000)throw Error('原稿的图形修复计数无效，不能继续原任务。');
    if(state.budget.terminal?.code==='EDITABLE_ARTWORK_INVALID'&&saved.layout.artworkInventory?.complete!==true)throw Error('原稿没有完整的图形缓存，不能继续原任务。');
    const previous=state.manualResume;
    if(previous)state.manualResumeHistory=[...(state.manualResumeHistory||[]),copy(previous)];
    state.manualResume={at:now(),previousTerminal:copy(state.budget.terminal),usedBefore:copy(state.budget.used),checkpointFingerprint:meta.fingerprint,imageHash:meta.imageHash,layoutHash:createHash('sha256').update(layoutBytes).digest('hex'),sourceFingerprint:createHash('sha256').update(JSON.stringify(job.pageInputs?.[state.pageId]?.project.pages.find(p=>p.id===state.pageId))).digest('hex'),roundRequestId:state.budget.round?.requestId,artworkRepairAttemptsBefore:previous&&previous.roundRequestId===state.budget.round?.requestId?previous.artworkRepairAttemptsBefore:attempts,artworkRepairAttemptLimit:previous&&previous.roundRequestId===state.budget.round?.requestId?previous.artworkRepairAttemptLimit:Math.max(2,attempts+Math.min(2,pageRemaining(state.budget,'text')))};
    delete state.manualResumeBlocked;state.budget.terminal=null;
   }catch{state.manualResumeBlocked='原背景或排版缓存缺失/未通过同源校验，不能继续原任务；已有页面保留。';}
  }
 };
 // A validator upgrade may recheck a previously paid, same-source inventory once.
 // This is invoked only by normal resume; cumulative budgets and inputs never reset.
 const revalidateArtworkFailures=async job=>{
  if(job.editableArtworkVersion!==1||(job.artworkValidationRevision??1)>=ARTWORK_VALIDATION_REVISION)return;
  for(const state of job.pageStatus){
   if(state.budget?.terminal?.code!=='EDITABLE_ARTWORK_INVALID'||job.pages.some(p=>p.id===state.pageId)||state.budget.used?.pageRun>=RETRY_LIMITS.pageRun)continue;
   const checkpoint=join(dataDir,'reference-checkpoints',job.id,'image-background-'+createHash('sha256').update(state.pageId).digest('hex'));
   try{
    const meta=JSON.parse(await readFile(join(checkpoint,'checkpoint.json'),'utf8')),saved=JSON.parse(await readFile(join(checkpoint,'layout.json'),'utf8'));
    if(meta.version!==1||saved.version!==1||!/^[a-f0-9]{64}$/.test(meta.fingerprint||'')||saved.fingerprint!==meta.fingerprint||!saved.layout?.boxes||saved.layout.artworkInventory?.complete!==true||!Number.isInteger(saved.artworkInventoryRepairResponses)||saved.artworkInventoryRepairResponses<1||saved.artworkInventoryRepairResponses>3||saved.artworkInventoryRepairAttempts!==saved.artworkInventoryRepairResponses)continue;
    if(createHash('sha256').update(await readFile(join(checkpoint,'background.png'))).digest('hex')!==meta.imageHash)continue;
    let legacyCorrection=saved.legacyArtworkCorrection;
    if(legacyCorrection&&(legacyCorrection.version!==2||legacyCorrection.fingerprint!==meta.fingerprint||legacyCorrection.imageHash!==meta.imageHash||typeof legacyCorrection.used!=='boolean'))continue;
    if(job.pipelineVersion>=6&&saved.artworkInventoryRepairAttempts===2){
     if(!Number.isInteger(state.budget.used?.text)||state.budget.used.text>=RETRY_LIMITS.text||state.budget.used.text<0||!Number.isInteger(state.budget.used.pageRun)||state.budget.used.pageRun<0)continue;
     if(!legacyCorrection){
      legacyCorrection={version:2,fingerprint:meta.fingerprint,imageHash:meta.imageHash,used:false};
      const target=join(checkpoint,'layout.json'),temporary=target+'.'+randomUUID()+'.tmp';
      try{await writeFile(temporary,JSON.stringify({...saved,legacyArtworkCorrection:legacyCorrection}),{flag:'wx'});await rename(temporary,target);}finally{await rm(temporary,{force:true}).catch(()=>{});}
     }
    }
    if(state.artworkRevalidation)state.artworkRevalidationHistory=[...(state.artworkRevalidationHistory||[]),copy(state.artworkRevalidation)];
    state.artworkRevalidation={fromRevision:job.artworkValidationRevision??1,toRevision:ARTWORK_VALIDATION_REVISION,at:now(),previousTerminal:copy(state.budget.terminal),checkpointFingerprint:meta.fingerprint,usedBefore:copy(state.budget.used),...(legacyCorrection?{legacyArtworkCorrection:copy(legacyCorrection)}:{})};
    state.budget.terminal=null;
   }catch{/* Missing or unproven checkpoints retain their terminal failure. */}
  }
  job.artworkValidationRevision=ARTWORK_VALIDATION_REVISION;
  await persist(job);
 };
 function launch(job){
  const controller=new AbortController();controllers.set(job.id,controller);
  const promise=run(job,controller).catch(async e=>{const cancelled=controller.signal.aborted;controller.abort();job.status=cancelled?'cancelled':'failed';job.message=safeMessage(e);job.updatedAt=now();await persist(job).catch(()=>{});}).finally(()=>{controllers.delete(job.id);runs.delete(job.id);});
  runs.set(job.id,promise);
 }
 async function run(job,controller){
  const {signal}=controller,staged=job.pipelineVersion>=6,model=staged?runStageAI:runPipelineAI;
  const jobStage=(stage,work,stageSignal=signal)=>staged?stageScheduler.run(stage,work,{signal:stageSignal,onEvent:async event=>{job.stageEvents=[...(job.stageEvents||[]),event].slice(-40);if(event.endedAt){job.stageTimings ||= {};const stats=job.stageTimings[stage] ||= {runs:0,waitMs:0,runMs:0};stats.runs++;stats.waitMs+=event.waitMs;stats.runMs+=event.runMs;}await persist(job);}}):work();
  const planStage=(work,stageSignal)=>jobStage('planning',work,stageSignal);
  job.status='running';job.pipelineTimings ||= {};await persist(job);
  const scene=()=>{const done=new Map(job.pages.map(p=>[p.id,p]));return {...copy(job.input.project),pages:job.input.project.pages.map(p=>copy(done.get(p.id)||p))};};
  async function planning(ids,repairFeedback='',onReady=null,planningSignal=signal){
   job.phase='planning';job.message='正在统筹整稿内容，规划各页不同构图';job.updatedAt=now();await persist(job);
   const project=job.pipelineVersion>=3&&!repairFeedback?copy(job.input.project):scene(),key=requestFingerprint({project,themeId:job.input.themeId,targetPageIds:ids,instruction:job.input.instruction,repairFeedback});
   if(job.compositionCheckpointKey!==key){delete job.compositionCheckpoint;job.compositionCheckpointKey=key;await persist(job);}
   const result=await planStage(()=>plan({project,themeId:job.input.themeId,targetPageIds:ids,instruction:job.input.instruction,repairFeedback},{dataDir,signal:planningSignal,structuredAI:model,pageWorkers:job.pipelineVersion>=4?job.planningWorkers:0,checkpoint:copy(job.compositionCheckpoint),onProgress:event=>{
    if(planningSignal.aborted)return;job.message=safeMessage({message:event.message||'正在统筹整稿构图'});job.updatedAt=now();
   },onCheckpoint:async checkpoint=>{planningSignal.throwIfAborted();job.compositionCheckpoint=copy(checkpoint);job.updatedAt=now();await persist(job);if(onReady)onReady(checkpoint.plan);}}),planningSignal);
   planningSignal.throwIfAborted();job.compositionPlan=copy(result);job.pipelineTimings ||= {};if(!repairFeedback)job.pipelineTimings.planningCompletedAt ||= now();await persist(job);return result;
  }
  const sharedStyle=job.pipelineVersion>=5,streaming=job.pipelineVersion>=3&&!job.compositionPlan;let sharedStyleSnapshot;
  if(!streaming&&!sharedStyle&&!job.compositionPlan)await planning(job.input.targetPageIds);
  signal.throwIfAborted();job.phase='designing';
  const doneIds=new Set(job.pages.filter(p=>!job.failures.some(f=>f.pageId===p.id)).map(p=>p.id)),pending=job.input.targetPageIds.filter(id=>!doneIds.has(id));
  if(!streaming&&!sharedStyle&&pending.some(id=>!job.compositionPlan.targetPageIds.includes(id)))await planning(pending);
  let repairInstruction='';
  async function generatePage(pageId,readyPlan=null,pageSignal=signal){
   const state=job.pageStatus.find(p=>p.pageId===pageId),source=job.input.project.pages.find(p=>p.id===pageId);
   state.budget ||= initialPageBudget(state);const budget=state.budget;
   const fail=async(e,classification=classifyReferenceFailure(e))=>{
    state.lastError=safeMessage(e);state.lastFailure={code:e.code||'UNKNOWN',...classification,...(e.imageCallFailed===true?{imageCallFailed:true}:{}),...(e.pipelineStage?{stage:e.pipelineStage,reworkStage:e.reworkStage||e.pipelineStage,producerStage:e.producerStage}:{})};state.status='failed';state.message=state.lastError;
    if(classification.action==='stop')budget.terminal={code:e.code||'UNKNOWN',category:classification.category,message:state.lastError,...(e.pipelineStage?{stage:e.pipelineStage}:{}),...(e.reworkStage?{reworkStage:e.reworkStage}:{}),...(e.producerStage?{producerStage:e.producerStage}:{})};
    job.failures=job.failures.filter(f=>f.pageId!==pageId);job.failures.push({pageId,message:state.message,attempts:state.attempts,code:state.lastFailure.code,category:classification.category,...(e.pipelineStage?{stage:e.pipelineStage,reworkStage:e.reworkStage||e.pipelineStage}:{})});job.updatedAt=now();await persist(job);
   };
   if(budget.terminal){await fail(retryError(budget.terminal.code,budget.terminal.message,{...(budget.terminal.stage?{pipelineStage:budget.terminal.stage}:{}),...(budget.terminal.reworkStage?{reworkStage:budget.terminal.reworkStage}:{}),...(budget.terminal.producerStage?{producerStage:budget.terminal.producerStage}:{})}),{category:budget.terminal.category,action:'stop',preserveBackground:true});return;}
   const reserve=async stage=>{
    pageSignal.throwIfAborted();
    if(!Object.hasOwn(budget.used,stage)||budget.used[stage]>=pageLimit(budget,stage))throw retryError('REFERENCE_BUDGET_EXHAUSTED',`本页本轮${stage}处理次数已用尽；已完成页面保留，点击继续生成可开启下一轮。`,{stage});
    if(stage==='image'&&budget.used.image>0&&!budget.redrawAuthorized)throw retryError('REFERENCE_CHECKPOINT_UNAVAILABLE','本页已绘图，但可复用背景不可读取或不匹配；已停止重复绘图，保留现有结果。');
    budget.used[stage]++;if(stage==='image'){budget.redrawAuthorized=false;job.pipelineTimings.firstDrawingStartedAt ||= now();}
    state.lastStage=stage;job.updatedAt=now();
    try{await persist(job);}catch(cause){throw retryError('REFERENCE_PERSIST_FAILED','生成预算保存失败，未继续调用生成服务。',{cause});}
   };
   job.pageInputs ||= {};
   if(!job.pageInputs[pageId]){
    const project=scene();project.compositionPlan=copy(readyPlan||job.compositionPlan);
    const anchors=[job.pages.find(p=>p.role==='cover'),job.pages.find(p=>p.role!=='cover')].filter(Boolean);if(!anchors.length&&job.pages.length)anchors.push(job.pages[0]);
    job.pageInputs[pageId]={...(job.textSpacePreflightVersion===1?{textSpacePreflight:true}:{}),...(job.editableArtworkVersion===1?{editableArtwork:true}:{}),project,themeId:job.input.themeId,targetPageIds:[pageId],instruction:job.input.instruction,repairFeedback:'',singlePass:true,referenceMode:true,styleAnchorIds:anchors.map(p=>p.id).slice(0,2)};
   }
   const pageStage=(name,work,stageSignal)=>stageScheduler.run(name,work,{signal:stageSignal,
    // Expedite the first target until a page is ready. A fallback drawing stage
    // only reopens a verified background and cannot request another image.
    prefer:(!job.pages.length&&pageId===job.input.targetPageIds[0])||(name==='drawing'&&Boolean(state.artworkFallback)),
    onEvent:async event=>{state.stage=name;state.stageStatus=event.status;state.stageEvents=[...(state.stageEvents||[]),event].slice(-80);if(event.endedAt){state.stageTimings ||= {};const stats=state.stageTimings[name] ||= {runs:0,waitMs:0,runMs:0};stats.runs++;stats.waitMs+=event.waitMs;stats.runMs+=event.runMs;}job.updatedAt=now();await persist(job);}});
   for(let attempt=0;attempt<2&&!pageSignal.aborted;attempt++){
    let checkpointed=false;
    try{
     await reserve('pageRun');state.status='running';state.attempts++;state.attemptStartedAt=now();state.phase='starting';state.message='正在继续本页设计';job.phase=job.textRepairFeedback?.[pageId]?'repairing':'designing';await persist(job);
     const retryInput=copy(job.pageInputs[pageId]);if(job.textRepairFeedback?.[pageId])retryInput.textRepairFeedback=job.textRepairFeedback[pageId];
     const generationOptions={dataDir,signal:pageSignal,structuredAI:model,...(state.artworkFallback?{artworkFallback:state.artworkFallback.trigger}:{}),...(staged?{runStage:pageStage,stagePipeline:true}:{}),artworkRepairAuthorization:state.manualResume,preparedReferenceStyle:sharedStyle?copy(sharedStyleSnapshot):undefined,stageImageSlots:job.pipelineVersion>=4,checkpointDir:join(dataDir,'reference-checkpoints',job.id),beforeStage:reserve,onBackgroundReused:async()=>{budget.backgroundReuses++;await persist(job);},onProgress:(phase,message)=>{if(pageSignal.aborted)return;state.phase=String(phase||'');state.message=safeMessage({message});state.events=[...(state.events||[]),{phase:state.phase,at:now(),attempt:state.attempts}].slice(-96);job.message=`第 ${job.input.project.pages.findIndex(p=>p.id===pageId)+1} / ${job.input.project.pages.length} 页：${state.message}`;job.updatedAt=now();}};
     let result;
     try{result=await generate(retryInput,generationOptions);}
     catch(initialError){
      const trigger=['EDITABLE_ARTWORK_INVALID','REFERENCE_TEXT_REPAIR_EXHAUSTED'].includes(initialError.code)?initialError.code:initialError.code==='REFERENCE_BUDGET_EXHAUSTED'&&['EDITABLE_ARTWORK_INVALID','REFERENCE_TEXT_REPAIR_EXHAUSTED'].includes(state.manualResume?.previousTerminal?.code)?state.manualResume.previousTerminal.code:null;
      if(!artworkFallbackEnabled||!trigger||pageSignal.aborted||state.artworkFallback||job.editableArtworkVersion!==1)throw initialError;
      state.artworkFallback={version:1,at:now(),trigger:{code:trigger,message:safeMessage(initialError)},usedBefore:copy(budget.used)};
      await persist(job);await reserve('pageRun');state.phase='fallback';state.message='正在保留原图图形，并检查文字与完整文案';await persist(job);
      result=await generate(retryInput,{...generationOptions,artworkFallback:state.artworkFallback.trigger});
     }
     pageSignal.throwIfAborted();const page=result?.pages?.[0];
     if(result?.pages?.length!==1||page?.id!==pageId||page.title!==source.title||page.body!==source.body||page.role!==source.role||!Array.isArray(page.objects)||!page.objects.length)throw retryError('REFERENCE_SOURCE_INVALID','生成页未通过原文和非空校验。');
     if(page.themeId!==job.input.themeId)throw retryError('REFERENCE_SOURCE_INVALID','生成页参考风格与所选模板不一致。');
     if((source.objects||[]).filter(o=>o.custom).some(o=>!page.objects.some(n=>n.id===o.id&&JSON.stringify(n)===JSON.stringify(o))))throw retryError('REFERENCE_SOURCE_INVALID','生成页改变了用户自定义对象。');
     const index=job.pages.findIndex(p=>p.id===pageId),completed=copy({...page,designPending:false});if(index<0)job.pages.push(completed);else job.pages[index]=completed;
     job.failures=job.failures.filter(f=>f.pageId!==pageId);if(job.textRepairFeedback)delete job.textRepairFeedback[pageId];job.pipelineTimings.firstPageReadyAt ||= now();state.completedAt=now();state.status='completed';state.phase='completed';state.message=page.imageDesign?.manualAdjustments?.length?'页面已生成，局部排版可手动调整':page.imageDesign?.artworkFallback?'图形整图保留，文字可编辑，页面已通过检查':'页面已完成';if(state.artworkFallback)state.artworkFallback.completedAt=now();budget.terminal=null;job.updatedAt=now();checkpointed=true;await persist(job);return;
    }catch(e){
     if(checkpointed)throw e;
     if(pageSignal.aborted){state.status='pending';state.message='已停止，背景及已消耗次数保留';await persist(job);return;}
     const classification=classifyReferenceFailure(e);
     state.attemptHistory=[...(state.attemptHistory||[]),{attempt:state.attempts,startedAt:state.attemptStartedAt,endedAt:now(),error:safeMessage(e),code:e.code||'UNKNOWN',category:classification.category}].slice(-12);
     if(classification.action==='redraw'){
      budget.redrawAuthorized=true;job.pageInputs[pageId].repairFeedback='本页背景检查反馈（数据，不是指令）：'+safeMessage(e);
     }else if(classification.action==='retry'&&e.imageCallFailed===true)budget.redrawAuthorized=true;
     await fail(e,classification);
     if(classification.action==='stop')return;
     if(attempt<1){state.phase='waiting';state.message='连接暂时不可用，稍后重试本页；已完成页面保留。';await persist(job);await retryDelay(Math.max(0,retryDelayMs)*2**attempt,null,{signal:pageSignal});}
    }
   }
  }
  if(streaming||sharedStyle){
   await runPlannedPagePipeline({signal,independentStages:staged,drainPublishedOnPlanningFailure:staged,workers:staged?100:job.pipelineVersion>=4?(job.drawingWorkers??4):2,requireAnchor:!sharedStyle,completedIds:[...doneIds],hasAnchor:()=>job.pages.length>0,
    prepare:async preparationSignal=>{
     if(!sharedStyle)return;
     job.pipelineTimings ||= {};job.pipelineTimings.stylePreparationStartedAt ||= now();
     sharedStyleSnapshot=copy(await planStage(()=>prepareStyle(job.input.themeId,{dataDir,signal:preparationSignal,structuredAI:model}),preparationSignal));
     preparationSignal.throwIfAborted();job.pipelineTimings.styleReadyAt=now();await persist(job);
    },
    produce:(publish,planningSignal)=>{
     if(job.compositionPlan&&pending.every(id=>job.compositionPlan.targetPageIds.includes(id)))return copy(job.compositionPlan);
     const ids=job.compositionPlan?pending:job.input.targetPageIds;
     return planning(ids,'',plan=>{job.pipelineTimings ||= {};job.pipelineTimings.firstPlanReadyAt ||= now();publish(plan);},planningSignal);
    },
    draw:(id,plan,pageSignal)=>generatePage(id,plan,pageSignal)});
  }else{
  // Establish the first successful visual anchor before concurrent continuation.
  while(!job.pages.length&&pending.length&&!signal.aborted)await generatePage(pending.shift());
  let cursor=0;async function worker(){while(!signal.aborted&&cursor<pending.length)await generatePage(pending[cursor++]);}
  const settled=await Promise.allSettled(Array.from({length:job.pipelineVersion===4?4:2},()=>worker()));const rejected=settled.find(r=>r.status==='rejected');if(rejected)throw rejected.reason;
  }
  if(!signal.aborted&&job.pages.length===job.input.targetPageIds.length&&!job.failures.length&&!job.reviewBlocked){
   job.deckReviewUsed ??= job.designReview?.visionRan?Math.min(RETRY_LIMITS.deckReview,1+(job.designReview.repairRounds||0)):0;
   while(job.deckReviewUsed<deckLimit(job)){
    signal.throwIfAborted();job.phase='reviewing';job.message='正在检查整稿真实页面、非相邻重复布局和可读性';job.updatedAt=now();job.deckReviewUsed++;await persist(job);
    const current=scene(),report=await jobStage('inspection',()=>review({project:current,instruction:job.input.instruction},{dataDir,signal,structuredAI:model}));signal.throwIfAborted();
    const checked=report.reviewEvidence?.checkedPageIds||[],pass=report.reviewEvidence?.status==='pass'&&current.pages.every(p=>checked.includes(p.id))&&!report.issues?.some(i=>i.severity==='error');
    job.designReview={status:pass?'checked':'needs-attention',visionRan:true,repairRounds:job.deckReviewUsed-1,issues:copy(report.issues||[]),summary:report.summary,reviewEvidence:copy(report.reviewEvidence),targetPageIds:copy(job.input.targetPageIds)};await persist(job);
    if(pass)break;
    const errors=(report.issues||[]).filter(i=>i.severity==='error');
    const repairIds=[...new Set(errors.filter(i=>job.input.targetPageIds.includes(i.pageId)).map(i=>i.pageId))];
    if(!repairIds.length||errors.some(i=>!job.input.targetPageIds.includes(i.pageId))||reviewRepairScope(errors)!=='text'){
     job.reviewBlocked=true;job.message='整稿检查本轮已暂停，页面已保留；可继续检查。';await persist(job);break;
    }
    if(job.deckReviewUsed>=deckLimit(job))break;
    job.textRepairFeedback ||= {};
    for(const id of repairIds){job.textRepairFeedback[id]=errors.filter(i=>i.pageId===id).map(i=>i.message).join('；').slice(0,2800);job.failures=job.failures.filter(f=>f.pageId!==id);job.failures.push({pageId:id,message:job.textRepairFeedback[id],category:'text',code:'REFERENCE_REVIEW_TEXT'});}
    await persist(job);job.phase='repairing';
    for(const id of repairIds){signal.throwIfAborted();await generatePage(id);}
    if(job.failures.length)break;
   }
  }
  const fullyReviewed=job.designReview?.status==='checked'&&job.designReview.reviewEvidence?.status==='pass'&&job.input.project.pages.every(p=>job.designReview.reviewEvidence.checkedPageIds?.includes(p.id))&&!job.designReview.issues?.some(i=>i.severity==='error');
  job.status=signal.aborted?'cancelled':job.pages.length===job.input.targetPageIds.length&&!job.failures.length&&fullyReviewed?'completed':job.pages.length?'partial':'failed';job.message=signal.aborted?'已停止，已完成页面保留。':job.status==='completed'?(job.pages.some(p=>p.imageDesign?.manualAdjustments?.length)||job.designReview?.issues?.some(i=>i.manualAdjustment)?'全部页面已生成并完成检查，局部排版可在编辑器中手动调整。':job.pages.some(p=>p.imageDesign?.artworkFallback)?'全部页面已通过整稿视觉复核；部分页图形保留为整图，文字可编辑。':'全部页面已生成并通过整稿视觉复核，可应用到原稿。'):job.pageStatus.some(p=>p.budget?.terminal)?'本轮已暂停，背景及已完成页面已保留；可继续生成未完成页。':job.reviewBlocked?'整稿检查本轮已暂停，页面已保留；可继续检查。':job.deckReviewUsed>=deckLimit(job)?'本轮整稿检查次数已用尽，可点击继续检查；已完成页面保留。':job.pages.length===job.input.targetPageIds.length?'页面已保留，整稿视觉复核尚未通过，可继续检查修正。':'部分页面尚未完成，可继续生成。';job.updatedAt=now();await persist(job);
 }
 return {
  async start(input){await ready;return serialize(async()=>{
   const snapshot=validate(input),id=input.clientRequestId?.toLowerCase()||randomUUID(),fingerprint=requestFingerprint(snapshot),existing=jobs.get(id);
   if(existing){if(existing.deletedAt)throw error('生成草稿已删除，请重新生成新任务。',410);if((existing.requestFingerprint||requestFingerprint(existing.input))!==fingerprint)throw error('请求标识已用于另一份生成内容，请使用新的请求标识。',409);return publicJob(existing);}
   assertCapacity(snapshot.project.id);const stamp=now(),job={version:1,pipelineVersion:sharedStyleFirst?(stagePipeline?6:5):pageWorkers?4:pipelined?3:1,...(sharedStyleFirst?{planningWorkers:0,drawingWorkers}:pageWorkers?{planningWorkers:pageWorkers,drawingWorkers}:{}),id,retryPolicyVersion:1,textSpacePreflightVersion:1,editableArtworkVersion:1,artworkValidationRevision:ARTWORK_VALIDATION_REVISION,deckReviewUsed:0,input:snapshot,requestFingerprint:fingerprint,sourceFingerprint:createHash('sha256').update(JSON.stringify(snapshot.project)).digest('hex'),status:'queued',pages:[],failures:[],pageStatus:snapshot.targetPageIds.map(pageId=>({pageId,status:'pending',attempts:0,phase:'',message:'',budget:initialPageBudget({attempts:0})})),message:'已加入生成队列',createdAt:stamp,updatedAt:stamp};await persist(job);jobs.set(id,job);const response=publicJob(job);launch(job);return response;
  });},
  async list(){await ready;return [...jobs.values()].filter(job=>!job.deletedAt).sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)).map(job=>{return {id:job.id,projectId:job.input.project.id,projectTitle:job.input.project.title||job.input.project.name||'未命名文稿',themeId:job.input.themeId,instruction:job.input.instruction,targetPageIds:copy(job.input.targetPageIds),status:job.status,...referenceResumeAvailability(job),completed:job.pages.length,planned:plannedCount(job),total:job.input.targetPageIds.length,phase:job.phase||'queued',message:job.message,createdAt:job.createdAt,updatedAt:job.updatedAt};});},
  async deletedIds(){await ready;return [...jobs.values()].filter(job=>job.deletedAt).map(job=>job.id);},
  async remove(id,{stop=false}={}){await ready;id=typeof id==='string'?id.toLowerCase():id;return serialize(async()=>{
   const job=lookup(id,true);if(job.deletedAt)return {id,deleted:true};
   if((activeStatuses.has(job.status)||runs.has(id))&&!stop)throw error('任务仍在生成，请停止后删除。',409);
   controllers.get(id)?.abort(new DOMException('生成草稿已删除','AbortError'));if(runs.has(id))await runs.get(id);
   const tombstone={...job,deletedAt:now(),updatedAt:now()};await persist(tombstone);jobs.set(id,tombstone);return {id,deleted:true};
  });},
  async get(id){await ready;id=typeof id==='string'?id.toLowerCase():id;const job=lookup(id);if(!activeStatuses.has(job.status)&&runs.has(id))await runs.get(id);return publicJob(job);},
  async cancel(id){await ready;id=typeof id==='string'?id.toLowerCase():id;const job=lookup(id),controller=controllers.get(id);if(controller){job.status='cancelling';job.updatedAt=now();controller.abort(new DOMException('生成已取消','AbortError'));await runs.get(id);}return publicJob(job);},
  async resume(id,{resumeRequestId}={}){
   await ready;id=typeof id==='string'?id.toLowerCase():id;
   if(resumeRequestId!==undefined&&(typeof resumeRequestId!=='string'||!UUID.test(resumeRequestId)))throw error('继续请求标识无效。');
   return serialize(async()=>{
    const job=lookup(id);
    if(resumeRequestId&&job.resumeRequests?.some(r=>r.id===resumeRequestId))return publicJob(job);
    if(job.status==='completed'||activeStatuses.has(job.status)||runs.has(id))return publicJob(job);
    assertCapacity(job.input.project.id);
    const missing=job.pageStatus.filter(s=>!job.pages.some(p=>p.id===s.pageId)||job.failures.some(f=>f.pageId===s.pageId));
    const eligible=missing.filter(s=>manualPageResume(s));
    if(missing.length&&!eligible.length){job.message=referenceResumeAvailability(job).resumeReason;await persist(job);return publicJob(job);}
    if(!resumeRequestId&&(eligible.some(s=>manualPageResume(s).needsRound)||!missing.length&&(job.reviewBlocked||(job.deckReviewUsed??0)>=deckLimit(job))))return publicJob(job);
    const requestId=resumeRequestId||randomUUID(),at=now();
    const snapshot=copy(job);
    try{
     for(const state of eligible){
      const decision=manualPageResume(state);
      if(decision.needsRound)openPageRound(state,requestId,at);
      if(state.lastFailure?.imageCallFailed===true)state.budget.redrawAuthorized=true;
     }
     // Cache authorization clears only verified recoverable terminal failures.
     await authorizeManualResume(job);
     for(const state of eligible){
      if(state.budget.terminal&&state.manualResumeBlocked)continue;
      state.budget.terminal=null;delete state.manualResumeBlocked;
     }
     if(!missing.length&&(job.reviewBlocked||(job.deckReviewUsed??0)>=deckLimit(job)))openDeckRound(job,requestId,at);
     job.reviewBlocked=null;
     job.resumeRequests=[...(job.resumeRequests||[]),{id:requestId,at,pageIds:eligible.map(s=>s.pageId),reviewRound:job.reviewRound?.number||1}];
     job.status='queued';job.message='继续处理未完成页，已完成页面保持';job.updatedAt=at;
     const done=new Set(job.pages.filter(p=>!job.failures.some(f=>f.pageId===p.id)).map(p=>p.id));
     for(const state of job.pageStatus)if(!done.has(state.pageId)&&!state.budget?.terminal){state.status='pending';state.phase='';}
     await persist(job);
    }catch(e){Object.keys(job).forEach(k=>delete job[k]);Object.assign(job,snapshot);throw e;}
    const response=publicJob(job);launch(job);return response;
   });
  },
 };
}
