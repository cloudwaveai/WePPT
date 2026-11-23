import {assertTemplateInheritance} from './editor-contract.js';
const W=1280,H=720;
const clone=value=>structuredClone(value);
const uid=()=>crypto.randomUUID();
const finite=o=>[o.x,o.y,o.w,o.h].every(Number.isFinite)&&o.w>0&&o.h>0;
const managed=o=>o.layoutManaged&&!o.custom;
const fullBackground=o=>o.x<=2&&o.y<=2&&o.x+o.w>=W-2&&o.y+o.h>=H-2;
function decoration(o,themeId){
 if(!managed(o)||!finite(o)||o.nativeType||o.nativeData||o.sourceField||o.layoutField||o.sourceRange)return false;
 if(o.type==='text')return false;
 const edge=o.x<=32||o.y<=32||o.x+o.w>=W-32||o.y+o.h>=H-32;
 if(!edge&&!fullBackground(o))return false;
 if(o.type==='image')return !!o.crop&&typeof o.src==='string'&&o.src.startsWith(`/assets/templates/${themeId}/`);
 if(o.type==='vector')return typeof o.svg==='string'&&!/<(?:text|tspan|image)\b/i.test(o.svg);
 return ['rect','ellipse','line'].includes(o.type)&&(fullBackground(o)||o.decorative||o.contentRole==='decoration');
}
function candidates(project){
 return (project.pages||[]).filter(p=>p.engine==='ppt-master-svg'&&!p.designPending&&(!p.themeId||p.themeId===project.themeId)&&(p.objects||[]).some(o=>o.type==='text'&&o.sourceField==='title'));
}
export function canInheritPage(project){return candidates(project).length>0;}
/** An immediate editable shell using the deck's actual designed visual assets.
 * This is intentionally not an AI page design; richer new copy can be designed later.
 */
export function createInheritedPage(project,page,{anchorPageId,excludeReferencePageId}={}){
 const all=candidates(project),others=all.filter(p=>p.id!==excludeReferencePageId),choices=others.length?others:all;if(!choices.length)return null;
 const score=p=>(['content','flow','data'].includes(p.role)?30:0)+(p.role===page.role?10:0)+(p.id===anchorPageId?3:0)+Math.min(5,(p.objects||[]).filter(o=>decoration(o,project.themeId)).length);
 const reference=choices.toSorted((a,b)=>score(b)-score(a))[0];
 const titleStyle=reference.objects.find(o=>o.type==='text'&&o.sourceField==='title');
 const bodyChoices=choices.flatMap(p=>(p.objects||[]).filter(o=>o.type==='text'&&o.sourceField==='body'&&o.fontSize>=24&&o.fontSize<=36));
 const bodyStyle=bodyChoices.toSorted((a,b)=>String(b.text||'').length-String(a.text||'').length)[0]||titleStyle;
 const decorations=reference.objects.filter(o=>decoration(o,project.themeId)).map(o=>({...clone(o),id:uid()}));
 const preserved=(page.objects||[]).filter(o=>o.custom||!o.layoutManaged).map(clone);
 const next=clone(page);
 for(const key of ['designPlan','designSource','designSourceGroups','designSnapshot','designReview','designReason','designPending','designManual','continuationOf','continuationIndex','continuationCount','layoutWarnings'])delete next[key];
 const fontSize=Math.max(36,Math.min(64,Number(titleStyle.fontSize)||44));
 const x=Math.max(64,Math.min(112,Number(titleStyle.x)||80)),y=Math.max(40,Math.min(90,Number(titleStyle.y)||64));
 const rightLimit=(top,bottom)=>Math.min(W-72,...decorations.filter(o=>!fullBackground(o)&&o.x>W*.6&&o.y<bottom&&o.y+o.h>top).map(o=>o.x-24));
 const titleWidth=Math.max(500,rightLimit(y,y+100)-x);
 const textWeight=Array.from(String(page.title||'')).reduce((n,c)=>n+(/[^\x00-\xff]/.test(c)?1:.55),0);
 const titleHeight=Math.max(fontSize*1.3,Math.min(180,Math.ceil(textWeight*fontSize/titleWidth)*fontSize*1.3));
 const bodyY=Math.max(190,y+titleHeight+38),bodyWidth=Math.max(480,rightLimit(bodyY,600)-x);
 const bottom=Math.min(H-64,...decorations.filter(o=>!fullBackground(o)&&o.y>=bodyY+100&&o.x<x+bodyWidth&&o.x+o.w>x&&o.w>W*.4).map(o=>o.y-24));
 const common={type:'text',rotation:0,opacity:1,layoutManaged:true,custom:false,align:'left',italic:false};
 const title={...common,id:uid(),text:page.title||'',sourceText:page.title||'',sourceField:'title',layoutField:'title',x,y,w:titleWidth,h:titleHeight,fontSize,fontFamily:titleStyle.fontFamily||'Microsoft YaHei',color:titleStyle.color||'#292d25',bold:!!titleStyle.bold,lineHeight:1.3};
 const body={...common,id:uid(),text:page.body||'',sourceText:page.body||'',sourceField:'body',layoutField:'body',sourceRange:[0,String(page.body||'').length],x,y:bodyY,w:bodyWidth,h:Math.max(180,bottom-bodyY),fontSize:Math.max(24,Math.min(32,Number(bodyStyle.fontSize)||28)),fontFamily:bodyStyle.fontFamily||title.fontFamily,color:bodyStyle.color||title.color,bold:false,lineHeight:1.45};
 Object.assign(next,{id:page.id||uid(),themeId:project.themeId,engine:'ppt-master-svg',background:reference.background||'#ffffff',variant:0,objects:[...decorations,title,body,...preserved],layoutSource:{title:page.title||'',body:page.body||''},inheritedTheme:{themeId:project.themeId,referencePageId:reference.id}});
 return next;
}

export function createConstrainedPage(project,page,options){const result=createInheritedPage(project,page,options);assertTemplateInheritance(project,result);return result;}

// Conservative capacity check before skipping content-driven design. Explicit
// line breaks count, so a short but tall list cannot overflow the quick shell.
export function inheritedCopyFits(page){
 return (page.objects||[]).filter(o=>o.type==='text'&&['title','body'].includes(o.sourceField)).every(o=>{
  const width=Math.max(1,o.w-8),size=o.fontSize||28;
  const lines=String(o.text||'').split('\n').reduce((n,line)=>n+Math.max(1,Math.ceil(Array.from(line).reduce((sum,c)=>sum+(/[^\x00-\xff]/.test(c)?1:.7),0)*size/width)),0);
  return lines*size*(o.lineHeight||1.45)<=o.h+.1;
 });
}
