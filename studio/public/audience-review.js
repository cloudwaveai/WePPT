import {audienceSource,validateAudiencePlan} from './audience-plan.js';
import {audienceSelection,createAudienceBranch} from './audience-branch.js';
import {fitAudienceLayout} from './audience-layout.js';

const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={keep:'保留',edit:'改写',delete:'删除',add:'新增'};
const countText=s=>`保留 ${s.keep} 页 · 改写 ${s.edit} 页 · 删除 ${s.delete} 页 · 新增 ${s.add} 页 · 调序 ${s.moved||0} 页`;
const positionText=position=>`${position.sourceIndex?'原第 '+position.sourceIndex+' 页':'新增页'} → ${position.targetIndex?'新第 '+position.targetIndex+' 页':'删除'}${position.moved?' · 调序':''}`;

export function createAudienceWorkflow({store,dialog,request,onConfirmed,notify,renderPage,isBusy=()=>false}){
 if(!document.querySelector('link[data-audience-style]')){const link=document.createElement('link');link.rel='stylesheet';link.href='/audience-review.css';link.dataset.audienceStyle='';document.head.append(link);}
 const historyButton=document.createElement('button');historyButton.id='audience-history';historyButton.textContent='改动清单';historyButton.hidden=true;document.querySelector('#projects').before(historyButton);historyButton.onclick=history;
 const sync=()=>{historyButton.hidden=!store.project?.audienceVersion;};store.subscribe(sync);sync();
 const head=title=>`<div class="modal-head"><h2>${escape(title)}</h2><button data-close aria-label="关闭">×</button></div>`;
 let active=null;
 function open({audience='',notes=''}={}){
  if(!store.project)return;if(isBusy()){notify('请先完成或停止当前 AI 请求，再创建受众版本。');return;}
  active?.abort();const controller=new AbortController();active=controller;
  const projectId=store.project.id,modal=dialog(`${head('创建受众版本')}<p class="manual-help">根据新受众重组叙事和页面顺序，逐项确认增删改，再预览沿用原稿设计的页面，保存独立版本。</p><label class="audience-field">版本受众<input id="audience-label" maxlength="50" required placeholder="例如：供应商、客户、团队" value="${escape(audience)}"></label><label class="audience-field">这份版本要达成什么目的？<textarea id="audience-notes" rows="3" maxlength="6000" placeholder="例如：明确合作方式与交付要求">${escape(notes)}</textarea></label><p id="audience-error" class="action-error" role="alert"></p><p id="audience-status" class="manual-help" role="status" aria-live="polite"></p><div class="modal-actions"><button data-close>取消</button><button id="audience-create" class="primary">生成改编方案</button></div>`);
  let saving=false;
  const stop=()=>{if(!saving)controller.abort();};modal.addEventListener('close',stop,{once:true});
  const closeSaving=e=>{if(saving)e.preventDefault();};modal.addEventListener('cancel',closeSaving);modal.addEventListener('close',()=>{modal.classList.remove('audience-review-dialog');modal.removeEventListener('cancel',closeSaving);},{once:true});
  const query=s=>modal.querySelector(s);
  query('#audience-create').onclick=async()=>{
   const audience=query('#audience-label').value.trim(),notes=query('#audience-notes').value.trim();
   if(!audience){query('#audience-error').textContent='请填写这个版本面向谁。';query('#audience-label').focus();return;}
   const button=query('#audience-create');if(button.disabled)return;button.disabled=true;query('#audience-error').textContent='';query('#audience-status').textContent='正在根据受众重组叙事，规划新目录和逐页改编建议…';query('#audience-label').readOnly=true;query('#audience-notes').readOnly=true;
   try{
    if(store.project?.id!==projectId)throw Error('原稿已切换，请重新打开改编流程。');await store.flush();controller.signal.throwIfAborted();
    const source=structuredClone(store.project),fingerprint=JSON.stringify(source.pages);
    const plan=await request('/api/audience/plan',{projectId:source.id,revision:source.revision,audience,notes},controller.signal);
    controller.signal.throwIfAborted();if(!modal.open)return;
    if(store.project?.id!==source.id||JSON.stringify(store.project.pages)!==fingerprint||plan.sourceProjectId!==source.id||plan.sourceRevision!==source.revision)throw Error('原稿已有修改，本次方案没有应用，请重新生成。');
    const checked=validateAudiencePlan({message:plan.message,narrative:plan.narrative||'',entries:plan.entries},audienceSource(source));
    review(source,{...checked,audience,notes},fingerprint);
   }catch(error){if(controller.signal.aborted)return;query('#audience-error').textContent=error.message||'生成失败，请重试。';button.disabled=false;query('#audience-status').textContent='';query('#audience-label').readOnly=false;query('#audience-notes').readOnly=false;}
  };
  function review(source,plan,fingerprint){
   const selections=plan.entries.map(entry=>({accept:true,title:entry.title,body:entry.body})),originalCopy=audienceSource(source),unaccounted=plan.entries.filter(entry=>entry.reason.includes('AI未交代此原页')).length;let order=plan.entries.map((_,i)=>i),branch=null,submitting=false;
   modal.classList.add('audience-review-dialog');
   query('#modal-content').innerHTML=`${head('确认受众改编方案')}<p class="audience-context">${escape(source.title)} → ${escape(plan.audience)}版</p><p class="manual-help">目的：${escape(plan.notes||'根据新受众调整表达与内容重点')}。先确认整份新结构和逐页文案，再对照原稿预览实际版式；确认后直接进入编辑器。</p><p class="audience-summary" id="audience-summary" role="status" aria-live="polite"></p><section class="audience-structure"><h3 id="audience-structure-title" tabindex="-1">新版本的叙事与目录</h3><label class="audience-field">叙事逻辑 · 可修改<textarea id="audience-narrative" rows="3" maxlength="6000">${escape(plan.narrative||'')}</textarea></label><p class="manual-help">目录即保存后的页面顺序。可以上下移动；取消改写只恢复原文，页面顺序在这里单独调整。</p><button id="audience-reset-order">恢复原页顺序</button><p id="audience-order-status" class="manual-help" role="status" aria-live="polite"></p><ol id="audience-outline" class="audience-outline"></ol></section><h3 class="audience-details-title">逐页核对文案与变化</h3><div class="audience-review-list">${plan.entries.map((entry,i)=>row(entry,i,originalCopy)).join('')}</div><p id="audience-error" class="action-error" role="alert"></p><div class="audience-review-actions"><button id="audience-back">修改受众与目的</button><button id="audience-confirm" class="primary">预览原稿版式</button></div>`;
   if(unaccounted){const warning=document.createElement('p');warning.className='audience-questions';warning.textContent=`AI 未交代 ${unaccounted} 个原页，已暂时保留在目录末尾。请在逐页核对中确认是否删除，并调整其位置。`;query('.audience-summary').after(warning);}
   query('[data-close]').onclick=()=>{if(!submitting)modal.close();};query('#audience-back').onclick=()=>{modal.addEventListener('close',()=>open({audience:plan.audience,notes:plan.notes}),{once:true});modal.close();};
   function current(){return audienceSelection(source,{...plan,narrative:query('#audience-narrative').value},selections,{order});}
   function visibleIndices(){return order.filter(i=>!(plan.entries[i].action==='add'&&selections[i].accept===false));}
   function update({keepError=false}={}){try{
    const selected=current(),indices=visibleIndices(),retained=indices.filter((_,j)=>selected.entries[j].action!=='delete');
    query('#audience-summary').textContent=`${countText(selected.summary)}；确认后共 ${selected.summary.total} 页。调序单独统计，可与改写同时发生。`;
    query('#audience-confirm').disabled=!selected.summary.changed||submitting;
    query('#audience-outline').innerHTML=selected.entries.map((entry,j)=>({entry,position:selected.positions[j],index:indices[j]})).filter(item=>item.position.targetIndex).map(({entry,position,index})=>`<li><div><strong>${position.targetIndex}. ${escape(entry.title||'（无标题）')}</strong><span>${positionText(position)} · ${names[entry.action]}</span></div><div class="audience-order-controls"><button data-order-index="${index}" data-direction="-1" aria-label="上移：${escape(entry.title||'无标题')}" ${retained[0]===index||submitting?'disabled':''}>上移</button><button data-order-index="${index}" data-direction="1" aria-label="下移：${escape(entry.title||'无标题')}" ${retained.at(-1)===index||submitting?'disabled':''}>下移</button></div></li>`).join('');
    for(const button of query('#audience-outline').querySelectorAll('[data-order-index]'))button.onclick=()=>{
     if(submitting)return;const index=Number(button.dataset.orderIndex),direction=Number(button.dataset.direction),at=retained.indexOf(index),other=retained[at+direction];if(other===undefined)return;
     const a=order.indexOf(index),b=order.indexOf(other);[order[a],order[b]]=[order[b],order[a]];branch=null;update();
     query('#audience-order-status').textContent='目录已调整，请核对叙事逻辑；保存将采用当前顺序。';
     query(`#audience-outline [data-order-index="${index}"][data-direction="${direction}"]`)?.focus({preventScroll:true});
    };
    for(const [j,index] of indices.entries()){
     const entry=selected.entries[j],card=query(`[data-audience-row="${index}"]`);
     card.querySelector('[data-position]').textContent=`${names[entry.action]} · ${positionText(selected.positions[j])}`;
     card.querySelector('[data-reason]').textContent=entry.reason;
     const removalNote=card.querySelector('[data-remove-note]');if(removalNote)removalNote.hidden=!selections[index].remove;
     const deleteCopy=card.querySelector('[data-delete-copy]');if(deleteCopy)deleteCopy.textContent=entry.action==='delete'?'从新版本删除此页，原稿保留。':'未采纳删除建议，保留原页。';
    }
    if(!keepError)query('#audience-error').textContent=selected.summary.changed?'':'当前没有实际增删改或调序，请调整方案后再确认。';
   }catch(error){query('#audience-error').textContent=error.message;query('#audience-confirm').disabled=true;}}
   query('#audience-narrative').oninput=()=>{branch=null;update();};
   query('#audience-reset-order').onclick=()=>{if(submitting)return;order=plan.entries.map((_,i)=>i).sort((a,b)=>{
    const first=originalCopy.pages.findIndex(p=>p.id===plan.entries[a].sourcePageId),second=originalCopy.pages.findIndex(p=>p.id===plan.entries[b].sourcePageId);
    return (first<0?originalCopy.pages.length+a:first)-(second<0?originalCopy.pages.length+b:second);
   });branch=null;update();query('#audience-order-status').textContent='已恢复原页的相对顺序；新增页放在末尾，可继续上下移动。';};
   for(const [i,entry] of plan.entries.entries()){
    const card=query(`[data-audience-row="${i}"]`),checkbox=card.querySelector('[data-accept]');
    if(checkbox)checkbox.onchange=()=>{selections[i].accept=checkbox.checked;branch=null;card.querySelectorAll('input[data-title],textarea').forEach(field=>field.disabled=!checkbox.checked||selections[i].remove===true);card.querySelector('[data-position]').textContent=checkbox.checked?'':'此项建议未采纳';update();};
    const remove=card.querySelector('[data-remove]');if(remove)remove.onchange=()=>{
     selections[i].remove=remove.checked;branch=null;if(checkbox)checkbox.disabled=remove.checked;
     card.querySelectorAll('input[data-title],textarea').forEach(field=>field.disabled=remove.checked||selections[i].accept===false);update();
    };
    for(const [selector,key] of [['[data-title]','title'],['[data-body]','body']]){const field=card.querySelector(selector);if(field)field.oninput=()=>{selections[i][key]=field.value;branch=null;update();};}
   }
   query('#audience-confirm').onclick=()=>{
    if(submitting)return;
    try{const chosen=current();if(!chosen.summary.changed)throw Error('请先调整方案。');if(typeof renderPage!=='function')throw Error('预览暂未加载，请刷新后重试。');preview(chosen);}
    catch(error){query('#audience-error').textContent=error.message;}
   };
   function preview(chosen){
    const content=query('#modal-content'),reviewNodes=document.createDocumentFragment(),references={},selectionIndices=visibleIndices();
    while(content.firstChild)reviewNodes.append(content.firstChild);
    let prepared=fitAudienceLayout(source,chosen).layout,index=0,expanded=false;
    const reflow=()=>{branch=null;prepared=fitAudienceLayout(source,chosen,{references}).layout;};
    const designText=record=>record.mode==='preserved'?'保留原页全部设计与对象':`沿用原稿第 ${source.pages.findIndex(p=>p.id===record.referencePageId)+1} 页的设计`;
    function draw(){
     const page=prepared.pages[index],record=prepared.records[index],reference=source.pages.find(p=>p.id===record.referencePageId);
     content.innerHTML=`${head('确认原稿版式')}<p class="audience-context">${escape(source.title)} → ${escape(plan.audience)}版 · ${prepared.pages.length} 页</p><p class="manual-help">保留页与调序页沿用原页；改写页和新增页使用原稿的设计元素与文字样式。左右对照实际效果，确认后保存并进入编辑器。</p><div class="audience-preview-toolbar"><button id="audience-preview-prev" ${index===0?'disabled':''}>上一页</button><label>查看页面<select id="audience-preview-page">${prepared.pages.map((p,i)=>`<option value="${i}" ${i===index?'selected':''}>${i+1}. ${escape(p.title||'（无标题）')}</option>`).join('')}</select></label><button id="audience-preview-next" ${index===prepared.pages.length-1?'disabled':''}>下一页</button></div><p class="audience-design-source" role="status">${escape(designText(record))}${record.note?' · '+escape(record.note):''}</p>${record.mode!=='preserved'?`<label class="audience-field">原稿设计参考页<select id="audience-reference">${source.pages.map((p,i)=>`<option value="${escape(p.id)}" ${p.id===record.referencePageId?'selected':''}>原第 ${i+1} 页 · ${escape(p.title||'（无标题）')}</option>`).join('')}</select></label>`:''}<div class="audience-layout-comparison"><section><h3>原稿参考页</h3><div id="audience-reference-canvas" class="audience-layout-canvas">${reference?renderPage(reference):'没有可用的原稿参考页'}</div></section><section><h3>改编后 · 第 ${index+1} 页</h3><div id="audience-result-canvas" class="audience-layout-canvas">${renderPage(page)}</div></section></div><details class="audience-preview-copy"><summary>核对本页完整文案</summary><strong>${escape(page.title)}</strong><p>${escape(page.body)}</p></details>${record.mode!=='preserved'?`<details class="audience-preview-edit"><summary>修改本页文案</summary><label class="audience-field">标题<input id="audience-preview-title" maxlength="500" value="${escape(page.title)}"></label><label class="audience-field">正文<textarea id="audience-preview-body" rows="6" maxlength="100000">${escape(page.body)}</textarea></label><button id="audience-preview-apply">应用文字并重新排版</button><p id="audience-edit-status" class="manual-help" role="status"></p></details>`:''}${prepared.issues.length?`<div class="audience-layout-issues" role="alert"><strong>还有 ${new Set(prepared.issues.map(i=>i.pageId)).size} 页还需要调整排版</strong><ul>${prepared.issues.map(issue=>{const i=prepared.pages.findIndex(p=>p.id===issue.pageId);return `<li><button data-issue-page="${i}">第 ${i+1} 页</button>：${escape(issue.message)}</li>`;}).join('')}</ul><p>已尝试按原稿分区调整布局与字号。可在“修改本页文案”中直接调整，或选择其他原稿参考页，再检查预览。</p></div>`:'<p class="manual-help">文案已完整排入页面，请检查实际效果。</p>'}<p id="audience-error" class="action-error" role="alert"></p><div class="audience-review-actions"><button id="audience-content-back">返回调整内容</button><button id="audience-layout-confirm" class="primary" ${prepared.issues.length?'disabled':''}>确认版式，创建版本</button></div>`;
     query('[data-close]').onclick=()=>{if(!submitting)modal.close();};
     const zoom=document.createElement('button');zoom.id='audience-preview-zoom';zoom.textContent=expanded?'并排对照':'放大改编页';zoom.setAttribute('aria-pressed',String(expanded));query('.audience-preview-toolbar').append(zoom);query('.audience-layout-comparison').classList.toggle('expanded',expanded);zoom.onclick=()=>{if(!applyText())return;expanded=!expanded;draw();};
     query('#audience-preview-prev').onclick=()=>{if(!applyText())return;index--;draw();};query('#audience-preview-next').onclick=()=>{if(!applyText())return;index++;draw();};
     query('#audience-preview-page').onchange=e=>{const next=Number(e.target.value);if(!applyText())return;index=next;draw();};
     for(const button of content.querySelectorAll('[data-issue-page]'))button.onclick=()=>{if(!applyText())return;index=Number(button.dataset.issuePage);draw();};
     const referenceSelect=query('#audience-reference');if(referenceSelect)referenceSelect.onchange=e=>{
      if(!applyText())return;references[record.entryIndex]=e.target.value;reflow();draw();
     };
     query('#audience-content-back').onclick=()=>{if(submitting||!applyText())return;branch=null;content.replaceChildren(reviewNodes);update();query('#audience-confirm').focus({preventScroll:true});};
     query('#audience-layout-confirm').onclick=save;
     const apply=query('#audience-preview-apply');
     if(apply){
      apply.onclick=()=>{if(applyText())draw();};
      for(const field of [query('#audience-preview-title'),query('#audience-preview-body')])field.oninput=()=>{query('#audience-layout-confirm').disabled=true;query('#audience-edit-status').textContent='文案有修改，点击“应用文字并重新排版”查看效果。';};
     }
     function applyText(){
      const title=query('#audience-preview-title'),body=query('#audience-preview-body');
      if(!title||title.value===page.title&&body.value===page.body)return true;
      try{
       const entries=chosen.entries.map((e,i)=>i===record.entryIndex?{...e,title:title.value,body:body.value}:e);
       chosen=validateAudiencePlan({message:chosen.message,narrative:chosen.narrative,entries},originalCopy);
       const selectionIndex=selectionIndices[record.entryIndex];
       Object.assign(selections[selectionIndex],{title:title.value,body:body.value});
       const card=reviewNodes.querySelector?reviewNodes.querySelector(`[data-audience-row="${selectionIndex}"]`):null;
       if(card){card.querySelector('[data-title]').value=title.value;card.querySelector('[data-body]').value=body.value;}
       reflow();return true;
      }catch(error){query('#audience-error').textContent=error.message;return false;}
     }
    }
    async function save(){
     if(submitting||prepared.issues.length)return;submitting=true;saving=true;
     const controls=[...content.querySelectorAll('button,select')];controls.forEach(b=>b.disabled=true);
     const button=query('#audience-layout-confirm');button.textContent='正在保存新版本…';query('#audience-error').textContent='';
     try{
      if(store.project?.id!==source.id||JSON.stringify(store.project.pages)!==fingerprint)throw Error('原稿已修改或切换，请重新生成方案；本次没有创建版本。');
      await store.flush();controller.signal.throwIfAborted();if(store.project.revision!==source.revision)throw Error('原稿版本已变化，请重新生成方案。');
      const latest=await request('/api/projects/'+encodeURIComponent(source.id),undefined,controller.signal);if(latest.revision!==source.revision)throw Error('服务器原稿已有更新，请重新打开原稿再生成方案。');
      if(store.project?.id!==source.id||JSON.stringify(store.project.pages)!==fingerprint)throw Error('原稿已有修改，请重新生成方案。');
      if(!branch)branch=createAudienceBranch(source,chosen,{audience:plan.audience,notes:plan.notes,id:crypto.randomUUID(),reviewId:crypto.randomUUID(),layout:prepared});
      await onConfirmed(branch,source);modal.close();
     }catch(error){draw();query('#audience-error').textContent=error.message||'保存失败，请重试。';query('#audience-layout-confirm').textContent='重试保存已确认版本';}
     finally{submitting=false;saving=false;}
    }
    draw();modal.scrollTop=0;
   };update();query('#audience-structure-title').focus({preventScroll:true});modal.scrollTop=0;
  }
 }
 function row(entry,index,source){
  const before=source.pages.find(page=>page.id===entry.sourcePageId),number=before?source.pages.indexOf(before)+1:null;
  return `<article class="audience-review-row" data-audience-row="${index}"><div class="audience-row-head"><h3 data-position>${names[entry.action]} · ${number?'原第 '+number+' 页':'新增页面'}</h3><div class="audience-row-options">${entry.action!=='keep'?`<label class="audience-accept"><input type="checkbox" data-accept checked>${entry.action==='delete'?'删除此页':entry.action==='add'?'加入此页':'采用改写'}</label>`:''}${before&&entry.action!=='delete'?'<label class="audience-accept"><input type="checkbox" data-remove>从新版本删除此页</label>':''}</div></div><p class="audience-reason" data-reason>${escape(entry.reason)}</p>${entry.questions.length?`<p class="audience-questions"><strong>待补充</strong>：${entry.questions.map(escape).join('；')}</p>`:''}<div class="audience-comparison"><section><h4>原稿内容</h4>${before?`<strong>${escape(before.title)}</strong><p>${escape(before.body)||'（无正文）'}</p>`:'<p>原稿没有此页</p>'}</section><section><h4>建议改后内容${entry.action==='delete'?'':' · 可直接修改'}</h4>${entry.action==='delete'?'<p data-delete-copy>从新版本删除此页，原稿保留。</p>':`<p data-remove-note hidden>此页将从新版本删除，原稿保留。</p><label>标题<input data-title maxlength="500" aria-label="第 ${index+1} 项建议标题" value="${escape(entry.title)}"></label><label>正文<textarea data-body rows="6" maxlength="100000" aria-label="第 ${index+1} 项建议正文">${escape(entry.body)}</textarea></label>`}</section></div></article>`;
 }
 function history(){
  const project=store.project,record=project?.audienceReview;
  if(!record){const modal=dialog(`${head('这份版本没有改编记录')}<p class="manual-help">旧版功能只复制文稿，没有保存逐页增删改记录。可以重新生成改编方案，逐项确认后保存新版本。</p><div class="modal-actions"><button data-close>关闭</button><button id="audience-replan" class="primary">重新规划改编</button></div>`);document.querySelector('#audience-replan').onclick=()=>{modal.addEventListener('close',()=>open({audience:project?.audienceLabel||'',notes:'明确合作方式与交付要求'}),{once:true});modal.close();};return;}
  let nextPage=0;
  const entries=record.entries.map(entry=>{const fallbackTarget=entry.action==='delete'?null:++nextPage;return {...entry,sourceIndex:entry.sourceIndex??((record.sourcePages||[]).findIndex(p=>p.id===entry.sourcePageId)+1||null),targetIndex:entry.targetIndex??fallbackTarget,moved:!!entry.moved};});
  const modal=dialog(`${head('已确认的改动清单')}<p class="audience-context">${escape(record.sourceTitle)} → ${escape(record.audience)}版</p><p class="audience-summary">${countText(record.summary)}</p><p class="manual-help">以下为创建此版本时确认的内容；之后的手动编辑另行保存。目的：${escape(record.notes||'适配新受众')}</p><section class="audience-structure"><h3>已确认的叙事与目录</h3>${record.narrative?`<p class="audience-history-narrative">${escape(record.narrative)}</p>`:''}<ol class="audience-outline">${entries.filter(entry=>entry.targetIndex).sort((a,b)=>a.targetIndex-b.targetIndex).map(entry=>`<li><div><strong>${entry.targetIndex}. ${escape(entry.after?.title||'（无标题）')}</strong><span>${positionText(entry)} · ${names[entry.action]}</span></div></li>`).join('')}</ol></section><div class="audience-review-list">${entries.map(entry=>`<article class="audience-review-row"><h3>${names[entry.action]} · ${positionText(entry)}</h3><p class="audience-reason">${escape(entry.reason)}</p>${entry.referencePageId?`<p class="audience-design-source">${entry.designMode==='preserved'?'保留原页全部设计与对象':'沿用原稿第 '+entry.referenceIndex+' 页设计'} · 已确认版式${entry.designNote?' · '+escape(entry.designNote):''}</p>`:''}<div class="audience-comparison"><section><h4>原稿内容</h4><strong>${escape(entry.before?.title||'原稿没有此页')}</strong><p>${escape(entry.before?.body||'')}</p></section><section><h4>确认后的内容</h4><strong>${escape(entry.after?.title||'从新版本删除')}</strong><p>${escape(entry.after?.body||'')}</p></section></div></article>`).join('')}</div><div class="modal-actions"><button data-close>关闭清单</button></div>`);
  modal.classList.add('audience-review-dialog');modal.addEventListener('close',()=>modal.classList.remove('audience-review-dialog'),{once:true});
 }
 return {open,history};
}
