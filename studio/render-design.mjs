import {applyManualLayoutIssues} from './manual-layout-policy.mjs';
import {vectorDataUrl} from './public/vector-scene.js';
import {chromium} from 'playwright-core';
import {existsSync} from 'node:fs';
import {readFile,realpath,stat} from 'node:fs/promises';
import {join,resolve,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('.',import.meta.url));
const aborted=signal=>{if(signal?.aborted)throw Error('设计检查已取消。');};

/** Only local app raster assets or bounded inline raster data; never fetch a user URL. */
export async function safeImageData(src,{dataDir=join(ROOT,'data'),publicDir=join(ROOT,'public')}={}){
  if(typeof src!=='string')throw Error('素材地址无效。');
  if(/^data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/.test(src)){
    if(src.length>12*1024*1024)throw Error('素材图片过大。');return src;
  }
  const template=/^\/assets\/templates\/(curated-[0-9]+)\/([0-9]+\.(?:jpg|png|webp))$/.exec(src);
  const upload=/^\/uploads\/([a-f\d-]+\.(?:png|jpg|gif|webp))$/i.exec(src);
  let base,path;
  if(template){base=resolve(publicDir,'assets','templates');path=join(base,template[1],template[2]);}
  else if(upload){base=resolve(dataDir,'uploads');path=join(base,upload[1]);}
  else throw Error('素材必须是本机已上传的图片或模板图片。');
  const [actualBase,actualPath]=await Promise.all([realpath(base),realpath(path)]);
  if(!actualPath.startsWith(actualBase+sep))throw Error('素材路径超出允许范围。');
  if((await stat(actualPath)).size>8*1024*1024)throw Error('素材图片过大。');
  const data=await readFile(actualPath),extension=actualPath.split('.').pop().toLowerCase();
  return `data:image/${extension==='jpg'?'jpeg':extension};base64,${data.toString('base64')}`;
}

export function auditSceneMetadata(project){
  const issues=[],geometries=new Map();
  for(const page of project.pages){
    const generated=(page.objects||[]).filter(o=>o.layoutManaged&&!o.custom);
    if(page.body&&generated.some(o=>o.sourceField==='body'||o.layoutField==='body')){
      const coverage=new Uint8Array(page.body.length);let mismatch=false;
      for(const object of generated){
        if(object.sourceField!=='body'&&object.layoutField!=='body')continue;
        const range=object.sourceRange;
        if(Array.isArray(range)&&range.length===2&&Number.isInteger(range[0])&&Number.isInteger(range[1])&&range[0]>=0&&range[1]<=page.body.length&&range[0]<=range[1]){
          coverage.fill(1,range[0],range[1]);if(String(object.text)!==page.body.slice(range[0],range[1]))mismatch=true;
        }
      }
      if(mismatch||page.body.split('').some((_,i)=>!coverage[i]&&!/[\s#]/.test(page.body[i])))issues.push({pageId:page.id,kind:'coverage',severity:'error',message:'排版正文与确认文案的来源区间不完整或不一致，请检查是否漏字。'});
    }
    for(const warning of page.layoutWarnings||[])issues.push({pageId:page.id,kind:'overflow',severity:'warning',message:String(warning).slice(0,500)});
    const plan=page.designPlan;
    const boxes=plan?[plan.titleBox,...plan.zones]:generated.filter(o=>o.type==='text').map(o=>({x:o.x,y:o.y,w:o.w,h:o.h}));
    if(boxes.length>1){
      const signature=JSON.stringify(boxes.map(b=>[b.x,b.y,b.w,b.h].map(n=>Math.round(Number(n)/24))));
      if(geometries.has(signature))issues.push({pageId:page.id,kind:'repetition',severity:'warning',message:`文字区域几何结构与第 ${geometries.get(signature)} 页近似；应依据内容关系改变构图，而非只换文字。`});
      else geometries.set(signature,project.pages.indexOf(page)+1);
    }
  }
  return issues;
}

/** Actual canvas screenshots with the editor's object styling; browser network is disabled. */
export async function renderDesignEvidence(project,{directory,dataDir=join(ROOT,'data'),publicDir=join(ROOT,'public'),signal,includeScenes=true}={}){
  aborted(signal);const issues=[],cache=new Map();
  const image=async src=>{if(!cache.has(src))cache.set(src,safeImageData(src,{dataDir,publicDir}));return cache.get(src);};
  const themes=JSON.parse(await readFile(join(publicDir,'templates.json'),'utf8')),theme=themes.find(t=>t.id===(project.themeId||'curated-139'));if(!theme)throw Error('参考模板不存在。');const references=[];for(const [i,src] of (theme.previews||[theme.cover]).entries())references.push({label:`参考 ${i}`,src:await image(src)});
  const executablePath=process.env.WEPPT_BROWSER_PATH||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe','/usr/bin/chromium','/usr/bin/google-chrome'].find(existsSync);
  let browser;
  try{browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});}catch{throw Error('无法启动页面审看浏览器，请检查 Edge 或 Chromium 安装。');}
  const cancel=()=>{browser.close().catch(()=>{});};signal?.addEventListener('abort',cancel,{once:true});
  try{
    const context=await browser.newContext({viewport:{width:1280,height:720},deviceScaleFactor:1});
    await context.route('**/*',route=>route.abort());const tab=await context.newPage();
    const reset=()=>tab.setContent('<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'"><style>*{box-sizing:border-box}html,body{margin:0;padding:0;background:#fff;font-family:Microsoft YaHei,Arial,sans-serif}.scene{position:relative;width:1280px;height:720px;overflow:hidden}.object{position:absolute;transform-origin:center}.object-image{overflow:hidden}.object-image img{position:absolute;left:0;top:0;width:100%;height:100%}.text{width:100%;height:100%;white-space:pre-wrap;overflow-wrap:anywhere;padding:0;margin:0}</style><main></main>');
    async function sheet(items,path,columns=2,width=640){
      aborted(signal);await tab.setViewportSize({width:columns*width,height:Math.ceil(items.length/columns)*(width*9/16+32)});await reset();
      await tab.evaluate(({items,columns,width})=>{const host=document.querySelector('main');Object.assign(host.style,{display:'grid',gridTemplateColumns:`repeat(${columns},${width}px)`});for(const item of items){const cell=document.createElement('div'),label=document.createElement('div'),img=document.createElement('img');label.textContent=item.label;Object.assign(label.style,{height:'32px',fontSize:'16px',padding:'5px 10px',background:'#f1f1f1',color:'#111'});img.src=item.src;Object.assign(img.style,{display:'block',width:width+'px',height:width*9/16+'px',objectFit:'contain',background:'#fff'});cell.append(label,img);host.append(cell);}}, {items,columns,width});
      await tab.evaluate(()=>Promise.all([...document.images].map(img=>img.decode())));await tab.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await tab.screenshot({path,fullPage:true});
    }
    const referenceImage=join(directory,'references.png');await sheet(references,referenceImage,4,640);
    const sceneItems=[],manifest=[];
    if(includeScenes)for(const [index,original] of project.pages.entries()){
      aborted(signal);const page=structuredClone(original);
      for(const object of page.objects||[]){if(object.type==='vector')object._vectorSrc=vectorDataUrl(object);if(object.type==='image'){try{object.src=await image(object.src);}catch{object.src='';issues.push({pageId:page.id,kind:'asset',severity:'error',message:'有图片无法安全读取，审看中未显示；请重新上传该素材。'});}}}
      await tab.setViewportSize({width:1280,height:720});await reset();
      await tab.evaluate(page=>{
        const n=(v,d=0)=>Number.isFinite(Number(v))?Number(v):d,c=(v,d='transparent')=>/^(?:#[a-f\d]{3,8}|transparent)$/i.test(v||'')?v:d;
        const scene=document.createElement('div');scene.className='scene';scene.style.background=c(page.background,'#fff');document.querySelector('main').append(scene);
        for(const object of page.objects||[]){const node=document.createElement('div');node.className=`object object-${object.type}`;node.dataset.objectId=object.id;node.dataset.type=object.type;
          Object.assign(node.style,{left:n(object.x)+'px',top:n(object.y)+'px',width:Math.max(0,n(object.w))+'px',height:Math.max(0,n(object.h))+'px',transform:`rotate(${n(object.rotation)}deg)`,opacity:String(Math.max(0,Math.min(1,n(object.opacity,1)))),background:['rect','ellipse'].includes(object.type)?c(object.fill):'',borderRadius:object.type==='ellipse'?'50%':n(object.radius)+'px',border:object.type==='line'?'none':object.strokeWidth?`${n(object.strokeWidth)}px solid ${c(object.stroke,'#333')}`:'none'});
          if(object.shadow){const s=object.shadow,hex=/^#[a-f\d]{6}$/i.test(s.color||'')?s.color:'#000000',rgb=hex.slice(1).match(/../g).map(x=>parseInt(x,16)).join(',');node.style.boxShadow=`${n(s.offsetX)}px ${n(s.offsetY,8)}px ${n(s.blur,20)}px rgba(${rgb},${Math.max(0,Math.min(1,n(s.opacity,.18)))})`;}
          if(object.type==='line'){node.style.background=c(object.stroke||object.fill,'#333');node.style.height=Math.max(n(object.strokeWidth)||n(object.h),1)+'px';}
          if(object.type==='text'){const text=document.createElement('div');text.className='text';text.textContent=String(object.text??'');Object.assign(text.style,{fontFamily:String(object.fontFamily||'Microsoft YaHei'),fontSize:n(object.fontSize,24)+'px',fontWeight:object.bold?'700':'400',fontStyle:object.italic?'italic':'normal',color:c(object.color,'#222'),textAlign:['left','center','right','justify'].includes(object.align)?object.align:'left',lineHeight:String(n(object.lineHeight,1.3))});node.append(text);}
          if(object.type==='vector'){const img=document.createElement('img');img.src=object._vectorSrc;Object.assign(img.style,{display:'block',width:'100%',height:'100%'});node.append(img);}if(object.type==='image'&&object.src){const img=document.createElement('img');img.src=object.src;img.style.objectFit=object.fit==='cover'?'cover':'contain';if(object.crop){const crop=object.crop,w=Math.max(.01,n(crop.w,1)),h=Math.max(.01,n(crop.h,1));Object.assign(img.style,{width:100/w+'%',height:100/h+'%',left:-n(crop.x)/w*100+'%',top:-n(crop.y)/h*100+'%',objectFit:'fill'});}node.append(img);}
          scene.append(node);
        }
      },page);
      await tab.evaluate(()=>Promise.all([...document.images].map(img=>img.decode().catch(()=>{}))));
      const found=await tab.evaluate(()=>{
        const issues=[],scene=document.querySelector('.scene'),base=scene.getBoundingClientRect(),texts=[];
        for(const node of scene.children){const r=node.getBoundingClientRect();if(Number(getComputedStyle(node).opacity)===0)continue;
          if(r.left<base.left-1||r.top<base.top-1||r.right>base.right+1||r.bottom>base.bottom+1)issues.push({kind:'bounds',severity:'error',message:`对象 ${node.dataset.objectId} 超出画布。`});
          const text=node.querySelector('.text');if(text){if(text.scrollHeight>text.clientHeight+2||text.scrollWidth>text.clientWidth+2)issues.push({kind:'overflow',severity:'error',message:`文字对象 ${node.dataset.objectId} 的实际文字超出文本框。`});texts.push({id:node.dataset.objectId,r});}
          if(['image','vector'].includes(node.dataset.type)){const img=node.querySelector('img');if(img&&(!img.complete||!img.naturalWidth))issues.push({kind:'asset',severity:'error',message:`图片对象 ${node.dataset.objectId} 未能显示。`});}
        }
        for(let i=0;i<texts.length;i++)for(let j=i+1;j<texts.length;j++){const a=texts[i],b=texts[j],w=Math.max(0,Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left)),h=Math.max(0,Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top));if(w*h>Math.min(a.r.width*a.r.height,b.r.width*b.r.height)*.06&&w>3&&h>3)issues.push({kind:'overlap',severity:'error',overlapRatio:w*h/Math.min(a.r.width*a.r.height,b.r.width*b.r.height),message:`文字对象 ${a.id} 与 ${b.id} 的文本框重叠。`});}
        return issues.slice(0,60);
      });
      issues.push(...found.map(issue=>({pageId:page.id,...issue})));
      await tab.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const bytes=await tab.screenshot({path:join(directory,`page-${index+1}.png`)});
      sceneItems.push({label:`第 ${index+1} 页 · ${page.id}`,src:`data:image/png;base64,${bytes.toString('base64')}`});manifest.push({number:index+1,pageId:page.id,title:page.title});
    }
    const sheetImages=[];for(let index=0;index<sceneItems.length;index+=8){const path=join(directory,`deck-${index/8+1}.png`);await sheet(sceneItems.slice(index,index+8),path);sheetImages.push(path);}
    aborted(signal);return {referenceImage,sheetImages,issues:applyManualLayoutIssues([...issues,...(includeScenes?auditSceneMetadata(project):[])]),manifest};
  }finally{signal?.removeEventListener('abort',cancel);await browser.close().catch(()=>{});}
}
