// Structural equality ignores object-key order while preserving array order and every value.
export const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().filter(k=>value[k]!==undefined).map(k=>[k,canonical(value[k])])):value;
export const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const meta=new Set(['revision','updatedAt','referenceJob','generationDrafts','referenceApplications']);
const copy=v=>v===undefined?undefined:structuredClone(v);
export function mergeProjectVersions(base,local,remote){
 if(!base||!local||!remote||base.id!==local.id||local.id!==remote.id)return null;
 const result={};
 for(const key of new Set([...Object.keys(base),...Object.keys(local),...Object.keys(remote)])){
  if(meta.has(key))continue;
  if(equal(local[key],base[key]))result[key]=copy(remote[key]);
  else if(equal(remote[key],base[key])||equal(local[key],remote[key]))result[key]=copy(local[key]);
  else return null;
 }
 const receipts={...(remote.referenceApplications||{})};
 for(const [id,value] of Object.entries(local.referenceApplications||{})){
  if(receipts[id]&&!equal(receipts[id],value))return null;
  receipts[id]=copy(value);
 }
 if(Object.keys(receipts).length)result.referenceApplications=receipts;
 const byKey=rows=>new Map((rows||[]).map(t=>[t.referenceJobId||t.id,t])),baseRows=byKey(base.generationDrafts),localRows=byKey(local.generationDrafts),remoteRows=byKey(remote.generationDrafts),rows=[];
 for(const key of new Set([...remoteRows.keys(),...localRows.keys(),...baseRows.keys()])){
  const b=baseRows.get(key),l=localRows.get(key),r=remoteRows.get(key);let row;
  if(equal(l,b))row=r;
  else if(equal(r,b)||equal(l,r))row=l;
  else if(!l||!r)row=undefined; // Concurrent deletion wins over stale progress.
  else row=r.applied&&!l.applied?r:l;
  if(row)rows.push(copy(row));
 }
 if(local.generationDrafts||remote.generationDrafts)result.generationDrafts=rows;
 const l=local.referenceJob,r=remote.referenceJob,b=base.referenceJob;
 let job;
 if(b&&(!r&&l?.id===b.id||!l&&r?.id===b.id))job=undefined;
 else if(equal(l,b))job=copy(r);
 else if(equal(r,b)||equal(l,r))job=copy(l);
 else if(l?.id&&l.id===r?.id&&equal(l.baseline,r.baseline))job={...copy(r),...copy(l)};
 else if(l&&receipts[l.id])job=copy(r);
 else if(r&&receipts[r.id])job=copy(l);
 else return null;
 if(job&&!receipts[job.id])result.referenceJob=job;
 for(const row of result.generationDrafts||[])if(receipts[row.referenceJobId]){row.applied=true;row.state='complete';row.phase='complete';row.message='生成结果已应用，可编辑或导出。';}
 result.revision=remote.revision;result.updatedAt=remote.updatedAt;
 return result;
}
export function sameSavedProject(a,b){const strip=p=>Object.fromEntries(Object.entries(p||{}).filter(([k])=>!['revision','updatedAt'].includes(k)));return equal(strip(a),strip(b));}
