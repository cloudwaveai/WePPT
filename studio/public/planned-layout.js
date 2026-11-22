import {getDesignGroups,validateDesignPlans,DESIGN_CASES} from './design-cases.js';
const BLUE='#316BF0',BLACK='#050505',WHITE='#FFFFFF';
export const DESIGN_PHOTOS={
 building:{src:'/assets/templates/curated-139/6.jpg',crop:{x:56/800,y:163/450,w:275/800,h:183/450}},
 architecture:{src:'/assets/templates/curated-139/4.jpg',crop:{x:457/800,y:107/450,w:265/800,h:132/450}},
 horse:{src:'/assets/templates/curated-139/1.jpg',crop:{x:48/800,y:190/450,w:113/800,h:190/450}},
 stairs:{src:'/assets/templates/curated-139/0.jpg',crop:{x:70/1600,y:72/900,w:162/1600,h:217/900}},
 window:{src:'/assets/templates/curated-139/0.jpg',crop:{x:1369/1600,y:608/900,w:157/1600,h:218/900}}
};
const units=s=>[...String(s)].reduce((n,c)=>n+(/[^\u0000-\u00ff]/.test(c)?1:.59),0);
const lines=(s,size,width)=>String(s).split('\n').reduce((n,line)=>n+Math.max(1,Math.ceil(units(line)*size/Math.max(size,width-size*2-10))),0);
function textSegments(group){const result=[];let start=0;for(const match of group.text.matchAll(/\n/g)){add(start,match.index);start=match.index+1;}add(start,group.text.length);return result;
 function add(a,b){const raw=group.text.slice(a,b),prefix=raw.match(/^##[ \t]+/),offset=prefix?prefix[0].length:0,value=raw.slice(offset),lead=value.match(/^\s*/)[0].length,trail=value.match(/\s*$/)[0].length;if(lead+trail>=value.length)return;result.push({text:value.slice(lead,value.length-trail),start:group.start+a+offset+lead,end:group.start+b-trail,heading:!!prefix,groupIndex:group.index});}}
/** Native editable scene from model-authored arbitrary zones; this never rewrites content. */
export function layoutPlannedPage(input,theme,proposed){
 const plan=validateDesignPlans([proposed],[input])[0],page=structuredClone(input),body=String(page.body||''),title=String(page.title||''),groups=getDesignGroups(body),font=theme?.fontFamily||'Microsoft YaHei';
 const objects=[];let serial=0;const warnings=[];let overflow=false;
 const make=(type,box,extra={})=>{const object={id:`layout-${page.id}-planned-${serial++}`,type,x:box.x,y:box.y,w:box.w,h:box.h,rotation:0,opacity:1,layoutManaged:true,designManaged:true,...extra};objects.push(object);return object;};
 const rect=(box,fill=WHITE,stroke=BLACK,strokeWidth=2)=>make('rect',box,{fill,stroke,strokeWidth,radius:0});
 const text=(value,box,size,extra={})=>make('text',box,{text:value,sourceText:value,fontFamily:font,fontSize:size,bold:false,color:BLACK,align:'left',lineHeight:1.4,...extra});
 const line=(a,b,color=BLACK,width=3)=>{const length=Math.hypot(b.x-a.x,b.y-a.y);if(length<1)return;return make('line',{x:(a.x+b.x)/2-length/2,y:(a.y+b.y)/2,w:length,h:0},{stroke:color,strokeWidth:width,rotation:Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI});};
 function controls(x,y,w,bar){if(w<220)return;for(let i=0;i<3;i++){const left=x+w-70+i*20;rect({x:left,y:y+(bar-13)/2,w:13,h:13},'#B9DBFF',BLACK,1);if(i===0){line({x:left+3,y:y+(bar-13)/2+3},{x:left+10,y:y+(bar-13)/2+10},BLACK,1);line({x:left+3,y:y+(bar-13)/2+10},{x:left+10,y:y+(bar-13)/2+3},BLACK,1);}else if(i===1)rect({x:left+3,y:y+(bar-13)/2+3,w:7,h:7},'#B9DBFF',BLACK,1);else line({x:left+3,y:y+(bar-13)/2+10},{x:left+10,y:y+(bar-13)/2+10},BLACK,1);}}
 // Photography is always behind text surfaces and never a whole-slide substitute.
 if(plan.photo.kind!=='none'){const p=plan.photo,spec=DESIGN_PHOTOS[p.kind];rect(p,BLACK);make('image',{x:p.x+2,y:p.y+2,w:p.w-4,h:p.h-4},{...structuredClone(spec),fit:'cover',referencePhoto:true,sourceReference:spec.src});}
 const heroSheet=[0,7].includes(plan.referencePage);
 if(heroSheet){const boxes=[plan.titleBox,...plan.zones],x=Math.max(8,Math.min(...boxes.map(b=>b.x))-24),y=Math.max(8,Math.min(...boxes.map(b=>b.y))-48),right=Math.min(1272,Math.max(...boxes.map(b=>b.x+b.w))+24),bottom=Math.min(700,Math.max(...boxes.map(b=>b.y+b.h))+24);rect({x,y,w:right-x,h:bottom-y},WHITE);rect({x,y,w:right-x,h:26},BLACK,BLACK,0);controls(x,y,right-x,26);rect({x:right-10,y:y+26,w:10,h:bottom-y-26},'#DADADA',BLACK,1);}
 // Draw every surface before the text to avoid a later surface hiding earlier copy.
 const areas=plan.zones.map((zone,index)=>{let pad=zone.style==='plain'?0:20,bar=0,header=null;const parts=zone.groupIndices.flatMap(i=>textSegments(groups[i]));
  if(zone.style==='window'&&!heroSheet){rect(zone,WHITE);header=parts[0]?.heading?parts[0]:null;bar=header?Math.max(44,lines(header.text,28,zone.w-40)*28*1.4+10):26;rect({x:zone.x,y:zone.y,w:zone.w,h:bar},BLACK,BLACK,0);if(!header)controls(zone.x,zone.y,zone.w,bar);}
  else if(zone.style==='band')rect(zone,BLACK,BLACK,0);
  const area={x:zone.x+pad,y:zone.y+bar+pad,w:zone.w-pad*2,h:zone.h-bar-pad*2};if(area.h<34||area.w<72){overflow=true;warnings.push(`正文区域 ${index+1} 太小，需要重新设计。`);}return {zone,index,parts,header,bar,area,color:zone.style==='band'||zone.style==='plain'&&!heroSheet?WHITE:BLACK};
 });
 // Connect relationships at zone edges, with arrowheads rather than lines through text centres.
 for(const connector of plan.connectors){const from=plan.zones[connector.from],to=plan.zones[connector.to],a={x:from.x+from.w/2,y:from.y+from.h/2},b={x:to.x+to.w/2,y:to.y+to.h/2},dx=b.x-a.x,dy=b.y-a.y,k1=Math.min(Math.abs(dx)>0?from.w/2/Math.abs(dx):Infinity,Math.abs(dy)>0?from.h/2/Math.abs(dy):Infinity),k2=Math.min(Math.abs(dx)>0?to.w/2/Math.abs(dx):Infinity,Math.abs(dy)>0?to.h/2/Math.abs(dy):Infinity);const start={x:a.x+dx*k1,y:a.y+dy*k1},end={x:b.x-dx*k2,y:b.y-dy*k2};line(start,end);const angle=Math.atan2(dy,dx);for(const sign of [-1,1])line(end,{x:end.x-10*Math.cos(angle+sign*.55),y:end.y-10*Math.sin(angle+sign*.55)});}
 let titleSize=['cover','chapter','ending'].includes(page.role)?76:48;while(titleSize>32&&lines(title,titleSize,plan.titleBox.w)*titleSize*1.4>plan.titleBox.h)titleSize--;if(lines(title,titleSize,plan.titleBox.w)*titleSize*1.4>plan.titleBox.h+1){overflow=true;warnings.push('标题空间不足，需要扩大标题区域。');}
 text(title,plan.titleBox,titleSize,{bold:true,color:heroSheet?BLACK:WHITE,layoutField:'title',sourceField:'title'});
 for(const {zone,index,parts,header,bar,area,color} of areas){
  const values=header?parts.slice(1):parts;let size=['cover','ending','chapter'].includes(page.role)?29:28;
  const measurements=()=>values.map((s,i)=>{const fontSize=size+(s.heading?3:0),previous=values[i-1],gap=i?(previous.groupIndex!==s.groupIndex?18:s.heading?12:5):0;return {fontSize,gap,height:lines(s.text,fontSize,area.w)*fontSize*1.4+1};});
  let dims=measurements();while(size>24&&dims.reduce((sum,d)=>sum+d.gap+d.height,0)>area.h){size--;dims=measurements();}
  if(dims.reduce((sum,d)=>sum+d.gap+d.height,0)>area.h+1){overflow=true;warnings.push(`正文区域 ${index+1} 超出可读容量，需要重新设计；原文完整保留。`);}
  function sourceStyle(s){return {bold:s.heading,contentRole:s.heading?'subheading':'paragraph',layoutField:'body',sourceField:'body',sourceRange:[s.start,s.end],sourceStart:s.start,sourceEnd:s.end,designGroupIndex:s.groupIndex,designZoneIndex:index};}
  if(header)text(header.text,{x:zone.x+20,y:zone.y+5,w:zone.w-40,h:bar-10},28,{...sourceStyle(header),color:WHITE});
  let y=area.y;values.forEach((s,i)=>{const d=dims[i];y+=d.gap;text(s.text,{x:area.x,y,w:area.w,h:d.height},d.fontSize,{...sourceStyle(s),color});y+=d.height;});
 }
 const retained=(page.objects||[]).filter(o=>o.custom||!o.layoutManaged).map(o=>structuredClone(o)),ids=new Set(objects.map(o=>o.id));for(const object of retained){if(ids.has(object.id))object.id=globalThis.crypto.randomUUID();ids.add(object.id);objects.push(object);}
 page.objects=objects;page.background=BLUE;page.themeId=theme?.id||'curated-139';page.layoutSource={title,body};page.designPlan=plan;page.designSource={referencePage:plan.referencePage,source:DESIGN_CASES[plan.referencePage].source,retainedFeatures:plan.retainedFeatures,relation:plan.relation,composition:plan.composition,reason:plan.reason,adaptation:plan.adaptation};page.designStatus='planned';page.designSourceGroups=groups.map(g=>({index:g.index,start:g.start,end:g.end}));page.layoutOverflow=overflow;page.layoutWarnings=[...new Set(warnings)];return page;
}
