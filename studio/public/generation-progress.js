const SVG='http://www.w3.org/2000/svg';
const paths={slide:'M4 4h16v16H4z M4 8h16',up:'m6 14 6-6 6 6',right:'m9 5 7 7-7 7',stop:'M6 6h12v12H6z',check:'m5 12 4 4L19 6',drafts:'m3 8 9-5 9 5-9 5z M3 12l9 5 9-5 M3 16l9 5 9-5'};
const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};
function icon(name){const svg=document.createElementNS(SVG,'svg');for(const [key,value]of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);const path=document.createElementNS(SVG,'path');path.setAttribute('d',paths[name]||paths.slide);svg.append(path);return svg;}
function button(text,name,action,className='gp-button'){const node=el('button',className);node.type='button';if(name)node.append(icon(name));node.append(el('span','',text));node.addEventListener('click',action);return node;}
const finite=(value,fallback=0)=>Number.isFinite(Number(value))?Number(value):fallback;
const timestamp=value=>typeof value==='number'?value:Date.parse(value);

export function generationProgressSummary(task={},now=Date.now()){
 const total=Math.max(0,Math.floor(finite(task.total))),completed=Math.min(total,Math.max(0,Math.floor(finite(task.completed))));
 const reference=task.kind==='reference',planned=Math.min(total,Math.max(0,Math.floor(finite(task.planned))));
 const running=task.state==='running',phase=(reference?task.generationPhase:null)||task.phase||'planning';
 const overlapping=reference&&running&&phase==='designing'&&planned<total;
 const labels={complete:'生成已完成',stopped:'已停止生成',failed:'生成未完成',interrupted:'生成已中断'};
 const status=running?(reference?(phase==='reviewing'?'整稿检查中':phase==='designing'?(overlapping?'正在边规划边绘制':'正在逐页绘制'):'正在规划布局'):(phase==='reviewing'?'正在检查生成结果':phase==='designing'?'正在逐页排版':'正在准备排版')):(labels[task.state]||'等待生成');
 const started=timestamp(task.startedAt),updated=timestamp(task.updatedAt);
 const elapsed=Number.isFinite(task.elapsedMs)?Math.max(0,task.elapsedMs)+(running&&Number.isFinite(updated)?Math.max(0,now-updated):0):Number.isFinite(started)?Math.max(0,(running?now:Number.isFinite(updated)?updated:started)-started):0;
 const seconds=Math.floor(elapsed/1000),time=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
 const displayCompleted=reference&&phase==='planning'?planned:completed,progressLabel=reference&&phase==='planning'?'已规划':'已生成';
 const count=total?`${reference?progressLabel+' ':''}${displayCompleted} / ${total} 页`:'正在确认页数';
 const reviewStatus=task.state==='complete'?'通过':phase==='reviewing'?(running?'进行中':task.state==='failed'?'未通过':'已停止'):'待开始';
 const phaseCounts={planning:`规划 ${planned} / ${total}`,designing:`绘制 ${completed} / ${total}`,reviewing:`检查 ${reviewStatus}`};
 return {overlapping,total,completed,planned,displayCompleted,progressLabel,reference,reviewStatus,phaseCounts,running,phase,status,time,count,ratio:total?displayCompleted/total:0};
}

function drawSegments(host,summary){
 const {total,displayCompleted:completed,running,phase}=summary;
 host.setAttribute('role','progressbar');host.setAttribute('aria-label',summary.progressLabel+'页面');host.setAttribute('aria-valuemin','0');
 host.setAttribute('aria-valuetext',total?`${summary.progressLabel} ${completed} 页，共 ${total} 页。${summary.status}`:summary.status);
 if(total){host.setAttribute('aria-valuemax',String(total));host.setAttribute('aria-valuenow',String(completed));}else{host.removeAttribute('aria-valuemax');host.removeAttribute('aria-valuenow');}
 const cells=Math.min(100,total),key=JSON.stringify([cells,total,completed,running,phase,summary.reference]);
 if(host.dataset.cells===key)return;host.dataset.cells=key;host.replaceChildren();host.classList.toggle('gp-segments-empty',!total);
 if(!total){host.append(el('span','gp-pending-count','页面数量确认后显示进度'));return;}
 host.style.setProperty('--gp-cell-count',String(cells));
 for(let i=0;i<cells;i++){
  const start=i*total/cells,end=(i+1)*total/cells,filled=Math.max(0,Math.min(1,(completed-start)/(end-start)));
  const cell=el('span','gp-cell');cell.setAttribute('aria-hidden','true');
  if(filled===1)cell.classList.add('is-done');
  else if(filled>0){const fill=el('span','gp-cell-fill');fill.style.width=`${filled*100}%`;cell.append(fill);}
  if(running&&(phase==='designing'||summary.reference&&phase==='planning')&&completed>=start&&completed<end)cell.classList.add('is-current');
  host.append(cell);
 }
}

function preview(page,renderMini){
 const frame=el('span','gp-preview');
 if(typeof renderMini==='function')try{const rendered=renderMini(page);if(typeof rendered==='string')frame.innerHTML=rendered;else if(rendered?.nodeType)frame.append(rendered);}catch{}
 if(!frame.childNodes.length)frame.append(el('span','gp-preview-title',page.title||'未命名页面'));
 return frame;
}
function completedPages(task,pages){const ids=new Set(task.completedPageIds||[]);return pages.map((page,index)=>({page,index})).filter(({page})=>ids.has(page.id)&&!page.designPending);}

export function mountGenerationProgress(host,{onCollapse=()=>{},onStop=()=>{},onResume,onViewCompleted,onOpenDrafts=()=>{},onShowPage=()=>{},renderMini}={}){
 const root=el('section','generation-progress');root.setAttribute('aria-label','页面生成进度');
 const expanded=el('div','gp-expanded'),header=el('div','gp-header'),heading=el('div','gp-heading'),status=el('strong','gp-status');
 status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.setAttribute('aria-atomic','true');
 heading.append(icon('slide'),status);
 const drafts=button('已收进草稿箱',null,()=>onOpenDrafts(task?.id),'gp-drafts-link');heading.append(drafts);
 const meta=el('div','gp-meta'),count=el('strong','gp-count'),time=el('span','gp-elapsed');time.setAttribute('aria-live','off');
 const collapse=button('收起','up',()=>onCollapse(true)),stop=button('停止','stop',()=>onStop(task?.id));
 meta.append(count,time,collapse,stop);header.append(heading,meta);
 const segments=el('div','gp-segments'),steps=el('ol','gp-steps');
 const stepNodes=['文案已确认','逐页排版','完成检查'].map((label,index)=>{const step=el('li','gp-step'),mark=el('span','gp-step-mark',String(index+1)),labelNode=el('span','',label);step.append(mark,labelNode);steps.append(step);return {step,mark,labelNode};});
 const phaseCounts=el('div','gp-phase-counts');phaseCounts.setAttribute('aria-label','各阶段进度');
 const phaseCountNodes=['planning','designing','reviewing'].map(key=>{const node=el('span');phaseCounts.append(node);return {key,node};});
 const message=el('p','gp-message'),thumbnails=el('div','gp-thumbnails');
 const recovery=el('div','gp-recovery-actions'),resume=button('继续生成','right',()=>onResume?.(task?.id),'gp-button gp-resume');recovery.append(resume);
 const viewCompleted=button('查看已完成页','right',()=>onViewCompleted?.(task?.id),'gp-button gp-view-pages');
 expanded.append(header,segments,steps,phaseCounts,message,recovery,viewCompleted,thumbnails);
 const compact=button('查看进度','slide',()=>onCollapse(false),'gp-compact');
 const compactStatus=el('span','gp-compact-status'),compactCount=el('strong','gp-compact-count'),compactAction=el('span','gp-compact-action','查看进度');
 compact.replaceChildren(icon('slide'),compactStatus,compactCount,compactAction,icon('right'));compact.setAttribute('aria-expanded','false');
 root.append(expanded,compact);host.append(root);let task=null,pages=[],destroyed=false,thumbKey='';
 function tick(){if(task&&!destroyed)time.textContent=`已用时 ${generationProgressSummary(task).time}`;}
 const timer=setInterval(tick,1000);
 function update(nextTask,nextPages=[]){
  if(destroyed)return;task=nextTask;pages=Array.isArray(nextPages)?nextPages:[];
  if(!task){root.hidden=true;return;}root.hidden=false;viewCompleted.hidden=!onViewCompleted||task.kind!=='reference'||!task.completed||task.state==='complete';viewCompleted.disabled=!!task.resumePending;
  const summary=generationProgressSummary(task);root.dataset.state=task.state;root.dataset.phase=summary.phase;
  expanded.hidden=!!task.collapsed;compact.hidden=!task.collapsed;
  status.textContent=summary.status;count.textContent=summary.count;compactStatus.textContent=summary.status;compactCount.textContent=summary.count;tick();
  compact.setAttribute('aria-label',`${summary.status}，${summary.count}，查看进度`);stop.hidden=!summary.running;
  recovery.hidden=!onResume||!task.resumable||summary.running||(task.state==='complete'&&!task.applyReady);resume.disabled=!!task.resumePending;resume.children[1].textContent=task.applyReady?'查看并应用':'继续生成';
  drawSegments(segments,summary);
  const stage=task.state==='complete'?3:summary.phase==='reviewing'?2:summary.reference&&summary.phase==='planning'?0:1;
  const stepLabels=summary.reference?['布局规划','逐页绘制','整稿检查']:['文案已确认','逐页排版','完成检查'];
  phaseCounts.hidden=!summary.reference;phaseCountNodes.forEach(({key,node})=>{node.textContent=summary.phaseCounts[key];});
  stepNodes.forEach(({step,mark,labelNode},i)=>{labelNode.textContent=stepLabels[i];const done=summary.reference?(i===0?summary.total>0&&summary.planned===summary.total:i===1?summary.total>0&&summary.completed===summary.total:task.state==='complete'):i<stage,current=summary.running&&(summary.overlapping?i<2:i===stage);step.classList.toggle('is-done',done);step.classList.toggle('is-active',current);if(current)step.setAttribute('aria-current','step');else step.removeAttribute('aria-current');mark.replaceChildren(done?icon('check'):document.createTextNode(String(i+1)));});
  const text=task.message||(!summary.running&&task.state!=='complete'?'已完成的页面已保留，可在草稿箱查看。':'');message.textContent=text;message.hidden=!text;
  const done=completedPages(task,pages).slice(-3),key=JSON.stringify([task.id,done.map(({page,index})=>[index,page]),summary.running]);
  if(key!==thumbKey){thumbKey=key;thumbnails.replaceChildren();
   for(const {page,index}of done){const tile=button('',null,()=>onShowPage(page.id,task),'gp-thumbnail');tile.setAttribute('aria-label',`查看第 ${index+1} 页：${page.title||'未命名页面'}`);tile.replaceChildren(preview(page,renderMini),el('span','gp-thumbnail-caption',`第 ${index+1} 页`));thumbnails.append(tile);}
   if(done.length)thumbnails.append(button('查看已完成页面','right',()=>onShowPage(done.at(-1).page.id,task),'gp-view-pages'));
  }
  thumbnails.hidden=!done.length;
 }
 update(null);
 return {update,destroy(){if(destroyed)return;destroyed=true;clearInterval(timer);root.remove();}};
}

export function createGenerationDraftRow(task,pages=[],{onView=()=>{},onStop=()=>{},onResume,onViewCompleted,onRetry,onDelete,renderMini}={}){
 const row=el('article','generation-draft-row'),summary=generationProgressSummary(task);row.dataset.taskId=task.id;
 const done=completedPages(task,pages),cover=done[0]?.page;
 if(cover){const thumb=button('',null,()=>onView(task.id),'gp-draft-thumb');thumb.setAttribute('aria-label',`查看${task.title||'生成草稿'}`);thumb.replaceChildren(preview(cover,renderMini));row.append(thumb);}else{const placeholder=el('span','gp-draft-icon');placeholder.append(icon('drafts'));placeholder.setAttribute('aria-hidden','true');row.append(placeholder);}
 const content=el('div','gp-draft-content'),title=el('strong','gp-draft-title',task.title||'生成草稿'),state=el('span','gp-draft-state',`${summary.status} · ${summary.count}`),segments=el('div','gp-segments gp-segments-small');
 drawSegments(segments,summary);content.append(title,state,segments);
 if(task.message&&!summary.running)content.append(el('span','gp-draft-message',task.message));
 const actions=el('div','gp-draft-actions');actions.append(button('查看',null,()=>onView(task.id)));if(onViewCompleted&&task.kind==='reference'&&task.completed>0&&task.state!=='complete'){const view=button('查看已完成页',null,()=>onViewCompleted(task.id));view.disabled=!!task.resumePending;actions.append(view);}if(summary.running)actions.append(button('停止','stop',()=>onStop(task.id)));
 if(onResume&&task.resumable&&!summary.running&&task.state!=='complete'){const resume=button('继续生成','right',()=>onResume(task.id),'gp-button gp-resume');resume.disabled=!!task.resumePending;actions.append(resume);}
 if(onRetry&&task.kind==='reference'&&!summary.running){const retry=button('重新生成',null,()=>onRetry(task.id));retry.disabled=!!task.resumePending;actions.append(retry);}
 if(onDelete){const remove=button(summary.running?'停止并删除':'删除',null,()=>onDelete(task.id));remove.disabled=!!task.resumePending;actions.append(remove);}
 row.append(content,actions);return row;
}
