import {readFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright-core';
import {createLibraryObject} from './public/library-assets.js';
const ROOT=fileURLToPath(new URL('.',import.meta.url));
export async function loadAssetLibrary(){
 const catalog=JSON.parse(await readFile(join(ROOT,'public/assets/library/catalog.json'),'utf8'));
 if(catalog.version!==1||!Array.isArray(catalog.items))throw Error('本地素材库目录无效。');
 return catalog;
}
export function selectLibraryCandidates(catalog,theme,pages,limit=20){
 const text=[theme.name,theme.description,theme.adaptation,...pages.map(p=>p.title+' '+p.body)].join(' ');
 const words=[];
 for(const [pattern,terms] of [[/合同|文档|文件/,'file document contract'],[/财务|发票|付款|收款/,'receipt cash coin'],[/招聘|团队|责任|人力/,'users user briefcase'],[/流程|步骤|验收/,'check arrow list'],[/植物|自然|生态/,'leaf plant flower'],[/建筑|几何|折面/,'triangle cube square polygon'],[/品牌|渐变|金属/,'star abstract ellipse']])if(pattern.test(text))words.push(...terms.split(' '));
 const score=a=>words.reduce((n,w)=>n+([a.name,...a.tags].join(' ').toLowerCase().includes(w)?1:0),0);
 const result=[];let salt=[...theme.id].reduce((n,c)=>n+c.charCodeAt(0),0);
 for(const lib of ['geometry','coolshapes','geopattern','blobshape','tabler']){
  const items=catalog.items.filter(a=>a.library===lib).sort((a,b)=>score(b)-score(a)||a.id.localeCompare(b.id));
  const relevant=items.filter(a=>score(a)>0);const pool=relevant.length?relevant:items;
  for(let i=0;i<Math.min(5,pool.length);i++)result.push(pool[(relevant.length?i:(salt+i)%pool.length)]);
 }
 return result.slice(0,limit);
}
export async function readLibrarySvg(item){
 if(!/^\/assets\/library\/[\w/-]+\.svg$/.test(item.src))throw Error('素材路径无效。');
 return readFile(resolve(ROOT,'public',item.src.slice(1)),'utf8');
}
export const libraryPlacementSchema={type:'array',maxItems:6,items:{type:'object',additionalProperties:false,required:['id','x','y','w','h','color'],properties:{id:{type:'string'},x:{type:'number'},y:{type:'number'},w:{type:'number'},h:{type:'number'},color:{type:'string'}}}};
export async function materializeLibraryPlacements(placements,candidates){
 if(!Array.isArray(placements)||placements.length>6)throw Error('素材库使用数量无效。');
 return Promise.all(placements.map(async p=>{
  const item=candidates.find(a=>a.id===p.id);if(!item)throw Error('设计使用了候选列表外的素材。');
  if(p.color!==''&&!/^#[a-f\d]{6}$/i.test(p.color))throw Error('素材颜色格式无效。');
  return createLibraryObject(item,await readLibrarySvg(item),{x:p.x,y:p.y,w:p.w,h:p.h,color:p.color||undefined,custom:false});
 }));
}
export async function renderLibraryCandidates(items,file,{signal}={}){
 signal?.throwIfAborted();
 const content=await Promise.all(items.map(async item=>({id:item.id,src:'data:image/svg+xml;base64,'+Buffer.from(await readLibrarySvg(item)).toString('base64')})));
 const executablePath=process.env.WEPPT_BROWSER_PATH||['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
 const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
 const cancel=()=>browser.close().catch(()=>{});signal?.addEventListener('abort',cancel,{once:true});
 try{
  const tab=await browser.newPage({viewport:{width:1200,height:Math.ceil(items.length/5)*190}});await tab.route('**/*',route=>route.abort());
  await tab.setContent('<html><head><style>body{margin:0;padding:12px;background:#eee;display:grid;grid-template-columns:repeat(5,1fr);gap:12px;font:12px Arial}article{height:174px;background:#fff;text-align:center;overflow:hidden}img{display:block;margin:8px auto;width:160px;height:130px;object-fit:contain}span{display:block;overflow-wrap:anywhere}</style></head><body></body></html>');
  await tab.evaluate(content=>{for(const item of content){const article=document.createElement('article'),img=document.createElement('img'),label=document.createElement('span');img.src=item.src;label.textContent=item.id;article.append(img,label);document.body.append(article);}},content);
  await tab.evaluate(()=>Promise.all([...document.images].map(img=>img.decode())));signal?.throwIfAborted();await tab.screenshot({path:file,fullPage:true});return file;
 }finally{signal?.removeEventListener('abort',cancel);await browser.close();}
}
