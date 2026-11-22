import {equal} from './project-version-recovery.js';
export const referenceFingerprint=p=>JSON.stringify({themeId:p.themeId,designEngine:p.designEngine,stage:p.stage,pages:p.pages});
export function matchesReferenceBaseline(project,job){
 let baseline;try{baseline=JSON.parse(job.baseline);}catch{return false;}
 const delivered=new Set(job.appliedPageIds||[]);
 return project.themeId===baseline.themeId&&project.designEngine===baseline.designEngine&&project.stage===baseline.stage&&
  project.pages.length===baseline.pages.length&&project.pages.every((p,i)=>p.id===baseline.pages[i].id&&(delivered.has(p.id)||equal(p,baseline.pages[i])));
}
export function applyReferencePartial(project,state){
 const job=project.referenceJob;
 if(!job||state.id!==job.id||state.projectId!==project.id||!matchesReferenceBaseline(project,job))throw Error('文稿已有修改或任务不匹配，生成页不会覆盖当前内容。');
 if(!Array.isArray(state.pages)||!Array.isArray(state.sourcePages)||state.themeId!==job.themeId)throw Error('生成页来源信息不完整。');
 const source=new Map(state.sourcePages.map(p=>[p.id,p])),failed=new Set((state.failures||[]).map(f=>f.pageId)),seen=new Set(),updates=new Map();
 for(const p of state.pages){
  const s=source.get(p?.id);if(!s||seen.has(p.id)||!job.targetPageIds.includes(p.id)||p.themeId!==job.themeId||p.title!==s.title||p.body!==s.body||p.role!==s.role||!Array.isArray(p.objects)||!p.objects.length)throw Error('生成页未通过文案和来源校验。');
  seen.add(p.id);if(!failed.has(p.id))updates.set(p.id,structuredClone(p));
 }
 if(!updates.size)throw Error('暂时还没有可编辑的完成页。');
 const result=structuredClone(project),delivered=new Set(job.appliedPageIds||[]),snapshots={...(job.appliedSnapshots||{})};
 result.pages=result.pages.map(p=>{
  if(delivered.has(p.id))return p;
  const next=updates.get(p.id);
  if(next){delete next.designPending;delivered.add(p.id);snapshots[p.id]=JSON.stringify(next);return next;}
  return job.targetPageIds.includes(p.id)?{...p,designPending:true}:p;
 });
 result.stage='editor';
 result.referenceJob={...result.referenceJob,appliedPageIds:[...delivered],appliedSnapshots:snapshots,status:state.status,completed:state.completed,baseline:referenceFingerprint(result)};
 result.designReview={status:'needs-attention',visionRan:false,summary:'部分页面已可编辑，其余仍在生成；整稿检查尚未完成。',issues:result.pages.filter(p=>p.designPending).map(p=>({pageId:p.id,kind:'design-incomplete',severity:'warning',message:'此页尚未完成生成。'}))};
 return result;
}
export function mergeReferenceCompletion(project,result){
 const job=project.referenceJob;if(!job||!matchesReferenceBaseline(project,job))throw Error('文稿已有修改，未覆盖你的内容。');
 const delivered=new Set(job.appliedPageIds||[]),updates=new Map(result.pages.map(p=>[p.id,p]));
 const edited=project.pages.filter(p=>delivered.has(p.id)&&JSON.stringify(p)!==job.appliedSnapshots?.[p.id]);
 const merged=structuredClone(result);merged.pages=project.pages.map(p=>delivered.has(p.id)?structuredClone(p):structuredClone(updates.get(p.id)||p));
 if(edited.length)merged.designReview={...merged.designReview,status:'needs-attention',visionRan:false,summary:'生成已完成，已保留你的手动修改；修改后的页面可重新检查。',issues:[...(merged.designReview?.issues||[]),...edited.map(p=>({pageId:p.id,kind:'stale-review',severity:'warning',message:'已保留手动修改，整稿原检查不涵盖此页的最新编辑。'}))]};
 return merged;
}
export function completedReferenceExport(project){
 if(!project.referenceJob?.appliedPageIds?.length)return project;
 const delivered=new Set(project.referenceJob.appliedPageIds),pages=project.pages.filter(p=>delivered.has(p.id)&&!p.designPending);
 if(!pages.length)throw Error('暂时没有可导出的完成页。');
 return {...structuredClone(project),title:`${project.title||'演示文稿'}（已完成${pages.length}页）`,pages:structuredClone(pages)};
}

// A receipt and its pages are saved in the same project revision.
export function completeReferenceApplication(project,result,jobId){
 const targetIds=result.referenceResultIdentity?.targetPageIds||project.referenceJob?.targetPageIds||result.pages.map(p=>p.id);
 const next=structuredClone(project);next.pages=structuredClone(result.pages);next.themeId=result.themeId;next.stage='editor';next.designReview=structuredClone(result.designReview);
 next.referenceApplications={...(next.referenceApplications||{}),[jobId]:next.referenceApplications?.[jobId]||{jobId,projectId:project.id,identity:structuredClone(result.referenceResultIdentity||{jobId,projectId:project.id,themeId:result.themeId,targetPageIds:result.pages.map(p=>p.id)}),pageIds:[...targetIds]}};
 if(next.referenceJob?.id===jobId)delete next.referenceJob;
 for(const task of next.generationDrafts||[])if(task.referenceJobId===jobId){task.applied=true;task.state='complete';task.phase='complete';task.completed=task.total=targetIds.length;task.completedPageIds=[...targetIds];task.message='生成结果已应用，可编辑或导出。';}
 return next;
}
export function alreadyAppliedReference(project,result,jobId){
 if(project.id!==result.id)return false;
 const receipt=project.referenceApplications?.[jobId],identity=result.referenceResultIdentity||{jobId,projectId:project.id,themeId:result.themeId,targetPageIds:result.pages.map(p=>p.id)};
 if(receipt?.jobId===jobId&&receipt.projectId===project.id&&equal(receipt.identity,identity))return true;
 if(project.stage!=='editor'||project.themeId!==result.themeId)return false;
 const targetIds=result.referenceResultIdentity?.targetPageIds||project.referenceJob?.targetPageIds||result.pages.map(p=>p.id);
 if(new Set(project.pages.map(p=>p.id)).size!==project.pages.length||targetIds.some(id=>!project.pages.some(p=>p.id===id)||!result.pages.some(p=>p.id===id)))return false;
 const clean=p=>{const v=structuredClone(p);delete v.designPending;return v;};
 return targetIds.every(id=>equal(clean(project.pages.find(p=>p.id===id)),clean(result.pages.find(p=>p.id===id))));
}
export function reconcileAppliedReference(project,result,jobId){
 if(!alreadyAppliedReference(project,result,jobId))return null;
 // Receipt means these pages may have been edited since delivery. Never reapply them.
 return completeReferenceApplication(project,{...result,pages:project.pages,themeId:project.themeId,designReview:project.designReview||result.designReview},jobId);
}
