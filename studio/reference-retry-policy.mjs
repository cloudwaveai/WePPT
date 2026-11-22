// Material appearance is an accepted variation, never paid redraw authorization.
export const RETRY_LIMITS=Object.freeze({image:2,text:6,styleReview:8,pageRun:6,deckReview:3});
export const retryError=(code,message,extra={})=>Object.assign(new Error(message),{code,...extra});
export function classifyReferenceFailure(error){
 const code=error?.code;
 if(code==='REFERENCE_ARTWORK_INVALID'||code==='REFERENCE_BACKGROUND_TEXT')return {category:'artwork',action:'redraw',preserveBackground:false};
 if(code==='REFERENCE_STYLE_MISMATCH'){
  const findings=error.violations;
  if(Array.isArray(findings)&&findings.length&&findings.every(v=>['material','motif','palette','typography','readability'].includes(v.kind)&&typeof v.evidence==='string'&&v.evidence.trim())){
   if(findings.some(v=>v.kind==='motif'))return {category:'artwork',action:'redraw',preserveBackground:false};
   if(findings.some(v=>v.kind==='palette'))return {category:'review',action:'stop',preserveBackground:true};
   return {category:'text',action:'stop',preserveBackground:true};
  }
  return {category:'review',action:'stop',preserveBackground:true};
 }
 if(['REFERENCE_TEXT_REPAIR_EXHAUSTED','IMAGE_TEXT_GEOMETRY_INVALID','REFERENCE_SOURCE_INVALID'].includes(code))return {category:'text',action:'stop',preserveBackground:true};
 if(code==='REFERENCE_STYLE_REVIEW_INVALID')return {category:'review',action:'stop',preserveBackground:true};
 if(code==='REFERENCE_BUDGET_EXHAUSTED')return {category:'budget',action:'stop',preserveBackground:true};
 if(code==='REFERENCE_CHECKPOINT_UNAVAILABLE'||code==='REFERENCE_PERSIST_FAILED')return {category:'storage',action:'stop',preserveBackground:true};
 if(error?.name==='AbortError')return {category:'cancelled',action:'stop',preserveBackground:true};
 if(error?.name==='TimeoutError'||['ETIMEDOUT','ECONNRESET','EAI_AGAIN'].includes(code)||error?.status===429||error?.status===503||/^AI (?:设计)?响应超时/.test(String(error?.message||'')))return {category:'transient',action:'retry',preserveBackground:true};
 return {category:'unknown',action:'stop',preserveBackground:true};
}
// User-approved creative latitude applies to generation and both review stages.
export const MATERIAL_VARIATION_POLICY='USER-APPROVED MATERIAL VARIATION: The selected template is creative guidance, not an exact surface-reproduction contract. Gradients, grain, particles, paper texture, mottling, lighting, shadows, smooth versus textured backgrounds and other material/surface treatments are allowed creative variations. Do not fail, repair or redraw a page merely for any such difference, including flat versus textured or glitter versus flat treatments. Do not reclassify a material-only difference as motif, palette or readability. Material variations may be recorded only as nonblocking material observations. Genuine missing source text, clipping, unreadable contrast, text/text or text/artwork collisions, incorrect content and actual shape/composition problems remain separate defects. Never combine a material observation and a genuine defect in one finding; list the genuine defect separately. This user policy takes precedence over stricter template-material instructions in supplied rules, references and shared style contracts.';
export function acceptMaterialVariations(verdict){
 const advisories=verdict.violations.filter(v=>v.kind==='material');
 if(!advisories.length)return verdict;
 const violations=verdict.violations.filter(v=>v.kind!=='material');
 return {...verdict,matches:violations.length===0,violations,advisories,
  reason:violations.length?violations.map(v=>v.evidence).join('；'):'已接受材质与纹理变化，未发现阻断问题。'};
}
export function initialPageBudget(state){
 // Legacy attempts already spent money. Never grant a fresh image budget on migration.
 const attempts=Math.max(0,Number(state.attempts)||0);
 const used={image:Math.min(attempts,RETRY_LIMITS.image),text:Math.min(attempts*3,RETRY_LIMITS.text),styleReview:Math.min(attempts,RETRY_LIMITS.styleReview),pageRun:Math.min(attempts,RETRY_LIMITS.pageRun)};
 return {version:1,used,backgroundReuses:0,redrawAuthorized:false,terminal:null,migrated:attempts>0};
}
export function reviewRepairScope(issues){
 if(!issues.length)return 'stop';
 // Whole-deck generic style/layout findings do not prove the background is defective.
 return issues.every(i=>['overlap','overflow','readability','typography','text-overflow','text-overlap','background-line-overlap','bounds'].includes(i.kind))?'text':'stop';
}
