import {pageLimit,pageRemaining,validUsage,deckLimit} from './reference-retry-rounds.mjs';
// Eligibility is independent of exhausted lifetime counters. Only an explicit
// resume command may open a bounded new round; queries never grant anything.
export function manualPageResume(state,{ignoreBlocked=false}={}){
 if(!validUsage(state?.budget?.used))return null;
 if(state.budget.round&&!pageLimit(state.budget,'pageRun'))return null;
 if(state.manualResumeBlocked&&!ignoreBlocked)return null;
 const code=state.budget.terminal?.code;
 if(code&&!['EDITABLE_ARTWORK_INVALID','REFERENCE_TEXT_REPAIR_EXHAUSTED','IMAGE_TEXT_GEOMETRY_INVALID','REFERENCE_STYLE_MISMATCH','REFERENCE_STYLE_REVIEW_INVALID','REFERENCE_BUDGET_EXHAUSTED'].includes(code)&&state.lastFailure?.imageCallFailed!==true)return null;
 const stage=code==='REFERENCE_STYLE_REVIEW_INVALID'?'styleReview':['EDITABLE_ARTWORK_INVALID','REFERENCE_TEXT_REPAIR_EXHAUSTED','IMAGE_TEXT_GEOMETRY_INVALID','REFERENCE_STYLE_MISMATCH'].includes(code)?'text':null;
 return {stage,needsRound:!!code||!pageRemaining(state.budget,'pageRun')||['image','text','styleReview'].every(k=>!pageRemaining(state.budget,k))};
}
export function referenceResumeAvailability(job){
 if(job.deletedAt)return {canResume:false,resumeReason:'生成草稿已删除。'};
 if(['queued','running','cancelling','completed'].includes(job.status))return {canResume:true,resumeReason:''};
 const missing=job.pageStatus.filter(s=>!job.pages.some(p=>p.id===s.pageId)||job.failures.some(f=>f.pageId===s.pageId));
 if(missing.length){const canResume=missing.some(s=>manualPageResume(s));return {canResume,resumeReason:canResume?'': missing.find(s=>s.manualResumeBlocked)?.manualResumeBlocked||'文案、底图内容或累计消耗记录需先处理；已完成页面保留。'};}
 return {canResume:deckLimit(job)>0,resumeReason:deckLimit(job)>0?'':'整稿审查记录需先恢复。'};
}
