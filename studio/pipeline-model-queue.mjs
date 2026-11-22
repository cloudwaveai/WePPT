import {runStructuredAI} from './ai.mjs';

// Shared across v4 decks. Reserve one of the existing three model slots for
// interactive work; page planning, restoration and style checks wait FIFO.
export function createPipelineModelQueue(call,limit=2){
 let active=0;const pending=[];
 const pump=()=>{
  while(active<limit&&pending.length){
   const item=pending.shift();item.options.signal?.removeEventListener('abort',item.abort);
   if(item.options.signal?.aborted){item.reject(item.options.signal.reason);continue;}
   active++;
   Promise.resolve().then(()=>{item.options.signal?.throwIfAborted();return call(item.input,item.options);})
    .then(item.resolve,item.reject).finally(()=>{active--;pump();});
  }
 };
 return (input,options={})=>new Promise((resolve,reject)=>{
  const {signal}=options;if(signal?.aborted){reject(signal.reason);return;}
  const item={input,options,resolve,reject,abort:()=>{const i=pending.indexOf(item);if(i>=0)pending.splice(i,1);reject(signal.reason);}};
  signal?.addEventListener('abort',item.abort,{once:true});pending.push(item);pump();
 });
}
export const runPipelineAI=createPipelineModelQueue(runStructuredAI);
