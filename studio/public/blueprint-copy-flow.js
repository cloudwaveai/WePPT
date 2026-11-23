// Source-preserving copy flow for opt-in, offline-designed layouts. No I/O or
// geometry repair: measurement and rendering use this same fixed-font algorithm.
const clone=value=>structuredClone(value);
const finite=(value,fallback)=>Number.isFinite(value)?value:fallback;
const style=region=>({size:Math.max(1,finite(region.fontSize,26)),lineHeight:Math.max(1,finite(region.lineHeight,1.42))});

function paragraphs(source){
 const sections=[];let section=null,hasHeadings=false;
 for(const match of source.matchAll(/[^\r\n]+/g)){
  const raw=match[0],prefix=raw.match(/^##[ \t]+/),heading=!!prefix;
  let start=match.index+(prefix?prefix[0].length:0),end=match.index+raw.length;
  while(start<end&&/\s/u.test(source[start]))start++;
  while(end>start&&/\s/u.test(source[end-1]))end--;
  if(start===end)continue;
  if(heading){hasHeadings=true;section=[];sections.push(section);}
  else if(!section||!hasHeadings){section=[];sections.push(section);}
  section.push({start,end,text:source.slice(start,end),heading});
 }
 return sections;
}

function glyphUnits(char){
 if(/\s/u.test(char))return .34;
 if(/[MW@%]/u.test(char))return .92;
 if(/[ilI.,:;!'|]/u.test(char))return .36;
 return /[^\u0000-\u00ff]/u.test(char)?1:.64;
}

function glyphsFitWidth(text,width,size){
 const limit=width/size*.95;
 return [...text].every(char=>char==='\n'||char==='\r'||glyphUnits(char)<=limit);
}

function lines(text,width,size){
 // A small width reserve handles normal font-metric variance without reducing
 // the selected font size. Actual Office/browser rendering is still reviewed.
 const limit=Math.max(.01,width/size*.95);let count=1,used=0;
 for(const char of text){
  if(char==='\n'){count++;used=0;continue;}
  const next=glyphUnits(char);
  if(used>0&&used+next>limit){count++;used=0;}
  used+=next;
 }
 return text?count:0;
}

function paragraphHeight(part,region){
 const {size,lineHeight}=style(region),fontSize=part.heading?Math.max(size,finite(region.headingSize,size)):size;
 return Math.ceil(lines(part.text,region.w,fontSize)*fontSize*lineHeight);
}
const gapAfter=(part,region)=>Math.max(0,part.heading?finite(region.headingGap,8):finite(region.paragraphGap,14));
const sectionGap=region=>Math.max(0,finite(region.sectionGap,24));
// Opt-in editorial columns continue only at a complete source clause. A numeric
// comma/date is not a boundary; source offsets and punctuation stay unchanged.
function clauseEnds(text){
 const ends=[];
 for(const match of text.matchAll(/[。！？；，]|[.!?;](?=\s|$)/gu))ends.push(match.index+match[0].length);
 return ends;
}
function groupHeight(sections,region){
 return sections.reduce((total,section,index)=>total+(index?sectionGap(region):0)+section.reduce((height,part,i)=>height+(i?gapAfter(section[i-1],region):0)+paragraphHeight(part,region),0),0);
}

// Keep whole semantic sections together. The partition changes only which
// existing region receives each section; it never changes a region's geometry.
function partition(sections,regions){
 const count=Math.min(sections.length,regions.length),memo=new Map();
 const solve=(start,index)=>{
  if(index===count)return start===sections.length?{cost:0,groups:[]}:null;
  const key=start+':'+index;if(memo.has(key))return memo.get(key);
  let best=null;
  const max=sections.length-(count-index-1);
  for(let end=start+1;end<=max;end++){
   const tail=solve(end,index+1);if(!tail)continue;
   const height=groupHeight(sections.slice(start,end),regions[index]),room=Math.max(1,regions[index].h),overflow=Math.max(0,height-room);
   const cost=tail.cost+overflow*overflow*1000+Math.pow((room-height)/room,2);
   if(!best||cost<best.cost)best={cost,groups:[sections.slice(start,end),...tail.groups]};
  }
  memo.set(key,best);return best;
 };
 return count?solve(0,0).groups:[];
}

function clearSource(object){
 for(const key of ['sourceField','layoutField','sourceText','sourceRange','sourceStart','sourceEnd'])delete object[key];
 return object;
}

export function fillBlueprintCopy(page,layout){
 const source=String(page.body??''),sections=paragraphs(source),prototypes=clone(layout.objects||[]),regions=prototypes.filter(o=>o.blueprintSlot==='body'),titles=prototypes.filter(o=>o.blueprintSlot==='title');
 const warnings=[],objects=[],used=new Set(),demand=new Map();let serial=0;
 const warn=message=>{if(!warnings.includes(message))warnings.push(message);};
 const minSections=layout.contentContract?.minSections;
 if(Number.isInteger(minSections)&&minSections>sections.length)warn(`当前构图需要至少 ${minSections} 个内容小节，原文只有 ${sections.length} 个；原文已保留，请重新选择构图。`);
 const maxSections=layout.contentContract?.maxSections;
 if(Number.isInteger(maxSections)&&maxSections<sections.length)warn(`当前构图最多支持 ${maxSections} 个内容小节，原文有 ${sections.length} 个；原文已保留，请重新选择构图。`);
 if([...titles,...regions].some(region=>![region.x,region.y,region.w,region.h].every(Number.isFinite)||region.x<0||region.y<0||region.w<=0||region.h<=0||region.x+region.w>1280||region.y+region.h>720))warn('模板文本区域无效或超出画布，不能通过验收。');
 const overflowMessage='文字超过模板文本区域容量，完整原文已保留；请重新选择构图或调整内容，字号未缩小。';
 const add=(part,region,y)=>{
  const height=paragraphHeight(part,region),bottom=region.y+region.h,{size,lineHeight}=style(region),fontSize=part.heading?Math.max(size,finite(region.headingSize,size)):size;
  const fits=y+height<=bottom+.01&&region.w>0&&region.h>0;
  if(!fits)warn(overflowMessage);
  if(!glyphsFitWidth(part.text,region.w,fontSize))warn('正文单字超过文本区域横向宽度，完整原文已保留，字号未缩小。');
  // Even on overflow, preserve every source segment in an editable object and
  // keep its frame within the original region. The warning blocks acceptance.
  const safeY=Math.min(Math.max(region.y,y),Math.max(region.y,bottom-1));
  const object={...clearSource(clone(region)),id:`${page.id||'page'}-${region.id||'body'}-flow-${serial++}`,type:'text',x:region.x,y:safeY,w:region.w,h:Math.max(1,Math.min(height,bottom-safeY)),fontSize,lineHeight,bold:part.heading||!!region.bold,text:source.slice(part.start,part.end),sourceText:source.slice(part.start,part.end),sourceField:'body',layoutField:'body',sourceRange:[part.start,part.end],sourceStart:part.start,sourceEnd:part.end,layoutManaged:true,flowTypesetting:true,flowRegionId:region.id,flowHeading:part.heading};
  objects.push(object);used.add(region);demand.set(region,Math.max(demand.get(region)||0,y+height-region.y));return height;
 };
 for(const prototype of prototypes){
  if(prototype.blueprintSlot==='body'||prototype.blueprintSlot==='title')continue;
  objects.push(prototype);
 }
 if(titles.length!==1)warn('流式模板需要一个完整标题区域，当前模板结构无效。');
 if(titles.length){
  const title=clearSource(clone(titles[0])),text=String(page.title??''),{size,lineHeight}=style(title);
  objects.push({...title,text,sourceText:text,sourceField:'title',layoutField:'title',fontSize:size,lineHeight,layoutManaged:true,flowTypesetting:true});
  if(lines(text,title.w,size)*size*lineHeight>title.h+.01)warn('标题超过模板文本框容量，完整标题已保留，字号未缩小。');
  if(!glyphsFitWidth(text,title.w,size))warn('标题单字超过文本框横向宽度，完整标题已保留，字号未缩小。');
 }
 if(sections.length&&!regions.length)warn('模板缺少正文区域，原始正文保留在页面中，不能通过验收。');
 if(layout.bodyFlow==='continuous'&&regions.length){
  let regionIndex=0,y=regions[0].y;
  const advance=()=>{if(regionIndex>=regions.length-1)return false;regionIndex++;y=regions[regionIndex].y;return true;};
  for(let s=0;s<sections.length;s++){
   if(s)y+=sectionGap(regions[regionIndex]);
   for(let p=0;p<sections[s].length;p++){
    let part={...sections[s][p]};if(p)y+=gapAfter(sections[s][p-1],regions[regionIndex]);
    while(part.start<part.end){
     let region=regions[regionIndex],height=paragraphHeight(part,region);
     const next=sections[s][p+1],clauseFlow=layout.flowBreakPolicy==='punctuation';
     const lead=next&&clauseFlow?{...next,text:next.text.slice(0,clauseEnds(next.text)[0]||next.text.length)}:null;
     const reserve=part.heading&&next?gapAfter(part,region)+(lead?paragraphHeight(lead,region):style(region).size*style(region).lineHeight):0;
     if(y+height+reserve>region.y+region.h&&regionIndex<regions.length-1){
      // Do not orphan a heading or split an ordinary paragraph when it fits
      // intact in the following region.
      const following=regions[regionIndex+1];
      if(part.heading||!clauseFlow&&paragraphHeight(part,following)<=following.h){advance();continue;}
      let end=part.start,accepted=part.start;
      for(const char of source.slice(part.start,part.end)){
       end+=char.length;
       if(paragraphHeight({...part,text:source.slice(part.start,end)},region)>region.y+region.h-y)break;
       accepted=end;
      }
      if(clauseFlow){
       const boundaries=clauseEnds(source.slice(part.start,part.end)).map(offset=>part.start+offset);
       accepted=boundaries.filter(offset=>offset<=accepted).at(-1)||part.start;
      }
      if(accepted>part.start){const head={...part,end:accepted,text:source.slice(part.start,accepted)};y+=add(head,region,y);part={...part,start:accepted,text:source.slice(accepted,part.end)};}
      advance();continue;
     }
     y+=add(part,region,y);break;
    }
   }
  }
 }else if(regions.length){
  const groups=partition(sections,regions);
  groups.forEach((group,index)=>{
   const region=regions[index];let y=region.y;
   group.forEach((section,s)=>{if(s)y+=sectionGap(region);section.forEach((part,p)=>{if(p)y+=gapAfter(section[p-1],region);y+=add(part,region,y);});});
  });
 }
 const availableHeight=regions.reduce((n,region)=>n+region.h,0);
 const requiredHeight=[...demand.values()].reduce((n,height)=>n+height,0);
 return {objects,warnings,fits:warnings.length===0,requiredHeight,availableHeight,bodyRegions:regions.length,usedRegions:used.size,bodySections:sections.length};
}

export function measureBlueprintCopy(page,layout){
 const {objects,...measurement}=fillBlueprintCopy(page,layout);return measurement;
}
