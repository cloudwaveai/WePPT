/** Apply copy edits inside native text boxes or retained SVG effect groups. */
function writeSvgRun(objects,run,value){
 const object=objects.find(item=>item.type==='vector'&&item.id===run.objectId);if(!object?.svg)return false;
 const document=new DOMParser().parseFromString(object.svg,'image/svg+xml');if(document.querySelector('parsererror'))return false;
 const node=document.querySelector(`[data-weppt-source-run-id="${run.id}"]`);if(!node)return false;
 const spans=[...node.querySelectorAll('tspan')],lines=String(value).split('\n');
 if(!spans.length)node.textContent=String(value);
 else{
  for(const child of [...node.childNodes])if(child.nodeType===Node.TEXT_NODE)child.textContent='';
  while(spans.length<lines.length){const span=spans.at(-1).cloneNode(false);const first=spans[0],fontSize=parseFloat(getComputedStyle(first).fontSize)||parseFloat(node.getAttribute('font-size'))||24;span.removeAttribute('y');span.setAttribute('x',first.getAttribute('x')||node.getAttribute('x')||'0');span.setAttribute('dy',String(fontSize*1.2));node.append(span);spans.push(span);}
  spans.forEach((span,index)=>{span.textContent=lines[index]||'';});
 }
 object.svg=new XMLSerializer().serializeToString(document.documentElement);run.text=String(value);run.sourceText=String(value);return true;
}
function writeRef(objects,ref,value){if(ref.kind==='object'){ref.value.text=value;ref.value.sourceText=value;return true;}return writeSvgRun(objects,ref.value,value);}
export function updateSvgCopy(page){
 const next=structuredClone(page),source=next.layoutSource;if(next.engine!=='ppt-master-svg'||!source)return null;
 const runs=next.sourceTextRuns||[],textObjects=next.objects.filter(object=>object.type==='text');
 const titleObject=textObjects.find(object=>object.sourceField==='title'),titleRun=runs.find(run=>run.sourceField==='title');
 if(next.title!==source.title){const ref=titleObject?{kind:'object',value:titleObject}:{kind:'run',value:titleRun};if(!ref.value||!writeRef(next.objects,ref,next.title))return null;}
 if(next.body!==source.body){
  const refs=[...textObjects.filter(object=>object.sourceField==='body'&&object.sourceRange).map(value=>({kind:'object',value,sourceRange:value.sourceRange,text:value.text})),...runs.filter(run=>run.sourceField==='body'&&run.sourceRange).map(value=>({kind:'run',value,sourceRange:value.sourceRange,text:value.text}))].sort((a,b)=>a.sourceRange[0]-b.sourceRange[0]);
  if(!refs.length)return null;
  const before=String(source.body),after=String(next.body);let start=0,end=before.length,newEnd=after.length;
  while(start<end&&start<newEnd&&before[start]===after[start])start++;
  while(end>start&&newEnd>start&&before[end-1]===after[newEnd-1]){end--;newEnd--;}
  const candidate=refs.filter(ref=>ref.sourceRange[0]<=start&&ref.sourceRange[1]>=end);
  if(candidate.length===1){const target=candidate[0],[a,b]=target.sourceRange,delta=(newEnd-start)-(end-start);const value=before.slice(a,start)+after.slice(start,newEnd)+before.slice(end,b);if(!writeRef(next.objects,target,value))return null;target.value.sourceRange=[a,b+delta];for(const ref of refs)if(ref!==target&&ref.sourceRange[0]>=end){ref.value.sourceRange=ref.sourceRange.map(n=>n+delta);}}
  else{
   const paragraphs=after.split('\n'),weights=refs.map(ref=>Math.max(1,ref.sourceRange[1]-ref.sourceRange[0])),total=weights.reduce((sum,value)=>sum+value,0);let cursor=0,offset=0;
   for(let i=0;i<refs.length;i++){const count=i===refs.length-1?paragraphs.length-cursor:Math.min(paragraphs.length-cursor,Math.max(0,Math.round(paragraphs.length*weights[i]/total)));const value=paragraphs.slice(cursor,cursor+count).join('\n');cursor+=count;if(value&&!writeRef(next.objects,refs[i],value))return null;if(!value&&refs[i].kind==='object'){refs[i].value.text='';refs[i].value.sourceText='';}if(value){refs[i].value.sourceRange=[offset,offset+value.length];offset+=value.length+1;}else{delete refs[i].value.sourceRange;delete refs[i].value.sourceField;delete refs[i].value.layoutField;delete refs[i].value.sourceText;}}
  }
 }
 next.layoutSource={title:next.title,body:next.body};delete next.designSnapshot;return next;
}
