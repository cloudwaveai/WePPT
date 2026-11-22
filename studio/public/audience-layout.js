// Audience adaptation uses the actual source objects and their composition.
import {analyseSourceComposition,composeSourceText,measureAudienceText} from './audience-composition.js';
import {audienceSource} from './audience-plan.js';
const clone=value=>structuredClone(value);
const W=1280,H=720;
const geometry=o=>[o.x,o.y,o.w,o.h].every(Number.isFinite)&&o.w>0&&o.h>0;
const hasSvgText=o=>o.type==='vector'&&/<text\b/i.test(o.svg||'');
const isText=o=>o.type==='text'||hasSvgText(o);
const decode=s=>String(s||'').replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&').replace(/&#(\d+);/g,(_,n)=>String.fromCodePoint(+n));
const attribute=(s,name)=>decode(s.match(new RegExp(`\\b${name}="([^"]*)"`,'i'))?.[1]||'');
function hex(value){
 if(/^#[\da-f]{3,8}$/i.test(value))return value;
 const rgb=value.match(/rgb\(\s*([\d.]+)[, ]+\s*([\d.]+)[, ]+\s*([\d.]+)\s*\)/i);
 return rgb?'#'+rgb.slice(1).map(n=>Math.max(0,Math.min(255,Math.round(+n))).toString(16).padStart(2,'0')).join(''):'#222222';
}
function textStyle(o){
 if(o.type==='text')return {fontSize:Number(o.fontSize)||24,fontFamily:o.fontFamily||'Microsoft YaHei',color:hex(o.color||'#222222'),bold:!!o.bold,italic:!!o.italic,align:o.align||'left',lineHeight:Number(o.lineHeight)||1.3};
 const tag=o.svg.match(/<text\b[^>]*>/i)?.[0]||'';
 const localSize=parseFloat(attribute(tag,'font-size'));
 const scale=o.svg.slice(0,o.svg.indexOf(tag)).match(/scale\(\s*([\d.]+)/i);
 const fontSize=localSize*(scale?+scale[1]:1);
 return {fontSize:Number.isFinite(fontSize)&&fontSize>0?fontSize:o.h/1.2,fontFamily:attribute(tag,'font-family').split(',')[0].replace(/["']/g,'').trim()||'Microsoft YaHei',color:hex(attribute(tag,'fill')),bold:+attribute(tag,'font-weight')>=600,italic:attribute(tag,'font-style')==='italic',align:'left'};
}
function objectText(o){return o.type==='text'?String(o.text||''):decode([...String(o.svg||'').matchAll(/<tspan\b[^>]*>([\s\S]*?)<\/tspan>/gi)].map(m=>m[1].replace(/<[^>]*>/g,'')).join(''));}
function sourceRegions(page){
 const objects=page.objects||[],text=objects.filter(isText).filter(geometry).map(o=>({o,style:textStyle(o)}));
 const pictures=objects.filter(o=>o.type==='image'||/<image\b/i.test(o.svg||''));
 const unsupported=objects.some(o=>hasSvgText(o)&&/<image\b/i.test(o.svg));
 if(!text.length)return {regions:[],unsupported};
 if(text.some(t=>hasSvgText(t.o))){
  const composition=analyseSourceComposition(page,{objectText,textStyle});
  return {...composition,regions:[...(composition.title?[composition.title]:[]),...composition.frames.map(f=>({...f,field:'body',style:f.detail}))],pictureCount:pictures.length};
 }
 // Native text boxes already carry the author's intended frame geometry.
 if(text.every(t=>t.o.type==='text')){
  const title=text.find(t=>t.o.sourceField==='title'||t.o.layoutField==='title')||[...text].sort((a,b)=>b.style.fontSize-a.style.fontSize)[0];
  return {unsupported,regions:[{...clone(title.o),style:title.style,field:'title'},...text.filter(t=>t!==title).map(t=>({...clone(t.o),style:t.style,field:'body'}))]};
 }
 return {regions:[],unsupported};
}

const charWidth=c=>/\s/.test(c)?.35:/[\u0000-\u00ff]/.test(c)?.65:1;
function fitPrefix(text,region){
 const measured=measureAudienceText(text,region.w,region.style);
 if(measured!==null)return measured<=region.h+.01?text.length:0;
 const size=region.style.fontSize,lineHeight=region.style.lineHeight||1.15,width=Math.max(1,region.w-6)/size;
 const maxLines=Math.max(0,Math.floor((region.h+.01)/(size*lineHeight)));
 if(!maxLines)return 0;
 let line=1,used=0,index=0;
 for(const c of text){
  if(c==='\n'){if(line>=maxLines)break;line++;used=0;index+=c.length;continue;}
  const n=charWidth(c);
  if(used+n>width){if(line>=maxLines)break;line++;used=0;}
  used+=n;index+=c.length;
 }
 return index;
}
function capacity(regions){return regions.filter(r=>r.field==='body').reduce((n,r)=>n+Math.floor(r.w/r.style.fontSize)*Math.floor(r.h/(r.style.fontSize*(r.style.lineHeight||1.15))),0);}
function paragraphs(body){const result=[];for(const m of body.matchAll(/[^\n]+/g)){if(m[0].trim())result.push({text:m[0],start:m.index,end:m.index+m[0].length});}return result;}
function placeParagraphs(body,regions){
 const blocks=paragraphs(body),placements=[];let next=0;
 for(const region of regions.filter(r=>r.field==='body')){
  let end=next,display='';
  while(end<blocks.length){const candidate=body.slice(blocks[next].start,blocks[end].end);if(fitPrefix(candidate,region)<candidate.length)break;display=candidate;end++;}
  if(end===next)continue;
  placements.push({region,text:display,start:blocks[next].start,end:blocks[end-1].end});next=end;
  if(next===blocks.length)break;
 }
 return {placements,remaining:next<blocks.length?body.slice(blocks[next].start):''};
}
export function audienceLayoutFingerprint(source,checkedPlan){
 return {sourceFingerprint:JSON.stringify({id:source.id,revision:source.revision,pages:source.pages}),planFingerprint:JSON.stringify({entries:checkedPlan.entries,narrative:checkedPlan.narrative})};
}
export function prepareAudienceLayout(source,checkedPlan,{references={},textScales={},adaptive=false,uuid=()=>crypto.randomUUID()}={}){
 const pages=[],records=[],issues=[],entries=checkedPlan?.entries||[],originals=source.pages||[];
 const canonical=new Map(originals.length?audienceSource({...source,title:source.title??''}).pages.map(p=>[p.id,p]):[]);
 const analyses=new Map(originals.map(p=>[p.id,sourceRegions(p)]));
 const addIssue=(pageId,message)=>issues.push({pageId,message});
 for(const [entryIndex,entry] of entries.entries()){
  if(entry.action==='delete')continue;
  const original=originals.find(p=>p.id===entry.sourcePageId);
  const pageId=original?.id||uuid();
  if(entry.action==='keep'){
   if(!original){addIssue(pageId,'原稿页面已不存在，请返回重新生成改编方案。');continue;}
   pages.push(clone(original));records.push({pageId,sourcePageId:original.id,referencePageId:original.id,mode:'preserved',entryIndex});continue;
  }
  if(entry.action==='edit'&&!original)addIssue(pageId,'待改写的原稿页面已不存在，请返回重新生成改编方案。');
  let reference;
  const selected=references[entryIndex];
  if(selected)reference=originals.find(p=>p.id===selected);
  else if(original)reference=original;
  else {
   const candidates=originals.filter(p=>!analyses.get(p.id).unsupported&&!(p.objects||[]).some(o=>o.type==='image'||/<image\b/i.test(o.svg||''))&&(entry.role==='cover'?p.role==='cover':p.role!=='cover'));
   const score=p=>{
    const a=analyses.get(p.id);if(!a.rich)return capacity(a.regions);
    const result=composeSourceText(a,{title:entry.title||'',body:entry.body||'',role:entry.role,pageNumber:pages.length+1});
    return (result.structured?10000:0)+(entry.role==='ending'&&p===originals.at(-1)?500:0)+a.frames.filter(f=>f.kind==='column').length*40-Math.abs(a.frames.length-String(entry.body||'').split('\n').filter(Boolean).length)*10;
   };
   reference=[...candidates].sort((a,b)=>score(b)-score(a))[0];
  }
  let autoReference=false;
  if(!selected&&!original&&reference&&!analyses.get(reference.id).rich&&!analyses.get(reference.id).pictureCount&&placeParagraphs(String(entry.body||''),analyses.get(reference.id).regions).remaining){
   const fitting=originals.filter(p=>!analyses.get(p.id).unsupported&&!analyses.get(p.id).pictureCount&&!placeParagraphs(String(entry.body||''),analyses.get(p.id).regions).remaining).sort((a,b)=>capacity(analyses.get(b.id).regions)-capacity(analyses.get(a.id).regions))[0];
   if(fitting&&fitting.id!==reference.id){reference=fitting;autoReference=true;}
  }
  const record={pageId,sourcePageId:original?.id||null,referencePageId:reference?.id||null,mode:entry.action==='add'?'added':'rewritten',entryIndex};
  if(autoReference)Object.assign(record,{autoReference:true,note:'原页面文字容量不足，已自动采用可容纳完整段落的原稿参考页，请在预览中确认。'});
  records.push(record);
  const before=canonical.get(original?.id);
  if(original&&reference?.id===original.id&&entry.title===before?.title&&entry.body===before?.body){
   const preserved=clone(original);
   Object.assign(preserved,{title:entry.title,body:entry.body,role:entry.role});
   pages.push(preserved);
   Object.assign(record,{copyPreserved:true,note:'本页文案未改变，完整保留原页排版与对象。'});
   continue;
  }
  if(!reference){pages.push({id:pageId,title:entry.title||'',body:entry.body||'',role:entry.role||'content',objects:[],engine:'ppt-master-svg',designPending:true});addIssue(pageId,selected?'所选原稿参考页已不存在，请重新选择。':'没有可安全继承的原稿版式，请选择原稿参考页。');continue;}
  const baseAnalysis=analyses.get(reference.id);
  const analysis=scaledAnalysis(adaptive?adaptNativeRegions(reference,baseAnalysis):baseAnalysis,textScales[entryIndex]),page=clone(reference);
  for(const key of ['normalizedSvg','sourceTextRuns','designPlan','designSource','designSourceGroups','designSnapshot','designReview','designReason','designPending','designManual','continuationOf','continuationIndex','continuationCount','layoutWarnings'])delete page[key];
  Object.assign(page,{id:pageId,title:String(entry.title||''),body:String(entry.body||''),role:entry.role||reference.role||'content',engine:'ppt-master-svg',layoutSource:{title:String(entry.title||''),body:String(entry.body||'')},sourceTextRuns:[],inheritedTheme:{themeId:source.themeId||'',referencePageId:reference.id}});
  page.objects=(reference.objects||[]).filter(o=>!isText(o)||analysis.retainedTextIds?.has(o.id)).map(o=>{
   const inherited=clone(o);
   if(o.type==='text'&&analysis.retainedTextIds?.has(o.id)){
    for(const key of ['sourceField','layoutField','sourceText','sourceRange','layoutManaged'])delete inherited[key];
    inherited.sourceField='decoration';inherited.layoutField='decoration';
   }
   return {...inherited,...(reference.id!==pageId?{id:uuid(),inheritedSourceObjectId:o.id}: {})};
  });
  const textObject=(region,text,field,start=0,end=start+text.length)=>({id:uuid(),type:'text',...Object.fromEntries(['x','y','w','h'].map(k=>[k,region[k]])),...region.style,text,sourceText:field==='body'?page.body.slice(start,end):text,sourceField:field,layoutField:field,...(field==='body'?{sourceRange:[start,end]}:{}),rotation:0,opacity:1,lineHeight:region.style.lineHeight||1.15,layoutManaged:true,custom:false});
  if(analysis.rich){
   const composition=composeSourceText(analysis,{title:page.title,body:page.body,role:page.role,pageNumber:pages.length+1});
   page.objects=page.objects.filter(o=>!composition.removePanels.has(o.inheritedSourceObjectId||o.id));
   for(const placed of [...composition.placements,...composition.decorative])page.objects.push(textObject(placed.region,placed.text,placed.field,placed.start,placed.end));
   if(analysis.unsupported)addIssue(pageId,'原稿含文字与图片混合的矢量对象，无法可靠替换全部旧文案；请换用其他原稿参考页。');
   if(!analysis.title)addIssue(pageId,'此原稿参考页没有可识别的标题区域，请换用其他原稿参考页。');
   if(composition.titleOverflow)addIssue(pageId,'标题超出原稿标题区域，请缩短标题或更换参考页。');
   if(composition.unplacedBody)addIssue(pageId,`正文有 ${Array.from(composition.unplacedBody).length} 个字符无法完整排入原稿分区，请精简正文、拆页或更换参考页。`);
   page.audienceLayout={version:2,referencePageId:reference.id,entryIndex,unplacedBody:composition.unplacedBody,titleBodyRanges:composition.titleBodyRanges,components:composition.components};
   Object.assign(record,{layoutAdjusted:true,note:`保留原稿的标题层级、${composition.components} 个内容分区${analysis.pictureCount?'及 '+analysis.pictureCount+' 幅原图':''}，按已确认文案重排。`});
   pages.push(page);continue;
  }
  if(analysis.unsupported)addIssue(pageId,'原稿含文字与图片混合的矢量对象，无法可靠替换全部旧文案；请换用其他原稿参考页。');
  const titleRegion=analysis.regions.find(r=>r.field==='title');
  if(!titleRegion)addIssue(pageId,'此原稿参考页没有可识别的标题区域，请换用其他原稿参考页。');
  else{
   page.objects.push(textObject(titleRegion,page.title,'title'));
   if(fitPrefix(page.title,titleRegion)<page.title.length)addIssue(pageId,'标题超出原稿标题区域，请缩短标题或更换参考页。');
  }
  const {placements,remaining}=placeParagraphs(page.body,analysis.regions);
  for(const placed of placements)page.objects.push(textObject(placed.region,placed.text,'body',placed.start,placed.end));
  const usedPanels=new Set(placements.map(p=>p.region.panelId).filter(Boolean));
  const unusedPanels=new Set((analysis.textPanels||[]).filter(id=>!usedPanels.has(id)));
  page.objects=page.objects.filter(o=>!unusedPanels.has(o.inheritedSourceObjectId||o.id));
  if(analysis.pictureCount)Object.assign(record,{layoutAdjusted:true,note:`保留本页 ${analysis.pictureCount} 幅原图，沿用原稿字体与背景，按完整段落重排图片说明与正文。`});
  page.audienceLayout={referencePageId:reference.id,entryIndex,unplacedBody:remaining};
  if(remaining.trim())addIssue(pageId,`正文有 ${Array.from(remaining).length} 个字符放不进原稿文字区域，请精简正文、拆页或换用文字容量更大的原稿参考页。`);
  pages.push(page);
 }
 for(const record of records){
  const scale=textScales[record.entryIndex];
  if(record.mode!=='preserved'&&!record.copyPreserved&&Number.isFinite(scale)&&scale<1){record.textScale=Math.max(.55,scale);record.note=(record.note?record.note+' ':'')+'已在原稿文字区域内适配字号，全文保留，请检查可读性。';}
  if(adaptive&&record.mode!=='preserved'&&!record.copyPreserved)record.note=(record.note?record.note+' ':'')+'已按原稿分区调整文字布局。';
 }
 return {pages,records,issues,...audienceLayoutFingerprint(source,checkedPlan)};
}

function scaledAnalysis(analysis,scale){
 if(!Number.isFinite(scale)||scale>=1)return analysis;
 scale=Math.max(.55,scale);
 const result=clone(analysis);
 const resized=new Set();
 const resize=(style,floor)=>{if(style&&Number.isFinite(style.fontSize)&&!resized.has(style)){resized.add(style);style.fontSize=Math.min(style.fontSize,Math.max(floor,Math.round(style.fontSize*scale*10)/10));}};
 if(result.title)resize(result.title.style,24);
 for(const region of result.regions||[])resize(region.style,region.field==='title'?24:18);
 for(const frame of result.frames||[]){
  for(const key of ['style','primary','detail','readingStyle'])resize(frame[key],18);
  for(const style of frame.levels||[])resize(style,18);
 }
 return result;
}

// Explicit recovery uses the same source frames and canonical copy. It never
// changes a reference page or suppresses a remaining validation issue.
export function fitAudienceLayout(source,checkedPlan,{references={},textScales={},uuid=()=>crypto.randomUUID()}={}){
 const scales={...textScales};
 let layout=prepareAudienceLayout(source,checkedPlan,{references,textScales:scales,uuid});
 if(!layout.issues.length)return {layout,textScales:scales};
 layout=prepareAudienceLayout(source,checkedPlan,{references,textScales:scales,adaptive:true,uuid});
 for(let step=1;step<=9&&layout.issues.length;step++){
  const affected=new Set(layout.issues.map(issue=>layout.records.find(r=>r.pageId===issue.pageId)?.entryIndex));
  for(const index of affected)if(index!==undefined)scales[index]=Math.min(scales[index]||1,1-step*.05);
  layout=prepareAudienceLayout(source,checkedPlan,{references,textScales:scales,adaptive:true,uuid});
 }
 return {layout,textScales:scales};
}

function adaptNativeRegions(page,analysis){
 if(analysis.rich||analysis.unsupported)return analysis;
 const result=clone(analysis),objects=page.objects||[];
 const overlap=(a,b)=>a.x<b.x+b.w&&a.x+a.w>b.x;
 const contains=(a,b)=>a.x<=b.x&&a.y<=b.y&&a.x+a.w>=b.x+b.w&&a.y+a.h>=b.y+b.h;
 for(const region of result.regions){
  const containers=objects.filter(o=>!isText(o)&&geometry(o)&&!hasPicture(o)&&contains(o,region)&&o.w>region.w+16&&o.h>region.h+16);
  const panel=containers.sort((a,b)=>a.w*a.h-b.w*b.h)[0];
  const bottom=panel?Math.min(H-40,panel.y+panel.h-16):H-64;
  const obstacles=[...result.regions.filter(r=>r!==region),...objects.filter(o=>!isText(o)&&geometry(o)&&!contains(o,region)&&!(o.x<=2&&o.y<=2&&o.w>=W-4&&o.h>=H-4))];
  const next=Math.min(bottom,...obstacles.filter(o=>overlap(region,o)&&o.y>=region.y+region.h-1).map(o=>o.y-12));
  if(next>region.y+region.h)region.h=next-region.y;
 }
 return result;
}
const hasPicture=o=>o.type==='image'||/<image\b/i.test(o.svg||'');
