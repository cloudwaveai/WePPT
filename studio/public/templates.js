import {vectorDataUrl} from './vector-scene.js';
import {RETRO_ID,retroVariants,layoutRetro,paginateRetro} from './retro-layout.js';
import {isPrecompiledTheme,layoutPrecompiledPage,setBlueprintPacks,precompiledVariantCount,getBlueprintPack} from './template-blueprints.js';
import {planBlueprintDeck} from './blueprint-planner.js';
/* Editable layout recipes derived from the reviewed references, never screenshot slides. */
let themes=[];
let themesPromise=null;
const fallback={id:'neutral',name:'留白叙事',fontFamily:'Microsoft YaHei',depth:'editorial',palette:{background:'#F4F2ED',ink:'#27332F',accent:'#58756A',secondary:'#C8D4C9',surface:'#FFFFFF',muted:'#626C66',dark:false}};
export function loadTemplates(){if(themesPromise)return themesPromise;themesPromise=(async()=>{const response=await fetch('/templates.json');if(!response.ok)throw new Error('模板库载入失败，请刷新重试。');themes=await response.json();try{const indexResponse=await fetch('/template-blueprint-packs/index.json');if(indexResponse.ok){const index=await indexResponse.json(),entries=await Promise.all((index.packs||[]).map(async entry=>{const packResponse=await fetch(entry.href);if(!packResponse.ok)return null;const pack=await packResponse.json();return pack.status==='ready'&&pack.schemaVersion===1&&pack.themeId===entry.themeId?[entry.themeId,pack]:null;}));setBlueprintPacks(Object.fromEntries(entries.filter(Boolean)));}}catch{setBlueprintPacks({});}return themes;})().catch(error=>{themesPromise=null;throw error;});return themesPromise;}
export function getTemplates(){return themes;}
export function getTheme(id){return themes.find(t=>t.id===id)||themes[0]||fallback;}
const recipes={
 cover:[['层叠主视觉','大标题与透光几何错落'],['居中宣言','居中标题，留出完整呼吸空间'],['编辑式封面','左右错位，强调标题与说明']],
 toc:[['分栏目录','条目沿列排列，长标题自动换行'],['纵向目录','左侧标题，右侧清晰顺序'],['章节索引','紧凑编号与分组，适合多章节']],
 content:[['清晰叙事','宽正文区，稳定阅读节奏'],['侧题正文','标题与内容分区'],['双栏阅读','长文分栏，保留原文顺序']],
 data:[['指标并置','依据原文分组，不虚构数值'],['对比面板','两侧并置，适合数据对比'],['纵向数据','大段数据说明与条目对齐']],
 flow:[['横向步骤','从左到右展示操作顺序'],['纵向流程','长步骤纵向展开'],['分组路径','分组说明，适合多阶段流程']],
 chapter:[['章节起点','醒目标题与轻量说明'],['居中章节','章节标题居中，保持整稿节奏'],['侧边章节','不对称构图强调转场']],
 ending:[['收束观点','以核心结论结束'],['居中结束','简洁明确的结尾'],['行动提示','保留后续步骤与联系信息']]
};
export function getVariants(role,themeId){if(themeId===RETRO_ID&&!isPrecompiledTheme(themeId))return retroVariants(role);return (recipes[role]||recipes.content).map(([name,description],id)=>({id,name,description}));}
// Manual page arrangements are independent of the deck's decorative theme recipes.
export function getPageLayouts(role='content'){
 const common=[{id:'top',name:'上题下文',description:'标题在上，正文完整展开'},{id:'left',name:'左题右文',description:'标题与正文左右分区'},{id:'right',name:'左文右题',description:'正文在左，标题靠右'}];
 return ['cover','chapter','ending'].includes(role)
  ? [{id:'center',name:'居中标题',description:'标题与说明居中排列'},...common,{id:'bottom',name:'底部标题',description:'说明在上，标题沉到底部'}]
  : [...common,{id:'columns',name:'双栏正文',description:'正文按顺序分为两栏'},{id:'thirds',name:'三栏并列',description:'内容分组并排展示'},{id:'rows',name:'分行列表',description:'内容分组逐行展开'}];
}
export function layoutCurrentPage(input,themeId,layoutId){
 if(!getPageLayouts(input.role).some(v=>v.id===layoutId))throw new Error('此页面类型不支持所选布局。');
 const result=layoutPage(input,themeId,0,layoutId);
 delete result.designPlan;delete result.designSource;delete result.designSnapshot;
 result.designManual=true;return result;
}
export function inferRole(title='',body='',index=0){const t=String(title),all=t+'\n'+String(body);if(/目录|议程|今天掌握|本次(?:学习|分享|培训)|内容概览|contents|agenda/i.test(t))return 'toc';if(/结束|谢谢|感谢|总结|下一步|thank|结语/i.test(t))return 'ending';if(/第[一二三四五六七八九十\d]+[章节]|chapter/i.test(t))return 'chapter';if(/流程|步骤|路径|时间线|路线|阶段|闭环|process|workflow/i.test(t))return 'flow';if(/数据|指标|业绩|增长|统计|对比|财务|营收|预算|金额|支出|data|metrics/i.test(t))return 'data';return index===0?'cover':'content';}
const clone=x=>JSON.parse(JSON.stringify(x));
const safeNumber=(n,d=0)=>Number.isFinite(Number(n))?Number(n):d;
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
const onAccent=hex=>{const rgb=hex.replace('#','').match(/../g).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]>.179?'#17231E':'#FFFFFF';};
const uid=()=>globalThis.crypto?.randomUUID?.()||'p-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
function linesAt(text,size,width){const units=Math.max(1,width/size);return String(text).split('\n').reduce((sum,line)=>sum+Math.max(1,Math.ceil([...line].reduce((n,c)=>n+(/[^\u0000-\u00ff]/.test(c)?1:.55),0)/units)),0);}
function fontFor(text,width,height,preferred=28,min=18){let size=preferred;while(size>min&&linesAt(text,size,width)*size*1.4>height)size-=1;return size;}
function chunks(text,max=6){const s=String(text);if(!s)return[];const raw=[];let start=0;
 const headings=[...s.matchAll(/^##[ \t]+.+$/gm)];
 if(headings.length){if(headings[0].index>0&&s.slice(0,headings[0].index).trim())raw.push({start:0,end:headings[0].index});headings.forEach((match,i)=>raw.push({start:match.index,end:headings[i+1]?.index??s.length}));}
 else {for(const match of s.matchAll(/\n/g)){raw.push({start,end:match.index});start=match.index+1;}raw.push({start,end:s.length});}
 const nonempty=raw.filter(x=>s.slice(x.start,x.end).trim());if(!nonempty.length)return[{text:s,start:0,end:s.length}];const size=Math.ceil(nonempty.length/max),groups=[];for(let i=0;i<nonempty.length;i+=size){const a=nonempty[i],b=nonempty[Math.min(i+size-1,nonempty.length-1)];groups.push({text:s.slice(a.start,b.end),start:a.start,end:b.end});}return groups;}
function recoverContent(page){let title=String(page.title??''),body=String(page.body??'');const source=page.layoutSource;if(!source)return{title,body};if(title===source.title){const o=(page.objects||[]).find(o=>o.layoutField==='title');if(o&&o.text!==o.sourceText)title=String(o.text??'');}
 if(body===source.body){const edits=(page.objects||[]).filter(o=>o.layoutField==='body'&&o.sourceRange&&o.text!==o.sourceText).sort((a,b)=>b.sourceRange[0]-a.sourceRange[0]);for(const o of edits){const [a,b]=o.sourceRange;body=body.slice(0,a)+String(o.text??'')+body.slice(b);}}return{title,body};}
export function layoutPage(input,themeId,variant=0,pageLayoutId=null){
 const page=clone(input),theme=getTheme(themeId),p=theme.palette||fallback.palette;
 const {title,body}=recoverContent(page);page.id ||=uid();page.title=title;page.body=body;page.role ||=inferRole(title,body,0);page.themeId=theme.id;
 variant=clamp(Math.floor(safeNumber(variant)),0,isPrecompiledTheme(themeId)?precompiledVariantCount(themeId)-1:2);page.variant=variant;page.background=p.background;page.layoutWarnings=[];
 delete page.pageLayoutId;
 if(themeId===RETRO_ID&&!pageLayoutId&&!isPrecompiledTheme(themeId))return layoutRetro(page,theme);
 if(pageLayoutId){page.pageLayoutId=pageLayoutId;page.background=input.background||p.background;}
 if(!pageLayoutId&&isPrecompiledTheme(themeId))return layoutPrecompiledPage(page,theme,variant);
 const objects=[],prefix='layout-'+page.id+'-';let count=0;
 const make=(type,box,extra={})=>{const o={id:prefix+(count++),type,x:box[0],y:box[1],w:box[2],h:box[3],rotation:0,opacity:1,layoutManaged:true,...extra};objects.push(o);return o;};
 const rect=(box,fill,extra={})=>make('rect',box,{fill,strokeWidth:0,radius:0,...extra});
 const line=(x,y,w,color=p.secondary)=>make('line',[x,y,w,0],{stroke:color,strokeWidth:1.5,fill:color});
 const shadow=(blur=28,offsetY=13,opacity=.15)=>({color:'#14232B',opacity,blur,offsetX:0,offsetY});
 const text=(value,box,extra={})=>{const size=fontFor(value,box[2],box[3],extra.fontSize||28,extra.minSize||18);if(linesAt(value,size,box[2])*size*1.4>box[3]+4)page.layoutWarnings.push('本页文字较多，请检查是否需要拆页或扩大文本框。');return make('text',box,{text:String(value),sourceText:String(value),fontFamily:theme.fontFamily||'Microsoft YaHei',fontSize:size,color:p.ink,bold:false,italic:false,align:'left',lineHeight:1.4,...extra,fontSize:size});};
 const heading=(box,extra={})=>text(title,box,{fontSize:48,minSize:28,bold:true,layoutField:'title',sourceField:'title',...extra});
 const bodyText=(part,box,extra={})=>{
  const common={fontSize:27,minSize:18,layoutField:'body',sourceField:'body',...extra};
  const add=(value,start,end,target,style={})=>text(value,target,{...common,sourceRange:[start,end],sourceStart:start,sourceEnd:end,...style});
  if(!/^##[ \t]+.+$/m.test(part.text))return add(part.text,part.start,part.end,box);
  const segments=[];let cursor=0;
  const paragraph=(start,end)=>{const value=part.text.slice(start,end),leading=value.match(/^\s*/)[0].length,trailing=value.match(/\s*$/)[0].length;if(leading+trailing<value.length)segments.push({text:value.slice(leading,value.length-trailing),start:part.start+start+leading,end:part.start+end-trailing,heading:false});};
  for(const match of part.text.matchAll(/^##[ \t]+(.+)$/gm)){paragraph(cursor,match.index);const prefix=match[0].length-match[1].length;segments.push({text:match[1],start:part.start+match.index+prefix,end:part.start+match.index+match[0].length,heading:true});cursor=match.index+match[0].length;}
  paragraph(cursor,part.text.length);
  let size=common.fontSize;const minimum=common.minSize;
  const measures=()=>segments.map((segment,i)=>{const fontSize=size+(segment.heading?2:0),gap=i?(segment.heading?size*.55:size*.16):0;return {fontSize,gap,height:linesAt(segment.text,fontSize,box[2])*fontSize*1.4};});
  let dimensions=measures();while(size>minimum&&dimensions.reduce((sum,d)=>sum+d.gap+d.height,0)>box[3]){size--;dimensions=measures();}
  const total=dimensions.reduce((sum,d)=>sum+d.gap+d.height,0),ratio=Math.min(1,box[3]/Math.max(1,total));if(ratio<1)page.layoutWarnings.push('本页文字较多，请检查是否需要拆页或扩大文本框。');
  let y=box[1];return segments.map((segment,i)=>{const d=dimensions[i];y+=d.gap*ratio;const height=Math.max(1,d.height*ratio),object=add(segment.text,segment.start,segment.end,[box[0],y,box[2],height],{fontSize:d.fontSize,minSize:minimum,bold:segment.heading||common.bold,contentRole:segment.heading?'subheading':'paragraph'});y+=height;return object;});
 };
 const whole={text:body,start:0,end:body.length};
 function depth(right=true){const x=right?905:94;rect([x+28,100,246,420],p.secondary,{rotation:9,opacity:.25});rect([x,127,246,420],p.surface,{rotation:-5,opacity:.87,shadow:shadow(36,18,.18)});rect([x+39,184,170,258],p.accent,{opacity:p.dark?.65:.17});line(x+36,468,174,p.accent);}
 function standardTitle(){rect([64,55,40,6],p.accent);heading([64,86,1152,104]);line(64,208,1152);}
 const isHero=['cover','chapter','ending'].includes(page.role);
 if(pageLayoutId){
  // Plain editable regions make the topology visible; no placeholder artwork.
  const heroSize=isHero?64:48;
  if(pageLayoutId==='center'){
   heading([160,188,960,204],{fontSize:heroSize,minSize:28,align:'center'});
   if(body)bodyText(whole,[240,428,800,190],{fontSize:26,align:'center'});
  }else if(pageLayoutId==='left'||pageLayoutId==='right'){
   const left=pageLayoutId==='left',titleX=left?72:830,bodyX=left?530:72;
   heading([titleX,134,378,438],{fontSize:isHero?56:46,minSize:26});
   rect([left?474:778,100,2,520],p.accent,{opacity:.6});
   if(body)bodyText(whole,[bodyX,144,678,456],{fontSize:29});
  }else if(pageLayoutId==='bottom'){
   if(body)bodyText(whole,[76,88,920,230],{fontSize:27});
   line(76,368,1128,p.accent);heading([76,410,1128,230],{fontSize:heroSize,minSize:28});
  }else{
   heading([72,64,1136,144],{fontSize:heroSize,minSize:28});line(72,228,1136,p.accent);
   if(pageLayoutId==='top'){if(body)bodyText(whole,[72,282,1136,366],{fontSize:30});}
   else {
    const parts=chunks(body,pageLayoutId==='thirds'?3:pageLayoutId==='columns'?2:6),n=Math.max(1,parts.length);
    if(pageLayoutId==='rows'){
     const height=384/n;parts.forEach((part,i)=>{bodyText(part,[72,268+i*height,1136,height-20],{fontSize:27});if(i<n-1)line(72,268+(i+1)*height-10,1136);});
    }else{
     const columns=pageLayoutId==='thirds'?3:2;
     // Flow a prose paragraph across columns while preserving exact source ranges.
     // Keep a Markdown heading with its group instead of splitting its marker.
     let columnParts=parts;
     if(parts.length===1&&!/^##[ \t]+/m.test(body)&&[...body].length>=columns){
      const characters=[...body],step=Math.ceil(characters.length/columns);let start=0;columnParts=[];
      for(let i=0;i<characters.length;i+=step){const value=characters.slice(i,i+step).join('');columnParts.push({text:value,start,end:start+value.length});start+=value.length;}
     }
     const width=(1136-(columns-1)*48)/columns;columnParts.forEach((part,i)=>bodyText(part,[72+i*(width+48),282,width,366],{fontSize:28}));
     for(let i=1;i<columns;i++)rect([48+i*(width+48),282,1,366],p.secondary);
    }
   }
  }
 }else if(isHero){
  if(variant===0){depth();rect([64,80,56,7],p.accent);heading([64,160,790,215],{fontSize:64,minSize:32});if(body)bodyText(whole,[68,410,730,205],{fontSize:28});}
  else if(variant===1){rect([172,95,936,500],p.surface,{opacity:.82,shadow:shadow(40,16,.13)});rect([218,126,844,438],p.surface,{opacity:.72});rect([560,144,160,6],p.accent);heading([220,211,840,190],{fontSize:62,minSize:32,align:'center'});if(body)bodyText(whole,[240,428,800,150],{fontSize:25,align:'center'});}
  else {rect([0,0,410,720],p.accent);rect([64,96,330,510],p.secondary,{opacity:.35,rotation:-5,shadow:shadow()});rect([92,123,296,450],p.surface,{opacity:.9,rotation:3});heading([465,125,740,235],{fontSize:57,minSize:30});line(468,398,650,p.accent);if(body)bodyText(whole,[468,430,690,205],{fontSize:26});}
 } else if(page.role==='toc'){
  const parts=chunks(body,variant===0?9:7);if(variant===1){rect([0,0,386,720],p.accent);heading([48,100,290,275],{fontSize:50,color:onAccent(p.accent)});const step=Math.min(80,536/Math.max(1,parts.length));parts.forEach((part,i)=>{text(String(i+1).padStart(2,'0'),[438,92+i*step,66,45],{fontSize:28,bold:true,color:p.accent});bodyText(part,[520,91+i*step,680,step-8],{fontSize:26});line(520,90+(i+1)*step-8,680);});}
  else {standardTitle();const cols=variant===0?3:2,rows=Math.ceil(parts.length/cols),w=(1152-(cols-1)*48)/cols,h=Math.min(136,410/Math.max(rows,1));parts.forEach((part,i)=>{const col=variant===0?Math.floor(i/rows):i%cols,row=variant===0?i%rows:Math.floor(i/cols),x=64+col*(w+48),y=244+row*h;text(String(i+1).padStart(2,'0'),[x,y,50,38],{fontSize:24,bold:true,color:p.accent});bodyText(part,[x+57,y,w-57,h-28],{fontSize:26});line(x,y+h-15,w);});}
 } else if(page.role==='flow'){
  standardTitle();const parts=chunks(body,variant===1?5:6),n=Math.max(1,parts.length);
  if(variant===1){const h=414/n;rect([86,250,2,Math.max(0,(n-1)*h)],p.secondary);parts.forEach((part,i)=>{make('ellipse',[66,246+i*h,42,42],{fill:p.accent,strokeWidth:0});text(String(i+1),[69,251+i*h,36,32],{fontSize:21,minSize:18,bold:true,color:onAccent(p.accent),align:'center'});bodyText(part,[138,245+i*h,1050,h-12],{fontSize:27});});}
  else {const cols=variant===0?Math.min(3,n):Math.min(2,n),rows=Math.ceil(n/cols),w=(1152-40*(cols-1))/cols,h=(410-30*(rows-1))/rows;parts.forEach((part,i)=>{const x=64+(i%cols)*(w+40),y=245+Math.floor(i/cols)*(h+30);if(i%cols<cols-1&&i<n-1)line(x+w,y+h/2,40,p.accent);rect([x,y,w,h],p.surface,{radius:12,shadow:shadow(20,9,.11)});rect([x,y,Math.min(w,64),5],p.accent);text(String(i+1).padStart(2,'0'),[x+24,y+18,70,42],{fontSize:27,bold:true,color:p.accent});bodyText(part,[x+24,y+74,w-48,h-94],{fontSize:25,minSize:18});});}
 } else if(page.role==='data'){
  standardTitle();const parts=chunks(body,variant===0?3:variant===1?4:5);
  if(variant===2){const h=410/Math.max(parts.length,1);parts.forEach((part,i)=>{if(i%2===0)rect([64,236+i*h,1152,h],p.surface,{opacity:.7});bodyText(part,[90,250+i*h,1100,h-22],{fontSize:28});});}
  else {const cols=variant===0?Math.max(1,parts.length):2,rows=Math.ceil(parts.length/cols),w=(1152-(cols-1)*30)/cols,h=(410-(rows-1)*24)/Math.max(rows,1);parts.forEach((part,i)=>{const x=64+(i%cols)*(w+30),y=240+Math.floor(i/cols)*(h+24);rect([x,y,w,h],i===0?p.accent:p.surface,{radius:12,shadow:shadow(24,10,.13)});bodyText(part,[x+30,y+34,w-60,h-68],{fontSize:32,minSize:20,color:i===0?onAccent(p.accent):p.ink});});}
 } else {
  if(variant===1){rect([0,0,370,720],p.surface);rect([48,62,44,6],p.accent);heading([48,112,275,460],{fontSize:43,minSize:25});bodyText(whole,[424,90,780,546],{fontSize:29});}
  else {standardTitle();if(variant===2){const parts=chunks(body,2);if(parts.length>1){const split=parts[1].start;bodyText({text:body.slice(0,split),start:0,end:split},[64,247,540,400],{fontSize:28});bodyText({text:body.slice(split),start:split,end:body.length},[676,247,540,400],{fontSize:28});}else bodyText(whole,[64,246,1152,410],{fontSize:29});}
   else {rect([64,235,1152,416],p.surface,{opacity:p.dark?.55:.8,radius:10,shadow:theme.depth==='layered'?shadow(24,10,.1):undefined});bodyText(whole,[94,262,1092,364],{fontSize:29});}}
 }
 // Preserve user-created media and text, including objects imported before any recipe existed.
 const retained=(page.objects||[]).filter(o=>o.custom||!o.layoutManaged).map(clone);const ids=new Set(objects.map(o=>o.id));for(const o of retained){if(ids.has(o.id))o.id=uid();objects.push(o);}
 page.objects=objects;page.layoutSource={title,body};page.layoutWarnings=[...new Set(page.layoutWarnings)];return page;
}
export function layoutDeck(pages,themeId){let chapter=0;const recoveredPages=pages.map((page,index)=>{const recovered=recoverContent(page);return {...page,...recovered,role:page.role||inferRole(recovered.title,recovered.body,index)};});return planBlueprintDeck(recoveredPages,getBlueprintPack(themeId)).flatMap((page,index)=>{if(page.role==='chapter')chapter++;const prepared={...page,...(page.role==='chapter'?{chapterNumber:page.chapterNumber||chapter}:{}),variant:isPrecompiledTheme(themeId)?Number.isInteger(page.precompiledVariant)?page.precompiledVariant:index%precompiledVariantCount(themeId):Number.isInteger(page.variant)?page.variant:0};return themeId===RETRO_ID&&!isPrecompiledTheme(themeId)?paginateRetro(prepared,getTheme(themeId)):[layoutPage(prepared,themeId,prepared.variant)];});}
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const color=(v,f='#27332F')=>/^#[0-9a-f]{3,8}$/i.test(v||'')?v:f;
function imageSrc(src){return /^(\/assets\/|\/uploads\/|data:image\/(?:png|jpe?g|webp|gif);base64,|blob:)/i.test(String(src))?String(src):'';}
export function renderMini(page){
 if(page?.designPending&&!(page.objects||[]).length)return `<div role="status" aria-label="${escape(page.title||'未命名页面')} · 待生成" style="position:relative;aspect-ratio:16/9;width:100%;overflow:hidden;container-type:inline-size;background:#F5F4F0;color:#272824"><div style="position:absolute;inset:12%;display:flex;flex-direction:column;justify-content:space-between;gap:8%;overflow:hidden"><strong style="font-family:Microsoft YaHei,sans-serif;font-size:7cqw;line-height:1.35;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden">${escape(page.title||'未命名页面')}</strong><span style="flex-shrink:0;font-family:Microsoft YaHei,sans-serif;font-size:6cqw;line-height:1.4;color:#62655E">待生成 · 文案已保留</span></div></div>`;
 if(!page?.objects)return '<div style="aspect-ratio:16/9;background:#f5f4f0"></div>';const content=page.objects.map(o=>{const base=`position:absolute;box-sizing:border-box;left:${safeNumber(o.x)/12.8}%;top:${safeNumber(o.y)/7.2}%;width:${Math.max(0,safeNumber(o.w))/12.8}%;height:${Math.max(0,safeNumber(o.h))/7.2}%;opacity:${clamp(safeNumber(o.opacity,1),0,1)};transform:rotate(${safeNumber(o.rotation)}deg);transform-origin:center;`;if(o.type==='vector')return `<img alt="" src="${escape(vectorDataUrl(o))}" style="${base}">`;if(o.type==='text')return `<div style="${base}font-family:${escape(o.fontFamily||'Microsoft YaHei')},sans-serif;font-size:${safeNumber(o.fontSize,24)/12.8}cqw;font-weight:${o.bold?700:400};font-style:${o.italic?'italic':'normal'};line-height:${safeNumber(o.lineHeight,1.4)};text-align:${['left','center','right'].includes(o.align)?o.align:'left'};color:${color(o.color)};white-space:pre-wrap;overflow-wrap:anywhere;overflow:hidden">${escape(o.text)}</div>`;if(o.type==='image'){const crop=o.crop;if(crop){const w=clamp(safeNumber(crop.w,1),.01,1),h=clamp(safeNumber(crop.h,1),.01,1),x=clamp(safeNumber(crop.x),0,1-w),y=clamp(safeNumber(crop.y),0,1-h);return `<div style="${base}overflow:hidden"><img alt="" loading="lazy" src="${escape(imageSrc(o.src))}" style="position:absolute;max-width:none;width:${100/w}%;height:${100/h}%;left:${-x/w*100}%;top:${-y/h*100}%;object-fit:fill"></div>`;}return `<img alt="" loading="lazy" src="${escape(imageSrc(o.src))}" style="${base}object-fit:${o.fit==='cover'?'cover':'contain'}">`;}const shadow=o.shadow?`box-shadow:${safeNumber(o.shadow.offsetX)/12.8}cqw ${safeNumber(o.shadow.offsetY)/12.8}cqw ${safeNumber(o.shadow.blur)/12.8}cqw ${color(o.shadow.color,'#14232B')}${Math.round(clamp(safeNumber(o.shadow.opacity,.15),0,1)*255).toString(16).padStart(2,'0')};`:'';return `<div style="${base}background:${color(o.fill,'transparent')};border-radius:${o.type==='ellipse'?'50%':safeNumber(o.radius)/12.8+'cqw'};${o.type==='line'?`border-top:${Math.max(.5,safeNumber(o.strokeWidth,1))/12.8}cqw solid ${color(o.stroke)};`:o.stroke&&o.strokeWidth?`border:${safeNumber(o.strokeWidth)/12.8}cqw solid ${color(o.stroke)};`:''}${shadow}"></div>`;}).join('');return `<div aria-hidden="true" style="position:relative;aspect-ratio:16/9;width:100%;overflow:hidden;container-type:inline-size;background:${color(page.background,'#FFFFFF')}">${content}</div>`;}
