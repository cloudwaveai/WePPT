/* Source-specific editable reconstruction of curated-139, based on its eight reference images. */
export const RETRO_ID='curated-139';
const BLUE='#316BF0',BLACK='#050505',WHITE='#FFFFFF',PAPER='#E7E7E7';
const source='/assets/templates/curated-139/';
const variants={cover:['主窗口拼贴','黑白影像封面','蓝底宣言'],toc:['影像目录窗口','整页目录窗口','双栏索引'],content:['黑条内容分组','影像与正文','完整阅读窗口'],data:['数据并置窗口','影像与数据','纵向数据清单'],flow:['横向流程窗口','纵向步骤窗口','双栏流程'],chapter:['章节宣言','影像章节','章节窗口'],ending:['收束窗口拼贴','影像结语','蓝底结论']};
export function retroVariants(role){return (variants[role]||variants.content).map((name,id)=>({id,name,description:'复古蓝黑窗口 · 文案与素材均可编辑'}));}
const clone=x=>JSON.parse(JSON.stringify(x));
const units=s=>[...String(s)].reduce((n,c)=>n+(/[^\u0000-\u00ff]/.test(c)?1:.58),0);
const lines=(s,size,w)=>String(s).split('\n').reduce((n,line)=>n+Math.max(1,Math.ceil(units(line)*size/Math.max(size,w-size*2-8))),0);
const id=()=>globalThis.crypto.randomUUID();
function segments(body){const result=[];let start=0;for(const match of body.matchAll(/\n/g)){result.push({text:body.slice(start,match.index),start,end:match.index});start=match.index+1;}result.push({text:body.slice(start),start,end:body.length});return result.filter(s=>s.text.trim()).map(s=>{const m=s.text.match(/^##[ \t]+(.+)$/);if(m)return {...s,text:m[1],start:s.start+s.text.length-m[1].length,heading:true};return {...s,heading:false};});}
function groups(body){const headings=[...body.matchAll(/^##[ \t]+.+$/gm)];if(headings.length){const starts=headings.map(m=>m.index);if(starts[0]>0&&body.slice(0,starts[0]).trim())starts.unshift(0);return starts.map((start,i)=>({start,end:starts[i+1]??body.length,text:body.slice(start,starts[i+1]??body.length)}));}const parts=[...body.matchAll(/[^\n]+(?:\n|$)/g)];return parts.map(m=>({start:m.index,end:m.index+m[0].length,text:m[0]})).filter(p=>p.text.trim());}
export function layoutRetro(input,theme){
 const page=clone(input),body=String(page.body||''),title=String(page.title||''),variant=page.variant||0,role=page.role||'content';
 page.background=BLUE;page.themeId=RETRO_ID;page.layoutWarnings=[];page.layoutOverflow=false;
 const objects=[];let serial=0;const font=theme.fontFamily||'Microsoft YaHei';
 const make=(type,x,y,w,h,extra={})=>{const o={id:`layout-${page.id}-retro-${serial++}`,type,x,y,w,h,rotation:0,opacity:1,layoutManaged:true,...extra};objects.push(o);return o;};
 const rect=(x,y,w,h,fill=WHITE,stroke=BLACK,strokeWidth=2)=>make('rect',x,y,w,h,{fill,stroke,strokeWidth,radius:0});
 const line=(x,y,w,rotation=0,color=BLACK,width=3)=>make('line',x,y,w,0,{stroke:color,strokeWidth:width,rotation});
 const rawText=(value,x,y,w,h,size=28,extra={})=>make('text',x,y,w,h,{text:value,sourceText:value,fontFamily:font,fontSize:size,bold:false,color:BLACK,align:'left',lineHeight:1.4,...extra});
 function titleAt(x,y,w,h,color=BLACK,preferred=64){let size=preferred;while(size>32&&lines(title,size,w)*size*1.4>h)size--;if(lines(title,size,w)*size*1.4>h)page.layoutWarnings.push('标题较长，请缩短标题或调整标题框。');return rawText(title,x,y,w,h,size,{bold:true,color,layoutField:'title',sourceField:'title'});}
 function chevrons(x,y,count=4,color=BLACK){for(let n=0;n<count;n++){line(x+n*17,y,15,45,color,4);line(x+n*17,y+11,15,-45,color,4);}}
 function photo(name,x,y,w,h){const crops={building:{src:'6.jpg',crop:{x:56/800,y:163/450,w:275/800,h:183/450}},architecture:{src:'4.jpg',crop:{x:457/800,y:107/450,w:265/800,h:132/450}},horse:{src:'1.jpg',crop:{x:48/800,y:190/450,w:113/800,h:190/450}},stairs:{src:'0.jpg',crop:{x:70/1600,y:72/900,w:162/1600,h:217/900}},window:{src:'0.jpg',crop:{x:1369/1600,y:608/900,w:157/1600,h:218/900}}};const spec=crops[name];rect(x-2,y-2,w+4,h+4,BLACK);return make('image',x,y,w,h,{src:source+spec.src,crop:spec.crop,fit:'cover',referencePhoto:true,sourceReference:RETRO_ID+'/'+spec.src});}
 function windowFrame(x,y,w,h,{fill=WHITE,bar=28,scroll=false}={}){rect(x,y,w,h,fill);rect(x,y,w,bar,BLACK,BLACK,0);for(let i=0;i<3;i++){const xx=x+w-24-(2-i)*22;rect(xx,y+7,15,14,'#B9DBFF',BLACK,1);if(i===0){line(xx+3,y+11,10,45,BLACK,1.5);line(xx+3,y+16,10,-45,BLACK,1.5);}else if(i===1)rect(xx+3,y+10,9,8,'#B9DBFF',BLACK,1);else line(xx+3,y+18,9,0,BLACK,1.5);}if(scroll){rect(x+w-18,y+bar,18,h-bar,PAPER,BLACK,1.5);rect(x,y+h-18,w,18,PAPER,BLACK,1.5);}return [x+26,y+bar+22,w-52-(scroll?18:0),h-bar-44-(scroll?18:0)];}
 const overflow=()=>{page.layoutOverflow=true;page.layoutWarnings.push('文字超出本页可读容量；应用排版时将续页，预览不缩小文字。');};
 function bodyAt(part,box,{color=BLACK,size=28}={}){const list=segments(part.text).map(s=>({...s,start:s.start+part.start,end:s.end+part.start}));let preferred=size;const measure=()=>list.map((s,i)=>({size:preferred+(s.heading?3:0),gap:i?(s.heading?14:6):0,height:lines(s.text,preferred+(s.heading?3:0),box[2])*(preferred+(s.heading?3:0))*1.4}));let dims=measure();while(preferred>24&&dims.reduce((n,d)=>n+d.height+d.gap,0)>box[3]){preferred--;dims=measure();}const sum=dims.reduce((n,d)=>n+d.height+d.gap,0);if(sum>box[3]+1)overflow();let y=box[1];list.forEach((s,i)=>{const d=dims[i];y+=d.gap;rawText(s.text,box[0],y,box[2],d.height,d.size,{color,bold:s.heading,contentRole:s.heading?'subheading':'paragraph',layoutField:'body',sourceField:'body',sourceRange:[s.start,s.end],sourceStart:s.start,sourceEnd:s.end});y+=d.height;});}
 const whole={text:body,start:0,end:body.length};
 function topTitle(){titleAt(68,35,1000,105,WHITE,47);chevrons(1103,61,4);}
 function groupedPanel(part,x,y,w,h,index,{number=false}={}){rect(x,y,w,h,WHITE);const head=segments(part.text)[0];if(head?.heading){const headHeight=lines(head.text,28,w-32)*28*1.4+12;rect(x,y,w,headHeight,BLACK,BLACK,0);rawText(head.text,x+16,y+4,w-32,headHeight-8,28,{bold:true,color:WHITE,contentRole:'subheading',layoutField:'body',sourceField:'body',sourceRange:[part.start+head.start,part.start+head.end]});const restStart=head.end;const rest={text:part.text.slice(restStart),start:part.start+restStart,end:part.end};bodyAt(rest,[x+18,y+headHeight+14,w-36,h-headHeight-28],{size:26});if(headHeight>h-35)overflow();}else{rect(x,y,w,number?38:16,BLACK,BLACK,0);if(number)rawText(String(index+1).padStart(2,'0'),x+15,y+1,w-30,35,26,{bold:true,color:WHITE});bodyAt(part,[x+20,y+(number?52:32),w-40,h-(number?68:48)],{size:27});}}
 const hero=['cover','ending','chapter'].includes(role);
 if(role==='chapter'&&variant===0){
  titleAt(64,70,740,210,WHITE,62);rawText(String(page.chapterNumber||1).padStart(2,'0'),865,32,345,275,180,{bold:true,color:BLACK});
  const area=windowFrame(64,353,1015,272);bodyAt(whole,area,{size:30});chevrons(1112,564,4);
 }else if(hero){
  if(variant===0){
   photo('stairs',50,46,210,247);photo('window',1025,443,196,227);chevrons(590,61,5);const area=windowFrame(184,124,914,445,{scroll:true});titleAt(area[0]+20,area[1]+24,area[2]-40,205,BLACK,76);bodyAt(whole,[area[0]+22,area[1]+247,area[2]-44,100],{size:27});chevrons(660,636,5);
  }else if(variant===1){
   photo('building',60,122,450,440);const area=windowFrame(475,73,740,555,{scroll:true});titleAt(area[0]+5,area[1]+18,area[2]-10,235,BLACK,66);bodyAt(whole,[area[0]+5,area[1]+280,area[2]-10,170],{size:27});chevrons(80,630,5);
  }else{
   titleAt(64,55,1110,270,WHITE,76);const area=windowFrame(64,382,1020,262);bodyAt(whole,area,{size:30});chevrons(1110,580,4,BLACK);rect(1120,382,95,95,BLACK);rect(1144,404,49,49,BLUE,WHITE,3);
  }
 }else if(role==='toc'){
  topTitle();const area=windowFrame(64,180,1152,454);let region=area;
  if(variant===0){photo('horse',66,209,190,423);region=[287,232,896,365];}
  else if(variant===2){photo('architecture',928,47,288,115);region=[93,237,1095,365];}
  const list=groups(body),cols=variant===1?1:2,rows=Math.max(1,Math.ceil(list.length/cols)),gap=22,rowH=region[3]/rows,w=(region[2]-(cols-1)*gap)/cols;
  list.forEach((part,i)=>{const col=variant===1?0:Math.floor(i/rows),row=variant===1?i:i%rows,x=region[0]+col*(w+gap),y=region[1]+row*rowH;rawText(String(i+1).padStart(2,'0'),x,y,60,52,38,{bold:true});bodyAt(part,[x+70,y+4,w-76,rowH-12],{size:27});});
 }else if(role==='content'&&variant===1){
  topTitle();const area=windowFrame(64,175,1152,480,{fill:PAPER});photo('building',38,257,434,300);const list=groups(body);if(list.length<=2&&list.length){const h=(392-(list.length-1)*20)/list.length;list.forEach((part,i)=>groupedPanel(part,510,229+i*(h+20),668,h,i));}else bodyAt(whole,[510,232,660,380],{size:28});
 }else if(role==='content'&&variant===2||role==='data'&&variant===2||role==='flow'&&variant===1){
  topTitle();const area=windowFrame(64,172,1152,484,{scroll:true});bodyAt(whole,[area[0]+14,area[1]+2,area[2]-28,area[3]-4],{size:29});
 }else{
  topTitle();const list=groups(body);let cols=role==='flow'&&variant===0?Math.min(3,Math.max(1,list.length)):2;const n=Math.max(1,list.length),rows=Math.ceil(n/cols),gap=24,top=183,availableH=455;
  if(role==='data'&&variant===1){photo('architecture',827,181,388,194);const left={text:body,start:0,end:body.length};const area=windowFrame(64,180,730,457);bodyAt(left,area,{size:28});chevrons(885,458,5);}
  else{const width=(1152-gap*(cols-1))/cols,height=(availableH-gap*(rows-1))/rows;if(height<100)overflow();list.forEach((part,i)=>{const x=64+(i%cols)*(width+gap),y=top+Math.floor(i/cols)*(height+gap);groupedPanel(part,x,y,width,Math.max(1,height),i,{number:role==='flow'});if(role==='flow'&&i%cols<cols-1&&i<list.length-1){line(x+width+4,y+height/2,16,0,BLACK,3);}});}
 }
 if(page.continuationIndex)rawText(`续 ${page.continuationIndex+1}`,1105,665,110,38,24,{color:WHITE,align:'right'});
 const retained=(page.objects||[]).filter(o=>o.custom||!o.layoutManaged).map(clone),ids=new Set(objects.map(o=>o.id));for(const o of retained){if(ids.has(o.id))o.id=id();objects.push(o);}
 page.objects=objects;page.layoutSource={title,body};page.layoutWarnings=[...new Set(page.layoutWarnings)];return page;
}
// Split only when applying a complete layout; a preview never mutates page count.
export function paginateRetro(page,theme){
 const first=layoutRetro(page,theme);if(!first.layoutOverflow)return[first];
 const body=page.body||'',pieces=[];let offset=0;
 while(offset<body.length){
  let low=1,high=body.length-offset,best=0;
  while(low<=high){const mid=Math.floor((low+high)/2),candidate={...page,body:body.slice(offset,offset+mid),objects:[],role:pieces.length&&['cover','ending','chapter'].includes(page.role)?'content':page.role};const rendered=layoutRetro(candidate,theme);if(!rendered.layoutOverflow){best=mid;low=mid+1;}else high=mid-1;}
  if(!best){best=1;}
  let end=offset+best;
  if(end<body.length){const cut=body.lastIndexOf('\n',end-1);if(cut>offset+Math.floor(best*.45))end=cut+1;}
  if(end<=offset)end=offset+1;
  pieces.push({start:offset,end});offset=end;
 }
 if(!pieces.length)return[first];
 return pieces.map((range,i)=>{const input={...page,id:i?id():page.id,body:body.slice(range.start,range.end),objects:i?[]:page.objects,role:i&&['cover','ending','chapter'].includes(page.role)?'content':page.role,continuationOf:page.continuationOf||page.id,continuationIndex:i,continuationCount:pieces.length,continuationRange:[range.start,range.end]};return layoutRetro(input,theme);});
}
