import {RETRY_LIMITS} from './reference-retry-policy.mjs';
const keys=Object.keys(RETRY_LIMITS).filter(k=>k!=='deckReview');
const roundIdentity=r=>Number.isSafeInteger(r?.number)&&r.number>=2&&/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(r.requestId||'')&&typeof r.openedAt==='string'&&Number.isFinite(Date.parse(r.openedAt));

export function validUsage(used){return !!used&&Object.keys(RETRY_LIMITS).filter(k=>k!=='deckReview').every(k=>Number.isSafeInteger(used[k])&&used[k]>=0);}
export function pageLimit(budget,stage){
 if(!Object.hasOwn(RETRY_LIMITS,stage)||stage==='deckReview'||!validUsage(budget?.used))return 0;
 const round=budget.round;
 if(!round)return RETRY_LIMITS[stage]; // Legacy counters never receive an implicit grant.
 if(!roundIdentity(round)||!validUsage(round.startedWith)||!validUsage(round.ceiling))return 0;
 if(keys.some(k=>round.ceiling[k]!==round.startedWith[k]+RETRY_LIMITS[k]||budget.used[k]<round.startedWith[k]||budget.used[k]>round.ceiling[k]))return 0;
 return round.ceiling[stage];
}
export const pageRemaining=(budget,stage)=>Math.max(0,pageLimit(budget,stage)-(budget?.used?.[stage]??0));
export function openPageRound(state,requestId,at){
 const budget=state.budget;
 if(!validUsage(budget?.used))throw Error('本页的累计消耗记录损坏，需恢复记录后继续。');
 if(budget.round&&!pageLimit(budget,'text'))throw Error('本页轮次记录损坏，需恢复记录后继续。');
 const previous=structuredClone(budget.round||{number:1,startedWith:{image:0,text:0,styleReview:0,pageRun:0},ceiling:Object.fromEntries(Object.entries(RETRY_LIMITS).filter(([k])=>k!=='deckReview'))});
 const round={number:previous.number+1,requestId,openedAt:at,startedWith:structuredClone(budget.used),ceiling:Object.fromEntries(Object.entries(budget.used).map(([k,v])=>[k,v+RETRY_LIMITS[k]]))};
 if(!validUsage(round.ceiling))throw Error('本页处理计数超出可记录范围。');
 state.retryRounds=[...(state.retryRounds||[]),{...previous,endedWith:structuredClone(budget.used),terminal:structuredClone(budget.terminal)}];
 budget.round=round;return round;
}
export function deckLimit(job){
 const used=job.deckReviewUsed??0;if(!Number.isSafeInteger(used)||used<0)return 0;
 if(!job.reviewRound)return RETRY_LIMITS.deckReview;
 const r=job.reviewRound;
 return roundIdentity(r)&&Number.isSafeInteger(r.startedWith)&&r.startedWith>=0&&Number.isSafeInteger(r.ceiling)&&r.ceiling===r.startedWith+RETRY_LIMITS.deckReview&&used>=r.startedWith&&used<=r.ceiling?r.ceiling:0;
}
export function openDeckRound(job,requestId,at){
 const used=job.deckReviewUsed??0;if(!Number.isSafeInteger(used)||used<0)throw Error('整稿审查计数损坏，需恢复记录后继续。');
 if(job.reviewRound&&!deckLimit(job))throw Error('整稿审查轮次记录损坏。');
 if(!Number.isSafeInteger(used+RETRY_LIMITS.deckReview))throw Error('整稿审查计数超出可记录范围。');
 job.reviewRounds=[...(job.reviewRounds||[]),{...(job.reviewRound||{number:1,startedWith:0,ceiling:3}),endedWith:used}];
 job.reviewRound={number:(job.reviewRound?.number||1)+1,requestId,openedAt:at,startedWith:used,ceiling:used+RETRY_LIMITS.deckReview};
}
