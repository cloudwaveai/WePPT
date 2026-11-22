import {reviewPrecompiledDeck} from './template-blueprints.js';
import {auditDeck,auditRenderedDeck} from './design-audit.js';

// A reviewed template is not a review of the current copy. Check the candidate
// before any editor commit; never repair it by clipping or dropping source text.
export async function checkPrecompiledLayout(pages,targetPageIds,{measure=auditRenderedDeck}={}){
 const ids=new Set(targetPageIds||pages.map(page=>page.id));
 const selected=pages.filter(page=>ids.has(page.id));
 const review=reviewPrecompiledDeck(selected,[...ids]);
 if(selected.length!==ids.size)review.issues.push({kind:'missing-page',severity:'error',message:'模板候选缺少目标页面，不能应用。'});
 // Box intersections are warnings in the general audit, but an unattended
 // fast path must not apply an ambiguous overlap without content-aware design.
 review.issues.push(...auditDeck(selected).issues.filter(issue=>['text-overlap','geometry','bounds'].includes(issue.kind)));
 if(!review.issues.length){
  const rendered=await measure(selected);
  review.issues.push(...rendered.issues);
 }
 const accepted=review.issues.length===0;
 return {accepted,review:{...review,status:accepted?'checked':'needs-attention',summary:accepted?'当前文案的模板映射、容量和浏览器文字测量通过；未执行逐稿 AI 视觉审看。':'预绘模板无法安全容纳当前文案，将按文案重新设计，原稿保持不变。'}};
}
