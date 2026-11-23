import {setTimeout as delay} from 'node:timers/promises';
import {runStructuredAI,MODEL_CONCURRENCY} from './ai.mjs';

export const STAGE_LIMITS=Object.freeze({drawing:5,restoration:3,inspection:3,repair:3,planning:1});

/** Independent process-wide stage queues. A page owns a permit only while doing that stage. */
export function createStageScheduler(limits=STAGE_LIMITS,{sharedStages=[],sharedLimit=6}={}){
 if(!Array.isArray(sharedStages)||new Set(sharedStages).size!==sharedStages.length||sharedStages.some(stage=>!Object.hasOwn(limits,stage)))throw new RangeError('Invalid shared stages');
 if(!Number.isInteger(sharedLimit)||sharedLimit<1||sharedLimit>9)throw new RangeError('Invalid shared capacity');
 const shared=new Set(sharedStages);let sharedActive=0,sharedCursor=0;
 const lanes=new Map(Object.entries(limits).map(([stage,limit])=>{
  if(!Number.isInteger(limit)||limit<1||limit>8)throw new RangeError('Invalid stage capacity');
  return [stage,{limit,active:0,pending:[],lastWasPreferred:false}];
 }));
 function run(stage,work,{signal,onEvent=async()=>{},prefer=false}={}){
  const lane=lanes.get(stage);if(!lane)return Promise.reject(new Error('Unknown pipeline stage: '+stage));
  const queuedAt=Date.now();
  return new Promise((resolve,reject)=>{
   if(signal?.aborted){reject(signal.reason);return;}
   const item={work,signal,onEvent,prefer,resolve,reject,queuedAt,abort:null};
   item.abort=()=>{const i=lane.pending.indexOf(item);if(i>=0){lane.pending.splice(i,1);reject(signal.reason);}};
   // Persist queued state before the item becomes runnable.
   signal?.addEventListener('abort',item.abort,{once:true});
   Promise.resolve().then(()=>onEvent({stage,status:'queued',queuedAt})).then(()=>{
    if(signal?.aborted){signal.removeEventListener('abort',item.abort);reject(signal.reason);return;}
    lane.pending.push(item);pump();
   },error=>{signal?.removeEventListener('abort',item.abort);if(error&&typeof error==='object')error.pipelineStage=stage;reject(error);});
  });
 }
 // Within each stage, alternate classes when both are waiting. FIFO within each
 // class keeps other decks moving even under a continuous stream of new work.
 function takeNext(lane){
  const index=lane.pending.findIndex(item=>item.prefer!==lane.lastWasPreferred);
  const item=index>0?lane.pending.splice(index,1)[0]:lane.pending.shift();
  lane.lastWasPreferred=item.prefer;
  return item;
 }
 function pump(){
  for(const [stage,lane] of lanes){
   if(shared.has(stage))continue;
   while(lane.active<lane.limit&&lane.pending.length)start(stage,lane,takeNext(lane));
  }
  // Borrow every free downstream permit; rotate between waiting professions.
  // A stage with no waiting work leaves its share available to the others.
  while(sharedActive<sharedLimit){
   let selected=null;
   for(let n=0;n<sharedStages.length;n++){
    const index=(sharedCursor+n)%sharedStages.length,stage=sharedStages[index],lane=lanes.get(stage);
    if(lane.pending.length&&lane.active<lane.limit){selected={stage,lane,index};break;}
   }
   if(!selected)break;
   sharedCursor=(selected.index+1)%sharedStages.length;
   start(selected.stage,selected.lane,takeNext(selected.lane));
  }
 }
 function start(stage,lane,item){
   item.signal?.removeEventListener('abort',item.abort);
   if(item.signal?.aborted){item.reject(item.signal.reason);return;}
   if(shared.has(stage))sharedActive++;
   lane.active++;const startedAt=Date.now(),event={stage,queuedAt:item.queuedAt,startedAt,waitMs:startedAt-item.queuedAt};
   (async()=>{
    let result,failure;
    try{await item.onEvent({...event,status:'running'});item.signal?.throwIfAborted();result=await item.work();item.signal?.throwIfAborted();}
    catch(error){failure=error;}
    const endedAt=Date.now();
    try{await item.onEvent({...event,status:failure?(item.signal?.aborted?'cancelled':'failed'):'completed',endedAt,runMs:endedAt-startedAt,...(result?.stageOutcome?{outcome:result.stageOutcome,...(result.reworkStage?{reworkStage:result.reworkStage,producerStage:result.producerStage,findings:result.findings}:{})}:{}),...(failure?{message:String(failure.message||failure).slice(0,800)}:{})});}catch(error){failure ||= error;}
    lane.active--;if(shared.has(stage))sharedActive--;pump();
    if(failure){if(failure&&typeof failure==='object')failure.pipelineStage=stage;item.reject(failure);}else item.resolve(result);
   })();
 }
 return {run,snapshot(){const result=Object.fromEntries([...lanes].map(([name,lane])=>[name,{limit:lane.limit,active:lane.active,waiting:lane.pending.length}]));if(sharedStages.length)result.sharedPool={limit:sharedLimit,active:sharedActive,waiting:sharedStages.reduce((sum,stage)=>sum+lanes.get(stage).pending.length,0)};return result;}};
}

export const stageScheduler=createStageScheduler(STAGE_LIMITS,{sharedStages:['restoration','inspection','repair'],sharedLimit:Math.min(9,MODEL_CONCURRENCY-1)});
// New staged jobs use stage admission; legacy jobs retain their original two-call queue.
export async function runStageAI(input,options={}){
 for(;;){options.signal?.throwIfAborted();try{return await runStructuredAI(input,{...options,background:true});}catch(error){if(error?.code!=='MODEL_CAPACITY')throw error;await delay(25,undefined,{signal:options.signal});}}
}
