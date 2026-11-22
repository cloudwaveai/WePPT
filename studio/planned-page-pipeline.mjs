/** Consume only persisted validated plan snapshots; drain all branches on failure/cancellation. */
export async function runPlannedPagePipeline({produce,draw,hasAnchor,completedIds=[],signal,workers=2,independentStages=false,drainPublishedOnPlanningFailure=false,requireAnchor=true,prepare=async()=>{}}){
 if(!Number.isInteger(workers)||workers<1||workers>(independentStages?100:8))throw new RangeError('Page workers exceed the coordinator limit');
 const stop=new AbortController(),combined=signal?AbortSignal.any([signal,stop.signal]):stop.signal;
 const queued=new Set(completedIds),queue=[],waiters=new Set();let closed=false,failure;
 const wake=()=>{for(const resolve of waiters)resolve();waiters.clear();};
 combined.addEventListener('abort',wake);
 const guard=async work=>{try{return await work();}catch(e){failure ||= e;stop.abort(e);wake();}};
 const take=async()=>{while(true){combined.throwIfAborted();if(queue.length)return queue.shift();if(closed)return null;await new Promise(resolve=>waiters.add(resolve));}};
 const publish=plan=>{
  combined.throwIfAborted();const snapshot=structuredClone(plan);
  snapshot.targetPageIds=snapshot.pages.map(p=>p.pageId);
  for(const id of snapshot.targetPageIds)if(!queued.has(id)){queued.add(id);queue.push({id,plan:snapshot});}
  wake();
 };
 const preparation=guard(()=>prepare(combined));
 // A later planning rejection cannot invalidate a persisted, validated snapshot.
 // Let paid work on those snapshots finish; cancellation and fatal consumers
 // still use the shared abort path, and the planning failure is still reported.
 const producer=(async()=>{try{const final=await produce(publish,combined);publish(final);}catch(e){failure ||= e;if(!drainPublishedOnPlanningFailure)stop.abort(e);}finally{closed=true;wake();}})();
 const worker=async()=>{while(true){const item=await take();if(!item)return;await draw(item.id,structuredClone(item.plan),combined);}};
 const consumer=guard(async()=>{
  // v5 shares a validated template contract; older runs retain the first-page anchor gate.
  await preparation;combined.throwIfAborted();
  while(requireAnchor&&!hasAnchor()){const item=await take();if(!item)return;await draw(item.id,structuredClone(item.plan),combined);}
  await Promise.all(Array.from({length:workers},()=>guard(worker)));
 });
 try{await Promise.allSettled([producer,consumer,preparation]);if(failure)throw failure;combined.throwIfAborted();}
 finally{combined.removeEventListener('abort',wake);}
}
