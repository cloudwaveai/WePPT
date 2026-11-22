import {getTheme} from './templates.js';
import {validateDesignPlans,getDesignGroups} from './design-cases.js';
import {layoutPlannedPage} from './planned-layout.js';
import {auditDeck,auditRenderedDeck,snapshotPage,getRepairTargets} from './design-audit.js';

const clone=value=>structuredClone(value);
const abortIfNeeded=signal=>{if(signal?.aborted)throw new DOMException('已停止设计，原稿保留。','AbortError');};
function combine(pages,...reports){
 const issues=[],seen=new Set();for(const report of reports)for(const issue of report?.issues||[]){const key=JSON.stringify([issue.pageId,issue.kind,issue.message]);if(!seen.has(key)){seen.add(key);issues.push(issue);}}
 const errors=issues.filter(i=>i.severity==='error').length;
 return {issues,summary:issues.length?`已检查 ${pages.length} 页，${errors} 项需处理、${issues.length-errors} 项需留意。`:`已完成 ${pages.length} 页的内容、布局及视觉检查，未发现本轮检查覆盖的问题。`,checkedAt:new Date().toISOString()};
}
async function localAudit(pages,sourcePages,signal){abortIfNeeded(signal);const result=auditDeck(pages,{sourcePages});const rendered=await auditRenderedDeck(pages);abortIfNeeded(signal);return combine(pages,result,rendered);}
function renderPlans(source,plans,theme){const validated=validateDesignPlans(plans,source),byId=new Map(validated.map(p=>[p.pageId,p]));return source.map(page=>{const next=layoutPlannedPage(page,theme,byId.get(page.id));next.designManual=false;next.designSnapshot=snapshotPage(next);return next;});}

/** Prepare readable semantic chunks before planning; every continuation receives its own AI plan. */
export function prepareDesignPages(originalPages){
 const weight=s=>[...s].reduce((n,c)=>n+(/[^\u0000-\u00ff]/.test(c)?1:.6),0);
 const result=[];
 for(const original of originalPages){
  const body=String(original.body||''),groups=getDesignGroups(body);let chunks=[],current='';
  const pieces=[];for(const group of groups){let remaining=group.text;while(weight(remaining)>360){let end=0,cost=0;for(const char of remaining){if(cost+(weight(char))>330)break;cost+=weight(char);end+=char.length;}let cut=-1;for(const match of remaining.slice(0,end).matchAll(/[。；！？\n]/g))if(match.index>end*.35)cut=match.index+1;if(cut>0)end=cut;if(!end)end=1;pieces.push(remaining.slice(0,end));remaining=remaining.slice(end);}if(remaining)pieces.push(remaining);}
  let count=0;for(const piece of pieces){if(current&&(weight(current+piece)>360||count>=(original.role==='toc'?8:4))){chunks.push(current);current='';count=0;}current+=piece;count++;}if(current)chunks.push(current);if(!chunks.length)chunks=[body];
  for(const [index,content]of chunks.entries()){const page={...clone(original),body:content,objects:index?[]:clone(original.objects||[])};delete page.designPlan;delete page.designSource;delete page.designSnapshot;delete page.designManual;if(chunks.length>1){page.id=index?crypto.randomUUID():original.id;page.continuationOf=original.id;page.continuationIndex=index;page.continuationCount=chunks.length;if(index&&['cover','chapter','ending'].includes(page.role))page.role='content';}result.push(page);}
 }
 return result;
}

/** Model calls stay outside project commits. Cancellation or stale inputs cannot partially apply. */
export async function designProject(project,{themeId='curated-139',request,onProgress=()=>{},onBatchReady=()=>{},signal,batchSize=3,targetPageIds,instruction=''}={}){
 if(themeId!=='curated-139')throw Error('逐页设计目前先支持蓝色复古窗口。');
 const theme=getTheme(themeId),original=clone(project);abortIfNeeded(signal);
 onProgress({phase:'prepare',message:'正在整理页面内容与参考案例…'});
 const selectedIds=new Set(targetPageIds||original.pages.map(p=>p.id));
 if(!selectedIds.size||[...selectedIds].some(id=>!original.pages.some(p=>p.id===id)))throw Error('需要设计的页面不存在。');
 const sources=original.pages.flatMap(p=>selectedIds.has(p.id)?prepareDesignPages([p]).map(pg=>({...pg,themeId})):clone(p));
 const designSources=sources.filter(p=>selectedIds.has(p.id)||selectedIds.has(p.continuationOf)&&!original.pages.some(old=>old.id===p.id)),designIds=new Set(designSources.map(p=>p.id));
 if(!sources.length||sources.length>100)throw Error('本轮设计需要 1 至 100 页，请分批处理。');
 const plannedProject={...original,themeId,pages:sources};
 batchSize=Math.max(1,Math.min(3,Math.floor(batchSize)||3));
 let pages=[];
 async function planBatches(context,targets,feedback=[],deliver=false){
  const batches=[];for(let i=0;i<targets.length;i+=batchSize)batches.push(targets.slice(i,i+batchSize));
  const controller=new AbortController(),batchSignal=signal?AbortSignal.any([signal,controller.signal]):controller.signal;
  const ready=new Map();let next=0;
  async function worker(){while(next<batches.length){abortIfNeeded(batchSignal);const batch=batches[next++];
   onProgress({phase:deliver?'plan':'repair',message:deliver?`已排版 ${ready.size} / ${designSources.length} 页，正在设计下一批…`:`正在分批调整页面，已完成 ${ready.size} / ${targets.length} 页…`,pages:deliver?clone(pages):undefined});
   const response=await request('/api/design/plan',{project:context,themeId,targetPageIds:batch.map(p=>p.id),feedback,instruction},batchSignal);abortIfNeeded(batchSignal);
   const designed=renderPlans(batch,response.plans,theme);for(const page of designed)ready.set(page.id,page);
   context={...context,pages:context.pages.map(p=>ready.get(p.id)||p)};
   if(deliver){pages=sources.filter(p=>ready.has(p.id)).map(p=>ready.get(p.id));await onBatchReady({pages:clone(designed),sources:clone(sources),targetPageIds:[...designIds],completed:ready.size,total:designSources.length});abortIfNeeded(batchSignal);onProgress({phase:'render',message:`已排版 ${ready.size} / ${designSources.length} 页，已完成的页面可以编辑`,pages:clone(pages)});}
  }}
  try{await Promise.all(Array.from({length:Math.min(2,batches.length)},worker));}catch(error){controller.abort();throw error;}
  return targets.map(p=>ready.get(p.id));
 }
 const initial=await planBatches(plannedProject,designSources,[],true),initialMap=new Map(initial.map(p=>[p.id,p]));pages=sources.map(p=>initialMap.get(p.id)||p);
 const auditSelected=()=>localAudit(pages.filter(p=>designIds.has(p.id)),designSources,signal);
 let mechanical=await auditSelected(),repairRounds=0,visual;
 onProgress({phase:'review',message:'整稿已可编辑，正在后台检查风格与重复构图…',pages:clone(pages)});
 try{visual=await request('/api/design/review',{project:{...plannedProject,pages},instruction},signal);}catch(error){abortIfNeeded(signal);visual={issues:[{pageId:designSources[0].id,kind:'review-unavailable',severity:'warning',message:`AI 视觉审看未完成：${error.message}`}],summary:'视觉审看未完成'};}
 let report=combine(pages,mechanical,visual);const visionRan=!visual.issues?.some(i=>i.kind==='review-unavailable');
 for(let round=1;round<=2;round++){
  abortIfNeeded(signal);const actionable={issues:report.issues.filter(i=>i.kind!=='review-unavailable'&&i.severity!=='info')};const targets=getRepairTargets(actionable,pages).filter(id=>designIds.has(id));if(!targets.length)break;
  onProgress({phase:'repair',message:`正在调整 ${targets.length} 页的具体问题（第 ${round} 轮，最多两轮）…`,pages:clone(pages)});
  try{
   const selected=sources.filter(p=>targets.includes(p.id)),updates=await planBatches({...plannedProject,pages},selected,actionable.issues),byId=new Map(updates.map(p=>[p.id,p]));abortIfNeeded(signal);
   pages=pages.map(p=>byId.get(p.id)||p);repairRounds=round;
   mechanical=await auditSelected();
   // A review of an earlier image is never marked resolved by changing coordinates alone.
   const outstandingVision=(visual.issues||[]).map(issue=>targets.includes(issue.pageId)&&issue.kind!=='review-unavailable'?{...issue,kind:'visual-recheck',severity:'warning',message:`已针对上次审看调整，请复看：${issue.message}`}:issue);
   report=combine(pages,mechanical,{issues:outstandingVision});
   onProgress({phase:'render',message:`第 ${round} 轮调整已完成，正在复核实际排版…`,pages:clone(pages)});
   // Subsequent automatic repair addresses only newly measured failures, not already-repaired vision suggestions.
   if(!getRepairTargets(mechanical,pages).length)break;
   report=combine(pages,mechanical,{issues:(visual.issues||[]).filter(i=>i.kind==='review-unavailable')});
  }catch(error){abortIfNeeded(signal);report=combine(pages,report,{issues:[{pageId:targets[0],kind:'repair-failed',severity:'warning',message:`本轮自动调整未完成，保留可编辑结果：${error.message}`}]});break;}
 }
 abortIfNeeded(signal);
 return {...plannedProject,pages,stage:'editor',designReview:{...report,repairRounds,visionRan,status:report.issues.length?'needs-attention':'checked',sourceSnapshot:pages.map(p=>({id:p.id,snapshot:snapshotPage(p)}))}};
}

/** Read-only review, including hand-edited pages. It never applies repairs. */
export async function reviewProject(project,{request,onProgress=()=>{},signal,targetPageIds,instruction='',visual:runVisual=true}={}){
 const pages=clone(project.pages.filter(p=>!targetPageIds||targetPageIds.includes(p.id)));if(!pages.length)throw Error('需要检查的页面不存在。');onProgress({phase:'review',message:'正在检查页面内容、边界与真实文字显示…'});
 const mechanical=await localAudit(pages,undefined,signal);let visual={issues:[]},visionRan=false;
 if(runVisual&&(project.themeId==='curated-139'||['svg','slidev','pptagent'].includes(project.designEngine))){
  onProgress({phase:'review',message:'正在对照参考模板审看整稿…'});
  try{visual=await request('/api/design/review',{project:{...project,pages},instruction},signal);visionRan=true;}catch(error){abortIfNeeded(signal);visual={issues:[{pageId:pages[0]?.id,kind:'review-unavailable',severity:'warning',message:`AI 视觉审看未完成：${error.message}`}]};}
 }
 const report=combine(pages,mechanical,visual);return {...report,targetPageIds:pages.map(p=>p.id),visionRan,repairRounds:0,status:report.issues.length?'needs-attention':'checked',sourceSnapshot:pages.map(p=>({id:p.id,snapshot:snapshotPage(p)}))};
}
