// Read the source composition before assigning copy. A panel is a container,
// not permission to flatten its columns, captions and emphasis into one box.
const W=1280,H=720;
const box=o=>[o.x,o.y,o.w,o.h].every(Number.isFinite)&&o.w>0&&o.h>0;
const text=o=>o.type==='text'||o.type==='vector'&&/<text\b/i.test(o.svg||'');
const image=o=>o.type==='image'||/<image\b/i.test(o.svg||'');
const full=o=>o.x<=2&&o.y<=2&&o.x+o.w>=W-2&&o.y+o.h>=H-2;
const inside=(p,o)=>o.x+o.w/2>=p.x&&o.x+o.w/2<=p.x+p.w&&o.y+o.h/2>=p.y&&o.y+o.h/2<=p.y+p.h;
const bounds=items=>{const x=Math.min(...items.map(o=>o.x)),y=Math.min(...items.map(o=>o.y));return {x,y,w:Math.max(...items.map(o=>o.x+o.w))-x,h:Math.max(...items.map(o=>o.y+o.h))-y};};
const sameRow=(a,b)=>Math.abs(a.y-b.y)<Math.max(4,Math.min(a.h,b.h)*.3);
const normalized=s=>s.trim().replace(/\s*[｜|：:]\s*/g,'|');
const arrow=s=>/^[\s→←↑↓▸▶+＋·—–\d]+$/.test(s);
const area=o=>o.w*o.h;

function rows(items){
 const lines=[];
 for(const item of [...items].sort((a,b)=>a.y-b.y||a.x-b.x)){
  let line=lines.find(row=>sameRow(row,item));
  if(!line){line={y:item.y,h:item.h,items:[]};lines.push(line);}line.items.push(item);
 }
 return lines.map(line=>{
  const groups=[];
  for(const item of line.items.sort((a,b)=>a.x-b.x)){
   const prev=groups.at(-1);
   if(prev&&item.x-(prev.x+prev.w)<=Math.max(18,item.style.fontSize*1.2)){
    prev.items.push(item);Object.assign(prev,bounds(prev.items));
   }else groups.push({...item,items:[item]});
  }
  return {...line,groups:groups.map(g=>({...g,text:g.items.map(i=>i.text).join(''),style:[...g.items].sort((a,b)=>b.text.length-a.text.length)[0].style}))};
 });
}
function columnAnchors(lines){
 const candidates=lines.map(line=>line.groups.filter(g=>!arrow(g.text)&&g.w>=30)).filter(groups=>groups.length>=2&&groups.length<=4);
 return candidates.filter(groups=>candidates.some(other=>other!==groups&&Math.abs(other[0].y-groups[0].y)>10&&other.length===groups.length&&groups.every((g,i)=>Math.abs(g.x-other[i].x)<65))).sort((a,b)=>b.length-a.length||a[0].y-b[0].y)[0];
}
function makeFrame(items,geometry,kind,panelId,priority){
 const copyItems=items.filter(o=>!arrow(o.text)&&/[\p{L}\p{N}]/u.test(o.text));
 const lines=rows(copyItems.length?copyItems:items),first=lines[0]?.groups[0],style=first?.style||items[0]?.style;
 const levels=lines.map(line=>line.groups[0]?.style).filter(Boolean);
 const primary=levels.reduce((best,s)=>s.fontSize>best.fontSize?s:best,style);
 const detail=levels.at(-1)||style;
 return {...geometry,kind,panelId,priority,style,primary,detail,levels,headlineFirst:style.fontSize>=primary.fontSize-1,sourceIds:items.map(o=>o.id)};
}

export function analyseSourceComposition(page,{objectText,textStyle}){
 const objects=page.objects||[],items=objects.filter(text).filter(box).map(o=>({...o,text:objectText(o),style:textStyle(o)}));
 const unsupported=objects.some(o=>text(o)&&image(o));
 const pictures=objects.filter(image).filter(box);
 const panels=objects.filter(o=>!text(o)&&!image(o)&&box(o)&&!full(o)&&o.x>=-2&&o.y>=-2&&o.x+o.w<=W+2&&o.y+o.h<=H+2&&o.w>=90&&o.h>=30);
 const visible=items.filter(o=>o.y>=0&&o.y+o.h<=H+2);
 const lines=rows(visible.filter(o=>o.y<650));
 const titleLine=[...lines].filter(l=>page.role==='cover'||l.y<180).sort((a,b)=>Math.max(...b.items.map(o=>o.style.fontSize))-Math.max(...a.items.map(o=>o.style.fontSize)))[0];
 if(!titleLine)return {frames:[],unsupported,pictures,panels,items,title:null,rich:true};
 const titleItems=titleLine.items,titleBox=bounds(titleItems),titleStyle=[...titleItems].sort((a,b)=>b.text.length-a.text.length)[0].style;
 const titlePanel=panels.filter(p=>titleItems.every(o=>inside(p,o))).sort((a,b)=>area(a)-area(b))[0];
 // The title can use its actual containing shape, without migrating to a
 // different page just because that page has a larger text box.
 const title={...titleBox,h:Math.max(titleBox.h,titleStyle.fontSize*1.2),style:{...titleStyle},field:'title',sourceIds:titleItems.map(o=>o.id)};
 if(titlePanel){title.x=titlePanel.x+28;title.w=titlePanel.w-56;title.h=Math.min(titlePanel.h-20,Math.max(title.h,titleStyle.fontSize*1.2));title.style.align='center';}
 else if(page.role!=='cover')title.w=Math.max(title.w,W-80-title.x);
 const diagramPanels=panels.filter(p=>p.w>=300&&p.h>=200&&pictures.filter(i=>i.x>=p.x&&i.y>=p.y&&i.x+i.w<=p.x+p.w+2&&i.y+i.h<=p.y+p.h+2).length>=3&&panels.filter(c=>c!==p&&area(c)<area(p)&&inside(p,c)).length>=4);
 const retainedTextIds=new Set(visible.filter(o=>diagramPanels.some(p=>inside(p,o))).map(o=>o.id));
 const timelines=objects.filter(o=>!text(o)&&!image(o)&&box(o)&&o.w>W*.5&&o.h<12&&o.y>200).map(line=>({line,nodes:objects.filter(o=>!text(o)&&!image(o)&&box(o)&&o.w<45&&o.h<45&&Math.abs(o.y-line.y)<35&&o.x>=line.x&&o.x+o.w<=line.x+line.w+5)})).filter(t=>t.nodes.length>=3);
 const timelineIds=new Set(timelines.flatMap(t=>[t.line.id,...t.nodes.map(o=>o.id)]));
 const assigned=new Set([...title.sourceIds,...retainedTextIds]),frames=[],decorations=[],pillPanels=[];
 const storyFooterIds=new Set(rows(visible.filter(o=>o.y>=640)).flatMap(row=>row.groups).filter(group=>Math.max(...group.items.map(o=>o.style.fontSize))>20&&group.text.length>18).flatMap(group=>group.items.map(o=>o.id)));
 const content=visible.filter(o=>!assigned.has(o.id)&&(o.y<650||storyFooterIds.has(o.id))&&o.style.fontSize>=14&&o.y>=titleBox.y+titleBox.h-2);
 const parent=new Map(content.map(o=>[o.id,panels.filter(p=>p!==titlePanel&&inside(p,o)).sort((a,b)=>area(a)-area(b))[0]]));
 const addFrame=(selected,geometry,kind,panelId,priority)=>{if(!selected.length)return;frames.push(makeFrame(selected,geometry,kind,panelId,priority));selected.forEach(o=>assigned.add(o.id));};

 // Portraits are four independent biographies, not three full-width rows.
 const portraitGroups=[];
 for(const p of pictures.filter(p=>p.h>=120&&p.w>=100&&p.w/p.h>.7&&p.w/p.h<1.35)){
  let row=portraitGroups.find(g=>sameRow(g[0],p));if(!row){row=[];portraitGroups.push(row);}row.push(p);
 }
 const portraits=portraitGroups.find(g=>g.length>=3&&g.length<=4&&g.every(p=>Math.abs(p.w/g[0].w-1)<.12&&Math.abs(p.h/g[0].h-1)<.12))?.sort((a,b)=>a.x-b.x);
 if(portraits){
  const anchors=portraits.map(p=>p.x+p.w/2),start=Math.max(...portraits.map(p=>p.y+p.h))+12;
  const bottom=Math.min(650,...panels.filter(p=>p.y>start&&p.w>W*.6).map(p=>p.y-12));
  for(let i=0;i<portraits.length;i++){
   const left=i?(anchors[i-1]+anchors[i])/2:Math.max(64,portraits[0].x-36),right=i<portraits.length-1?(anchors[i]+anchors[i+1])/2:Math.min(1216,portraits.at(-1).x+portraits.at(-1).w+36);
   const selected=content.filter(o=>!parent.get(o.id)&&o.y>=start-5&&o.y<bottom&&o.x+o.w/2>=left&&o.x+o.w/2<right);
   if(selected.length)addFrame(selected,{x:left+10,y:Math.min(...selected.map(o=>o.y)),w:right-left-20,h:bottom-Math.min(...selected.map(o=>o.y))},'column',null,110);
  }
 }
 for(const panel of panels){
  if(panel===titlePanel)continue;
  const selected=content.filter(o=>!assigned.has(o.id)&&parent.get(o.id)===panel);
  if(!selected.length)continue;
  if(panel.w<260&&panel.h<65){pillPanels.push({panel,items:selected});selected.forEach(o=>assigned.add(o.id));continue;}
  const grouped=rows(selected.filter(o=>!arrow(o.text))),anchors=columnAnchors(grouped);
  if(anchors&&panel.h>=120){
   const top=Math.min(...anchors.map(g=>g.y));
   const bottom=Math.min(panel.y+panel.h-18,...panels.filter(p=>p!==panel&&p.x>=panel.x&&p.x+p.w<=panel.x+panel.w+2&&p.y>top+25&&p.y<panel.y+panel.h).map(p=>p.y-12));
   for(let i=0;i<anchors.length;i++){
    const left=anchors[i].x,right=i<anchors.length-1?anchors[i+1].x-48:panel.x+panel.w-28;
    const cell=selected.filter(o=>!arrow(o.text)&&o.y>=top-3&&o.y<bottom&&o.x>=left-5&&o.x<right);
    addFrame(cell,{x:left,y:top,w:right-left,h:bottom-top},'column',panel.id,100);
   }
   const header=selected.filter(o=>o.y<top-5&&!arrow(o.text));
   if(header.length){decorations.push({kind:'heading',...makeFrame(header,{...bounds(header)},'heading',panel.id,0)});header.forEach(o=>assigned.add(o.id));}
   selected.filter(o=>arrow(o.text)).forEach(o=>{decorations.push({kind:'source',object:o});assigned.add(o.id);});
  }else{
   const textBox=bounds(selected),padX=Math.max(20,Math.min(40,textBox.x-panel.x)),padY=panel.h>=65?12:Math.max(6,Math.min(12,textBox.y-panel.y));
   const nested=panels.filter(p=>p!==panel&&area(p)<area(panel)&&p.x>=panel.x&&p.x+p.w<=panel.x+panel.w+2&&p.y>textBox.y+20&&p.y<panel.y+panel.h);
   const bottom=Math.min(panel.y+panel.h-padY,...nested.map(p=>p.y-10));
   addFrame(selected,{x:panel.x+padX,y:panel.y+padY,w:panel.w-padX*2,h:bottom-panel.y-padY},panel.h<65?'band':'summary',panel.id,panel.h<65?70:90);
  }
 }
 // Text on an uninterrupted background keeps its original reading groups.
 // Evidence captions may share a wide row, but never paint over screenshots.
 const remaining=content.filter(o=>!assigned.has(o.id)&&!arrow(o.text));
 if(page.role==='cover'){
  for(const row of rows(remaining)){
   const b=bounds(row.items),next=Math.min(650,...visible.filter(o=>o.y>b.y+b.h+1&&o.x<b.x+b.w&&o.x+o.w>b.x).map(o=>o.y-8));
   const right=Math.min(1200,...pictures.filter(p=>p.x>b.x+80&&p.y<b.y+70&&p.y+p.h>b.y).map(p=>p.x-20));
   const parts=[];
   for(const o of row.items){if(o.text.trim()==='·'){parts.push([]);continue;}if(!parts.length)parts.push([]);parts.at(-1).push(o);}
   if(parts.length>=2&&b.y<520){
    for(const part of parts.filter(p=>p.length)){const partBox=bounds(part);addFrame(part,{...partBox,w:Math.max(partBox.w,Math.min(290,right-partBox.x)),h:Math.max(partBox.h,66)},'cover-detail',null,60);}
   }else addFrame(row.items,{x:b.x,y:b.y,w:Math.min(right-b.x,Math.max(b.w,880)),h:Math.max(b.h,row.items[0].style.fontSize*1.2+1,Math.min(66,next-b.y))},'cover-detail',null,60);
  }
 }else if(pictures.length&&!portraits){
  const captionRows=rows(remaining.filter(o=>o.y>Math.min(...pictures.map(p=>p.y+p.h))-8));
  for(const row of captionRows){
   const b=bounds(row.items),left=Math.max(64,Math.min(...pictures.map(p=>p.x))),right=Math.min(1216,Math.max(...pictures.map(p=>p.x+p.w)));
   const next=Math.min(650,...panels.filter(p=>p.y>b.y+b.h-2).map(p=>p.y-8),...pictures.filter(p=>p.y+p.h>b.y&&p.x<right&&p.x+p.w>left).map(p=>p.y-8),...remaining.filter(o=>o.y>b.y+b.h+4).map(o=>o.y-4));
   addFrame(row.items,{x:left,y:b.y,w:right-left,h:Math.max(b.h,Math.min(90,next-b.y))},'caption',null,75);
  }
 }else{
  for(const row of rows(remaining)){
   const b=bounds(row.items),next=Math.min(650,...panels.filter(p=>p.y>b.y+b.h-2).map(p=>p.y-10),...remaining.filter(o=>o.y>b.y+b.h+4).map(o=>o.y-8));
   addFrame(row.items,{...b,w:Math.max(b.w,Math.min(1118,1200-b.x)),h:Math.max(b.h,Math.min(70,next-b.y))},'line',null,40);
  }
 }
 // The brand/footer is part of the source design, not discarded body copy.
 const preTitle=visible.filter(o=>o.y<titleBox.y-12&&o.y<70&&o.style.fontSize>=14);
 if(page.role!=='cover'&&preTitle.length){const b=bounds(preTitle);addFrame(preTitle,{...b,w:W-80-b.x,h:Math.max(b.h,preTitle[0].style.fontSize*1.2)},'band',null,45);}
 const fixed=rows(visible.filter(o=>!assigned.has(o.id)&&(o.y>=650||page.role==='cover'&&o.y<titleBox.y))).flatMap(row=>row.groups);
 const bodyFaces=visible.filter(o=>o.style.fontSize>=17&&o.style.fontSize<25&&o.y>titleBox.y+titleBox.h&&o.y<650&&/[\p{L}\p{N}]/u.test(o.text)&&!arrow(o.text)).map(o=>o.style);
 for(const frame of frames){if(frame.levels.length===1&&frame.primary.fontSize>25&&bodyFaces.length)frame.detail={...bodyFaces[0],color:frame.style.color};frame.readingStyle=bodyFaces.find(s=>s.fontSize<=22);frame.emphasis=visible.find(o=>o.style.color.toLowerCase()==='#ff0000')?.style.color;frame.timeline=timelines.some(t=>frame.y>=t.line.y-65&&frame.y<t.line.y+65);}
 return {rich:true,frames:frames.filter(f=>f.w>0&&f.h>0).sort((a,b)=>Math.abs(a.y-b.y)<4?a.x-b.x:a.y-b.y),title,pictures,panels,pillPanels,decorations,fixed,retainedTextIds,diagramPanels,timelineIds,unsupported,items};
}

const charWidth=c=>/\s/.test(c)?.35:/[\u0000-\u00ff]/.test(c)?.65:1;
let measurer;
const heightCache=new Map();
export function measureAudienceText(value,width,style){
 if(typeof document==='undefined'||!document.body)return null;
 const key=JSON.stringify([value,width,style.fontSize,style.fontFamily,style.bold,style.italic,style.lineHeight]);
 if(heightCache.has(key))return heightCache.get(key);
 if(!measurer?.isConnected){measurer=document.createElement('div');measurer.setAttribute('aria-hidden','true');document.body.append(measurer);}
 Object.assign(measurer.style,{position:'fixed',left:'-100000px',top:'0',visibility:'hidden',pointerEvents:'none',boxSizing:'border-box',margin:'0',padding:'0',border:'0',height:'auto',width:width+'px',fontFamily:(style.fontFamily||'Microsoft YaHei')+',sans-serif',fontSize:style.fontSize+'px',fontWeight:style.bold?'700':'400',fontStyle:style.italic?'italic':'normal',lineHeight:String(style.lineHeight||1.15),whiteSpace:'pre-wrap',overflowWrap:'anywhere'});
 measurer.textContent=value;
 const result=measurer.getBoundingClientRect().height;
 if(heightCache.size>=512)heightCache.clear();heightCache.set(key,result);
 return result;
}
export function fitCompositionText(value,region){
 const measured=measureAudienceText(value,region.w,region.style);
 if(measured!==null)return measured<=region.h+.01?value.length:0;
 const size=region.style.fontSize,width=(region.w-4)/size,maxLines=Math.floor((region.h+.01)/(size*(region.style.lineHeight||1.15)));
 if(maxLines<1)return 0;let lines=1,used=0,index=0;
 for(const c of value){if(c==='\n'){if(lines===maxLines)break;lines++;used=0;index+=c.length;continue;}const n=charWidth(c);if(used+n>width){if(lines===maxLines)break;lines++;used=0;}used+=n;index+=c.length;}
 return index;
}
function height(value,width,style){const measured=measureAudienceText(value,width,style);if(measured!==null)return measured+(style.fontSize>=28?style.fontSize*.1:0);let h=style.fontSize*(style.lineHeight||1.15);let used=0;for(const c of value){if(c==='\n'||used+charWidth(c)>(width-4)/style.fontSize){h+=style.fontSize*(style.lineHeight||1.15);used=0;if(c==='\n')continue;}used+=charWidth(c);}return h+(style.fontSize>=28?style.fontSize*.1:0);}
function blocks(body,title){
 const aliases=[],result=[];
 for(const m of body.matchAll(/[^\n]+/g)){
  if(!m[0].trim())continue;
  const b={text:m[0],start:m.index,end:m.index+m[0].length};
  if([title,...title.split(/[｜|]/)].some(t=>normalized(b.text)===normalized(t))){aliases.push([b.start,b.end]);continue;}
  result.push(b);
 }
 // A heading followed by a numbered list is one semantic group. Keeping it
 // together prevents a checklist heading floating alone in a large panel.
 for(let i=0;i<result.length-1;i++)if(/[：:]\s*$/.test(result[i].text)&&/^\s*\d+[.、．]/.test(result[i+1].text)){
  let end=i+1;while(end+1<result.length&&/^\s*\d+[.、．]/.test(result[end+1].text))end++;
  result.splice(i,end-i+1,{text:body.slice(result[i].start,result[end].end),start:result[i].start,end:result[end].end});
 }
 return {blocks:result,titleBodyRanges:aliases};
}
function pieces(block,frame){
 const s=block.text,pipe=s.search(/[｜|]/),colon=s.search(/[：:]/),parts=[];
 if(frame.kind==='band'||frame.kind==='line'||frame.kind==='caption'||frame.kind==='cover-detail'||frame.levels.length===1){
  for(const base of [frame.primary,frame.detail]){
   const style={...base,lineHeight:1.15},h=height(s,frame.w,style);
   if(h<=frame.h+.1)return [{region:{x:frame.x,y:frame.y,w:frame.w,h,style},text:s,start:block.start,end:block.end,field:'body'}];
  }
  return null;
 }
 // Preserve labels, names, roles and their smaller explanatory copy. Every
 // displayed character is sliced from the confirmed text, with exact ranges.
 if(pipe>0&&pipe<18&&colon>pipe&&colon<36){parts.push([0,pipe],[pipe,colon+1],[colon+1,s.length]);}
 else if(colon>0&&colon<26)parts.push([0,colon+1],[colon+1,s.length]);
 else parts.push([0,s.length]);
 const primary={...frame.primary,lineHeight:1.15},detail={...frame.detail,lineHeight:1.2};
 const smallDetail=frame.readingStyle&&frame.readingStyle.fontSize<detail.fontSize?{...detail,fontSize:frame.readingStyle.fontSize,fontFamily:frame.readingStyle.fontFamily}:detail;
 const label={...frame.style,lineHeight:1.15};
 const make=(small=false)=>{
  let y=frame.y;const placed=[];
  for(let i=0;i<parts.length;i++){
   const [a,b]=parts[i];if(a===b)continue;
   let style;
   if(parts.length===1)style=small?smallDetail:primary;
   else if(parts.length===3)style=i===0?primary:i===1?{...(frame.levels[1]||label),lineHeight:1.15}:detail;
   else if(frame.headlineFirst)style=i===0?primary:small?smallDetail:detail;
   else style=i===0?label:small?smallDetail:primary;
   const value=s.slice(a,b);if(frame.kind==='summary'&&frame.primary.fontSize>30&&value.includes('待补充')&&frame.emphasis)style={...style,color:frame.emphasis};const h=height(value,frame.w,style);
   if(y+h>frame.y+frame.h+.1)return null;
   placed.push({region:{x:frame.x,y,w:frame.w,h,style},text:value,start:block.start+a,end:block.start+b,field:'body'});y+=h+(i<parts.length-1?6:0);
  }
  return placed;
 };
 return make()||make(true);
}
function inFrame(block,frame){
 const p=pieces(block,frame);return p?{placements:p,remaining:''}:null;
}
function assignBlocks(input,frames){
 // Prefer an entire source component for each confirmed paragraph. Dynamic
 // programming retains reading order while avoiding one giant greedy box.
 const cache=new Map();
 const walk=(i,j)=>{
  if(i===input.length)return {score:0,placements:[],used:[]};if(j===frames.length)return null;
  const key=i+':'+j;if(cache.has(key))return cache.get(key);
  let best=walk(i,j+1);best=best&&{...best,score:best.score-1};
  let display='',parts=[];
  for(let end=i;end<input.length;end++){
   const frame=frames[j],all=input.slice(i,end+1),gap=all.length>1?2:0;
   let y=frame.y,placed=[],valid=true;
   for(const b of all){const p=inFrame(b,{...frame,y,h:frame.y+frame.h-y});if(!p){valid=false;break;}placed.push(...p.placements);const last=p.placements.at(-1);y=last.region.y+last.region.h+gap;}
   if(!valid)break;
   const tail=walk(end+1,j+1);if(!tail)continue;
   const score=tail.score+frame.priority-(end-i)*35;
   if(!best||score>best.score)best={score,placements:[...placed,...tail.placements],used:[j,...tail.used]};
  }
  cache.set(key,best);return best;
 };
 return walk(0,0);
}
export function composeSourceText(analysis,{title,body,pageNumber,role}){
 const {blocks:input,titleBodyRanges}=blocks(body,title),frames=analysis.frames.filter(f=>!f.timeline||role==='flow');
 const assignment=assignBlocks(input,frames),placements=[],decorative=[],removePanels=new Set(role==='flow'?[]:analysis.timelineIds);
 const titleRegion=analysis.title;
 if(titleRegion)placements.push({region:titleRegion,text:title,field:'title'});
 if(assignment)placements.push(...assignment.placements);
 const used=new Set((assignment?.used||[]).map(i=>frames[i].panelId).filter(Boolean));
 // Empty small widgets can be removed, while the major source containers and
 // their arrows remain intact. Fill tag labels only from confirmed copy.
 const labels=input.map(b=>b.text.match(/^(.{1,12}?)[：:｜|]/)?.[1]).filter(Boolean);
 let labelIndex=0;
 for(const pill of analysis.pillPanels||[]){
  const original=pill.items.map(o=>o.text).join('');const token=original.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');let value=pill.panel.y<350?(body.includes('待补充')?'待补充':''):original.length<=12&&new RegExp('(?:^|[、，,\\s：:；;])'+token+'(?=$|[、，,\\s。；;])').test(body)?original:null;
  const style={...pill.items[0].style,align:'center'},region={x:pill.panel.x+6,y:pill.panel.y+5,w:pill.panel.w-12,h:pill.panel.h-10,style};
  if(!value&&pill.panel.y>=350)while(labelIndex<labels.length){const candidate=labels[labelIndex++];if(fitCompositionText(candidate,region)===candidate.length){value=candidate;break;}}
  if(value&&fitCompositionText(value,region)===value.length)decorative.push({region,text:value,field:'decoration'});else removePanels.add(pill.panel.id);
 }
 for(const d of analysis.decorations||[]){
  if(d.kind==='source'){
   if(!body.includes('→')||!/^[→←↑↓]$/.test(d.object.text.trim())||!assignment||analysis.frames.some(f=>inside(f,d.object)))continue;
   decorative.push({region:{...d.object,style:d.object.style},text:d.object.text,field:'decoration'});
  }
  else if(d.kind==='heading'&&used.has(d.panelId)){
   const region={x:d.x,y:d.y,w:d.w,h:Math.max(d.h,d.primary.fontSize*1.2),style:d.primary};
   const value=title.replace(/^.*?[｜|]/,'');if(fitCompositionText(value,region)===value.length)decorative.push({region,text:value,field:'decoration'});
  }
 }
 for(const o of analysis.fixed||[]){
  let value=o.text;
  if(o.y>=650&&/^\d{1,3}$/.test(value.trim()))value=String(pageNumber).padStart(2,'0');
  // Footer brand and source cover mark belong to the design, independently
  // of whether the new narrative happens to repeat the brand in its body.
  const region={x:o.x,y:o.y,w:Math.max(o.w,value.length*o.style.fontSize*.7+4),h:Math.max(o.h,o.style.fontSize*1.2),style:o.style};
  decorative.push({region,text:value,field:'decoration'});
 }
 return {placements,decorative,removePanels,unplacedBody:assignment?'':input.map(b=>b.text).join('\n'),titleBodyRanges,structured:!!assignment,components:assignment?.used.length||0,titleOverflow:titleRegion&&fitCompositionText(title,titleRegion)<title.length};
}
