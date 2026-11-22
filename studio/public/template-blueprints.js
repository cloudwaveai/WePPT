import {fillBlueprintCopy} from './blueprint-copy-flow.js';

const PILOT_IDS=new Set();
let BLUEPRINT_PACKS=new Map();
const clone=value=>JSON.parse(JSON.stringify(value));
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
const units=text=>[...String(text)].reduce((n,char)=>n+(/[^\u0000-\u00ff]/.test(char)?1:.55),0);
const lineCount=(text,size,width)=>String(text).split('\n').reduce((n,line)=>n+Math.max(1,Math.ceil(units(line)/(width/size))),0);
const fit=(text,width,height,size,min)=>{while(size>min&&lineCount(text,size,width)*size*1.42>height)size--;return size;};

export const isPrecompiledTheme=themeId=>PILOT_IDS.has(themeId)||BLUEPRINT_PACKS.has(themeId);
export const precompiledThemeIds=()=>[...new Set([...PILOT_IDS,...BLUEPRINT_PACKS.keys()])];
export const precompiledVariantCount=themeId=>BLUEPRINT_PACKS.get(themeId)?.contentVariants?.length||8;

export function reviewPrecompiledDeck(pages,targetPageIds=pages.map(page=>page.id)){
 const ids=new Set(targetPageIds),issues=[],compositions=new Map();
 for(const page of pages.filter(item=>ids.has(item.id))){
  const objects=Array.isArray(page.objects)?page.objects:[];
  if(!objects.length)issues.push({pageId:page.id,kind:'empty-layout',severity:'error',message:'预制模板没有生成可编辑页面对象。'});
  const mappedTitle=objects.filter(object=>object.type==='text'&&object.sourceField==='title').map(object=>object.text||'').join('');
  if(mappedTitle!==page.title)issues.push({pageId:page.id,kind:'title-coverage',severity:'error',message:'页面标题未完整映射到模板文字框。'});
  if(page.body?.trim()&&!objects.some(object=>object.type==='text'&&object.sourceField==='body'))issues.push({pageId:page.id,kind:'body-coverage',severity:'error',message:'页面正文没有映射到模板文字框。'});
  if(page.body?.trim()){
   const source=String(page.body),covered=new Uint8Array(source.length);let mismatch=false;
   for(const match of source.matchAll(/^##[ \t]+/gm))covered.fill(1,match.index,match.index+match[0].length);
   for(const object of objects.filter(object=>object.type==='text'&&object.sourceField==='body')){
    if(!object.text)continue;
    const range=object.sourceRange;
    if(!Array.isArray(range)||range.length!==2||!range.every(Number.isInteger)||range[0]<0||range[1]>source.length||range[0]>range[1]){mismatch=true;continue;}
    if(String(object.text)!==source.slice(range[0],range[1]))mismatch=true;
    covered.fill(1,range[0],range[1]);
   }
   if(mismatch||source.split('').some((char,index)=>!covered[index]&&!/\s/.test(char)))issues.push({pageId:page.id,kind:'body-range-coverage',severity:'error',message:'正文来源区间存在遗漏或与显示文字不一致。'});
  }
  if(page.role==='content'){
   const signature=JSON.stringify(objects.filter(object=>object.type==='text'&&['title','body'].includes(object.sourceField)).map(({x,y,w,h})=>[x,y,w,h].map(value=>Math.round(value/24))));
   if(compositions.has(signature))issues.push({pageId:page.id,kind:'repeated-composition',severity:'error',message:`正文主体布局与页面 ${compositions.get(signature)} 重复，需要重新规划。`});
   else compositions.set(signature,page.id);
  }
  for(const object of objects){
   if(!Number.isFinite(object.x)||!Number.isFinite(object.y)||!Number.isFinite(object.w)||!Number.isFinite(object.h)||object.x<-.01||object.y<-.01||object.x+object.w>1280.01||object.y+object.h>720.01){issues.push({pageId:page.id,kind:'bounds',severity:'error',message:'模板对象超出幻灯片画布。'});break;}
  }
  for(const warning of page.layoutWarnings||[])issues.push({pageId:page.id,kind:'layout-warning',severity:'error',message:warning});
 }
 const errors=issues.filter(issue=>issue.severity==='error');
 return {status:errors.length?'needs-attention':'checked',visionRan:false,reviewMode:'precompiled-template',blueprintVersion:1,repairRounds:0,issues,summary:errors.length?`模板本地完整性检查发现 ${errors.length} 项问题，页面已保留。`:`已完成 ${ids.size} 页模板版式；标题、正文映射、画布边界和版式容量检查通过。此流程使用已预制模板包，不调用逐稿 AI 视觉审看。`,targetPageIds:[...ids],checkedAt:new Date().toISOString()};
}

function textParts(value,maxParts){
 const source=String(value??''),matches=[...source.matchAll(/^##[ \t]+.+$/gm)],ranges=[];
 if(matches.length){if(matches[0].index>0&&source.slice(0,matches[0].index).trim())ranges.push({start:0,end:matches[0].index,heading:false});matches.forEach((match,index)=>{const prefix=match[0].match(/^##[ \t]+/)[0].length;ranges.push({start:match.index+prefix,end:matches[index+1]?.index??source.length,heading:true});});}
 else {let start=0;for(const match of source.matchAll(/\n/g)){ranges.push({start,end:match.index,heading:false});start=match.index+1;}ranges.push({start,end:source.length,heading:false});}
 const nonempty=ranges.map(range=>{const raw=source.slice(range.start,range.end),leading=raw.match(/^\s*/)[0].length,trailing=raw.match(/\s*$/)[0].length;return {...range,start:range.start+leading,end:range.end-trailing,text:raw.trim()};}).filter(range=>range.text);
 if(!nonempty.length)return source?[{text:source,start:0,end:source.length,heading:false}]:[];
 if(matches.length)return nonempty;
 const groups=Array.from({length:Math.min(maxParts,nonempty.length)},()=>[]);
 nonempty.forEach((range,index)=>groups[Math.floor(index*groups.length/nonempty.length)].push(range));
 return groups.filter(group=>group.length).map(group=>{const start=group[0].start,end=group.at(-1).end;return{text:source.slice(start,end).trim(),start,end,heading:false};});
}

export function drawPrecompiledPage(input,theme,variant=0){
 const page=clone(input),id=page.id,palette=theme.palette,objects=[],prefix=`bp-${id}-`;
 const put=(type,box,extra={})=>{const object={id:`${prefix}${objects.length}`,type,x:box[0],y:box[1],w:box[2],h:box[3],rotation:0,opacity:1,layoutManaged:true,...extra};objects.push(object);return object;};
 const rect=(box,fill,extra={})=>put('rect',box,{fill,strokeWidth:0,...extra});
 const rule=(box,color=palette.accent,width=2)=>put('line',box,{stroke:color,fill:color,strokeWidth:width});
 const label=(value,box,{size=28,color=palette.ink,bold=false,align='left',field,range,min=16,opacity=1}={})=>{
  const fontSize=fit(value,box[2],box[3],size,min);
  if(lineCount(value,fontSize,box[2])*fontSize*1.42>box[3]+1)page.layoutWarnings.push('文字超过模板文本框容量，请拆页或调整内容。');
  return put('text',box,{text:String(value),sourceText:String(value),fontFamily:theme.fontFamily||'Microsoft YaHei',fontSize,minSize:min,color,bold,align,lineHeight:1.36,opacity,...(field?{layoutField:field,sourceField:field}:{}),...(range?{sourceRange:range,sourceStart:range[0],sourceEnd:range[1]}:{})});
 };
 const title=(box,style={})=>label(page.title,box,{size:style.size||54,min:style.min||30,color:style.color||palette.ink,bold:true,field:'title',...style});
 const body=(box,{parts=1,size=27,numbered=false,startNumber=1,gap=16,color=palette.ink,bold=false}={})=>{
  const chunks=textParts(page.body,parts);if(!chunks.length)return;
  const rowH=(box[3]-gap*(chunks.length-1))/chunks.length;
  chunks.forEach((part,index)=>{
   const y=box[1]+index*(rowH+gap);
   if(numbered)label(String(startNumber+index).padStart(2,'0'),[box[0],y,54,Math.min(rowH,54)],{size:31,color:palette.accent,bold:true});
   label(part.text,[box[0]+(numbered?66:0),y,box[2]-(numbered?66:0),rowH],{size:part.heading?size+2:size,min:17,color,bold:part.heading||bold,field:'body',range:[part.start,part.end]});
  });
 };
 const image=(src,box,crop,rotation=0,opacity=1)=>put('image',box,{src,crop,fit:'cover',rotation,opacity,decorative:true});
 const fabric=(box,opacity=.48)=>image('/assets/templates/curated-085/0.jpg',box,{x:.9,y:.22,w:.09,h:.62},0,opacity);

 const key=theme.id;variant=((Number(variant)||0)%8+8)%8;page.themeId=key;page.variant=variant;page.layoutWarnings=[];page.layoutSource={title:page.title,body:page.body};page.background=palette.background;
 const headingBox=[72,64,1136,114];
 if(key==='curated-129'){
  if(page.role==='cover'){
   page.background='#4F22D8';rect([0,0,1280,720],'#4F22D8');
   image('/assets/templates/curated-129/0.jpg',[720,0,560,720],{x:.54,y:.02,w:.46,h:.79},0,.97);
   rect([72,76,56,7],palette.secondary);title([72,168,620,235],{size:66,color:'#D7F52F'});body([78,455,550,150],{parts:2,size:27,color:'#fff',gap:25});
   label(String(page.pageNumber||1).padStart(2,'0'),[1190,656,48,32],{size:20,color:'#101010',align:'right'});
  }else if(page.role==='toc'){
   page.background='#F7F6F3';image('/assets/templates/curated-129/0.jpg',[940,112,300,495],{x:.66,y:.06,w:.32,h:.7},0,.92);
   title([72,70,700,100],{size:58});rule([72,190,112,0],palette.secondary,7);
   body([76,245,740,396],{parts:9,size:25,numbered:true,gap:8});
  }else if(variant===0){
   title([72,65,1000,112],{size:50});rect([72,194,18,410],palette.secondary);body([120,205,690,390],{parts:5,size:25,gap:15});image('/assets/templates/curated-129/0.jpg',[858,205,350,385],{x:.68,y:.08,w:.30,h:.64},0,.92);
  }else if(variant===1){
   image('/assets/templates/curated-129/0.jpg',[0,0,510,720],{x:.57,y:.03,w:.43,h:.82},0,.94);rect([510,0,770,720],'#F4F1EC');
   title([570,76,620,140],{size:48});rule([574,238,140,0],palette.accent,3);body([574,278,628,335],{parts:5,size:26,gap:13});
  }else if(variant===2){
   page.background='#4F22D8';rect([0,0,1280,720],'#4F22D8');image('/assets/templates/curated-129/0.jpg',[810,0,470,720],{x:.62,y:.02,w:.38,h:.8},0,.95);
   title([76,148,660,175],{size:58,color:'#D7F52F'});rule([76,355,420,0],palette.secondary,5);body([80,396,620,245],{parts:4,size:25,color:'#fff',gap:12});
  }else if(variant===3){
   title([74,66,770,108],{size:48});image('/assets/templates/curated-129/0.jpg',[854,72,338,248],{x:.66,y:.04,w:.32,h:.42},0,.94);rule([76,195,740,0],palette.secondary,4);body([80,242,1060,365],{parts:6,size:26,numbered:true,gap:12});
  }else if(variant===4){
   page.background='#4F22D8';rect([0,0,1280,720],'#4F22D8');image('/assets/templates/curated-129/0.jpg',[0,0,430,720],{x:.57,y:.03,w:.43,h:.82},0,.95);title([488,82,720,140],{size:49,color:'#D7F52F'});rule([492,238,660,0],palette.secondary,4);body([498,280,650,350],{parts:5,size:25,color:'#fff',gap:14});
  }else if(variant===5){
   title([80,76,760,168],{size:60,color:palette.accent});image('/assets/templates/curated-129/0.jpg',[870,0,410,720],{x:.65,y:.02,w:.33,h:.78},0,.94);body([88,300,690,330],{parts:4,size:27,gap:20});
  }else if(variant===6){
   page.background='#F7F6F3';image('/assets/templates/curated-129/0.jpg',[0,0,1280,188],{x:.02,y:.02,w:.96,h:.23},0,.88);title([76,220,1125,96],{size:46});
   const parts=textParts(page.body,3),cardW=350,gap=36;parts.slice(0,3).forEach((part,index)=>{const x=76+index*(cardW+gap);rect([x,360,cardW,250],'#FFFFFF',{stroke:palette.secondary,strokeWidth:1});rect([x,360,cardW,12],palette.accent);label(String(index+1).padStart(2,'0'),[x+22,390,60,42],{size:30,color:palette.accent,bold:true});label(part.text,[x+22,452,cardW-44,128],{size:24,color:palette.ink,field:'body',range:[part.start,part.end]});});
  }else{
   page.background='#4F22D8';rect([0,0,1280,720],'#4F22D8');image('/assets/templates/curated-129/0.jpg',[0,0,430,720],{x:.57,y:.03,w:.43,h:.82},0,.95);
   title([486,66,700,116],{size:48,color:'#D7F52F'});rule([490,208,650,0],palette.secondary,4);const parts=textParts(page.body,3);parts.slice(0,3).forEach((part,index)=>{const y=260+index*128;label(String(index+1).padStart(2,'0'),[494,y,58,54],{size:31,color:palette.secondary,bold:true});label(part.text,[572,y,570,90],{size:25,color:'#FFFFFF',field:'body',range:[part.start,part.end]});});
  }
 }else if(key==='curated-006'){
  const tape='/assets/templates/curated-006/3.jpg',tapeCrop={x:.70,y:.20,w:.18,h:.22};
  image(tape,[0,0,1280,720],{x:.6,y:.4,w:.15,h:.12},0,.25);
  if(page.role==='cover'){
   image(tape,[80,92,220,84],tapeCrop,-12,.96);title([82,296,830,165],{size:62,color:palette.ink});rule([84,482,116,0],palette.accent,5);body([86,520,790,112],{parts:2,size:27,color:palette.ink,gap:18});
   image(tape,[1000,96,210,82],tapeCrop,12,.95);
  }else if(page.role==='toc'){
   title([82,62,650,100],{size:55});image(tape,[1010,66,190,74],tapeCrop,-8,.96);rect([82,195,1116,440],'#fff');body([112,220,1040,390],{parts:9,size:25,numbered:true,gap:8});
  }else if(variant===0){
   title([72,58,1000,102],{size:46});image(tape,[1040,56,160,64],tapeCrop,8,.9);rect([64,194,1152,438],'#fff');body([98,225,1080,365],{parts:6,size:25,gap:16});
  }else if(variant===1){
   rect([0,0,350,720],'#fff');image(tape,[42,78,206,83],tapeCrop,-10,.96);title([54,226,270,360],{size:47});body([404,110,780,515],{parts:5,size:27,gap:18});
  }else if(variant===2){
   image(tape,[74,90,210,84],tapeCrop,-12,.95);title([72,216,1110,112],{size:46});rule([72,347,1136,0],palette.secondary,2);body([78,390,730,235],{parts:4,size:27,numbered:true,gap:12});image(tape,[850,380,330,230],{x:.04,y:.02,w:.23,h:.40},0,.92);
  }else if(variant===3){
   title([72,64,680,170],{size:54});image(tape,[810,78,350,260],{x:.04,y:.02,w:.23,h:.40},0,.95);rule([72,258,620,0],palette.accent,3);body([80,304,1060,320],{parts:5,size:26,gap:18});
  }else if(variant===4){
   image(tape,[54,86,200,80],tapeCrop,-12,.96);title([70,205,1080,106],{size:48});rect([72,352,1134,2],palette.secondary);body([82,398,1050,220],{parts:6,size:26,numbered:true,gap:10});
  }else if(variant===5){
   title([78,74,350,480],{size:49});rect([465,70,2,570],palette.accent);image(tape,[500,88,190,74],tapeCrop,8,.95);body([505,210,675,410],{parts:5,size:27,gap:22});
  }else if(variant===6){
   title([72,58,890,94],{size:45});image(tape,[1030,52,170,68],tapeCrop,8,.94);rect([64,192,1152,456],'#FFFFFF');
   const parts=textParts(page.body,4);parts.slice(0,4).forEach((part,index)=>{const y=220+index*99;image(tape,[88,y+7,104,42],tapeCrop,(index%2?8:-8),.88);label(String(index+1).padStart(2,'0'),[218,y,56,42],{size:28,color:palette.accent,bold:true});label(part.text,[292,y,850,66],{size:25,color:palette.ink,field:'body',range:[part.start,part.end]});});
  }else{
   rect([0,0,1280,720],'#FFFFFF');image(tape,[760,0,520,720],{x:.04,y:.02,w:.23,h:.40},0,.95);title([78,92,620,160],{size:54});rule([82,278,550,0],palette.accent,4);const parts=textParts(page.body,3);parts.slice(0,3).forEach((part,index)=>label(part.text,[88,330+index*100,590,76],{size:25,color:palette.ink,field:'body',range:[part.start,part.end]}));image(tape,[76,620,198,70],tapeCrop,-8,.9);
  }
 }else if(key==='curated-085'){
  if(page.role==='cover'){
   fabric([1020,18,260,684],.56);title([88,148,780,215],{size:76,color:palette.ink});body([94,440,590,150],{parts:2,size:28,color:palette.muted,gap:22});
  }else if(page.role==='toc'){
   fabric([1120,36,160,630],.38);title([80,76,280,118],{size:58});rule([82,207,114,0],palette.accent,3);body([400,93,680,525],{parts:9,size:27,numbered:true,gap:9});
  }else if(variant===0){
   title(headingBox,{size:48});rule([74,192,1132,0],palette.secondary,2);body([100,236,1010,385],{parts:6,size:26,gap:17});
  }else if(variant===1){
   title([78,86,336,485],{size:48});rect([448,73,2,560],palette.secondary);body([502,106,680,510],{parts:5,size:28,gap:22});
  }else if(variant===2){
   fabric([960,122,320,560],.48);title([80,66,860,110],{size:48});body([84,220,720,390],{parts:4,size:26,gap:20});
  }else if(variant===3){
   title([82,74,700,112],{size:48});rule([84,202,1050,0],palette.secondary,2);body([102,246,840,378],{parts:6,size:26,numbered:true,gap:14});fabric([1054,188,226,470],.42);
  }else if(variant===4){
   fabric([0,0,260,720],.4);title([320,92,860,165],{size:56});rule([324,280,740,0],palette.accent,3);body([330,326,780,304],{parts:5,size:27,gap:16});
  }else if(variant===5){
   title([82,62,760,110],{size:48});fabric([860,214,320,420],.52);body([86,222,710,390],{parts:5,size:27,gap:18});
  }else if(variant===6){
   fabric([0,0,255,720],.48);title([314,58,860,108],{size:46});rule([318,190,860,0],palette.secondary,2);const parts=textParts(page.body,4),cardW=400;parts.slice(0,4).forEach((part,index)=>{const col=index%2,row=Math.floor(index/2),x=320+col*430,y=236+row*190;rect([x,y,400,156],'#FBFAF7',{stroke:'#E4E0D8',strokeWidth:1,radius:8});label(String(index+1).padStart(2,'0'),[x+20,y+18,56,42],{size:28,color:palette.accent,bold:true});label(part.text,[x+88,y+20,290,116],{size:24,color:palette.ink,field:'body',range:[part.start,part.end]});});
  }else{
   title([84,58,1110,96],{size:46});fabric([1090,194,190,526],.44);rect([76,188,1090,2],palette.secondary);const parts=textParts(page.body,3);parts.slice(0,3).forEach((part,index)=>{const y=236+index*138;rect([80,y,250,104],'#EFECE6',{radius:52});label(String(index+1).padStart(2,'0'),[111,y+28,80,45],{size:32,color:palette.accent,bold:true,align:'center'});label(part.text,[370,y+5,680,94],{size:25,color:palette.ink,field:'body',range:[part.start,part.end]});});
  }
 }
 page.objects=objects;
 const retained=(input.objects||[]).filter(object=>object.custom||!object.layoutManaged).map(clone);page.objects.push(...retained);
 if(objects.some(object=>object.type==='text'&&object.sourceField==='body')){
  const mapped=objects.filter(object=>object.layoutField==='body'),covered=mapped.map(object=>object.sourceRange||[0,0]).sort((a,b)=>a[0]-b[0]);
  const source=String(page.body||''),uncovered=(start,end)=>source.slice(start,end).replace(/^##[ \t]+/gm,'').trim();let cursor=0;for(const [start,end] of covered){if(start>cursor&&uncovered(cursor,start))page.layoutWarnings.push('部分正文未放入版式，请检查内容完整性。');cursor=Math.max(cursor,end);}if(uncovered(cursor,source.length))page.layoutWarnings.push('部分正文未放入版式，请检查内容完整性。');
 }
 return page;
}

export function setBlueprintPacks(packs={}){
 BLUEPRINT_PACKS=new Map(Object.entries(packs).filter(([id,pack])=>pack?.status==='ready'&&pack.themeId===id&&Array.isArray(pack.contentVariants)&&pack.contentVariants.length>=8));
}

export function renderBlueprintPackage(input,theme,pack,variant=0){
 const page=clone(input),role=['cover','toc','chapter','ending'].includes(page.role)&&pack.layouts?.[page.role]?'layout':null;
 const selected=page.role==='chapter'&&pack.chapterVariants?.length?pack.chapterVariants[variant]||pack.layouts?.chapter:role?pack.layouts?.[page.role]:(pack.contentVariants?.length?pack.contentVariants[((Math.floor(Number(variant)||0)%pack.contentVariants.length)+pack.contentVariants.length)%pack.contentVariants.length]:pack.layouts?.content);
 if(!selected)return drawPrecompiledPage(input,theme,variant);
 if(selected.copyPolicy==='flow-v1'){
  const flow=fillBlueprintCopy(page,selected),objects=flow.objects.map(object=>({...object,layoutManaged:true}));
  page.layoutWarnings=[...(page.blueprintPlanningWarning?[page.blueprintPlanningWarning]:[]),...flow.warnings];
  if(page.role==='chapter'&&!pack.layouts?.chapter&&!pack.chapterVariants?.length)page.layoutWarnings.push('模板包缺少独立章节版式，本页尚未通过验收。');
  const numbers=objects.filter(object=>object.blueprintSlot==='sequence-number');
  numbers.forEach((object,index)=>{object.text=String(index+1).padStart(2,'0');});
  for(const object of objects){
   if(object.blueprintSlot==='page-number')object.text=String(page.pageNumber||1).padStart(2,'0');
   if(object.blueprintSlot==='chapter-number'){
    object.text=String(page.chapterNumber||1).padStart(2,'0');object.sourceField='chapterNumber';object.layoutField='chapterNumber';object.sourceText=object.text;
    delete object.sourceRange;delete object.sourceStart;delete object.sourceEnd;
   }
  }
  const unusedNumbers=new Set(numbers.slice(flow.bodySections));
  page.themeId=theme.id;page.variant=variant;page.background=selected.background||theme.palette.background;page.layoutSource={title:page.title,body:page.body};
  const retained=(input.objects||[]).filter(object=>object.custom||!object.layoutManaged).map(clone);
  page.objects=[...objects.filter(object=>!unusedNumbers.has(object)&&!(Number.isInteger(object.blueprintEntry)&&object.blueprintEntry>=flow.bodySections)),...retained];
  return page;
 }
 const objects=clone(selected.objects||[]).map(object=>({...object,layoutManaged:true})),titles=objects.filter(object=>object.blueprintSlot==='title'),bodies=objects.filter(object=>object.blueprintSlot==='body'),numbers=objects.filter(object=>object.blueprintSlot==='sequence-number'),pageNumbers=objects.filter(object=>object.blueprintSlot==='page-number');
 const splitByWeights=(value,slots)=>{
  if(!slots.length)return[];const weights=slots.map(slot=>Math.max(1,Number(slot.blueprintWeight)||1)),total=weights.reduce((sum,n)=>sum+n,0),chars=[...String(value??'')],parts=[];let offset=0;
  weights.forEach((weight,index)=>{const end=index===weights.length-1?chars.length:Math.min(chars.length,offset+Math.round(chars.length*weight/total));parts.push(chars.slice(offset,end).join(''));offset=end;});return parts;
 };
 let structureOverflow=false;
 const bodyParts=(value,count)=>{
  if(!count)return[];
  const source=String(value??''),parts=[];
  for(const match of source.matchAll(/[^\n]+/g)){
   const raw=match[0],leading=raw.match(/^\s*/)[0].length,trailing=raw.match(/\s*$/)[0].length;
   let start=match.index+leading,end=match.index+raw.length-trailing,heading=false;
   const markdown=source.slice(start,end).match(/^##[ \t]+/);
   if(markdown){start+=markdown[0].length;heading=true;}
   if(start<end)parts.push({text:source.slice(start,end),start,end,heading});
  }
  if(page.role==='toc'&&parts.length>count)structureOverflow=true;
  while(page.role!=='toc'&&page.role!=='chapter'&&parts.length<count){
   let index=-1,longest=1;
   parts.forEach((part,i)=>{const length=[...part.text].length;if(length>longest){longest=length;index=i;}});
   if(index<0)break;
   const part=parts[index],chars=[...part.text];let split=Math.floor(chars.length/2);
   const min=Math.floor(chars.length*.34),max=Math.ceil(chars.length*.66),boundary=/[。！？；，、,.!?;：:]/u;
   for(let distance=0;distance<=max-min;distance++){
    const candidates=[split-distance,split+distance].filter(point=>point>=min&&point<=max);
    const found=candidates.find(point=>boundary.test(chars[point-1]||''));
    if(found){split=found;break;}
   }
   const first=chars.slice(0,split).join(''),second=chars.slice(split).join(''),offset=first.length;
   if(!first||!second)break;
   parts.splice(index,1,{text:first,start:part.start,end:part.start+offset,heading:part.heading},{text:second,start:part.start+offset,end:part.end,heading:false});
  }
  while(parts.length>count){
   let best=-1,weight=Infinity;
   for(let index=0;index<parts.length-1;index++){
    const [first,second]=parts.slice(index,index+2),gap=source.slice(first.end,second.start);
    if(gap.replace(/\s/g,'').length)continue;
    const combined=[...first.text].length+[...second.text].length;if(combined<weight){weight=combined;best=index;}
   }
   // A Markdown marker between groups is meaningful source data. If no
   // whitespace-only merge fits, preserve the contiguous source and flag it.
   if(best<0){best=0;structureOverflow=true;}
   const [first,second]=parts.splice(best,2),gap=source.slice(first.end,second.start);parts.splice(best,0,{text:first.text+gap+second.text,start:first.start,end:second.end,heading:first.heading});
  }
  return parts;
 };
 page.layoutWarnings=[];
 if(page.blueprintPlanningWarning)page.layoutWarnings.push(page.blueprintPlanningWarning);
 const titlesText=splitByWeights(page.title,titles),bodyText=bodyParts(page.body,bodies.length);
 if(structureOverflow)page.layoutWarnings.push('内容分组超过模板槽位，完整原文已保留，请拆页后重新排版。');
 if(page.role==='chapter'&&!pack.layouts?.chapter&&!pack.chapterVariants?.length)page.layoutWarnings.push('模板包缺少独立章节版式，本页尚未通过验收。');
 titles.forEach((object,index)=>{object.text=titlesText[index]||'';object.sourceText=object.text;object.sourceField='title';object.layoutField='title';object.fontSize=fit(object.text,object.w,object.h,object.fontSize||44,object.minSize||18);if(object.text&&lineCount(object.text,object.fontSize,object.w)*object.fontSize*1.42>object.h+1)page.layoutWarnings.push('标题超过模板文本框容量，请调整标题或版式。');});
 bodies.forEach((object,index)=>{const part=bodyText[index];object.text=part?.text||'';object.sourceText=object.text;object.sourceField='body';object.layoutField='body';if(part){object.sourceRange=[part.start,part.end];object.sourceStart=part.start;object.sourceEnd=part.end;}object.fontSize=fit(object.text,object.w,object.h,object.fontSize||26,object.minSize||16);if(lineCount(object.text,object.fontSize,object.w)*object.fontSize*1.42>object.h+1)page.layoutWarnings.push('文字超过模板文本框容量，请拆页或调整内容。');});
 numbers.forEach((object,index)=>{object.text=String(index+1).padStart(2,'0');});
 pageNumbers.forEach(object=>{object.text=String(page.pageNumber||1).padStart(2,'0');});
 objects.filter(object=>object.blueprintSlot==='chapter-number').forEach(object=>{object.text=String(page.chapterNumber||1).padStart(2,'0');object.sourceField='chapterNumber';object.layoutField='chapterNumber';delete object.sourceRange;delete object.sourceStart;delete object.sourceEnd;});
 page.themeId=theme.id;page.variant=variant;page.background=selected.background||theme.palette.background;page.layoutSource={title:page.title,body:page.body};
 const unusedNumbers=new Set(numbers.slice(bodyText.length));const retained=(input.objects||[]).filter(object=>object.custom||!object.layoutManaged).map(clone);page.objects=[...objects.filter(object=>!unusedNumbers.has(object)&&!(Number.isInteger(object.blueprintEntry)&&object.blueprintEntry>=bodyText.length)),...retained];
 return page;
}

export function layoutPrecompiledPage(input,theme,variant=0){
 const pack=BLUEPRINT_PACKS.get(theme.id);return pack?renderBlueprintPackage(input,theme,pack,variant):drawPrecompiledPage(input,theme,variant);
}

export function getBlueprintPack(themeId){return BLUEPRINT_PACKS.get(themeId)||null;}
