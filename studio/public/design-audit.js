// Read-only scene checks. Never changes pages, objects, plans or source text.
const W=1280,H=720;
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
export const snapshotPage=page=>JSON.stringify({title:page.title,body:page.body,objects:page.objects,background:page.background});
const duplicateChapterMarker=(p,o)=>{
 if(o.type!=='text'||!o.layoutManaged||o.custom||o.sourceField||o.layoutField||o.sourceRange)return false;
 const number=String(o.text||'').trim();if(!/^(?:0?[1-9]\d?)$/.test(number))return false;
 // Preserve numbered titles/captions; remove only the additional unbound numeral.
 return (p.objects||[]).some(t=>{
  if(t===o||t.type!=='text')return false;
  const text=String(t.text||'').trim();if(text.length>100||text.includes('\n'))return false;
  const heading=/^(0?[1-9]\d?)[\s.、．]+(.+)$/.exec(text);
  return heading?.[1]===number;
 });
};
const substantive=o=>o.type==='text'&&String(o.text||'').trim()&&!o.decorative&&!['control','decoration'].includes(o.contentRole);
function bounds(o){const {x,y,w,h}=o,angle=(Number(o.rotation)||0)*Math.PI/180,cx=x+w/2,cy=y+h/2;const points=[[-w/2,-h/2],[w/2,-h/2],[-w/2,h/2],[w/2,h/2]].map(([a,b])=>[cx+a*Math.cos(angle)-b*Math.sin(angle),cy+a*Math.sin(angle)+b*Math.cos(angle)]);return {x:Math.min(...points.map(p=>p[0])),y:Math.min(...points.map(p=>p[1])),right:Math.max(...points.map(p=>p[0])),bottom:Math.max(...points.map(p=>p[1]))};}
function report(pages,issues,extra={}){const errors=issues.filter(i=>i.severity==='error').length,warnings=issues.length-errors;return {issues,summary:issues.length?`检查了 ${pages.length} 页，发现 ${errors} 项需处理、${warnings} 项需留意。`:`已检查 ${pages.length} 页，未发现本次检查覆盖的问题。`,stats:{pageCount:pages.length,objectCount:pages.reduce((n,p)=>n+(p.objects||[]).length,0),errors,warnings,...extra}};}
function fingerprint(page){const vectors=(page.objects||[]).filter(o=>substantive(o)||(o.type==='rect'&&o.w>=128&&o.h>=72&&o.w*o.h<W*H*.92)||(o.type==='image'&&o.w>=128&&o.h>=72)).filter(o=>[o.x,o.y,o.w,o.h].every(Number.isFinite)).map(o=>({type:o.type==='text'?(o.layoutField==='title'||o.sourceField==='title'?'title':'text'):o.type,v:[o.x/W,o.y/H,o.w/W,o.h/H],rotation:Math.round((o.rotation||0)/10)})).sort((a,b)=>a.type.localeCompare(b.type)||a.v[1]-b.v[1]||a.v[0]-b.v[0]);return vectors;}
function similarity(a,b){if(a.length<2||b.length<2)return 0;const used=new Set();let matched=0;for(const x of a){let best=-1,distance=Infinity;for(let i=0;i<b.length;i++){if(used.has(i)||x.type!==b[i].type||x.rotation!==b[i].rotation)continue;const d=Math.max(...x.v.slice(0,['text','title'].includes(x.type)?3:4).map((v,k)=>Math.abs(v-b[i].v[k])));if(d<distance){distance=d;best=i;}}if(best>=0&&distance<=.045){matched++;used.add(best);}}return matched/Math.max(a.length,b.length);}
function checkTextCoverage(page,issues){const objects=(page.objects||[]).filter(substantive),title=String(page.title||''),body=String(page.body||'');if(title&&!objects.some(o=>(o.layoutField==='title'||o.sourceField==='title')&&o.text===title))issues.push({pageId:page.id,kind:'title-coverage',severity:'error',message:'页面标题未完整出现在可编辑文字中。'});if(!body.trim())return;const ranges=objects.filter(o=>(o.layoutField==='body'||o.sourceField==='body')&&Array.isArray(o.sourceRange));if(!ranges.length){if(!objects.some(o=>o.text===body))issues.push({pageId:page.id,kind:'body-coverage',severity:'error',message:'正文缺少可验证的完整文字来源，需核对是否遗漏。'});return;}const covered=new Uint8Array(body.length);let mismatch=false;for(const o of ranges){const [start,end]=o.sourceRange;if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end>body.length||end<start||body.slice(start,end)!==o.text){mismatch=true;continue;}covered.fill(1,start,end);}for(const match of body.matchAll(/^##[ \t]+/gm))covered.fill(1,match.index,match.index+match[0].length);if(mismatch||body.split('').some((_,i)=>!covered[i]&&!/\s/.test(body[i])))issues.push({pageId:page.id,kind:'body-coverage',severity:'error',message:mismatch?'正文对象与原文位置不一致，需核对内容完整性。':'部分正文未出现在可编辑文字中。'});}
export function auditDeck(pages,{sourcePages}={}){
 const issues=[],ids=new Set();for(const p of pages){if(ids.has(p.id))issues.push({pageId:p.id,kind:'duplicate-page',severity:'error',message:'页面标识重复。'});ids.add(p.id);const text=[];
  for(const o of p.objects||[]){if(duplicateChapterMarker(p,o))issues.push({pageId:p.id,kind:'duplicate-chapter-number',severity:'warning',message:'章节标题已有编号，不应再重复显示同一装饰编号。'});if(![o.x,o.y,o.w,o.h].every(Number.isFinite)||o.w<0||o.h<0){issues.push({pageId:p.id,kind:'geometry',severity:'error',message:`对象 ${o.id} 的位置或尺寸无效。`});continue;}const b=bounds(o);if(b.x< -1||b.y< -1||b.right>W+1||b.bottom>H+1)issues.push({pageId:p.id,kind:'bounds',severity:'error',message:`对象 ${o.id} 超出页面边界。`});if(substantive(o)){text.push({o,b});if(!Number.isFinite(o.fontSize)||o.fontSize<24)issues.push({pageId:p.id,kind:'small-text',severity:o.layoutManaged&&!o.custom&&!o.sourceField&&!o.layoutField&&!o.sourceRange&&o.fontSize>=16&&/^(?:0[1-9]|[1-9]\d?[.)、]?)$/.test(String(o.text).trim())?'warning':'error',message:`文字“${String(o.text).slice(0,22)}”小于 24 像素，可能影响阅读。`});}}
  for(let i=0;i<text.length;i++)for(let j=i+1;j<text.length;j++){const a=text[i],b=text[j],width=Math.min(a.b.right,b.b.right)-Math.max(a.b.x,b.b.x),height=Math.min(a.b.bottom,b.b.bottom)-Math.max(a.b.y,b.b.y);if(width>2&&height>2&&width*height>Math.max(64,Math.min(a.o.w*a.o.h,b.o.w*b.o.h)*.02))issues.push({pageId:p.id,kind:'text-overlap',severity:'warning',message:`文字“${String(a.o.text).slice(0,14)}”与“${String(b.o.text).slice(0,14)}”重叠，需检查。`});}
  if(p.designPlan||sourcePages)checkTextCoverage(p,issues);
  if(p.themeId==='curated-139'){const colors=[p.background,...(p.objects||[]).flatMap(o=>[o.fill,o.color,o.stroke])].filter(Boolean).map(c=>String(c).toLowerCase());if(!colors.includes('#316bf0')||!colors.some(c=>['#050505','#000000'].includes(c)))issues.push({pageId:p.id,kind:'style-consistency',severity:'warning',message:'本页缺少整套蓝黑视觉中的主要颜色，请核对风格一致性。'});}
 }
 if(sourcePages){const actual=new Map(pages.map(p=>[p.id,p]));for(const source of sourcePages){const p=actual.get(source.id);if(!p){issues.push({pageId:source.id,kind:'source-missing',severity:'error',message:'确认过的来源页面未出现在生成结果中。'});continue;}if(p.title!==source.title||p.body!==source.body)issues.push({pageId:p.id,kind:'source-changed',severity:'error',message:'标题或正文与已确认原文不一致。'});for(const object of (source.objects||[]).filter(o=>o.custom||!o.layoutManaged)){if(!(p.objects||[]).some(o=>equal(o,object)))issues.push({pageId:p.id,kind:'custom-object-changed',severity:'error',message:`原有素材或手动对象 ${object.id} 未完整保留。`});}}const sourceIds=new Set(sourcePages.map(p=>p.id));for(const p of pages)if(!sourceIds.has(p.id))issues.push({pageId:p.id,kind:'unplanned-page',severity:'warning',message:'生成结果含有未在本轮确认来源中登记的页面。'});}
 for(let i=1;i<pages.length;i++)if(String(pages[i].title||'').trim()&&String(pages[i].title).trim()===String(pages[i-1].title||'').trim())issues.push({pageId:pages[i].id,relatedPageId:pages[i-1].id,kind:'repeated-adjacent-title',severity:'warning',message:'相邻两页标题相同，请核对是否应合并或明确区分表达目的。'});
 const prints=pages.map(fingerprint);for(let i=1;i<pages.length;i++)if(similarity(prints[i-1],prints[i])>=.88)issues.push({pageId:pages[i].id,relatedPageId:pages[i-1].id,kind:'adjacent-repetition',severity:'warning',message:'与上一页的文字、面板和图片分布高度相似，建议调整表达结构。'});
 const counted=new Set();for(let i=0;i<pages.length;i++){if(counted.has(i))continue;const group=[i];for(let j=i+1;j<pages.length;j++)if(similarity(prints[i],prints[j])>=.88)group.push(j);if(group.length>=3&&group.length/pages.length>=.4){group.forEach(n=>counted.add(n));for(const n of group.slice(1))issues.push({pageId:pages[n].id,relatedPageId:pages[i].id,kind:'deck-repetition',severity:'warning',message:`整稿中 ${group.length} 页的主要构图高度相似，需检查页面节奏。`});}}
 return report(pages,issues,{sourceChecked:!!sourcePages});
}
export function getRepairTargets(result,pages){const ids=new Set((result?.issues||[]).map(i=>i.pageId));return pages.filter(p=>ids.has(p.id)&&!p.designManual&&typeof p.designSnapshot==='string'&&p.designSnapshot===snapshotPage(p)).map(p=>p.id);}
export async function auditRenderedDeck(pages){return inspectRenderedDeck(pages);}

// Only grow generated frames into verified free space; never edit copy or user objects.
export async function fitGeneratedTextFrames(pages){
 const fitted=structuredClone(pages);
 for(const p of fitted)p.objects=(p.objects||[]).filter(o=>!duplicateChapterMarker(p,o));
 // Crop generated, non-content vectors to the canvas without moving their visible ink.
 // SVG import adds stroke/filter padding, including around full-bleed backgrounds.
 if(typeof DOMParser!=='undefined')for(const p of fitted)for(const o of p.objects||[]){
  if(o.type!=='vector'||!o.layoutManaged||o.custom||o.nativeType||o.rotation||/<(?:text|tspan|image)\b/i.test(o.svg||''))continue;
  if(![o.x,o.y,o.w,o.h].every(Number.isFinite)||o.w<=0||o.h<=0)continue;
  const x=Math.max(0,o.x),y=Math.max(0,o.y),right=Math.min(W,o.x+o.w),bottom=Math.min(H,o.y+o.h);
  if(right<=x||bottom<=y||x===o.x&&y===o.y&&right===o.x+o.w&&bottom===o.y+o.h)continue;
  const doc=new DOMParser().parseFromString(o.svg,'image/svg+xml'),root=doc.documentElement;
  if(doc.querySelector('parsererror')||root.localName!=='svg')continue;
  const vb=(root.getAttribute('viewBox')||'').trim().split(/[ ,]+/).map(Number);
  if(vb.length!==4||!vb.every(Number.isFinite)||vb[2]<=0||vb[3]<=0)continue;
  // Non-proportional viewports use SVG's preserveAspectRatio mapping; leave them to repair.
  if(Math.abs(vb[2]/vb[3]-o.w/o.h)>.001)continue;
  const w=right-x,h=bottom-y;
  root.setAttribute('viewBox',[vb[0]+(x-o.x)*vb[2]/o.w,vb[1]+(y-o.y)*vb[3]/o.h,w*vb[2]/o.w,h*vb[3]/o.h].join(' '));
  root.setAttribute('width',String(w));root.setAttribute('height',String(h));
  root.setAttribute('overflow','hidden');
  o.svg=new XMLSerializer().serializeToString(root);Object.assign(o,{x,y,w,h});
 }
 if(fitted.some(p=>(p.objects||[]).some(o=>substantive(o)&&o.layoutManaged&&!o.custom)))await inspectRenderedDeck(fitted,true);
 return fitted;
}
async function inspectRenderedDeck(pages,fit=false){
 if(typeof document==='undefined')throw Error('文字溢出检查需要浏览器页面环境。');const issues=[],host=document.createElement('div');host.dataset.designAudit='true';host.setAttribute('aria-hidden','true');Object.assign(host.style,{position:'fixed',left:'-100000px',top:'0',width:W+'px',height:H+'px',visibility:'hidden',pointerEvents:'none',contain:'layout style'});document.body.append(host);
 try{await document.fonts?.ready;const entries=[];for(const p of pages)for(const o of p.objects||[]){if(!substantive(o)||![o.x,o.y,o.w,o.h].every(Number.isFinite))continue;const node=document.createElement('div');node.textContent=String(o.text||'');Object.assign(node.style,{position:'absolute',boxSizing:'border-box',left:o.x+'px',top:o.y+'px',width:o.w+'px',height:o.h+'px',padding:'0',margin:'0',border:'0',fontFamily:(o.fontFamily||'Microsoft YaHei')+', sans-serif',fontSize:(o.fontSize||24)+'px',fontWeight:o.bold?'700':'400',fontStyle:o.italic?'italic':'normal',lineHeight:String(o.lineHeight||1.3),textAlign:o.align||'left',whiteSpace:'pre-wrap',overflowWrap:'anywhere',overflow:'visible'});host.append(node);entries.push({p,o,node});}for(const {p,o,node}of entries){
 // Imported numeral labels can be a few pixels narrower with local font metrics.
 // Widen only into free space, so a short label never becomes a vertical stack.
 if(fit&&o.layoutManaged&&!o.custom&&!(Number(o.rotation)||0)&&(node.scrollHeight>node.clientHeight+2||node.scrollWidth>node.clientWidth+2||/^(?:0[1-9]|[1-9]\d?[.)、]?)$/.test(String(o.text).trim()))){
  const measure=node.cloneNode(true);Object.assign(measure.style,{width:'max-content',height:'auto',whiteSpace:'pre'});host.append(measure);
  const natural=Math.ceil(measure.getBoundingClientRect().width)+Math.max(4,Math.ceil(o.fontSize*.12));measure.remove();
  let available=Math.min(W-o.x,Math.max(o.w*1.25,o.w+o.fontSize*2));
  for(const other of p.objects||[]){
   if(other===o||!(['text','image'].includes(other.type)||other.custom)||![other.x,other.y,other.w,other.h].every(Number.isFinite))continue;
   const b=bounds(other);if(b.bottom>o.y&&b.y<o.y+o.h&&b.right>o.x)available=Math.min(available,b.x-o.x-4);
  }
  const desired=Math.min(natural,available);
  if(desired>o.w&&desired<=available&&o.x>=0&&o.y>=0&&o.y+o.h<=H){o.w=desired;node.style.width=desired+'px';}
 }
 if(fit&&o.layoutManaged&&!o.custom&&!(Number(o.rotation)||0)&&node.scrollHeight>node.clientHeight){
  const desired=Math.ceil(node.scrollHeight)+2;
  let available=H-o.y;
  for(const other of p.objects||[]){
   if(other===o||!(['text','image'].includes(other.type)||other.custom))continue;
   if(![other.x,other.y,other.w,other.h].every(Number.isFinite))continue;
   const b=bounds(other);
   if(b.right>o.x&&b.x<o.x+o.w&&b.bottom>o.y)available=Math.min(available,b.y-o.y-4);
  }
  if(desired<=available&&o.y>=0&&o.x>=0&&o.x+o.w<=W){o.h=desired;node.style.height=desired+'px';}
 }
 if(node.scrollHeight>node.clientHeight+2||node.scrollWidth>node.clientWidth+2)issues.push({pageId:p.id,kind:'text-overflow',severity:'error',message:`文字“${String(o.text).slice(0,22)}”超出文字框，需扩大区域或重新安排内容。`});}return report(pages,issues,{rendered:true});}finally{host.remove();}
}
