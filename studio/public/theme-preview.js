import {designSvgProject} from './svg-design-pipeline.js';

// Revisions may change after an autosave without changing the document.
export const previewFingerprint=project=>JSON.stringify({id:project.id,themeId:project.themeId,designEngine:project.designEngine,pages:project.pages,assets:project.assets});

export function selectPreviewPageIds(pages){
 if(!pages.length)throw Error('请先添加至少一页文案。');
 const ids=[];
 const add=page=>{if(page&&!ids.includes(page.id))ids.push(page.id);};
 add(pages.find(p=>p.role==='cover')||pages[0]);
 add(pages.find(p=>p.role==='toc'));
 const score=p=>String(p.body||'').length+String(p.body||'').split('\n').length*25+(['flow','data'].includes(p.role)?100:0);
 const candidates=pages.filter(p=>!ids.includes(p.id)&&!['cover','toc','ending','chapter'].includes(p.role)).sort((a,b)=>score(b)-score(a));
 add(candidates[0]);
 for(const page of pages){if(ids.length>=Math.min(3,pages.length))break;add(page);}
 return ids;
}

export async function createThemePreview(project,{themeId,request,signal,onProgress=()=>{},onBatchReady=()=>{},design=designSvgProject,timeoutMs=180000,previousPreview}={}){
 signal?.throwIfAborted();
 const deadline=AbortSignal.timeout(timeoutMs);
 signal=signal?AbortSignal.any([signal,deadline]):deadline;
 const source=structuredClone(project),selectedIds=selectPreviewPageIds(source.pages);
 // Whole-deck templates always use the same editable, image-grounded SVG route.
 source.designEngine='svg';
 const errors=previousPreview?.review?.issues?.filter(i=>i.severity==='error')||[];
 const failed=new Set(errors.map(i=>i.pageId));
 const reusePages=previousPreview?.sourceFingerprint===previewFingerprint(project)&&previousPreview?.themeId===themeId&&errors.length&&errors.every(i=>i.pageId)?previousPreview.pages.filter(p=>!failed.has(p.id)&&!p.continuationOf&&!p.continuationCount&&selectedIds.includes(p.id)&&source.pages.some(s=>s.id===p.id&&s.title===p.title&&s.body===p.body)):[];
 const result=await design(source,{themeId,targetPageIds:selectedIds,request,signal,onProgress,onBatchReady,previewOnly:true,reusePages,instruction:'这是整套模板应用前的真实预览。严格沿用所选模板的视觉语言和真实素材；完整保留标题和正文，不用通用色块代替模板主视觉。逐页依据内容设计，预览确认后这些页面会原样应用。'});
 signal?.throwIfAborted();
 const originalIds=new Set(source.pages.map(p=>p.id));
 const pages=result.pages.filter(p=>selectedIds.includes(p.id)||!originalIds.has(p.id)&&selectedIds.includes(p.continuationOf));
 if(!selectedIds.every(id=>pages.some(p=>p.id===id)))throw Error('预览页面不完整，请重试。');
 if(new Set(pages.map(p=>p.id)).size!==pages.length)throw Error('预览页面标识重复，请重试。');
 for(const id of selectedIds){
  const before=source.pages.find(p=>p.id===id),parts=pages.filter(p=>p.id===id||p.continuationOf===id&&!originalIds.has(p.id));
  if(parts.some(p=>p.title!==before.title)||parts.map(p=>p.body||'').join('')!==(before.body||''))throw Error('预览未完整保留确认文案，请重新生成。');
  for(const object of (before.objects||[]).filter(o=>o.custom||!o.layoutManaged)){
   if(!parts[0].objects?.some(o=>JSON.stringify(o)===JSON.stringify(object)))throw Error('预览未完整保留手动素材，请重新生成。');
  }
 }
 return {sourceFingerprint:previewFingerprint(project),themeId,designEngine:'svg',selectedIds,pages,review:result.designReview};
}

export function applyThemePreview(project,preview,baseline){
 if(previewFingerprint(project)!==baseline)throw Error('文稿已发生变化，请重新生成预览，避免覆盖你的修改。');
 const next=structuredClone(project),selected=new Set(preview.selectedIds),used=new Set();
 next.pages=next.pages.flatMap(page=>{
  if(!selected.has(page.id))return[page];
  const replacements=preview.pages.filter(p=>p.id===page.id||p.continuationOf===page.id&&!project.pages.some(o=>o.id===p.id));
  if(!replacements.length)throw Error('预览缺少页面，无法应用。');
  return replacements.map(p=>{if(used.has(p.id))throw Error('预览页面标识重复。');used.add(p.id);return structuredClone(p);});
 });
 next.themeId=preview.themeId;next.designEngine=preview.designEngine;next.stage='editor';
 next.designReview={...preview.review,status:'pending',summary:'已应用确认的真实预览，剩余页面等待设计。'};
 const remainingIds=next.pages.filter(p=>!used.has(p.id)).map(p=>p.id);
 next.pages=next.pages.map(p=>remainingIds.includes(p.id)?{...p,designPending:true}:p);
 if(!remainingIds.length)next.designReview=structuredClone(preview.review);
 return {project:next,remainingIds};
}

export function combinePreviewReview(previewReview,remainingReview,pages){
 if(!previewReview)return remainingReview;
 const issues=[...(previewReview.issues||[]),...(remainingReview.issues||[])],visionRan=!!previewReview.visionRan&&!!remainingReview.visionRan;
 return {...remainingReview,issues,status:issues.length?'needs-attention':visionRan?'checked':'pending',visionRan,sourceSnapshot:[...(previewReview.sourceSnapshot||[]),...(remainingReview.sourceSnapshot||[])],summary:issues.length?`已完成 ${pages.length} 页设计，预览及后续检查共 ${issues.length} 项需复核。`:visionRan?`已完成 ${pages.length} 页设计及检查。`:`已完成 ${pages.length} 页设计，视觉检查尚未完成。`};
}
