import {readFile,writeFile,copyFile,mkdir,mkdtemp,rm} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {chromium} from 'playwright-core';
import JSZip from 'jszip';
import {runStructuredAI} from './ai.mjs';
import {importPptxPages} from './svg-engine.mjs';
import {buildSkillContext} from './skill-runtime.mjs';
const root=fileURLToPath(new URL('./',import.meta.url));
const compact=s=>String(s||'').replace(/[\s#]/gu,'');
const inventory=s=>[...compact(s)].sort().join('');
function exactCopy(text,source){const normalized=compact(text);return inventory(text)===inventory(source.title+source.body)&&[source.title,...source.body.split(/\r?\n/)].filter(s=>compact(s)).every(s=>normalized.includes(compact(s)));}
const baseline='*{box-sizing:border-box}html,body{margin:0;width:1280px;height:720px;overflow:hidden;font-family:"Microsoft YaHei",sans-serif}p,h1,h2,h3,h4,h5,h6{margin:0}';
export function validateHtmlEngineInput(input){
 if(!['slidev','pptagent'].includes(input?.engine))throw Error('不支持的 HTML 设计引擎。');
 if(!Array.isArray(input.project?.pages)||input.project.pages.length>100||input.targetPageIds?.length!==1)throw Error('HTML 设计引擎每次只处理一页。');
 const page=input.project.pages.find(p=>p.id===input.targetPageIds[0]);
 if(!page||typeof page.title!=='string'||typeof page.body!=='string'||page.title.length>1000||page.body.length>12000||String(input.instruction||'').length>6000)throw Error('页面内容不完整或过长。');
 return page;
}
export async function validateEngineHtml(html,source,{signal}={}){
 if(typeof html!=='string'||html.length>120000||/\{\{|\}\}|url\s*\(|expression\s*\(|@import|@font-face|(?:javascript|data|file|https?):|\/\//i.test(html))throw Error('设计 HTML 包含外部资源或可执行内容。');
 signal?.throwIfAborted();const browser=await chromium.launch({executablePath:process.env.WEPPT_BROWSER_PATH||(process.platform==='win32'?'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe':'/usr/bin/chromium'),headless:true});
 const abort=()=>void browser.close();signal?.addEventListener('abort',abort,{once:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:720}});await page.route('**/*',r=>r.abort());
  const clean=await page.evaluate(({html,baseline})=>{
   const doc=new DOMParser().parseFromString(html,'text/html');const tags=new Set(['HTML','HEAD','BODY','META','STYLE','DIV','P','H1','H2','H3','H4','H5','H6','SPAN','BR','B','STRONG','EM','I']);
   for(const e of doc.querySelectorAll('*')){if(!tags.has(e.tagName))throw Error('Unsupported HTML tag: '+e.tagName);for(const a of e.attributes)if(!['id','class','style','charset','lang'].includes(a.name))throw Error('Unsupported HTML attribute: '+a.name);}
   const styles=baseline+'\n'+[...doc.querySelectorAll('style')].map(e=>e.textContent).join('\n');doc.querySelectorAll('style,meta').forEach(e=>e.remove());
   // Preserve body styling in a real root element; Slidev owns its outer body.
   const frame=doc.createElement('div');frame.id='engine-page';frame.style.cssText='position:relative;width:1280px;height:720px;overflow:hidden;'+doc.body.style.cssText;frame.innerHTML=doc.body.innerHTML;return {styles,body:frame.outerHTML};
  },{html,baseline});
  const canonical=`<!doctype html><html><head><meta charset="utf-8"><style>${clean.styles}</style></head><body>${clean.body}</body></html>`;
  await page.setContent(canonical);await page.evaluate(()=>document.fonts.ready);
  await page.evaluate(()=>{for(const e of document.body.querySelectorAll('*')){const s=getComputedStyle(e);for(const [property,allowed] of [['transform','none'],['clipPath','none'],['filter','none'],['backdropFilter','none'],['backgroundImage','none'],['mixBlendMode','normal']])if(s[property]&&s[property]!==allowed)throw Error('Unsupported editable CSS: '+property);for(const pseudo of ['::before','::after']){const content=getComputedStyle(e,pseudo).content;if(content&&content!=='none'&&content!=='normal'&&content!=='""')throw Error('Pseudo-element content cannot be edited');}}});
  const measured=await page.evaluate(()=>{const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;const text=[];while(n=walker.nextNode()){if(!n.textContent.trim())continue;const el=n.parentElement,style=getComputedStyle(el),r=document.createRange();r.selectNodeContents(n);const b=r.getBoundingClientRect();let hidden=false;for(let p=el;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<0.1)hidden=true;}if(hidden||!b.width||!b.height||b.x<-.5||b.y<-.5||b.right>1280.5||b.bottom>720.5||parseFloat(style.fontSize)<18)throw Error('Text hidden, too small or outside slide: '+n.textContent);text.push(n.textContent);}return text;});
  if(!exactCopy(measured.join(''),source))throw Error('设计改变或遗漏了确认文案，已保留原页面。');
  return {...clean,html:canonical};
 }finally{signal?.removeEventListener('abort',abort);await browser.close();}
}
async function runWorker(input,signal){return new Promise((yes,no)=>{
 const child=spawn(process.execPath,[join(root,'scripts/engine-runtime-worker.mjs')],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});let out='',err='',done=false;
 const kill=()=>{if(child.pid)spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});};
 const finish=(error,value)=>{if(done)return;done=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);error?no(error):yes(value);};
 const abort=()=>{kill();finish(Error('设计转换已取消或超时，原页面保持不变。'));};const timer=setTimeout(abort,60000);signal?.addEventListener('abort',abort,{once:true});
 child.stdout.on('data',b=>{out+=b;if(out.length>1000000)abort();});child.stderr.on('data',b=>err=(err+b).slice(-6000));child.on('error',e=>finish(e));child.on('close',code=>{if(code)return finish(Error(err||'设计转换失败。'));try{finish(null,JSON.parse(out));}catch{finish(Error('转换器返回无效结果。'));}});child.stdin.end(JSON.stringify(input));if(signal?.aborted)abort();
});}
export async function requireNativeText(bytes){const zip=await JSZip.loadAsync(bytes),names=Object.keys(zip.files).filter(n=>/^ppt\/slides\/slide\d+\.xml$/.test(n));if(names.length!==1)throw Error('转换器页数不正确。');const xml=await zip.file(names[0]).async('string');if(!/<a:t[ >]/.test(xml)||/<p:pic[ />]|<a:blip[ />]/.test(xml))throw Error('转换器返回图片化页面，不能作为可编辑设计。');}
function bindSource(imported,source,engine){
 const indexed=[];for(let i=0;i<source.body.length;i++)if(!/[\s#]/u.test(source.body[i]))indexed.push(i);const hay=compact(source.body),used=[];
 const objects=imported.objects.map(object=>{const o={...object,layoutManaged:true};for(const k of ['sourceField','layoutField','sourceText','sourceRange'])delete o[k];if(o.type==='text'){
  const needle=compact(o.text);if(needle===compact(source.title)){o.sourceField=o.layoutField='title';o.text=o.sourceText=source.title;}
  else if(needle){let at=hay.indexOf(needle);while(at>=0&&used.some(([a,b])=>at<b&&at+needle.length>a))at=hay.indexOf(needle,at+1);if(at>=0){used.push([at,at+needle.length]);o.sourceField=o.layoutField='body';o.sourceRange=[indexed[at],indexed[at+needle.length-1]+1];o.text=o.sourceText=source.body.slice(...o.sourceRange);}}
 }return o;});
 if(!objects.some(o=>o.type==='text'&&o.sourceField==='title'))throw Error('引擎将标题拆成了不兼容的文本块，未覆盖原页面；请缩短标题或重新设计。');
 if(objects.some(o=>o.type==='text'&&!o.sourceField))throw Error('部分文字无法映射回确认文案，未覆盖原页面。');
 return {...source,...imported,id:source.id,title:source.title,body:source.body,role:source.role,objects:[...objects,...structuredClone((source.objects||[]).filter(o=>o.custom))],layoutSource:{title:source.title,body:source.body},designEngine:engine,designEngineStatus:'editable-draft'};
}
export async function generateHtmlEngineDesign(input,{dataDir=join(root,'data'),signal,onProgress=()=>{},artifactDir}={}){
 const source=validateHtmlEngineInput(input),started=Date.now(),deadline=AbortSignal.timeout(150000),combined=signal?AbortSignal.any([signal,deadline]):deadline;
 const jobs=join(dataDir,'engine-design-jobs');await mkdir(jobs,{recursive:true});const outputDir=await mkdtemp(join(jobs,'html-'));
 try{
  const catalog=JSON.parse(await readFile(join(root,'public/templates.json'),'utf8'));const templates=Array.isArray(catalog)?catalog:catalog.templates||[];const theme=templates.find(t=>t.id===(input.themeId||input.project.themeId));
  if(!theme)throw Error('所选模板不存在，请重新选择模板。');
  const images=[theme.cover,...(theme.previews||[])].filter(p=>typeof p==='string'&&/^\/assets\/templates\/[\w/-]+\.(?:png|jpg|jpeg|webp)$/i.test(p)).map(p=>join(root,'public',p)).filter(existsSync).slice(0,4);
  const skills=buildSkillContext({mode:'plan',project:input.project,message:input.instruction||'',scope:'page'});
  const prompt=`设计一张1280×720可编辑PPT页面。使用用户已确认文案和所选模板，参考附图的配色、空间层次、排版与材质，针对本页语义独立设计。不可机械复制所有页布局。\n${skills.instructions}\n模板：${JSON.stringify({id:theme.id,name:theme.name,palette:theme.palette})}\n全稿目录：${JSON.stringify(input.project.pages.map(p=>({role:p.role,title:p.title})))}\n本页确认文案（必须逐字保留，允许移除Markdown的#及空白，不可增添装饰文字或数字）：${JSON.stringify({title:source.title,body:source.body,role:source.role})}\n用户要求：${input.instruction||''}\n输出完整静态HTML。只用html/head/body/meta/style/div/p/h1-h6/span/br/b/strong/em/i；属性只用id/class/style/charset/lang。绝对禁止脚本、事件、Vue语法、外链、图片、SVG、canvas、url()、渐变、滤镜、box-shadow。body必须width:1280px;height:720px;margin:0。每个文本块独立p或h标签，不能直接把文本写在div中。图形使用空div，阴影使用偏移的半透明矩形。文本24px起，标题38px起，所有文本在页面范围内可见。可用绝对定位，font-family:Microsoft YaHei。CSS使用class，禁止body选择器（外层由引擎管理）；禁止transform、clip-path、mix-blend-mode、background-image和伪元素。标题必须一个独立p元素，同一字号样式，不嵌套span、不用br，尽量单行；每个文本框宽度预留25%余量、不能紧贴文字估算宽度，正文每段独立p元素。内容复杂时可以压缩留白但不能删减事实。仅返回html和简短reason。`;
  onProgress({stage:'model',message:'正在参考模板设计当前页'});const modelStart=Date.now();const result=await runStructuredAI({prompt,images,effort:'medium',action:'html-engine-design',schema:{type:'object',properties:{html:{type:'string'},reason:{type:'string'}},required:['html','reason'],additionalProperties:false}},{dataDir,signal:AbortSignal.any([combined,AbortSignal.timeout(90000)]),onProgress});const modelMs=Date.now()-modelStart;
  if(artifactDir){await mkdir(artifactDir,{recursive:true});await writeFile(join(artifactDir,'model.html'),result.html);}const clean=await validateEngineHtml(result.html,source,{signal:combined});const conversionStart=Date.now();const converted=await runWorker({engine:input.engine,...clean,outputDir},combined);const bytes=await readFile(converted.pptxPath);if(artifactDir){await writeFile(join(artifactDir,'engine.pptx'),bytes);await writeFile(join(artifactDir,'source.html'),clean.html);}await requireNativeText(bytes);const convertMs=Date.now()-conversionStart;
  const importStart=Date.now(),imported=await importPptxPages(bytes,{dataDir,signal:combined});if(imported.pages.length!==1)throw Error('导入页数不正确。');const page=imported.pages[0];if(!exactCopy(page.objects.filter(o=>o.type==='text').map(o=>o.text).join(''),source))throw Error('导入时文案发生变化，已保留原页面。');
  return {pages:[bindSource(page,source,input.engine)],engine:input.engine,reviewStatus:'unreviewed',finalized:false,metrics:{modelMs,convertMs,importMs:Date.now()-importStart,totalMs:Date.now()-started},skills:{ids:skills.ids,version:skills.version,upstream:skills.upstream},reason:result.reason,message:'已生成原生可编辑草稿，尚未完成视觉审看与导出一致性验收。'};
 }finally{await rm(outputDir,{recursive:true,force:true});}
}

