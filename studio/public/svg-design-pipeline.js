import {assertGeneratedTheme} from './editor-contract.js';
import {prepareDesignPages,reviewProject} from './design-pipeline.js';
import {snapshotPage,fitGeneratedTextFrames} from './design-audit.js';
export async function designSvgProject(project,{themeId=project.themeId,targetPageIds,instruction='',request,onBatchReady=()=>{},onProgress=()=>{},signal,review=reviewProject,previewOnly=false,reusePages=[]}={}){
 const original=structuredClone(project),ids=new Set(targetPageIds||original.pages.map(p=>p.id));
 if(!ids.size||[...ids].some(id=>!original.pages.some(p=>p.id===id)))throw Error('目标页面不存在。');
 const sources=original.pages.flatMap(p=>ids.has(p.id)?prepareDesignPages([p]):[p]);
 const selected=sources.filter(p=>ids.has(p.id)||ids.has(p.continuationOf)&&!original.pages.some(o=>o.id===p.id)),targetIds=selected.map(p=>p.id),ready=new Map();let next=0;
 if(sources.length>100)throw Error('文稿超过100页，请分批处理。');
 const controller=new AbortController(),combined=signal?AbortSignal.any([signal,controller.signal]):controller.signal;
 if(previewOnly){
  for(const candidate of reusePages){const source=selected.find(p=>p.id===candidate.id);if(source&&candidate.themeId===themeId&&source.title===candidate.title&&source.body===candidate.body)ready.set(candidate.id,structuredClone(candidate));}
  if(ready.size)await onBatchReady({pages:[...ready.values()],sources,targetPageIds:targetIds,completed:ready.size,total:selected.length});
 }
 async function worker(){while(next<selected.length){combined.throwIfAborted();const p=selected[next++];if(ready.has(p.id))continue;onProgress({phase:'plan',message:`逐页设计已完成 ${ready.size} / ${selected.length} 页`});const result=await request(['slidev','pptagent'].includes(original.designEngine)?'/api/design/html':'/api/design/svg',{engine:original.designEngine,project:{...original,themeId,pages:sources.map(s=>ready.get(s.id)||s)},themeId,targetPageIds:[p.id],instruction},combined);combined.throwIfAborted();if(result.pages?.length!==1||result.pages[0].id!==p.id)throw Error('设计返回范围不正确');assertGeneratedTheme(result.pages[0],themeId);const page=previewOnly?(await fitGeneratedTextFrames(result.pages))[0]:result.pages[0];combined.throwIfAborted();delete page.designPending;page.designSnapshot=snapshotPage(page);ready.set(p.id,page);await onBatchReady({pages:[page],sources,targetPageIds:targetIds,completed:ready.size,total:selected.length});onProgress({phase:'render',message:`已完成 ${ready.size} / ${selected.length} 页，已完成页面可以编辑`,pages:[...ready.values()]});}}
 try{await Promise.all(Array.from({length:Math.min(2,selected.length)},worker));}catch(error){controller.abort();throw error;}
 combined.throwIfAborted();const pages=sources.map(p=>ready.get(p.id)||p),checked=pages.filter(p=>ready.has(p.id));
 onProgress({phase:'review',message:'页面已可编辑，正在后台对照模板检查内容与构图…',pages:checked});
 const result={...original,themeId,designEngine:original.designEngine||'svg',stage:'editor',pages};
 const reviewOptions={targetPageIds:checked.map(p=>p.id),instruction,request,onProgress,signal:combined};
 if(previewOnly){
  // Local repairs and focused retries share the original preview deadline.
  const options={...reviewOptions,visual:false};
  result.designReview=await review(result,options);
  for(let round=1;round<=2;round++){
   combined.throwIfAborted();
   const errors=(result.designReview.issues||[]).filter(i=>i.severity==='error'&&targetIds.includes(i.pageId));
   const targets=[...new Set(errors.map(i=>i.pageId))];if(!targets.length)break;
   onProgress({phase:'repair',message:`正在自动修复 ${targets.length} 个页面，已完成页面会保留（${round}/2）…`});
   const repairFailures=[];
   for(const id of targets){
    combined.throwIfAborted();
    const feedback=errors.filter(i=>i.pageId===id).map(({kind,message})=>({kind,message}));
    try{
     const response=await request('/api/design/svg',{engine:'svg',project:result,themeId,targetPageIds:[id],instruction:instruction+'\n完整保留原文和模板风格，修复以下检查问题。正文至少24px；图形和文字必须在1280×720画布内；文字框需容纳实际换行：'+JSON.stringify(feedback)},combined);
     combined.throwIfAborted();
     if(response.pages?.length!==1||response.pages[0].id!==id)throw Error('修正返回范围不正确');
     assertGeneratedTheme(response.pages[0],themeId);const page=(await fitGeneratedTextFrames(response.pages))[0];
     combined.throwIfAborted();delete page.designPending;page.designSnapshot=snapshotPage(page);
     result.pages=result.pages.map(p=>p.id===id?page:p);
     await onBatchReady({pages:[page],sources,targetPageIds:targetIds,completed:ready.size,total:selected.length});
    }catch(error){combined.throwIfAborted();repairFailures.push({pageId:id,kind:'repair-failed',severity:'warning',message:'本页自动修复暂未完成：'+error.message});break;}
   }
   result.designReview=await review(result,options);
   result.designReview.issues.push(...repairFailures);
   result.designReview.repairRounds=round;
  }
  result.designReview={...result.designReview,visionRan:false,status:result.designReview.issues.length?'needs-attention':'pending',summary:'预览已完成，确认后继续视觉检查。'};
  return result;
 }

 result.designReview=await review(result,reviewOptions);
 // Repair only this invocation's pages. Accepted preview pages and unselected
 // user content stay outside the repair scope, including whole-deck warnings.
 for(let round=1;round<=2;round++){
  combined.throwIfAborted();
  const actionable=(result.designReview.issues||[]).filter(i=>i.severity!=='info'&&!['review-unavailable','repair-failed'].includes(i.kind)&&targetIds.includes(i.pageId));
  const targets=[...new Set(actionable.map(i=>i.pageId))];if(!targets.length)break;
  onProgress({phase:'repair',message:`正在修正 ${targets.length} 页的检查问题（第 ${round} 轮，最多两轮）…`});
  try{
   const replacements=new Map();
   for(const id of targets){
    combined.throwIfAborted();
    const feedback=actionable.filter(i=>i.pageId===id).map(({kind,message})=>({kind,message}));
    const response=await request(['slidev','pptagent'].includes(original.designEngine)?'/api/design/html':'/api/design/svg',{engine:original.designEngine,project:result,themeId,targetPageIds:[id],instruction:(instruction.slice(0,1800)+'\n保持原模板身份和完整文案，修正实际检查问题：'+JSON.stringify(feedback).slice(0,4000))},combined);
    combined.throwIfAborted();
    if(response.pages?.length!==1||response.pages[0].id!==id)throw Error('修正返回范围不正确');
    const page=response.pages[0];delete page.designPending;page.designSnapshot=snapshotPage(page);replacements.set(id,page);
   }
   result.pages=result.pages.map(p=>replacements.get(p.id)||p);
   result.designReview=await review(result,reviewOptions);
   result.designReview.repairRounds=round;
  }catch(error){
   combined.throwIfAborted();
   result.designReview={...result.designReview,status:'needs-attention',repairRounds:round,issues:[...(result.designReview.issues||[]),{pageId:targets[0],kind:'repair-failed',severity:'warning',message:`自动修正未完成，保留当前结果：${error.message}`}],summary:'自动修正未完成，当前结果仍需检查。'};
   break;
  }
 }
 return result;
}
