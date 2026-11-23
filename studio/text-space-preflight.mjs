import {chromium} from 'playwright-core';
import {createHash} from 'node:crypto';

// Also exercised through CDP. Only DOM text is measured; never interpret source as HTML.
export async function measureTextSpaceInPage({title,body,zones}){
 await document.fonts.ready;
 const families=['Noto Serif CJK SC, SimSun, serif','Microsoft YaHei, Noto Sans CJK SC, sans-serif'];
 await Promise.all(families.map(f=>document.fonts.load('28px '+f)));
 const box=document.createElement('div');
 Object.assign(box.style,{all:'initial',display:'block',position:'fixed',left:'-10000px',top:'0',visibility:'hidden',whiteSpace:'pre-wrap',overflowWrap:'anywhere',wordBreak:'normal',lineHeight:'1.3',padding:'0',margin:'0',border:'0',boxSizing:'content-box'});
 document.body.append(box);
 const height=(text,width,size,bold)=>{
  box.textContent=text;box.style.width=width+'px';box.style.fontSize=size+'px';box.style.fontWeight=bold?'700':'400';
  return Math.ceil(Math.max(...families.map(f=>{box.style.fontFamily=f;return box.getBoundingClientRect().height;})));
 };
 try{return {version:1,canvas:{w:1280,h:720},minimumFontSize:18,regions:zones.map((z,index)=>({zone:index,x:Math.round(z.x*1280),y:Math.round(z.y*720),w:Math.floor(z.w*1280),h:Math.floor(z.h*720),titleAt48:height(title,z.w*1280,48,true),bodyAt28:height(body,z.w*1280,28,false),bodyAt18:height(body,z.w*1280,18,false)})),note:'Heights describe the ENTIRE title/body in each region, not independent per-region content. Distribute intact paragraph groups across regions. Measurements guide allocation; they are not final layout approval.'};}
 finally{box.remove();}
}

const cache=new Map();
export async function measureCompositionText(source,plan,{signal}={}){
 signal?.throwIfAborted();
 const zones=plan?.zones;
 if(!Array.isArray(zones)||!zones.length||zones.length>16||zones.some(z=>typeof z.purpose!=='string'||![z.x,z.y,z.w,z.h].every(Number.isFinite)||z.x<0||z.y<0||z.w<=0||z.h<=0||z.x+z.w>1.001||z.y+z.h>1.001))throw Error('文字空间预检需要有效的页面规划区域。');
 const payload={title:source.title,body:source.body.replace(/^##[ \t]+/gm,''),zones:zones.map(({purpose,x,y,w,h})=>({purpose,x,y,w,h}))};
 const key=createHash('sha256').update(JSON.stringify(payload)).digest('hex');
 if(cache.has(key))return structuredClone(cache.get(key));
 const browser=await chromium.launch({headless:true,executablePath:process.env.WEPPT_BROWSER_PATH||(process.platform==='win32'?'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe':'/usr/bin/chromium')});
 const abort=()=>{void browser.close().catch(()=>{});};signal?.addEventListener('abort',abort,{once:true});
 try{
  signal?.throwIfAborted();const page=await browser.newPage();await page.setContent('<!doctype html><html><body></body></html>');
  const result=await page.evaluate(measureTextSpaceInPage,payload);signal?.throwIfAborted();
  if(cache.size>=128)cache.delete(cache.keys().next().value);cache.set(key,result);return structuredClone(result);
 }finally{signal?.removeEventListener('abort',abort);await browser.close();}
}
