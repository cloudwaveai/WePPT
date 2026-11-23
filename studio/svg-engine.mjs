import {prepareReferenceArtworkForExport} from './reference-image-export.mjs';
import {prepareExportImageCrops} from './image-crop-export.mjs';
import {inferRole} from './public/templates.js';
import {prepareLibraryExport,embedLibrarySvgPictures} from './library-export.mjs';
import {chromium} from 'playwright-core';
import {mkdir,mkdtemp,readFile,writeFile,rm,readdir} from 'node:fs/promises';
import JSZip from 'jszip';
import {join,resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {upstreamPackage} from './upstream-skills.mjs';
import {validateSvg,validateVectorObject,pageToSvg} from './public/vector-scene.js';
import {measureNativeTextLines} from './public/native-text-lines.js';
import {compactSvgDefinitions} from './public/svg-definitions.js';
const ROOT=fileURLToPath(new URL('.',import.meta.url));
function compact(s){return String(s||'').replace(/[\s#]/g,'');}
function sourceRange(body,text,used){const target=compact(text);if(!target)return null;let value='',map=[];for(let i=0;i<body.length;i++)if(!/[\s#]/.test(body[i])){map.push(i);value+=body[i];}let pos=value.indexOf(target);while(pos>=0){const range=[map[pos],map[pos+target.length-1]+1];if(!used.some(([a,b])=>a<range[1]&&b>range[0])){used.push(range);return range;}pos=value.indexOf(target,pos+1);}return null;}

export async function importSvgPages(input,{signal}={}){
 if(!Array.isArray(input?.pages)||!input.pages.length||input.pages.length>100)throw Error('SVG 导入需要1至100页。');
 // PDF converters wrap embedded base64. XML turns these newlines into spaces;
 // canonicalize only supported inline raster data before validation and parsing.
 input={...input,pages:input.pages.map(page=>({...page,svg:typeof page.svg==='string'?page.svg.replace(/\b(?:[\w-]+:)?href\s*=\s*(["'])([\s\S]*?)\1/gi,(attribute,quote,value)=>/^data:image\/(?:png|jpeg|webp);base64,[a-z\d+/=\t\r\n ]+$/i.test(value)?attribute.replace(value,value.replace(/[\t\r\n ]/g,'')):attribute):page.svg}))};
 for(const p of input.pages)validateSvg(p.svg,{allowUse:true});
 if(signal?.aborted)throw Error('SVG 导入已取消。');
 const browser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const abort=()=>browser.close().catch(()=>{});signal?.addEventListener('abort',abort,{once:true});
 try{
  const tab=await browser.newPage({viewport:{width:1280,height:720}});await tab.route('**/*',r=>r.abort());await tab.addScriptTag({content:compactSvgDefinitions.toString()});
  const result=[];
  for(const source of input.pages){
   if(signal?.aborted)throw Error('SVG 导入已取消。');
   const extracted=await tab.evaluate(async raw=>{
    const parsed=new DOMParser().parseFromString(raw,'image/svg+xml');if(parsed.querySelector('parsererror'))throw Error('SVG XML格式不正确。');
    const root=parsed.documentElement;const vb=root.viewBox.baseVal;if(!(vb.width>0&&vb.height>0))throw Error('SVG缺少有效viewBox。');if(vb.width!==1280||vb.height!==720||vb.x!==0||vb.y!==0){const scale=Math.min(1280/vb.width,720/vb.height),g=parsed.createElementNS('http://www.w3.org/2000/svg','g');g.setAttribute('transform',`translate(${(1280-vb.width*scale)/2} ${(720-vb.height*scale)/2}) scale(${scale}) translate(${-vb.x} ${-vb.y})`);for(const child of [...root.children])if(child.localName!=='defs')g.append(child);root.append(g);root.setAttribute('viewBox','0 0 1280 720');root.setAttribute('width','1280');root.setAttribute('height','720');}
    for(const node of root.querySelectorAll('*'))for(const attr of [...node.attributes]){
     if(/^on/i.test(attr.name)||/\\|@|expression\s*\(/i.test(attr.value))throw Error('SVG 包含不允许的样式或事件。');
     if(attr.localName==='href'&&!/^#|^data:image\/(?:png|jpeg|webp);base64,/i.test(attr.value))throw Error('SVG 外部资源被拒绝。');
    }
    document.body.innerHTML='';document.body.style.margin='0';document.body.append(document.importNode(root,true));const svg=document.querySelector('svg');
    const definitions=new Map([...svg.querySelectorAll('[id]')].map(node=>[node.id,node]));let expandedUses=0;
    function expandUses(scope,chain=[]){for(const use of [...scope.querySelectorAll('use')]){if(++expandedUses>10000)throw Error('SVG复用元素数量超过安全限制。');const href=use.getAttribute('href')||use.getAttributeNS('http://www.w3.org/1999/xlink','href')||'';if(!/^#[\w:.-]+$/.test(href))throw Error('SVG复用元素只能引用本页内部图形。');const ref=href.slice(1);if(chain.includes(ref))throw Error('SVG复用元素存在循环引用。');const target=definitions.get(ref);if(!target)throw Error('SVG复用元素引用了不存在的图形。');const outer=document.createElementNS('http://www.w3.org/2000/svg','g'),inner=document.createElementNS('http://www.w3.org/2000/svg','g');for(const attr of [...use.attributes])if(!['href','xlink:href','x','y','width','height','transform'].includes(attr.name.toLowerCase()))outer.setAttribute(attr.name,attr.value);if(use.hasAttribute('transform'))outer.setAttribute('transform',use.getAttribute('transform'));const x=Number(use.getAttribute('x')||0),y=Number(use.getAttribute('y')||0);if(!Number.isFinite(x)||!Number.isFinite(y))throw Error('SVG复用元素位置无效。');if(x||y)inner.setAttribute('transform',`translate(${x} ${y})`);if(target.localName==='symbol'){const nested=document.createElementNS('http://www.w3.org/2000/svg','svg');const viewBox=target.getAttribute('viewBox');if(!viewBox)throw Error('SVG复用符号缺少viewBox。');nested.setAttribute('viewBox',viewBox);nested.setAttribute('width',use.getAttribute('width')||'100%');nested.setAttribute('height',use.getAttribute('height')||'100%');nested.setAttribute('preserveAspectRatio',use.getAttribute('preserveAspectRatio')||target.getAttribute('preserveAspectRatio')||'xMidYMid meet');for(const child of [...target.childNodes])nested.append(child.cloneNode(true));inner.append(nested);}else inner.append(target.cloneNode(true));outer.append(inner);use.replaceWith(outer);expandUses(outer,[...chain,ref]);}}
    expandUses(svg);for(const symbol of svg.querySelectorAll('defs symbol'))symbol.remove();
    // Use the same explicit fallback as the editor/preview, instead of platform serif defaults.
    for(const text of svg.querySelectorAll('text,tspan')){const family=getComputedStyle(text).fontFamily;if(!/(?:^|,)\s*(?:sans-serif|serif|monospace|system-ui)\s*(?:,|$)/i.test(family))text.style.fontFamily=family+', sans-serif';}
    await document.fonts.ready;
    const defs=[...svg.querySelectorAll('defs')].map(n=>n.outerHTML).join('');const objects=[],sourceTextRuns=[],textOrder=new Map([...svg.querySelectorAll('text')].map((node,index)=>[node,index]));let background='#FFFFFF';
    const readSvgText=node=>{let text='';for(const child of node.childNodes){if(child.nodeType===3)text+=child.textContent;else if(child.localName==='tspan'){if(text&&(child.hasAttribute('dy')||child.hasAttribute('y')))text+='\n';text+=child.textContent;}}return text;};
    const styles=['fill','fill-opacity','fill-rule','stroke','stroke-width','stroke-opacity','stroke-linecap','stroke-linejoin','stroke-dasharray','font-family','font-size','font-weight','font-style','text-anchor','letter-spacing','dominant-baseline'];
    const rgbaHex=color=>{const a=/rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color);return a?'#'+a.slice(1).map(n=>(+n).toString(16).padStart(2,'0')).join(''):color;};
    function visit(node){
     const tag=node.localName;if(['defs','metadata','title','desc'].includes(tag))return;
     const nativeType=node.getAttribute('data-pptx-replace-with');
     const groupEffect=tag==='g'&&['clip-path','mask','filter'].some(key=>node.hasAttribute(key)&&node.getAttribute(key)!=='none');
     if(tag==='g'&&!nativeType&&!groupEffect){for(const child of node.children)visit(child);return;}
     const cs=getComputedStyle(node);if(cs.display==='none'||cs.visibility==='hidden')return;
     if(groupEffect){for(const textNode of node.querySelectorAll('text')){const id=`weppt-source-run-${sourceTextRuns.length}`;textNode.setAttribute('data-weppt-source-run-id',id);sourceTextRuns.push({id,text:readSvgText(textNode),order:textOrder.get(textNode)??sourceTextRuns.length,objectIndex:objects.length});}}
     const box=node.getBBox(),matrix=node.getCTM();if(!matrix)throw Error('SVG 无法测量坐标。');
     const corners=[[box.x,box.y],[box.x+box.width,box.y],[box.x,box.y+box.height],[box.x+box.width,box.y+box.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(matrix));
     const x=Math.min(...corners.map(p=>p.x)),y=Math.min(...corners.map(p=>p.y)),w=Math.max(...corners.map(p=>p.x))-x,h=Math.max(...corners.map(p=>p.y))-y;
     if(![x,y,w,h].every(Number.isFinite))throw Error('SVG包含无效坐标。');
     if(x<-20000||y<-20000||w>20000||h>20000)throw Error('SVG对象超出安全尺寸。');
     let opacity=1;for(let ancestor=node;ancestor&&ancestor!==svg;ancestor=ancestor.parentElement)opacity*=Number(getComputedStyle(ancestor).opacity||1);
     if(tag==='rect'&&objects.length===0&&x===0&&y===0&&w===1280&&h===720&&!node.getAttribute('filter')&&!cs.fill.startsWith('url(')){background=rgbaHex(cs.fill);return;}
     const base={id:'svg-'+objects.length,type:'vector',x,y,w:Math.max(w,1),h:Math.max(h,1),rotation:0,opacity:1,layoutManaged:true,custom:false};
     let nativeShadow;const filterRef=node.getAttribute('filter');if(filterRef&&['text','tspan','image'].includes(tag)){const filterId=/url\(#([^)]*)\)/.exec(filterRef)?.[1],filter=filterId?svg.querySelector('#'+CSS.escape(filterId)):null,drop=filter?.querySelector('feDropShadow');if(!drop||filter.children.length!==1)throw Error('文字/图片包含尚未支持的复杂滤镜。');nativeShadow={offsetX:Number(drop.getAttribute('dx')||0),offsetY:Number(drop.getAttribute('dy')||0),blur:Number(drop.getAttribute('stdDeviation')||0)*2,color:drop.getAttribute('flood-color')||'#000000',opacity:Number(drop.getAttribute('flood-opacity')||1)};}
     if(tag==='text'||tag==='tspan'){
      if(Math.abs(matrix.b)>.001||Math.abs(matrix.c)>.001||Math.abs(matrix.a-matrix.d)>.001)throw Error('当前文字桥接不支持旋转、斜切或非等比缩放的文字；请先转成普通文本排版。');
      const spans=[...node.querySelectorAll('tspan')];if(spans.some(s=>{const a=getComputedStyle(s);return a.fontSize!==cs.fontSize||a.fontFamily!==cs.fontFamily||a.fill!==cs.fill||a.fontWeight!==cs.fontWeight;})){if([...node.childNodes].some(c=>c.nodeType===3&&c.textContent.trim()))throw Error('混合样式的直接文本和tspan需拆为独立tspan，才能无损编辑。');for(const child of node.children)visit(child);return;}
      let text='';for(const child of node.childNodes){if(child.nodeType===3)text+=child.textContent;else if(child.localName==='tspan'){if(text&&(child.hasAttribute('dy')||child.hasAttribute('y')))text+='\n';text+=child.textContent;}}
      const fontSize=parseFloat(cs.fontSize)*matrix.a;let lineHeight=1.2;if(spans.length>1){const ys=spans.map(s=>s.getStartPositionOfChar(0).y).filter(Number.isFinite);const gaps=ys.slice(1).map((v,i)=>v-ys[i]).filter(v=>v>0);if(gaps.length)lineHeight=gaps[0]*matrix.a/fontSize;}
      const baseline=node.getStartPositionOfChar(0).matrixTransform(matrix).y-y;
      // Glyph bounds are narrower than the original editable frame (especially
      // bold Chinese). Preserve the frame's available width to avoid inventing
      // a new line break in the editor and subsequent PPTX export.
      const measure=document.createElement('div');measure.textContent=text;
      Object.assign(measure.style,{position:'absolute',left:'-100000px',width:'max-content',height:'auto',padding:'0',margin:'0',border:'0',fontFamily:cs.fontFamily,fontSize:fontSize+'px',fontWeight:cs.fontWeight,fontStyle:cs.fontStyle,lineHeight:String(lineHeight),whiteSpace:'pre'});
      document.body.append(measure);const measured=measure.getBoundingClientRect();const measuredW=Math.max(measured.width,measure.scrollWidth),measuredH=Math.max(measured.height,measure.scrollHeight);measure.remove();
      const frame=node.closest('[data-pptx-frame]')?.getAttribute('data-pptx-frame')?.split(/\s+/).map(Number);let textWidth=Math.max(w+3,measuredW+4,4),textHeight=Math.max(h,measuredH+4,fontSize*lineHeight*text.split('\n').length);if(frame?.length===4&&frame.every(Number.isFinite)){textWidth=Math.max(4,frame[0]+frame[2]-x);textHeight=Math.max(textHeight,frame[3]);}
      objects.push({...base,type:'text',text,svgTextOrder:textOrder.get(node)??0,fontSize,fontFamily:cs.fontFamily.replace(/["']/g,''),color:rgbaHex(cs.fill),bold:+cs.fontWeight>=600,italic:cs.fontStyle==='italic',align:'left',lineHeight,svgBaseline:baseline,w:textWidth,h:textHeight,opacity,...(nativeShadow?{shadow:nativeShadow}:{})});return;
     }
     if(tag==='image'){
      if(node.hasAttribute('clip-path')||node.hasAttribute('mask'))throw Error('带裁剪路径的SVG图片暂不支持重新导入；现有编辑器裁剪可正常导出。');
      const href=node.getAttribute('href')||node.getAttributeNS('http://www.w3.org/1999/xlink','href');if(Math.abs(matrix.b)>.001||Math.abs(matrix.c)>.001)throw Error('当前图片桥接不支持斜切/旋转，请使用普通图片框。');
      objects.push({...base,type:'image',src:href,fit:(node.getAttribute('preserveAspectRatio')||'').includes('slice')?'cover':'contain',opacity,...(nativeShadow?{shadow:nativeShadow}:{})});return;
     }
     const clone=node.cloneNode(true);if(groupEffect&&node.hasAttribute('filter')&&clone.children.length===1){clone.children[0].setAttribute('filter',clone.getAttribute('filter'));clone.removeAttribute('filter');}const originalNodes=[node,...node.querySelectorAll('*')],clonedNodes=[clone,...clone.querySelectorAll('*')];
     for(let i=0;i<originalNodes.length;i++){if(originalNodes[i].localName==='metadata')continue;const s=getComputedStyle(originalNodes[i]);for(const key of styles){if(!['text','tspan','g'].includes(originalNodes[i].localName)&&/font|text-anchor|letter-spacing|dominant-baseline/.test(key))continue;if(key==='dominant-baseline'||(key==='letter-spacing'&&s.getPropertyValue(key)==='normal'))continue;if(s.getPropertyValue(key))clonedNodes[i].setAttribute(key,key==='stroke-dasharray'?s.getPropertyValue(key).replace(/px/g,'').replace(/,/g,' '):s.getPropertyValue(key).replace(/url\(["']?#([\w:.-]+)["']?\)/g,'url(#$1)'));}}
     clone.removeAttribute('transform');if(matrix.b===0&&matrix.c===0){if(matrix.e||matrix.f||matrix.a!==1||matrix.d!==1)clone.setAttribute('transform',`translate(${matrix.e} ${matrix.f}) scale(${matrix.a} ${matrix.d})`);}else clone.setAttribute('transform',`matrix(${matrix.a} ${matrix.b} ${matrix.c} ${matrix.d} ${matrix.e} ${matrix.f})`);clone.setAttribute('opacity',String(Number(cs.opacity)));
     const stroke=parseFloat(cs.strokeWidth)||0,pad=Math.max(stroke/2,node.hasAttribute('filter')?64:1);const vx=x-pad,vy=y-pad,vw=Math.max(w+pad*2,2),vh=Math.max(h+pad*2,2);
     let nativeData;if(nativeType){const metadata=node.querySelector('metadata');if(!metadata)throw Error('原生图表或表格缺少metadata。');nativeData=JSON.parse(metadata.textContent);}
     objects.push({...base,opacity:opacity/(Number(cs.opacity)||1),x:vx,y:vy,w:vw,h:vh,svg:globalThis.compactSvgDefinitions(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vx} ${vy} ${vw} ${vh}" width="${vw}" height="${vh}">${defs}${clone.outerHTML}</svg>`),...(nativeType?{nativeType,nativeData}:{}),name:nativeType==='chart'?'原生图表':nativeType==='table'?'原生表格':node.id||'矢量形状'});
    }
    for(const node of svg.children)visit(node);
    if(objects.length>1000)throw Error('SVG单页对象超过1000个。');return {objects,sourceTextRuns,background,normalizedSvg:svg.outerHTML};
   },source.svg);
   validateSvg(extracted.normalizedSvg);
   for(const run of extracted.sourceTextRuns){run.objectId=extracted.objects[run.objectIndex]?.id;delete run.objectIndex;}
   const used=[];let titleSet=false;const body=String(source.body||'');
   for(const o of extracted.objects){o.id=randomUUID();if(o.type==='vector')validateVectorObject(o);if(o.type==='text'){
    if(!titleSet&&compact(o.text)===compact(source.title)){o.layoutField='title';o.sourceField='title';o.sourceText=source.title;titleSet=true;}
    else {const range=sourceRange(body,o.text,used);if(range){o.layoutField='body';o.sourceField='body';o.sourceRange=range;o.sourceText=body.slice(...range);o.text=o.sourceText;o.h=Math.max(o.h,o.fontSize*o.lineHeight*o.text.split('\n').length);}}
   }}
   if(source.requireExactContent){const visible=compact(extracted.objects.filter(o=>o.type==='text').map(o=>o.text).join('')+extracted.objects.filter(o=>o.nativeData).map(o=>JSON.stringify(o.nativeData)).join(''));for(const text of [source.title,...body.split('\n').filter(Boolean)])if(!visible.includes(compact(text)))throw Error('SVG 文案完整性检查失败：'+String(text).slice(0,50));}
   const {svg,...rest}=source;result.push({...rest,id:source.id||randomUUID(),...extracted,engine:'ppt-master-svg',layoutSource:{title:source.title||'',body},variant:source.variant||0});
  }
  return {pages:result,warnings:[]};
 }finally{signal?.removeEventListener('abort',abort);await browser.close();}
}

function runPython(script,args,{signal,timeout=90000}={}){return new Promise((resolveRun,reject)=>{let log='';const child=spawn(process.env.PYTHON||'python',['-X','utf8',script,...args],{windowsHide:true,stdio:['ignore','pipe','pipe']});let done=false;const end=e=>{if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);e?reject(e):resolveRun(log);};const abort=()=>{child.kill();end(Error('原生导出已取消。'));};const timer=setTimeout(()=>{child.kill();end(Error('原生导出超时。'));},timeout);signal?.addEventListener('abort',abort,{once:true});for(const stream of [child.stdout,child.stderr])stream.on('data',b=>log=(log+b).slice(-20000));child.on('error',end);child.on('close',c=>end(c===0?null:Error('原生导出未通过：'+(log.split(/\r?\n/).filter(line=>line.includes('[ERROR]')).join('\n')||log.slice(-5000)))));if(signal?.aborted)abort();});}

export async function exportNativePptx(project,{dataDir=join(ROOT,'data'),signal}={}){
 if(!Array.isArray(project?.pages)||!project.pages.length)throw Error('没有可导出的页面。');
 const skill=upstreamPackage('ppt-master');if(!skill.installed)throw Error('PPT Master运行包未安装。');
 const parent=join(resolve(dataDir),'native-export-jobs');await mkdir(parent,{recursive:true});const directory=await mkdtemp(join(parent,'job-'));await mkdir(join(directory,'svg_output'));
 try{
  const prepared=structuredClone(project.pages);
  for(const p of prepared){for(const o of p.objects||[])if(o.type==='image'&&/^\/uploads\/[a-f\d-]+\.(png|jpg|webp)$/i.test(o.src)){const filename=o.src.split('/').pop();const bytes=await readFile(join(dataDir,'uploads',filename));o.src=`data:image/${filename.endsWith('.jpg')?'jpeg':filename.split('.').pop()};base64,${bytes.toString('base64')}`;}
   for(const o of p.objects||[])if(o.type==='image'&&o.src?.startsWith('/assets/templates/')){if(!/^\/assets\/templates\/[a-z\d_-]+\/[a-z\d_.-]+\.(png|jpe?g|webp)$/i.test(o.src))throw Error('模板素材路径无效。');const bytes=await readFile(join(ROOT,'public',o.src.slice(1)));const ext=o.src.split('.').pop().toLowerCase();o.src=`data:image/${ext==='jpg'?'jpeg':ext};base64,${bytes.toString('base64')}`;}
  }
  let libraryPictures=new Map();
  if(prepared.some(page=>page.objects?.some(o=>o.type==='vector'&&o.libraryAssetId))){
  const assetBrowser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try{libraryPictures=await prepareLibraryExport(prepared,await assetBrowser.newPage(),{signal});}finally{await assetBrowser.close();}
  }
  const textBrowser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try{
   const tab=await textBrowser.newPage();await tab.route('**/*',r=>r.abort());await prepareExportImageCrops(prepared,tab,{signal});await prepareReferenceArtworkForExport(prepared,tab);
   for(const page of prepared)for(const o of page.objects||[])if(o.type==='text'){
    if(o.flowTypesetting)o.exportLines=await tab.evaluate(measureNativeTextLines,o);
    else o.exportLines=await tab.evaluate(o=>{const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');ctx.font=`${o.italic?'italic ':''}${o.bold?'700':'400'} ${o.fontSize||24}px ${o.fontFamily||'Microsoft YaHei'}`;const lines=[];for(const paragraph of String(o.text||'').split('\n')){let line='';for(const character of paragraph){if(line&&ctx.measureText(line+character).width>o.w){lines.push(line);line='';}line+=character;}lines.push(line);}return lines;},o);
   }
  }finally{await textBrowser.close();}
  for(const [index,p]of prepared.entries()){
   const copy=structuredClone(p);
   const svg=pageToSvg(copy);validateSvg(svg);await writeFile(join(directory,'svg_output',`${String(index+1).padStart(3,'0')}.svg`),svg);
  }
  await runPython(join(skill.directory,'scripts/svg_quality_checker.py'),[directory,'--quick-generate','--canonical-authoring','--stage','final','--json'],{signal});
  const output=join(directory,'result.pptx');await runPython(join(skill.directory,'scripts/svg_to_pptx.py'),[directory,'--quick-generate','--primary-language','zh-CN','-t','none','--native-charts-and-tables','-o',output],{signal});
  // Preserve the scene's explicit font and fixed frame across Office implementations.
  // Theme aliases plus spAutoFit caused LibreOffice to reflow otherwise valid lines.
  const archive=await JSZip.loadAsync(await readFile(output));
  await embedLibrarySvgPictures(archive,libraryPictures);
  for(const [i,page] of prepared.entries()){
   const name=`ppt/slides/slide${i+1}.xml`,file=archive.file(name);if(!file)continue;
   let xml=await file.async('string');xml=xml.replace(/<p:sp>[\s\S]*?<\/p:sp>/g,shape=>{const index=/name="object-(\d+)"/.exec(shape)?.[1],object=index===undefined?null:page.objects?.[Number(index)];if(object?.type!=='text')return shape;const font=String(object.fontFamily||'Microsoft YaHei').split(',')[0].replace(/["']/g,'').trim().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');return shape.replace(/typeface="\+(?:mn|mj)-(?:lt|ea|cs)"/g,`typeface="${font}"`).replace(/<a:spAutoFit\s*\/>/g,'<a:noAutofit/>');});archive.file(name,xml);
  }
  return await archive.generateAsync({type:'nodebuffer',compression:'DEFLATE'});
 }finally{await rm(directory,{recursive:true,force:true});}
}

function bindPageCopyText(page,fallback){
 const entries=[...(page.objects||[]).filter(object=>object.type==='text').map(object=>({kind:'object',value:object,text:object.text,order:object.svgTextOrder??Number.MAX_SAFE_INTEGER})),...(page.sourceTextRuns||[]).map(run=>({kind:'run',value:run,text:run.text,order:run.order??Number.MAX_SAFE_INTEGER}))].sort((a,b)=>a.order-b.order);
 const texts=entries.map(entry=>String(entry.text||''));page.title=texts[0]||fallback;page.body=texts.slice(1).join('\n');let offset=0;
 for(const [index,entry] of entries.entries()){
  const value=entry.value;if(entry.kind==='object')delete value.svgTextOrder;else delete value.order;
  if(index===0)Object.assign(value,{sourceField:'title',layoutField:'title',sourceText:page.title});
  else {const text=String(entry.text||'');Object.assign(value,{sourceField:'body',layoutField:'body',sourceText:text,sourceRange:[offset,offset+text.length]});offset+=text.length+1;}
 }
 page.layoutSource={title:page.title,body:page.body};return page;
}

/** Import PDF pages as preserved SVG scenes, including embedded images. */
export async function importPdfPages(bytes,{signal}={}){
 if(!Buffer.isBuffer(bytes)||!bytes.length||bytes.length>20*1024*1024)throw Error('PDF 必须小于20MB。');
 if(signal?.aborted)throw Error('PDF 导入已取消。');
 const script=join(ROOT,'extract_material.py');
 const payload=JSON.stringify({mode:'pdf-pages',name:'source.pdf',data:bytes.toString('base64')});
 const raw=await new Promise((resolveRun,reject)=>{
  const child=spawn(process.env.PYTHON||'python',['-X','utf8',script],{windowsHide:true,stdio:['pipe','pipe','pipe']});let output='',errors='',done=false;
  const finish=error=>{if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);error?reject(error):resolveRun(output);};
  const abort=()=>{child.kill();finish(Error('PDF 导入已取消。'));};const timer=setTimeout(()=>{child.kill();finish(Error('PDF 解析超时。'));},120000);
  child.stdout.on('data',chunk=>{output+=chunk;if(output.length>64*1024*1024){child.kill();finish(Error('PDF 转换内容过大。'));}});child.stderr.on('data',chunk=>errors=(errors+chunk).slice(-5000));child.on('error',finish);child.on('close',code=>finish(code===0?null:Error(errors.trim()||'PDF 解析失败。')));signal?.addEventListener('abort',abort,{once:true});child.stdin.end(payload);if(signal?.aborted)abort();
 });
 const parsed=JSON.parse(raw);if(parsed.error)throw Error(parsed.error);if(!Array.isArray(parsed.pages)||!parsed.pages.length||parsed.pages.length>100)throw Error('原稿需包含 1 至 100 页。');
 const sources=parsed.pages.map((page,index)=>({id:randomUUID(),title:'',body:'',role:index?'content':'cover',svg:page.svg}));
 const result=await importSvgPages({pages:sources},{signal});
 for(const [index,page] of result.pages.entries()){
  bindPageCopyText(page,`第 ${index+1} 页`);page.role=inferRole(page.title,page.body,index);
 }
 return result;
}

/** Strict upstream OOXML conversion, then the same editable SVG bridge. */
export async function importPptxPages(bytes,{dataDir=join(ROOT,'data'),signal}={}){
 if(!Buffer.isBuffer(bytes)||!bytes.length||bytes.length>40*1024*1024)throw Error('PPTX 必须小于40MB。');
 const zip=await JSZip.loadAsync(bytes),entries=Object.values(zip.files);if(entries.length>20000||entries.reduce((n,e)=>n+(e._data?.uncompressedSize||0),0)>200*1024*1024)throw Error('PPTX 解压内容过大。');
 const skill=upstreamPackage('ppt-master');if(!skill.installed)throw Error('PPT Master运行包未安装。');
 const parent=join(resolve(dataDir),'native-import-jobs');await mkdir(parent,{recursive:true});const directory=await mkdtemp(join(parent,'job-'));
 try{
  const source=join(directory,'source.pptx'),output=join(directory,'converted');await writeFile(source,bytes);
  await runPython(join(skill.directory,'scripts/pptx_to_svg.py'),[source,'-o',output,'--embed-images','--inheritance-mode','flat','--strict'],{signal});
  const names=(await readdir(join(output,'svg'))).filter(n=>n.endsWith('.svg')).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  const sources=await Promise.all(names.map(async(name,index)=>({id:randomUUID(),title:'',body:'',role:index?'content':'cover',svg:await readFile(join(output,'svg',name),'utf8')})));
  for(const [index,p] of sources.entries())if(/data-pptx-fallback-kind=["']placeholder|data-pptx-replacement-status=["']unsupported-/i.test(p.svg))throw Error(`第${index+1}页含当前转换器无法完整还原的原生图表或表格。为避免丢失数据，已停止导入。请提供带原生数据标记的SVG，或先将该对象转为可编辑形状。`);
  const result=await importSvgPages({pages:sources},{signal});
  for(const [index,p] of result.pages.entries()){bindPageCopyText(p,'导入页面');p.role=inferRole(p.title,p.body,index);}
  return result;
 }finally{await rm(directory,{recursive:true,force:true});}
}
