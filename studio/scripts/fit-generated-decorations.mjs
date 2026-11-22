// Fit generated decoration bounds before visual review. Never touch copy, photos,
// native charts/tables, user objects, or groups containing text/images.
export function fitGeneratedDecorations(project) {
 const changes=[];
 for(const page of project.pages) for(const o of page.objects||[]){
  if(o.type!=='vector'||!o.layoutManaged||o.custom||o.nativeType||o.rotation||/<(?:text|tspan|image)\b/i.test(o.svg||''))continue;
  if(![o.x,o.y,o.w,o.h].every(Number.isFinite)||o.w<=0||o.h<=0)continue;
  if(o.x>=-1&&o.y>=-1&&o.x+o.w<=1281&&o.y+o.h<=721)continue;
  const before={x:o.x,y:o.y,w:o.w,h:o.h};
  const scale=Math.min(1,1280/o.w,720/o.h);o.w*=scale;o.h*=scale;
  o.x=Math.max(0,Math.min(o.x,1280-o.w));o.y=Math.max(0,Math.min(o.y,720-o.h));
  changes.push({pageId:page.id,objectId:o.id,before,after:{x:o.x,y:o.y,w:o.w,h:o.h},reason:'Fit generated decoration inside canvas; visual review still required'});
 }
 return changes;
}
