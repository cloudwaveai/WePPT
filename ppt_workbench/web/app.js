(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const icon = (name, extra = '') => { const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('class',`icon ${extra}`); const use = document.createElementNS('http://www.w3.org/2000/svg','use'); use.setAttribute('href',`#i-${name}`); svg.append(use); return svg; };
  const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = text; return e; };
  const ui = { state: null, connected: false, fetching: false, posting: false, previewKey: '', slideKey: '', messageKey: '', deckKey: '', revisionKey: '', deliveryKey: '', qualityKey: '', releaseKey: '', pinnedSlideId: null, explicitPageEditing: false, draftTarget: null, stagedChoiceGroups:new Map(), activeFrame: null, pendingFrame: null, object: null, uploads: [], optimistic: [], dragDepth: 0, mobileView: 'chat', reviewBusy: false, undoBusy: false, deckReviewBusy: false, deckReviewSnapshot: null, operatorIds:new Map(), agentBusy: false, deckBusy: false, deliveryBusy: false, qualityBusy: false, progressOpen: new Set(), measure: { projectId:null, active:null, entries:new Map(), timer:null }, toastTimer: null, failures: 0 };
  const design = { templates:[], filter:'recommended', role:'all', category:'all', query:'', edit:null, dirty:false, saving:false, applying:false, target:null, smartAvailable:false, smartBusy:false, smartRequestId:0, smartRanked:false, stripCategory:'recommended' };
  const editor = {scene:null,key:'',loadingKey:'',busy:false,suggesting:false,proposal:null,history:null,zoom:1};
  const previewLoader=globalThis.WePPTPreviewLoader && globalThis.IntersectionObserver ? new globalThis.WePPTPreviewLoader() : null;
  function lazyPreview(frame,url){if(previewLoader)previewLoader.watch(frame,url);else{frame.loading='lazy';frame.src=url;}}
  function clearPreviews(root){previewLoader?.clear(root);}
  function editorReady() {
    const slide=activeSlide();
    return !!slide?.hasPreview && !slide.stale && ui.connected && !editor.busy && !design.saving && !(ui.state?.jobs || []).some(isBusy);
  }
  function selectedEditorObject() {
    if(editor.key!==previewIdentity(activeSlide()))return null;
    return editor.scene?.objects.find(o=>o.id===ui.object?.id) || null;
  }
  function renderEditorTools() {
    if($('diagram-image')){
      $('diagram-image').hidden=!activeSlide()?.hasDiagram;
      $('diagram-image').disabled=!editorReady() || ui.posting || (ui.state?.imageBatches || []).some(j=>['pending','running'].includes(j.status));
    }
    const object=selectedEditorObject(), ready=editorReady(), text=object?.type==='text';
    $('text-format').disabled=!ready || !text;
    $('object-text').disabled=editor.busy || design.saving;$('save-object-text').disabled=editor.busy || design.saving;
    if(ui.activeFrame)ui.activeFrame.inert=editor.busy || !canSelectFrame(ui.activeFrame);
    $('format-selection').textContent=object?(text?'文本框':object.type==='image'?'图片':'形状'):'选择对象以编辑';
    if(text){
      if(document.activeElement!==$('font-size'))$('font-size').value=object.fontSize;
      const family=$('font-family');
      if(![...family.options].some(o=>o.value===object.fontFamily))family.add(new Option(object.fontFamily,object.fontFamily));
      if(document.activeElement!==family)family.value=object.fontFamily;
      if(document.activeElement!==$('font-color'))$('font-color').value=object.color;
      $('font-bold').setAttribute('aria-pressed',String(object.bold));$('font-italic').setAttribute('aria-pressed',String(object.italic));
      document.querySelectorAll('[data-align]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.align===object.align)));
    }
    const same=editor.history?.sceneRevision===activeSlide()?.sceneRevision;
    $('undo-button').disabled=!(ui.connected && ui.state?.documentHistory?.canUndo && !editor.busy) && (!ready || !same || !editor.history?.canUndo);
    $('redo-button').disabled=!ready || !same || !editor.history?.canRedo;
    $('ai-target').textContent=object?`所选${text?'文字':object.type==='image'?'图片':'对象'}`:activeSlide()?`第 ${slideIndex()+1} 页`:'生成初稿后可推荐';
    const mode=ui.state?.agent?.mode;
    $('ai-mode').textContent=ui.state?.selectedModelProfile?.model || (mode==='codex'?'Codex':mode==='claude'?'Claude Code':mode==='api'?'模型 API':'未连接模型');
    document.querySelectorAll('[data-ai-action]').forEach(b=>{b.disabled=!ready || editor.suggesting || (['concise','headline','polish'].includes(b.dataset.aiAction) && !text);});
    $('ai-custom').disabled=!ready || editor.suggesting;
    if(editor.proposal && $('ai-preview-dialog').open){
      const target=ui.state?.slides.find(s=>s.id===editor.proposal.slideId);
      const stale=!target || target.sceneRevision!==editor.proposal.sceneRevision || target.stale;
      $('ai-apply').disabled=editor.busy || stale;
      if(stale)$('ai-preview-error').textContent='页面已更新，这条建议不能覆盖新版本。请关闭并重新生成。';
    }
  }
  async function syncEditor() {
    renderEditorTools();
    const slide=activeSlide(),key=previewIdentity(slide);
    if(!slide?.hasPreview){editor.scene=null;editor.key='';editor.history=null;return;}
    if(editor.key===key || editor.loadingKey===key)return;
    editor.loadingKey=key;
    try{
      const [scene,history]=await Promise.all([api(`/api/scene?slide=${encodeURIComponent(slide.id)}&metadata=1`),api(`/api/editor/history?slide=${encodeURIComponent(slide.id)}`)]);
      if(key!==previewIdentity(activeSlide()) || scene.sceneRevision!==slide.sceneRevision)return;
      editor.scene=scene.scene;editor.key=key;editor.history=history;
      $('editor-save-state').textContent='已保存';renderEditorTools();
    }catch(error){$('editor-save-state').textContent='编辑信息载入失败';}
    finally{if(editor.loadingKey===key)editor.loadingKey='';}
  }
  async function commitProperties(properties, objectId=ui.object?.id, expectedFrame=null) {
    if(!editorReady() || !objectId || (expectedFrame && !canSelectFrame(expectedFrame))){toast('页面正在更新，请稍后再编辑。');return false;}
    const slide=activeSlide();
    if(design.dirty && design.edit?.objectId!==objectId){toast('请先保存正在编辑的文字。');return false;}
    if(design.dirty)properties={...properties,text:$('object-text').value};
    editor.busy=true;$('editor-save-state').textContent='正在保存…';renderEditorTools();
    try{
      await api('/api/edit','POST',{slideId:slide.id,sceneRevision:slide.sceneRevision,changes:[{objectId,properties}]});
      design.dirty=false;design.edit=null;$('text-editor').hidden=true;ui.draftTarget=null;editor.key='';
      await refreshState(true);await syncEditor();$('editor-save-state').textContent='已保存';return true;
    }catch(error){toast(error.message);$('editor-save-state').textContent='保存失败，请重试';return false;}
    finally{editor.busy=false;renderEditorTools();}
  }
  async function editorHistory(action) {
    if(action==='undo' && ui.state?.documentHistory?.canUndo && !design.dirty)return documentAction('undo');
    if(!editorReady())return;
    if(design.dirty){toast('请先保存文字；正在输入时可使用系统撤销。');return;}
    const slide=activeSlide();editor.busy=true;renderEditorTools();
    try{await api('/api/editor/history','POST',{slideId:slide.id,sceneRevision:slide.sceneRevision,action});design.edit=null;$('text-editor').hidden=true;editor.key='';await refreshState(true);await syncEditor();toast(action==='undo'?'已撤销编辑。':'已重做编辑。');}
    catch(error){toast(error.message);}
    finally{editor.busy=false;renderEditorTools();}
  }
  function showAssistant(show=true) {
    document.querySelector('.workspace').classList.toggle('assistant-hidden',!show);
    $('toggle-assistant').setAttribute('aria-expanded',String(show));
    if(innerWidth<=760)switchMobile(show?'chat':'preview');
    requestAnimationFrame(fitCanvas);
  }
  let templateMatchSequence=0;
  function closeTemplateMatches(){
    templateMatchSequence++;
    $('assistant-panel').classList.remove('matching-templates');
    $('template-matches').hidden=true;
  }
  async function requestTemplateMatches(){
    await loadTemplates();design.filter='all';design.category='all';design.role='all';design.query='';
    $('template-search').value='';renderTemplates();$('templates-panel').showModal();return;
  }
  $('template-match-close').addEventListener('click',closeTemplateMatches);
  $('template-match-all').addEventListener('click',requestTemplateMatches);
  async function requestSuggestion(action) {
    if(['layout','hierarchy','custom'].includes(action))return requestTemplateMatches();
    if(!editorReady() || editor.suggesting)return;
    if(design.dirty){toast('请先保存文字，再生成建议。');return;}
    if(!['codex','claude','api'].includes(ui.state?.agent?.mode)){
      $('ai-status').textContent='请先连接 Codex 或 Claude Code，再生成 AI 建议。';openConnectionDialog();return;
    }
    const slide=activeSlide(),target={slideId:slide.id,sceneRevision:slide.sceneRevision,objectId:ui.object?.id || null};
    editor.suggesting=true;showAssistant();$('ai-status').textContent='正在生成建议，原稿保持不变…';renderEditorTools();
    try{
      const result=await api('/api/editor/suggest','POST',{...target,action,instruction:action==='custom'?$('ai-instruction').value.trim():''});
      editor.proposal=result;
      $('ai-preview-reply').textContent=result.reply;
      $('ai-before').srcdoc=result.beforeHtml;$('ai-after').srcdoc=result.afterHtml;
      const list=$('ai-change-list');list.replaceChildren();
      result.changes.forEach(change=>{const row=node('div','ai-change-row');row.append(node('strong','',change.objectId),node('p','','修改前：\n'+readableChange(change.before)),node('p','','修改后：\n'+readableChange(change.after)));list.append(row);});
      $('ai-preview-error').textContent='';$('ai-preview-dialog').showModal();$('ai-status').textContent='建议已生成，尚未应用。';
    }catch(error){$('ai-status').textContent=error.message;}
    finally{editor.suggesting=false;renderEditorTools();}
  }
  async function applySuggestion() {
    if(!editor.proposal || editor.busy || $('ai-apply').disabled)return;
    if(design.dirty){$('ai-preview-error').textContent='还有未保存的文字，请先关闭建议并保存。';return;}
    editor.busy=true;renderEditorTools();
    try{await api('/api/editor/apply','POST',{proposalId:editor.proposal.proposalId});$('ai-preview-dialog').close();editor.proposal=null;editor.key='';design.edit=null;await refreshState(true);await syncEditor();$('ai-status').textContent='建议已应用，可使用撤销恢复。';}
    catch(error){$('ai-preview-error').textContent=error.message;}
    finally{editor.busy=false;renderEditorTools();}
  }
  function arrangeEditorPanels() {
    const strip=document.querySelector('.filmstrip-wrap');
    const destination=document.querySelector(innerWidth<=760?'.preview-panel':'.slides-pane');
    if(strip.parentElement!==destination)destination.append(strip);
  }
  function setZoom(value) {
    editor.zoom=Math.min(1.5,Math.max(.5,value));$('canvas-zoom').value=Math.round(editor.zoom*100);$('zoom-label').textContent=Math.round(editor.zoom*100)+'%';fitCanvas();
  }
  function editorShortcut(event) {
    const typing=event.target?.isContentEditable || ['INPUT','TEXTAREA','SELECT'].includes(event.target?.tagName);
    if(!(event.metaKey||event.ctrlKey))return;
    const key=event.key.toLowerCase();
    if(key==='s'){event.preventDefault();if(design.dirty)saveText();else toast('页面修改会自动保存。');return;}
    if(typing || document.querySelector('dialog[open]'))return;
    if(key==='z'||key==='y'){event.preventDefault();editorHistory(key==='y'||event.shiftKey?'redo':'undo');}
    if(key==='b' || key==='i'){const obj=selectedEditorObject();if(obj?.type==='text'){event.preventDefault();commitProperties(key==='b'?{bold:!obj.bold}:{italic:!obj.italic});}}
  }

  const activeSlide = () => ui.state?.slides?.find(s => s.id === (ui.pinnedSlideId || ui.state.selectedSlideId)) || ui.state?.slides?.[0] || null;
  const slideIndex = () => Math.max(0, (ui.state?.slides || []).findIndex(s => s.id === activeSlide()?.id));
  const isBusy = (job) => ['queued','pending','running','processing','claimed'].includes(String(job.status || '').toLowerCase());
  const time = (value) => { if (!value) return ''; const d = new Date(value); return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false}); };
  const requestId = () => globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const messageError = (data, fallback) => typeof data?.error === 'string' ? data.error : data?.error?.message || data?.message || fallback;
  const hasComposerDraft = () => !!$('message-input').value.trim() || ui.uploads.length > 0 || design.dirty;
  function pendingDeckQuestion() {
    const deck=ui.state?.deck;
    if(deck?.status!=='blocked' || deck.lastError?.code!=='PAGE_NEEDS_INPUT' || !Number(deck.currentPage))return null;
    return {kind:'deck-question',scope:'deck',pageId:null,objectId:null,deckId:deck.id,deckPageIndex:Number(deck.currentPage),choiceMessageId:deck.pendingQuestionMessageId || deck.lastError.questionMessageId || null,replyToDeckPage:true};
  }
  function pageMessageTarget() {
    return {kind:'page',scope:'page',pageId:ui.object?.pageId || activeSlide()?.id || null,objectId:ui.object?.id || null,objectLabel:ui.object?.label || null};
  }
  function currentMessageTarget() {
    if(ui.draftTarget)return ui.draftTarget;
    const question=pendingDeckQuestion();
    if(question && !ui.object && !ui.explicitPageEditing)return question;
    return ui.object || ui.explicitPageEditing ? pageMessageTarget() : {kind:'deck',scope:'deck',pageId:null,objectId:null};
  }
  function sameQuestion(a,b) {
    return !!a && !!b && a.kind==='deck-question' && b.kind==='deck-question' && a.deckId===b.deckId && a.deckPageIndex===b.deckPageIndex && a.choiceMessageId===b.choiceMessageId;
  }
  function renderComposerScope() {
    const target=currentMessageTarget(),question=pendingDeckQuestion(),answering=target.kind==='deck-question';
    const pageIndex=(ui.state?.slides || []).findIndex(s=>s.id===target.pageId);
    $('page-scope').textContent=answering?`回答第 ${target.deckPageIndex} 页的问题`:target.kind==='deck'?'整稿反馈':pageIndex>=0?`当前第 ${pageIndex+1} 页`:'当前页';
    $('composer').classList.toggle('answering-question',answering);
    $('question-scope-note').hidden=!answering;
    $('question-scope-note').textContent=answering && !sameQuestion(target,question)?'原问题已变化，输入仍绑定原问题。请先复制保存输入，再切换到当前问题。':'补充将用于这页，发送后自动继续；这条回答也计入一轮输入。';
    $('reply-question').hidden=!question || sameQuestion(target,question);
    $('reply-question').textContent=question?`回答第 ${question.deckPageIndex} 页的问题`:'';
    $('reply-question').disabled=hasComposerDraft();
    $('reply-question').title=hasComposerDraft()?'请先发送或保存当前输入，再切换回答目标。':'将下一条消息用于待生成页的补充材料';
    $('object-scope').hidden=answering || !target.objectId;
    $('object-scope-label').textContent=target.objectId?`仅修改：${target.objectLabel || target.objectId}`:'';
    $('scope-deck').setAttribute('aria-pressed',String(target.kind!=='page'));
    $('scope-page').setAttribute('aria-pressed',String(target.kind==='page'));
    $('scope-deck').disabled=hasComposerDraft();$('scope-page').disabled=hasComposerDraft() || !activeSlide();
    $('scope-switch-note').textContent=target.objectId?'已固定选中对象':answering?'补充当前待生成页':target.kind==='deck'?'一条消息可涉及多页':'只调整当前页';
    $('preview-instruction').replaceChildren(icon('cursor','small'),document.createTextNode(target.objectId?`已选中「${target.objectLabel || target.objectId}」，在对话里描述修改`:'双击文字编辑，拖动对象调整位置'));
  }

  function chooseScope(scope) {
    if(hasComposerDraft()){toast('当前输入已固定目标，请先发送或保存，再切换反馈范围。');return;}
    if(scope==='page' && !activeSlide())return;
    ui.explicitPageEditing=scope==='page';ui.draftTarget=null;
    if(scope==='page')ui.pinnedSlideId=activeSlide().id;
    clearObject();renderComposerScope();$('message-input').focus();
  }
  const propertyNames = {text:'文字',fontSize:'字号',color:'文字颜色',background:'背景',fill:'填充',stroke:'描边',strokeWidth:'线宽',bold:'加粗',align:'对齐',x:'横向位置',y:'纵向位置',w:'宽度',h:'高度',src:'图片',fontFamily:'字体',radius:'圆角'};
  const outlineTemplate = `按大纲排版
# [整套演示稿的标题]
用途：[这份 PPT 用来做什么]
听众：[谁会阅读]
Logo：[本次不使用，或注明已提供的素材]

## 封面｜[你的主标题]
结论：[用一句话说明这份演示稿想表达什么]
[署名与日期等真实信息]

## 内容｜[这一页要讲的观点]
结论：[这一页最重要的结论]
[你提供的第一条内容]
[你提供的第二条内容]

## 结束｜[希望读者采取的行动]
结论：[明确的下一步]
[具体安排或待补信息]`;
  const deckPageLabels = { queued:'待制作', pending:'待制作', generating:'制作中', running:'制作中', complete:'已生成', completed:'已生成', failed:'未完成', blocked:'待处理', cancelled:'已停止', canceled:'已停止' };
  function readableChange(value) {
    if (value === null || value === undefined) return '无';
    if (typeof value !== 'object') return String(value);
    return Object.entries(value).map(([key,val])=>`${propertyNames[key]||key}：${key==='src'&&String(val).startsWith('data:')?'图片已更新':typeof val==='boolean'?(val?'是':'否'):String(val)}`).join('\n');
  }

  async function api(path, method = 'GET', payload) {
    const controller = new AbortController();
    const largePreview = /^\/api\/(?:scene\?|templates(?:\/|\?|$))/.test(path);
    const timer = setTimeout(() => controller.abort(), path.startsWith('/api/templates/adapt') ? 600000 : method === 'GET' && !largePreview ? 30000 : 90000);
    try {
      const headers = { Accept: 'application/json' };
      const projectId = new URLSearchParams(location.search).get('project') || ui.state?.projectId;
      if (projectId) headers['X-WePPT-Project'] = projectId;
      if (payload !== undefined) headers['Content-Type'] = 'application/json';
      if (ui.state?.csrfToken) headers['X-PPT-CSRF'] = ui.state.csrfToken;
      const response = await fetch(path, { method, headers, credentials:'same-origin', cache:'no-store', signal:controller.signal, body:payload === undefined ? undefined : JSON.stringify(payload) });
      let data;
      try { data = await response.json(); } catch { throw new Error(response.ok ? '服务返回了无法读取的结果。' : `请求未完成（${response.status}）。`); }
      if (!response.ok || data?.ok === false) throw new Error(messageError(data, `请求未完成（${response.status}）。`));
      return data?.ok === true && data.data ? data.data : data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('连接等待较久，请稍后重试。已保存的页面不会丢失。');
      throw error;
    } finally { clearTimeout(timer); }
  }

  function toast(message, milliseconds = 4300) {
    $('toast').textContent = message; $('toast').hidden = false;
    clearTimeout(ui.toastTimer); ui.toastTimer = setTimeout(() => { $('toast').hidden = true; }, milliseconds);
  }

  function setConnection(connected, error) {
    ui.connected = connected;
    $('network-banner').hidden = connected;
    if (!connected) $('network-message').textContent = location.protocol === 'file:' ? '请运行 pptctl studio，通过它给出的本地地址打开工作台。' : (error || '暂时无法连接工作台，已显示的内容仍保留。');
    updateAgent(); updateSend();
  }

  let fullStateReadAt=0;
  async function refreshState(force = false) {
    if (ui.fetching) return;
    ui.fetching = true;
    try {
      const incremental=!force && ui.state && Date.now()-fullStateReadAt<10000;
      const query=incremental?'?'+new URLSearchParams({since:String(ui.state.version),sinceProject:ui.state.projectId}):'';
      const state = await api('/api/state'+query);
      if(state.unchanged===true){ui.failures=0;setConnection(true);}
      else{fullStateReadAt=Date.now();applyState(state, force);}
    } catch (error) {
      ui.failures++;
      if (ui.failures > 1 || !ui.state || force) setConnection(false, error.message);
    } finally { ui.fetching = false; }
  }

  function applyState(result, force = false) {
    const state = result?.state || result;
    if (!state || !Array.isArray(state.slides) || !Array.isArray(state.messages)) throw new Error('工作台状态不完整，请刷新或重新启动服务。');
    if (ui.state?.projectId === state.projectId && Number.isFinite(state.version) && Number.isFinite(ui.state.version) && state.version < ui.state.version) return;
    const oldPage = activeSlide()?.id;
    ui.state = state; ui.failures = 0; setConnection(true);
    if (oldPage && oldPage !== activeSlide()?.id) clearObject();
    reconcileOptimistic(); renderState(force);
  }

  function reconcileOptimistic() {
    const messages = ui.state?.messages || [];
    ui.optimistic = ui.optimistic.filter(local => !messages.some(m => m.clientMessageId === local.clientMessageId || m.id === local.clientMessageId || (local.accepted && m.role === 'user' && m.text === local.text && Math.abs(new Date(m.createdAt || 0).getTime() - local.sentAt) < 120000)));
  }

  function renderChatTemplate(state, slide) {
    const templateId=slide?.hasPreview ? slide.sceneTemplateId : !slide ? state.selectedTemplateId : null;
    const template=design.templates.find(item=>item.id===templateId);
    const name=template?.name || (templateId ? (design.loading ? '正在加载样式' : '样式信息不可用') : '');
    const staleLabel=slide?.previewContentStale ? '旧预览' : slide?.previewMaterialUnavailable ? '素材待补充' : slide?.stale ? '预览待核对' : '';
    const label=name ? `${staleLabel ? staleLabel+' · ' : ''}${slide ? '本页样式' : '已选样式'}：${name}` : (staleLabel ? `${staleLabel} · 样式信息不可用` : slide ? '本页尚无样式预览' : '尚未选择样式');
    const container=$('chat-template'), key=JSON.stringify([label,template?.previewUrl || '']);
    if(container.dataset.key!==key){
      clearPreviews(container);
      container.dataset.key=key;
      const children=[];
      if(template?.previewUrl){
        const preview=node('div','chat-template-preview'), frame=node('iframe');
        frame.title=`${template.name}模板预览`;frame.tabIndex=-1;frame.setAttribute('sandbox','allow-scripts');frame.setAttribute('aria-hidden','true');lazyPreview(frame,template.previewUrl);
        preview.append(frame);children.push(preview);
      }
      children.push(node('span','chat-template-label',label));container.replaceChildren(...children);
    }
    $('template-suggestion-text').textContent=name?label:slide?'想换个排法？根据这页内容选一个样式。':'先确认内容；设计案例帮助确定视觉方向。';
  }

  function renderState(force = false) {
    const state = ui.state, slide = activeSlide();
    $('project-title').textContent = state.project?.title || '新的演示稿';
    renderChatTemplate(state,slide);
    if(design.edit && !design.dirty && design.edit.key!==previewIdentity(activeSlide())){design.edit=null;$('text-editor').hidden=true;}
    const demo = !!(state.demo || state.isDemo || state.project?.isDemo || state.projectId === 'demo');
    $('demo-badge').hidden = !demo;
    const localOutline = state.agent?.mode === 'outline' || (state.agent?.mode === 'manual' && state.deck?.execution === 'outline');
    $('demo-controls').hidden = !((demo && state.agent?.mode === 'manual') || (localOutline && state.slides.length));
    $('local-controls-label').textContent = localOutline ? '本地排版 · 支持这些精确修改' : '本地演示 · 这些指令可直接运行';
    $('demo-button').hidden = state.slides.length > 0 || !!state.deck;
    document.title = `${state.project?.title || 'WePPT'} · 演示文稿编辑器`;
    $('mobile-page-count').textContent = state.slides.length ? String(state.slides.length) : '';
    $('slide-count').textContent = `${state.slides.length} 页`;
    updateExport();
    $('preview-heading').textContent = slide?.title || '页面预览';
    $('preview-kicker').textContent = slide ? `第 ${slideIndex() + 1} 页 · 根据当前内容生成` : '把想法变成看得见的一页';
    renderComposerScope();
    syncTemplateTarget();
    $('page-review-row').hidden = !slide;
    $('page-position-label').textContent = slide ? `${slideIndex() + 1} / ${state.slides.length}` : '';
    $('previous-page').disabled = slideIndex() <= 0;
    $('next-page').disabled = slideIndex() >= state.slides.length - 1;
    $('undo-button').disabled = ui.undoBusy || !slide || Number(slide.sceneRevision || 0) < 2;
    const reviewed = slide && (slide.reviewedSceneRevision === slide.sceneRevision || slide.approvedSceneRevision === slide.sceneRevision || slide.reviewed === true);
    $('review-button').classList.toggle('reviewed', !!reviewed);
    $('review-button').querySelector('span').textContent = reviewed ? '本页已认可' : '认可这一页';
    $('review-button').disabled = ui.reviewBusy || !slide?.hasPreview || !!slide?.stale || reviewed;
    updateAgent(); renderDelivery(); renderDeckProgress(); renderQuality(); renderRelease(); renderMessages(force); renderSlides(force); renderPreview(); renderDocumentTools(); renderBackgroundTasks(); renderSourceStatus(); restoreComposerDraft(); renderStyleBadge(); renderDerivedLine(); $('style-derive').hidden=!ui.state.styleReference;$('style-restyle').hidden=!ui.state.styleReference; updateJobStatus(); updateSend(); updateConnectionDialog(); updateReviewDialog(); fitCanvas(); scheduleMeasurements(); syncEditor();
  }

  function updateAgent() {
    const agent = ui.state?.agent || {};
    const modes = { claude:'Claude Code', codex:'Codex', manual:'Coding Agent', outline:'本地大纲排版' };
    const localWork=ui.state?.deck?.execution==='outline' && ui.state?.deck?.status==='running';
    let label = ui.state?.selectedModelProfile?.label || modes[agent.mode] || agent.label || 'Coding Agent', dot = '';
    if (!ui.connected) { label = ui.state ? '连接中断' : '等待工作台'; dot = 'offline'; }
    else if (localWork) { label = '本地大纲排版 · 制作中'; dot = 'busy'; }
    else if (['running','busy','processing'].includes(agent.status) || ui.state?.jobs?.some(j=>['running','processing','claimed'].includes(j.status))) { label += ' · 处理中'; dot = 'busy'; }
    else if (agent.mode === 'manual') { label = 'Coding Agent 模式'; dot = 'waiting'; }
    else if (agent.mode === 'outline') { label = '本地大纲排版'; }
    else if (!agent.available) { label += ' · 未连接'; dot = 'waiting'; }
    else { label += ' · 已选择'; }
    $('agent-status').textContent = label; $('agent-dot').className = `status-dot ${dot}`;
    $('chat-footnote').textContent = agent.mode === 'outline' || localWork ? '本地排版不调用模型。提供完整逐页文字后自动制作。' : agent.mode === 'manual' ? '网页消息需由 Coding Agent 领取；明确的大纲排版可本地完成。' : !agent.available ? `${modes[agent.mode] || '执行器'} 尚未连接。消息会保留，连接后才能处理。` : '页面逐页生成，预览自动更新。Shift + Enter 换行。';
    const unavailable = ui.connected && ['claude','codex'].includes(agent.mode) && !agent.available && !localWork;
    $('mode-notice').hidden = !unavailable;
    $('mode-notice-text').textContent = unavailable ? `${modes[agent.mode]} 尚未就绪。普通对话不会开始生成，可先连接客户端，或使用已写好的大纲本地排版。` : '';
  }

  const roundStatusLabels={processing:'制作中',checking:'检查中',waiting_agent:'等待执行器',needs_input:'需要补充',ready:'本轮结果已输出',failed:'本轮未完成',cancelled:'本轮已停止'};
  function snapshotRows(snapshot) {
    const value=snapshot?.slides || snapshot?.pages || snapshot;
    if(Array.isArray(value))return value;
    if(value && typeof value==='object')return Object.entries(value).filter(([key])=>/^S\d+$/.test(key)).map(([slideId,revision])=>typeof revision==='object'?{slideId,...revision}:{slideId,sceneRevision:revision});
    return [];
  }
  function renderDelivery() {
    const delivery=ui.state?.delivery;
    const count=Math.max(0,Number(delivery?.inputCount)||0);
    $('delivery-panel').classList.remove('exceeded');
    $('delivery-round-count').textContent=`${count} 轮输入`;
    document.querySelectorAll('[data-round-stage]').forEach(item=>{const n=Number(item.dataset.roundStage);item.classList.toggle('reached',count>=n);item.classList.toggle('current',count===n);});
    const current=delivery?.activeRound,status=current?.status || delivery?.status;
    let text=count?`已接收 ${count} 轮输入，已输出 ${Math.max(0,Number(delivery?.outputCount)||0)} 轮结果。`:'用途、逐页想法和资料可以一起提交。';
    if(current)text=`第 ${current.number} 轮 · ${roundStatusLabels[current.status] || '处理中'}。后台逐页制作和检查，完成后集中给出结果。`;
    else if(status==='needs_input')text='本轮有待补充内容。请把答案和其他反馈一起发送，补充也计入下一轮。';
    else if(status==='failed')text='本轮没有完成。可重试原任务，重试不另算用户输入。';
    $('delivery-status').textContent=text;
    $('delivery-budget-note').textContent='可以继续补充或修改；后台制作、检查和任务重试不增加输入轮次。';
    const rounds=delivery?.rounds || [],key=JSON.stringify(rounds);
    $('delivery-history').hidden=!rounds.length;
    $('delivery-history-title').textContent=`每轮记录 · ${rounds.length} 轮输入 / ${Math.max(0,Number(delivery?.outputCount)||0)} 轮输出`;
    if(key===ui.deliveryKey)return;
    ui.deliveryKey=key;
    const host=$('delivery-history-list');host.replaceChildren();
    for(const round of rounds){
      const item=node('li',`delivery-round ${round.status || ''}`);
      const head=node('div','delivery-round-heading');head.append(node('strong','',`第 ${round.number} 轮`),node('span','',roundStatusLabels[round.status] || '已记录'));item.append(head);
      const input=node('p','delivery-round-input',String(round.inputText || '').slice(0,180));input.title=round.inputText || '';item.append(input);
      const changed=(round.changedSlideIds || []).map(id=>{const n=ui.state?.slides?.findIndex(s=>s.id===id);return n>=0?String(n+1):id;});
      if(changed.length)item.append(node('p','delivery-round-pages',`涉及页面：${changed.join('、')}`));
      const rows=snapshotRows(round.snapshot);
      if(rows.length){
        const details=node('details','round-snapshot');details.append(node('summary','',round.snapshotStale?'当时版本记录 · 页面随后有变化':'本轮输出对应的页面版本'));
        const list=node('ul');
        for(const row of rows){const id=row.slideId || row.id,n=ui.state?.slides?.findIndex(s=>s.id===id);list.append(node('li','',`${n>=0?'第 '+(n+1)+' 页':id || '页面'} · v${row.sceneRevision ?? row.revision ?? '?'}`));}
        details.append(list);if(round.snapshotStale)details.append(node('p','','右侧显示当前稿件；这份记录只说明本轮输出时采用的版本。'));item.append(details);
      }
      if(round.status==='failed'){
        const retry=node('button','round-retry','重试本轮');retry.type='button';retry.disabled=ui.deliveryBusy || !ui.connected;retry.addEventListener('click',()=>controlDelivery('retry',round.id));item.append(retry);
      }
      host.append(item);
    }
  }

  function qualitySource() {return ui.state?.quality || ui.state?.delivery?.qualitySummary || null;}
  function renderQuality() {
    const quality=qualitySource(),slides=ui.state?.slides || [];
    $('quality-panel').hidden=!slides.length;
    if(!slides.length)return;
    const measuring=!!ui.measure.active;
    const labels={not_checked:'尚未检查',stale:'页面已变化',needs_attention:'有待解决问题',awaiting_browser:'等待浏览器测量',ready_to_review:'可审阅版式',measuring:'正在测量'};
    const status=measuring?'measuring':quality?.status || 'not_checked';
    $('quality-panel').dataset.status=status;$('quality-state-label').textContent=labels[status] || '检查待完成';
    const measured=Math.max(0,Number(quality?.browser?.measured)||0),total=Math.max(slides.length,Number(quality?.browser?.total)||0);
    $('quality-measure-progress').textContent=`浏览器实测 ${Math.min(measured,total)} / ${total} 页`;
    const messages={
      not_checked:'页面生成后会自动检查，并逐页测量实际文字与图片状态。',
      stale:'页面已变化，之前的检查结果不再代表当前版本，正在重新检查。',
      needs_attention:'检查发现仍需处理的问题。请结合明细查看对应页面。',
      awaiting_browser:'程序检查已记录，浏览器正在补充当前版本的实际测量。',
      ready_to_review:'当前版本的已实现版式检查完成。内容是否准确、表达和设计是否合适，仍需查看页面。',
      measuring:'正在单独测量页面。你查看的预览和正在输入的反馈目标保持不变。'
    };
    $('quality-summary').textContent=messages[status] || '检查结果已记录，请查看明细。';
    $('quality-check').disabled=ui.qualityBusy || measuring || !ui.connected;
    $('quality-check').textContent=ui.qualityBusy?'正在检查…':'重新检查';
    const failures=[...ui.measure.entries.values()].filter(e=>e.status==='failed' && slides.some(s=>measurementKey(s)===e.key));
    $('quality-local-error').hidden=!failures.length;
    $('quality-local-error').textContent=failures.length?`${failures.length} 页尚未完成浏览器测量：${failures[0].error || '页面载入或测量超时'}。可点击“重新检查”。`:'';
    const issues=Array.isArray(quality?.issues)?quality.issues:[],fixes=Array.isArray(quality?.fixes)?quality.fixes:[];
    const key=JSON.stringify([issues,fixes,quality?.status]);
    if(key===ui.qualityKey)return;
    ui.qualityKey=key;
    $('quality-details-title').textContent=`检查明细 · ${issues.length} 项待查看${fixes.length?' / '+fixes.length+' 项自动修正':''}`;
    const host=$('quality-issues');host.replaceChildren();
    for(const issue of issues){
      const row=node('li',`quality-issue ${issue.severity || ''}`),n=slides.findIndex(s=>s.id===issue.slideId);
      row.append(node('span','quality-issue-page',n>=0?`第 ${n+1} 页`:'整稿'),node('span','',issue.message || issue.code || '待检查问题'));
      if(issue.basis)row.append(node('small','quality-issue-basis',({browser:'浏览器实测','browser-reported':'浏览器实测',estimate:'程序估算',estimated:'程序估算',scene:'版式规则',geometry:'位置检查',content:'内容规则','content-marker':'待补内容检查','deck-consistency':'整稿一致性'})[issue.basis] || '规则检查'));
      if(n>=0){const button=node('button','','查看当前页');button.type='button';button.addEventListener('click',()=>{selectSlide(issue.slideId);if(innerWidth<=760)switchMobile('preview');});row.append(button);}
      host.append(row);
    }
    for(const fix of fixes.slice(-12)){const n=slides.findIndex(s=>s.id===fix.slideId);host.append(node('li','quality-fix',fix.message || fix.description || fix.summary || `${n>=0?'第 '+(n+1)+' 页':'页面'}：已调整文字区域${fix.beforeRevision && fix.afterRevision?' · v'+fix.beforeRevision+' → v'+fix.afterRevision:''}`));}
    if(!issues.length && !fixes.length)host.append(node('li','quality-empty',quality?.status==='ready_to_review'?'当前规则未发现阻断项。':'检查完成后会在这里显示结果。'));
  }

  function measurementKey(slide) {return `${ui.state?.projectId || ''}:${slide.id}:${slide.sceneRevision || 0}`;}
  function measurementIsCurrent(task) {
    const slide=ui.state?.slides?.find(s=>s.id===task.slideId);
    return !!slide && !slide.stale && slide.hasPreview && Number(slide.sceneRevision)===task.sceneRevision && task.projectId===ui.state.projectId;
  }
  function stopMeasurement(task) {
    if(!task)return;
    clearTimeout(task.timer);task.frame?.remove();
    if(ui.measure.active===task)ui.measure.active=null;
  }
  function finishMeasurement(task,success,error='') {
    if(ui.measure.active!==task)return;
    stopMeasurement(task);
    const entry=ui.measure.entries.get(task.key);
    if(entry){entry.status=success?'done':entry.attempts<2?'retry':'failed';entry.error=error;entry.nextAttempt=Date.now()+1000;}
    renderQuality();
    clearTimeout(ui.measure.timer);ui.measure.timer=setTimeout(scheduleMeasurements,success?30:1000);
  }
  async function submitMeasurement(task,report) {
    if(ui.measure.active!==task || task.sending || !measurementIsCurrent(task))return;
    task.sending=true;clearTimeout(task.timer);
    try{
      const result=await api('/api/quality/report','POST',{slideId:task.slideId,sceneRevision:task.sceneRevision,report});
      if(result?.accepted!==true)throw new Error('服务未确认这份页面测量。');
      const ready=report.fontsReady===true && report.imagesLoaded===true;
      await refreshState();
      finishMeasurement(task,ready,ready?'':'字体或图片尚未完整加载');
    }catch(error){finishMeasurement(task,false,error.message);}
  }
  function handleQualityMessage(event) {
    const task=ui.measure.active,data=event.data;
    if(!task || event.source!==task.frame.contentWindow || data?.type!=='ppt-quality' || task.sending || !measurementIsCurrent(task))return false;
    const report=data.report;
    if(!report || report.schema!=='ppt-browser-measurement' || report.schemaVersion!==1 || report.slideId!==task.slideId || !Array.isArray(report.objects) || report.objects.length>240 || !Array.isArray(report.overflowIds) || report.overflowIds.length>240)return false;
    if(typeof report.fontsReady!=='boolean' || typeof report.imagesLoaded!=='boolean')return false;
    task.lastReport=report;
    if(report.fontsReady && report.imagesLoaded)submitMeasurement(task,report);
    return true;
  }
  function scheduleMeasurements() {
    if(!ui.state || !ui.connected || !qualitySource() || ui.qualityBusy)return;
    if(ui.pendingFrame || !ui.activeFrame || ui.activeFrame.dataset.imagesReady!=='true')return;
    if(ui.measure.projectId!==ui.state.projectId){stopMeasurement(ui.measure.active);clearTimeout(ui.measure.timer);ui.measure.projectId=ui.state.projectId;ui.measure.entries.clear();}
    if(ui.measure.active){if(measurementIsCurrent(ui.measure.active))return;stopMeasurement(ui.measure.active);}
    const quality=qualitySource();
    const candidates=(ui.state.slides || []).filter(s=>s.hasPreview && !s.stale && Number(s.sceneRevision)>0);
    for(const slide of candidates){
      const measured=quality?.pages?.some(p=>p.slideId===slide.id && Number(p.sceneRevision)===Number(slide.sceneRevision) && p.measured===true);
      const key=measurementKey(slide),existing=ui.measure.entries.get(key);
      if(measured || existing?.status==='done' || existing?.status==='failed' || existing?.nextAttempt>Date.now())continue;
      const url=previewUrl(slide);if(!url)continue;
      const entry=existing || {key,slideId:slide.id,sceneRevision:Number(slide.sceneRevision),attempts:0,status:'queued',error:''};
      entry.attempts++;entry.status='measuring';ui.measure.entries.set(key,entry);
      const frame=node('iframe','quality-measure-frame');frame.title='用于版式检查的独立页面';frame.setAttribute('sandbox','allow-scripts');frame.setAttribute('aria-hidden','true');frame.tabIndex=-1;frame.inert=true;frame.loading='eager';
      const task={key,slideId:slide.id,sceneRevision:Number(slide.sceneRevision),projectId:ui.state.projectId,frame,sending:false,lastReport:null,timer:null};
      ui.measure.active=task;
      frame.addEventListener('error',()=>finishMeasurement(task,false,'测量页面载入失败'));
      // Hidden measurement frames load like thumbnails (fetch + srcdoc): some clients never
      // commit iframe navigations, which previously left every page unmeasured.
      $('quality-measure-host').append(frame);renderQuality();
      fetch(url,{credentials:'same-origin'}).then(response=>{if(!response.ok)throw Error('Preview unavailable');return response.text();}).then(markup=>{
        if(ui.measure.active!==task)return;
        task.timer=setTimeout(()=>{if(ui.measure.active!==task)return;if(task.lastReport)submitMeasurement(task,task.lastReport);else finishMeasurement(task,false,'未收到当前页面的真实测量');},10000);
        frame.srcdoc=markup;
      }).catch(()=>{if(ui.measure.active===task)finishMeasurement(task,false,'测量页面载入失败');});
      return;
    }
    renderQuality();
  }

  async function checkQuality() {
    if(ui.qualityBusy || ui.measure.active || !ui.connected)return;
    ui.qualityBusy=true;renderQuality();
    try{
      await api('/api/quality/check','POST',{autoFix:true});
      for(const [key,entry] of ui.measure.entries)if(entry.status!=='done')ui.measure.entries.delete(key);
      await refreshState(true);
    }catch(error){toast(error.message,6000);}
    finally{ui.qualityBusy=false;renderQuality();scheduleMeasurements();}
  }

  async function controlDelivery(action,roundId) {
    if(ui.deliveryBusy || !ui.connected)return;
    ui.deliveryBusy=true;
    try{await api('/api/delivery/control','POST',{action,roundId});await refreshState(true);}
    catch(error){toast(error.message,6000);}
    finally{ui.deliveryBusy=false;ui.deliveryKey='';renderDelivery();}
  }

  function renderDeckProgress() {
    const deck = ui.state?.deck;
    $('deck-progress').hidden = !deck;
    $('preview-deck-status').hidden = !deck;
    if (!deck) { ui.deckKey=''; return; }
    const total = Math.max(0, Number(deck.totalPages) || 0), completed = Math.max(0, Number(deck.completedPages) || 0);
    const current = Number(deck.currentPage) || null;
    const status = deck.status;
    const labels = { running:'逐页生成中', paused:'已暂停', blocked:'需要处理', complete:'初稿已生成', cancelled:'已停止' };
    const designReview = deck.designReview;
    if (status==='running' && completed===total && designReview) labels.running='整稿检查中';
    $('deck-progress-title').textContent = labels[status] || '整稿制作';
    $('deck-page-progress').textContent = `${completed} / ${total} 页`;
    $('deck-progress-bar').max = Math.max(1,total); $('deck-progress-bar').value = Math.min(completed,total);
    $('deck-progress').dataset.status = status || '';
    const page = (deck.pages || []).find(p=>Number(p.index)===current);
    const currentLabel = current ? `第 ${current} 页${page?.title ? ' · '+page.title : ''}` : '下一页';
    const messages = {
      running:`正在制作${currentLabel}，完成后自动继续。`,
      paused:`已完成 ${completed} 页。点击继续后从未完成的页面接着制作。`,
      blocked:deck.lastError?.code==='PAGE_NEEDS_INPUT'?`第 ${current || '?'} 页需要补充信息。把答案一起发送后自动继续。`:'当前页未完成。处理下面的问题后重试，已完成页面会保留。',
      complete:`${total} 页初稿已生成。请查看表达与版面，再提出具体修改。`,
      cancelled:`已停止生成，保留 ${completed} 页及原始逐页计划。`
    };
    if (completed===total && designReview) {
      if(status==='running') messages.running='正在检查整稿叙事、连续页面与视觉节奏，必要时自动修正问题页。';
      if(status==='complete' && designReview.summary) messages.complete=designReview.summary;
      if(status==='blocked') messages.blocked='页面已保留，整稿自动检查尚未完成。处理原因后可重试。';
    }
    $('deck-status-text').textContent = messages[status] || '逐页计划已保存。';
    $('preview-deck-status').textContent = `${labels[status] || '整稿制作'} · ${completed} / ${total} 页`;
    const detail = deck.lastError;
    const error = typeof detail === 'string' ? detail : detail?.message || '';
    $('deck-error').hidden = !error; $('deck-error').textContent = error;
    $('deck-pause').hidden = status !== 'running';
    $('deck-resume').hidden = status !== 'paused';
    $('deck-retry').hidden = status !== 'blocked';
    $('deck-follow').hidden = !ui.pinnedSlideId || !['running','paused','blocked'].includes(status);
    $('deck-follow').disabled = hasComposerDraft();
    $('deck-follow').title = hasComposerDraft() ? '请先发送或保存当前页的输入，避免改变修改对象。' : '自动显示正在制作的新页面';
    $('deck-cancel').hidden = !['running','paused','blocked'].includes(status);
    document.querySelectorAll('[data-deck-action]').forEach(button=>button.disabled=ui.deckBusy || !ui.connected);
    const hasInitial = !!deck.initialCompletedAt;
    const revisions = Math.max(0, Number(deck.revisionCount) || 0), target = Number.isFinite(Number(deck.revisionTarget)) ? Math.max(0,Number(deck.revisionTarget)) : 3;
    const exceeded = deck.withinRevisionTarget === false || revisions > target;
    $('revision-budget').hidden = !hasInitial && revisions === 0;
    $('revision-budget').classList.toggle('exceeded',exceeded);
    $('revision-count').textContent = `页面修改记录：${revisions} 次`;
    $('revision-budget-note').textContent = '这里记录实际页面变更；用户输入轮次以上方对话记录为准。';
    const revisionKey=JSON.stringify(deck.revisions || []);
    if(revisionKey!==ui.revisionKey){
      ui.revisionKey=revisionKey;const history=$('revision-history-list');history.replaceChildren();
      $('revision-history').hidden=!(deck.revisions || []).length;
      for(const revision of deck.revisions || []){
        const item=node('li');item.append(node('span','',`${revision.number}. ${revision.description || '页面修改'}`));
        const pageIndex=ui.state?.slides?.findIndex(s=>s.id===revision.slideId);
        const source={chat:'对话修改',external:'外部操作',direct:'直接操作',user:'用户反馈','local-or-external':'本机或外部操作'}[revision.source] || '修改记录';
        item.append(node('small','',[pageIndex>=0?`第 ${pageIndex+1} 页`:'',source,revision.stage==='during-initial-draft'?'生成期间':'',time(revision.createdAt)].filter(Boolean).join(' · ')));history.append(item);
      }
    }
    const key = JSON.stringify(deck.pages || []);
    if (key !== ui.deckKey) {
      ui.deckKey = key; const list=$('deck-plan-pages'); list.replaceChildren();
      for (const item of deck.pages || []) {
        const row=node('li',`deck-plan-page ${item.status || ''}`);
        const button=node('button','',`${item.index}. ${item.title || '未命名页面'}`); button.type='button'; button.disabled=!item.slideId;
        if(item.slideId)button.addEventListener('click',()=>{selectSlide(item.slideId); if(innerWidth<=760)switchMobile('preview');});
        row.append(button,node('span','deck-page-state',deckPageLabels[item.status] || '待制作'));
        const reason=typeof item.error==='string'?item.error:item.error?.message;
        if(reason)row.append(node('small','deck-page-error',reason));
        list.append(row);
      }
    }
  }

  function updateExport() {
    const deck=ui.state?.deck;
    const incomplete=!!deck && Number(deck.completedPages)<Number(deck.totalPages);
    $('export-button').disabled=!ui.state?.slides?.some(s=>s.hasPreview || s.sceneRevision) || incomplete;
    const ready=releaseIsReady();
    $('export-button').title=incomplete?'整套初稿尚未完成，完成后可导出。':ready?'可导出正式稿或草稿':'当前只能导出明确标注的草稿';
    $('export-status-text').textContent=ready?'当前稿件可正式导出':'当前可导出草稿；正式稿需完成确认与交付检查';
    $('export-release-pptx').disabled=!ready;$('export-release-html').disabled=!ready;
    if(incomplete)closeExport();
  }

  const deckReviewStatement='我已查看整套演示稿的全部页面，认可当前版本的内容表达和视觉呈现。';
  function hasRunningContent() {return (ui.state?.jobs || []).some(isBusy) || ui.posting || ui.undoBusy || ui.reviewBusy;}
  function currentSceneVersions() {return Object.fromEntries((ui.state?.slides || []).map(s=>[s.id,Number(s.sceneRevision)]));}
  function latestSnapshotIsCurrent() {
    const rounds=ui.state?.delivery?.rounds || [],latest=rounds[rounds.length-1];
    if(!latest || latest.snapshotStale!==false || latest.status!=='ready')return false;
    const rows=snapshotRows(latest.snapshot),slides=ui.state?.slides || [];
    if(!rows.length || rows.length!==slides.length)return false;
    return slides.every(slide=>rows.some(row=>(row.slideId || row.id)===slide.id && Number(row.sceneRevision)===Number(slide.sceneRevision) && (!row.contentRevision || Number(row.contentRevision)===Number(slide.revision))));
  }
  function releaseIsReady() {
    return !!(ui.state?.delivery?.releaseReady && ui.state.delivery.qualityAccepted && qualitySource()?.readyToReview && latestSnapshotIsCurrent() && !hasRunningContent() && !ui.deckReviewBusy && !ui.qualityBusy && !ui.measure.active && !(ui.state?.slides || []).some(s=>s.stale));
  }
  function canConfirmDeck() {
    const slides=ui.state?.slides || [],deck=ui.state?.deck;
    return !!(ui.connected && slides.length && slides.every(s=>s.hasPreview && !s.stale && Number.isInteger(Number(s.sceneRevision)) && Number(s.sceneRevision)>0) && (!deck || Number(deck.completedPages)===Number(deck.totalPages)) && qualitySource()?.readyToReview && !ui.state?.delivery?.qualityAccepted && !hasRunningContent() && !ui.deckReviewBusy && !ui.qualityBusy && !ui.measure.active);
  }
  function renderRelease() {
    const delivery=ui.state?.delivery || {},accepted=!!delivery.qualityAccepted;
    $('deck-review-button').disabled=!canConfirmDeck();
    $('deck-review-button').textContent=ui.deckReviewBusy?'正在记录确认…':accepted?'当前整稿已确认':'确认整稿';
    $('deck-review-note').textContent=accepted?(delivery.releaseReady?'表达与视觉已确认；正式交付状态见导出菜单。':'表达与视觉已确认，正式交付仍有下列待办。'):`一次认可全部页面，记录为第 ${Math.max(0,Number(delivery.inputCount)||0)+1} 轮输入。`;
    const issues=Array.isArray(delivery.releaseIssues)?delivery.releaseIssues:[],key=JSON.stringify(issues);
    $('release-details').hidden=!issues.length;
    $('release-details-title').textContent=`正式交付待办 · ${issues.length} 项`;
    if(key!==ui.releaseKey){ui.releaseKey=key;const host=$('release-issues');host.replaceChildren();for(const issue of issues){const row=node('li');row.append(node('span','',issue.message || '交付条件尚未满足'));if(issue.slideIds?.length){const pages=issue.slideIds.map(id=>{const n=ui.state?.slides?.findIndex(s=>s.id===id);return n>=0?String(n+1):id;});row.append(node('small','',`涉及页面：${pages.join('、')}`));}host.append(row);}}
    updateExport();
  }
  function operatorRequestId(action,details) {
    const key=JSON.stringify([ui.state?.projectId,action,details]);
    if(!ui.operatorIds.has(key))ui.operatorIds.set(key,requestId());
    return ui.operatorIds.get(key);
  }
  function openDeckReview() {
    if(hasComposerDraft()){toast('输入框还有未发送的反馈，请先发送或保存，再确认整稿。');return;}
    if(!canConfirmDeck()){toast('请等当前页面制作和版式检查完成，再查看并确认整稿。');return;}
    const versions=currentSceneVersions();
    ui.deckReviewSnapshot={projectId:ui.state.projectId,sceneRevisions:versions,statement:deckReviewStatement,clientMessageId:operatorRequestId('review-deck',versions)};
    $('deck-review-error').hidden=true;$('deck-review-statement').textContent=deckReviewStatement;
    updateReviewDialog();$('deck-review-dialog').showModal();
  }
  function reviewSnapshotIsCurrent(snapshot) {
    return !!snapshot && snapshot.projectId===ui.state?.projectId && JSON.stringify(snapshot.sceneRevisions)===JSON.stringify(currentSceneVersions()) && !(ui.state?.slides || []).some(s=>s.stale);
  }
  function updateReviewDialog() {
    const snapshot=ui.deckReviewSnapshot;if(!snapshot)return;
    const current=reviewSnapshotIsCurrent(snapshot),round=Math.max(0,Number(ui.state?.delivery?.inputCount)||0)+1;
    $('deck-review-snapshot').textContent=`已固定 ${Object.keys(snapshot.sceneRevisions).length} 页的当前版本。${current?'提交时按这组版本记录认可。':'稿件已变化，请返回查看后重新打开确认。'}`;
    $('deck-review-round-note').textContent=`确认将作为第 ${round} 轮输入，系统记录本轮结果。`;
    $('deck-review-round-note').classList.remove('exceeded');
    const issues=ui.state?.delivery?.releaseIssues || [];
    $('deck-review-boundary').textContent=(issues.length?`当前还有 ${issues.length} 项正式交付待办；确认本身不会完成这些待办。`:'')+'这项确认只记录你对内容表达和视觉呈现的认可。资料与数据核验仍单独检查。';
    $('submit-deck-review').disabled=ui.deckReviewBusy || !current || !canConfirmDeck();
    $('submit-deck-review').textContent=ui.deckReviewBusy?'正在记录…':'我已查看并确认';
    $('cancel-deck-review').disabled=ui.deckReviewBusy;$('close-deck-review').disabled=ui.deckReviewBusy;
  }
  async function confirmDeck() {
    const snapshot=ui.deckReviewSnapshot;
    if(!snapshot || ui.deckReviewBusy)return;
    if(!reviewSnapshotIsCurrent(snapshot) || !canConfirmDeck()){ $('deck-review-error').textContent='当前稿件或检查状态已变化，请返回查看后重新确认。';$('deck-review-error').hidden=false;updateReviewDialog();return; }
    ui.deckReviewBusy=true;$('deck-review-error').hidden=true;updateReviewDialog();renderRelease();
    try{
      const result=await api('/api/review/deck','POST',{sceneRevisions:{...snapshot.sceneRevisions},statement:snapshot.statement,clientMessageId:snapshot.clientMessageId});
      if(result?.slides || result?.state?.slides)applyState(result);else await refreshState(true);
      $('deck-review-dialog').close();ui.deckReviewSnapshot=null;
      toast(ui.state?.delivery?.releaseReady?'整稿确认已记录，当前可选择正式导出。':'整稿确认已记录。资料核验等交付待办仍需完成。',6000);
    }catch(error){$('deck-review-error').textContent=error.message;$('deck-review-error').hidden=false;}
    finally{ui.deckReviewBusy=false;updateReviewDialog();renderRelease();}
  }
  function closeDeckReview() {if(ui.deckReviewBusy)return;$('deck-review-dialog').close();ui.deckReviewSnapshot=null;}

  function exportRequestUrl(format,mode='draft') {
    if(!['html','pptx'].includes(format))throw new Error('请选择 HTML 或 PowerPoint 格式。');
    if(mode==='release' && !releaseIsReady())throw new Error('当前尚未满足正式交付条件；可以选择明确标注的草稿。');
    return `/api/export?project=${encodeURIComponent(ui.state.projectId)}&format=${encodeURIComponent(format)}${mode==='release'?'&strict=1':''}`;
  }

  function renderMessages(force = false) {
    const messages = [...(ui.state?.messages || []), ...ui.optimistic];
    const key = JSON.stringify([messages,ui.state?.imageBatches,(ui.state?.delivery?.rounds || []).map(r=>[r.id,r.status,r.snapshotStale])]);
    if (!force && key === ui.messageKey) return;
    ui.messageKey = key;
    const feed = $('chat-feed');
    const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 100;
    const oldTop = feed.scrollTop;
    const host = $('messages'); host.replaceChildren();
    $('chat-welcome').hidden = !!ui.state?.deck || !!ui.state?.slides?.length || messages.some(m=>m.role==='user');
    let progressGroup=null,progressKey=null,progressCount=0;
    for (const message of messages) {
      const role = ['user','assistant','system'].includes(message.role) ? message.role : 'system';
      const article = node('article', `message ${role} ${message.status === 'failed' ? 'failed' : ''}`);
      const author = node('div','message-author');
      author.append(node('span','message-avatar', role === 'user' ? '你' : role === 'assistant' ? '页' : '·'), node('span','', role === 'user' ? '你' : role === 'assistant' ? '制作助手' : '工作台'));
      if(message.isRoundOutput){const round=ui.state?.delivery?.rounds?.find(r=>r.outputMessageId===message.id);article.classList.add('round-output');author.append(node('span','round-output-badge',`第 ${message.roundNumber || round?.number || '?'} 轮结果${round?.status==='checking'?' · 检查中':round?.snapshotStale?' · 当时版本':''}`));}
      if(message.modelBinding)author.append(node('span','message-page',message.modelBinding.label));
      const pageId = message.pageId || message.slideId;
      if (pageId) { const n = ui.state?.slides?.findIndex(s => s.id === pageId); author.append(node('span','message-page', n >= 0 ? `第 ${n + 1} 页` : pageId)); }
      else if(message.deckPageIndex)author.append(node('span','message-page',`第 ${message.deckPageIndex} 页${message.isDeckQuestion?' · 待补充':message.isDeckAnswer?' · 补充材料':''}`));
      author.append(node('time','message-time',time(message.createdAt))); article.append(author, node('div','message-body',message.text || message.message || ''));
      const imageBatch=(ui.state?.imageBatches || []).find(b=>b.id===message.jobId);
      if(imageBatch){
        const saved=Number(imageBatch.generatedCount)||0;
        const retained=saved>0?`已保留 ${saved} 张生成图片，尚未应用到页面。`:'本次没有保存生成图片，页面保持原样。';
        const reasons={IMAGE_TOOL_UNAVAILABLE:'当前模型连接未提供图片生成工具。',IMAGE_NO_RESULT:'模型没有返回生成图片。',IMAGE_TIMEOUT:'图片生成超时。',IMAGE_START_FAILED:'图片生成服务未能启动。',IMAGE_SESSION_FAILED:'图片生成会话失败。',IMAGE_AUTH_FAILED:'图片服务认证失败。',IMAGE_SANDBOX_UNAVAILABLE:'图片生成运行环境不可用。',IMAGE_OUTPUT_INVALID:'生成图片未通过文件校验。',IMAGE_INVALID_RESPONSE:'图片服务返回了无法识别的结果。',IMAGE_RESULT_TOO_LARGE:'图片服务返回结果超过处理上限。'};
        const labels={pending:'图片等待生成',running:'图片生成中，可能需要几分钟',applied:'图片已生成并应用',failed:`图片生成失败。${reasons[imageBatch.errorCode]||''}${retained}`,conflict:`页面版本已变化。${retained}`,interrupted:`生成中断，不会自动重试。${retained}`};
        article.append(node('div','message-meta',labels[imageBatch.status] || imageBatch.status));
      }
      if (message.attachments?.length) {
        const attachments = node('div','message-attachments');
        message.attachments.forEach(a => { const chip = node('span','', typeof a === 'string' ? a : a.filename || a.name || '参考资料'); chip.prepend(icon('file','small')); attachments.append(chip); }); article.append(attachments);
      }
      if (message.changes?.length) {
        const details = node('details','message-diff'); details.append(node('summary','',`本次调整 · ${message.changes.length} 处`));
        message.changes.forEach(change => { const row = node('div','diff-row'); row.append(node('strong','',change.label || change.objectId || '页面调整')); if (change.before !== undefined) row.append(node('span','diff-before',readableChange(change.before))); if (change.after !== undefined) row.append(node('span','diff-after',readableChange(change.after))); details.append(row); }); article.append(details);
      }
      if (Array.isArray(message.choices) && message.choices.length) {
        const choices = node('div','message-choices');
        message.choices.forEach(choice => {
          const label=typeof choice==='string'?choice:choice.label || choice.text || choice.value;
          const value=typeof choice==='string'?choice:choice.value || choice.label || choice.text;
          if(!label)return;
          const button=node('button','',String(label));button.type='button';
          button.addEventListener('click',()=>stageChoice(String(value),message,button,choice));choices.append(button);
        }); article.append(choices,node('p','choice-hint','可继续选择或补充，再一次发送。'));
      }
      if (message.status && ['sending','queued','pending','failed'].includes(message.status)) {
        const errorText = typeof message.error === 'string' ? message.error : message.error?.message;
        const meta = node('div',`message-meta ${message.status === 'failed' ? 'error' : ''}`, message.status === 'sending' ? '正在发送…' : message.status === 'failed' ? (errorText || (message.local ? '发送未完成' : '本次处理未完成，请查看说明')) : '已收到，等待处理');
        if (message.status === 'failed' && message.local) { const retry = node('button','message-retry','重试'); retry.type = 'button'; retry.addEventListener('click',() => sendMessage(message.text,{ retry:message })); meta.append(retry); } article.append(meta);
      }
      if(message.internalProgress && !message.isRoundOutput){
        const key=message.roundId || 'work-progress';
        if(!progressGroup || progressKey!==key){
          progressKey=key;progressCount=0;progressGroup=node('details','work-progress');progressGroup.dataset.roundId=key;
          progressGroup.open=ui.progressOpen.has(key) || !!message.isDeckQuestion;
          const summary=node('summary');progressGroup.append(summary);
          const group=progressGroup;group.addEventListener('toggle',()=>{if(group.open)ui.progressOpen.add(key);else ui.progressOpen.delete(key);});
          host.append(progressGroup);
        }
        progressCount++;progressGroup.children[0].textContent=`后台制作记录 · ${progressCount} 项${message.isDeckQuestion?' · 需要补充':''}`;
        progressGroup.append(article);
      }else{progressGroup=null;progressKey=null;progressCount=0;host.append(article);}
    }
    if (nearBottom || force) scrollChat(false); else { feed.scrollTop = oldTop; $('new-messages-button').hidden = false; }
  }

  function replaceChoiceBlock(text,value,alternatives) {
    const lines=text.trimEnd()?text.trimEnd().split('\n'):[];
    const blocks=[...new Set([value,...alternatives])].filter(v=>typeof v==='string' && v.length).map(v=>v.split('\n')).sort((a,b)=>b.length-a.length);
    const result=[];let replaced=false;
    for(let i=0;i<lines.length;){
      const match=blocks.find(block=>block.every((line,offset)=>lines[i+offset]===line));
      if(match){if(!replaced){result.push(...value.split('\n'));replaced=true;}i+=match.length;}
      else result.push(lines[i++]);
    }
    if(!replaced)result.push(...value.split('\n'));
    return result.join('\n');
  }

  function stageChoice(value,message,button,choice) {
    const selected=choice && typeof choice==='object'?choice:{};
    const question=pendingDeckQuestion();
    const isDeckQuestion=!!selected.questionMessageId || message.isDeckQuestion===true || message.id===question?.choiceMessageId;
    let target;
    if(selected.intakeChoice===true)target={kind:'deck',scope:'deck',pageId:null,objectId:null};
    else if(isDeckQuestion)target={kind:'deck-question',scope:'deck',pageId:null,objectId:null,choiceMessageId:selected.questionMessageId || message.id,replyToDeckPage:true,deckId:selected.deckId || message.deckId || question?.deckId,deckPageIndex:selected.deckPageIndex || message.deckPageIndex || question?.deckPageIndex};
    else if(message.pageId || message.slideId)target={kind:'page',scope:'page',pageId:message.pageId || message.slideId,objectId:null};
    else target=ui.object || ui.explicitPageEditing?pageMessageTarget():{kind:'deck',scope:'deck',pageId:null,objectId:null};
    const existing=currentMessageTarget();
    const same=target.kind==='deck-question'?sameQuestion(target,existing):target.kind===existing.kind && target.pageId===existing.pageId && target.objectId===existing.objectId;
    if(hasComposerDraft() && !same){toast('当前输入属于另一个页面或问题，请先发送或保存后再选择。');return;}
    const input=$('message-input');
    if(!input.value.trim())ui.stagedChoiceGroups.clear();
    const groupKey=selected.groupId?`${selected.intakeChoice===true?'intake':'question'}:${selected.groupId}`:null;
    let alternatives;
    if(groupKey){
      alternatives=(message.choices || []).filter(c=>c && typeof c==='object' && c.groupId===selected.groupId && (c.intakeChoice===true)===(selected.intakeChoice===true)).map(c=>c.value || c.label || c.text);
      const previous=ui.stagedChoiceGroups.get(groupKey);if(previous)alternatives.push(previous);
    }else{
      const separator=value.includes('\n')?-1:value.indexOf('：');
      alternatives=(message.choices || []).map(c=>typeof c==='string'?c:c.value || c.label || c.text).filter(v=>typeof v==='string' && !v.includes('\n') && separator>0 && v.startsWith(value.slice(0,separator+1)));
    }
    const joined=replaceChoiceBlock(input.value,value,alternatives);
    if(joined.length>20000){toast('输入内容较长，请先整理后再添加选项。');return;}
    ui.draftTarget={...target};if(target.pageId)ui.pinnedSlideId=target.pageId;
    if(groupKey)ui.stagedChoiceGroups.set(groupKey,value);
    if(target.kind!=='page')ui.object=null;
    input.value=joined;button?.setAttribute('aria-pressed','true');resizeComposer();renderComposerScope();input.focus();
    toast('已加入输入框。可以继续选择和补充，再一起发送。');
  }

  function scrollChat(smooth = true) { const feed = $('chat-feed'); feed.scrollTo({top:feed.scrollHeight,behavior:smooth?'smooth':'auto'}); $('new-messages-button').hidden = true; }

  function previewUrl(slide) {
    const raw = slide.previewUrl || `/api/preview/${encodeURIComponent(slide.id)}`;
    const url = new URL(raw,location.href);
    if (url.origin !== location.origin) return null;
    url.searchParams.set('rev',String(slide.sceneRevision || slide.revision || 0));
    return url.pathname + url.search;
  }

  function previewIdentity(slide) {
    return slide?.hasPreview?`${slide.id}:${slide.sceneRevision || slide.revision}:${slide.previewUrl || ''}`:`empty:${slide?.id || ''}`;
  }

  function frameMatchesSelection(frame) {
    const slide=activeSlide();
    return !!frame && !!slide?.hasPreview && frame.dataset.slideId===slide.id && frame.dataset.previewKey===ui.previewKey && frame.dataset.previewKey===previewIdentity(slide);
  }

  function canSelectFrame(frame) {
    return !!frame && frame===ui.activeFrame && !ui.pendingFrame && frame.classList.contains('active') && frame.dataset.interactive==='true' && frameMatchesSelection(frame);
  }

  function setFrameInteractive(frame,enabled) {
    if(!frame)return;
    frame.dataset.interactive=String(enabled);frame.tabIndex=enabled?0:-1;frame.inert=!enabled;
    frame.setAttribute('aria-disabled',String(!enabled));
  }

  const thumbs = new Map();
  function renderSlides() {
    const slides = ui.state?.slides || [];
    const strip = $('filmstrip'), oldScroll = strip.scrollLeft, selected = activeSlide()?.id;
    if (!slides.length) { clearPreviews(strip); thumbs.clear(); strip.replaceChildren(node('div','filmstrip-empty','逐页大纲确认后，页面会出现在这里。')); return; }
    const keep = new Set(slides.map(s => s.id));
    for (const [id, entry] of thumbs) if (!keep.has(id)) { clearPreviews(entry.canvas); thumbs.delete(id); }
    const ordered = slides.map((slide,index) => {
      let entry = thumbs.get(slide.id);
      if (!entry) {
        const button = node('button','slide-thumb'); button.type = 'button';
        const canvas = node('div','thumb-canvas'), empty = node('div','thumb-empty'), number = node('span','thumb-index');
        const caption = node('div','thumb-caption'); caption.append(node('span'),node('span','thumb-revision'));
        canvas.append(empty,number); button.append(canvas,caption);
        button.addEventListener('click',() => selectSlide(slide.id));
        entry = {button,canvas,caption,empty,number,frame:null,url:undefined};
        thumbs.set(slide.id,entry);
      }
      const {button,canvas,caption,empty,number} = entry;
      button.classList.toggle('active',slide.id===selected);
      button.setAttribute('aria-current',slide.id===selected?'page':'false');
      button.setAttribute('aria-label',`第 ${index+1} 页：${slide.title || '未命名页面'}`);
      empty.textContent = String(index+1).padStart(2,'0'); number.textContent = String(index+1).padStart(2,'0');
      caption.children[0].textContent = slide.title || '未命名页面';
      caption.children[1].textContent = slide.sceneRevision ? `v${slide.sceneRevision}` : '';
      const url = slide.hasPreview ? previewUrl(slide) : null;
      if (url !== entry.url) {
        entry.url = url; clearPreviews(canvas);
        const old = entry.frame;
        if (!url) { entry.frame = null; old?.remove(); }
        else {
          const frame = node('iframe','thumb-frame'); frame.title = `第 ${index+1} 页缩略图`; frame.setAttribute('aria-hidden','true'); frame.tabIndex = -1; frame.setAttribute('sandbox','allow-scripts');
          entry.frame = frame;
          // The old thumbnail stays until the new document has really loaded:
          // about:blank fires load too, so srcdoc frames only swap once the
          // preview loader reports the fetched markup as ready.
          frame.addEventListener('load',() => { if (entry.frame === frame && (!previewLoader || frame.dataset.previewState === 'ready')) old?.remove(); });
          canvas.append(frame); lazyPreview(frame,url);
        }
      }
      return button;
    });
    strip.replaceChildren(...ordered);
    strip.scrollLeft = oldScroll;
  }

  let documentBusy=false;
  function renderDocumentTools(){
    const index=slideIndex(),count=ui.state?.slides?.length||0,busy=documentBusy||!ui.connected||(ui.state?.jobs||[]).some(isBusy);
    for(const id of ['slide-add','ribbon-add-slide'])$(id).disabled=busy;
    for(const id of ['slide-copy','slide-remove'])$(id).disabled=busy||index<0;
    $('slide-up').disabled=busy||index<=0;$('slide-down').disabled=busy||index<0||index>=count-1;
  }
  async function documentAction(action,extra={}){
    if(documentBusy)return;
    if(design.dirty){toast('请先保存正在编辑的文字。');return;}
    documentBusy=true;renderDocumentTools();
    try{
      const result=await api('/api/document','POST',{action,projectRevision:ui.state.projectRevision,slideId:activeSlide()?.id,...extra});
      ui.pinnedSlideId=result.state.selectedSlideId;ui.object=null;editor.key='';applyState(result.state);await syncEditor();
      toast(action==='undo'?'已撤销。':action==='remove'?'已删除，可用撤销恢复。':action==='insert'?'已在所选位置新建幻灯片。':'已更新页面。');
    }catch(error){toast(error.message);await refreshState(true);}
    finally{documentBusy=false;renderDocumentTools();}
  }
  function renderBackgroundTasks(){
    const host=$('background-status'),task=ui.state?.backgroundTasks?.[0];host.replaceChildren();host.hidden=!task;
    if(!task)return;
    host.append(node('span','',task.status==='failed'?(task.error?.message||'任务未完成'):task.stage));
    if(['queued','running'].includes(task.status))host.append(node('span','background-note','可以离开，任务会在后台继续'));
    if(task.result?.projectId){const link=node('button','button quiet compact','打开改版稿');link.type='button';link.addEventListener('click',()=>openProject(task.result.projectId));host.append(link);}
    const drafts=node('button','button quiet compact','我的草稿');drafts.type='button';drafts.addEventListener('click',openProjects);host.append(drafts);
  }

  function renderPreview() {
    const slide = activeSlide();
    const hasPreview = !!slide?.hasPreview;
    const nextKey = previewIdentity(slide);
    $('preview-version').textContent = hasPreview ? `v${slide.sceneRevision || 1}${slide.stale ? (slide.previewContentStale ? ' · 对应旧内容' : slide.previewMaterialUnavailable ? ' · 素材待补充' : ' · 待核对') : slide.updatedAt ? ' · '+time(slide.updatedAt) : ''}` : '';
    if (nextKey === ui.previewKey) return;
    ui.previewKey = nextKey;
    setFrameInteractive(ui.activeFrame,false);
    setOverflow([]);
    ui.pendingFrame?.remove(); ui.pendingFrame = null;
    if (!hasPreview || !previewUrl(slide)) {
      ui.activeFrame?.remove(); ui.activeFrame = null;
      $('empty-preview').hidden = false;
      setOverflow([]);
      $('empty-preview').querySelector('h3').textContent = slide ? '这一页的内容已记录' : '从内容开始，或打开已有 PPT';
      $('empty-preview').querySelector('p').textContent = slide ? '等待生成页面预览。你可以继续补充原话和资料，或在 Coding Agent 中继续制作。' : '粘贴内容即可生成整稿；也可以点击“打开 PPT”继续编辑。';
      $('empty-demo-button').hidden = !!slide;
      return;
    }
    const candidate = node('iframe','page-frame'); candidate.title = slide.title || '当前页面预览'; candidate.setAttribute('sandbox','allow-scripts');
    candidate.dataset.slideId=slide.id;candidate.dataset.previewKey=nextKey;setFrameInteractive(candidate,false);
    ui.pendingFrame = candidate;
    candidate.activatePreview=() => {
      if (ui.pendingFrame !== candidate) return;
      if(!frameMatchesSelection(candidate)){ui.pendingFrame=null;candidate.remove();renderPreview();updateJobStatus();return;}
      const old = ui.activeFrame; ui.activeFrame = candidate; ui.pendingFrame = null;
      $('empty-preview').hidden = true; candidate.classList.add('active');setFrameInteractive(candidate,true);setOverflow(candidate.overflowIds || []);updateJobStatus();
      // The old page stays fully visible underneath until the fade-in completes.
      if (old && old !== candidate) { const drop = () => old.remove(); candidate.addEventListener('transitionend',drop,{once:true}); setTimeout(drop,220); }
      if(ui.object)candidate.contentWindow.postMessage({type:'ppt-highlight',objectId:ui.object.id},'*');
    };
    // Only the preview document's own ppt-ready message proves it arrived: a frame left on
    // about:blank also fires load, and must never be marked editable.
    const ready=()=>candidate.dataset.ready==='true';
    const giveUp=()=>{if(ui.pendingFrame===candidate){ui.pendingFrame=null;candidate.remove();toast('新预览载入失败。旧预览仅供查看，暂不能选择对象。');updateJobStatus();}};
    candidate.markReady=()=>{candidate.dataset.ready='true';candidate.activatePreview();};
    candidate.addEventListener('load',()=>{candidate.dataset.imagesReady='true';if(ready())candidate.activatePreview();scheduleMeasurements();});
    // Some clients never commit this frame navigation. Thumbnails load through fetch + srcdoc,
    // so retry the same document that way; if it still never reports ready, stop waiting.
    setTimeout(async()=>{
      if(ui.pendingFrame!==candidate || ready())return;
      try{
        const response=await fetch(previewUrl(slide),{credentials:'same-origin'});
        if(!response.ok)throw Error('Preview unavailable');
        const markup=await response.text();
        if(ui.pendingFrame!==candidate || ready())return;
        candidate.dataset.imagesReady='';candidate.dataset.loadPath='srcdoc';candidate.srcdoc=markup;
        setTimeout(()=>{if(!ready())giveUp();},8000);
      }catch(error){giveUp();}
    },6000);
    candidate.addEventListener('error',giveUp);
    candidate.src = previewUrl(slide); $('page-canvas').append(candidate);
  }

  function fitCanvas() {
    const center = document.querySelector('.preview-center');
    if (!center.clientWidth || !center.clientHeight) return;
    const style = getComputedStyle(center);
    const width = center.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const caption = document.querySelector('.preview-caption');
    const warning = $('preview-warning');
    const height = center.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - caption.offsetHeight - parseFloat(getComputedStyle(caption).marginTop) - (warning?.hidden === false ? warning.offsetHeight + 6 : 0);
    const fittedWidth = Math.max(0,Math.min(width,height * 16 / 9)) * editor.zoom;
    $('canvas-wrap').style.width = fittedWidth + 'px';
    $('canvas-wrap').style.height = fittedWidth * 9 / 16 + 'px';
  }

  function setOverflow(ids) {
    let warning = $('preview-warning');
    if (!warning) { warning = node('div','preview-warning'); warning.id='preview-warning'; warning.setAttribute('role','status'); document.querySelector('.preview-center').append(warning); }
    warning.hidden = !ids.length;
    warning.textContent = ids.length ? `${ids.length} 处文字超出了当前区域，可以在对话里要求调整。` : '';
    fitCanvas();
  }

  function updateJobStatus() {
    const jobs = (ui.state?.jobs || []).filter(isBusy), slide = activeSlide(), deck=ui.state?.deck, agent=ui.state?.agent || {};
    const running = jobs.find(j => ['running','processing','claimed'].includes(j.status));
    const jobPage = j => j.slideId || j.pageId || ui.state?.messages?.find(m=>m.id===(j.messageId||j.message_id))?.pageId;
    const targetJob = jobs.find(j => !jobPage(j) || jobPage(j) === slide?.id);
    const status = $('job-status'); status.replaceChildren(); status.hidden = !jobs.length;
    if (jobs.length) {
      let text;
      const localDeck = deck?.execution === 'outline';
      const unavailable=['claude','codex'].includes(agent.mode) && !agent.available && !localDeck;
      if(deck?.status==='paused')text='整稿已暂停，已完成页面仍可查看。';
      else if(deck?.status==='blocked')text='整稿暂未完成，请查看上方原因并重试。';
      else if(unavailable)text='消息已保存；执行器未连接，尚未开始生成。';
      else if(running)text=localDeck?'正在按你提供的大纲排版，完成一页即更新预览。':`正在处理${running.slideId ? '当前页面' : '你的要求'}，预览更新后会自动出现`;
      else if(localDeck && deck?.status==='running')text='逐页任务已保存，即将制作下一页。';
      else text=agent.mode==='manual'?`${jobs.length} 条消息已保存，等待 Coding Agent 领取`:`${jobs.length} 条消息等待处理`;
      if(running && !unavailable && !['paused','blocked'].includes(deck?.status))status.append(node('span','loading-dot'));
      status.append(node('span','',text));
    }
    const waiting = targetJob && !['paused','blocked','cancelled'].includes(deck?.status);
    const supersededPreview=ui.activeFrame && !canSelectFrame(ui.activeFrame);
    $('preview-update').hidden = !(ui.pendingFrame || waiting || slide?.stale || supersededPreview);
    $('preview-update-text').textContent = ui.pendingFrame ? '正在载入新版本，稍后可选择对象' : supersededPreview ? '当前显示旧预览，暂不可选择对象' : waiting && ['running','processing','claimed'].includes(targetJob.status) ? '正在更新这一页' : slide?.stale ? (slide.previewContentStale ? '内容已更新，等待新预览' : slide.previewMaterialUnavailable ? '素材待补充，预览暂不可编辑' : '预览待核对，暂不可编辑') : '任务已保存，当前页面仍保留';
  }

  function updateSend() { $('send-button').disabled = !ui.connected || ui.posting || ui.uploads.some(a=>a.status==='uploading') || (!$('message-input').value.trim() && !ui.uploads.some(a=>a.status==='ready')); }
  function resizeComposer() { const input = $('message-input'); input.style.height='auto'; input.style.height=(!input.value && innerWidth>760?52:Math.min(innerWidth<=760?190:112,Math.max(innerWidth<=760?74:52,input.scrollHeight)))+'px'; updateSend(); }
  function protectDraftTarget(){
    if(hasComposerDraft()){
      if(!ui.draftTarget)ui.draftTarget={...currentMessageTarget()};
      if(ui.draftTarget.pageId)ui.pinnedSlideId=ui.draftTarget.pageId;
    }else {ui.draftTarget=null;ui.stagedChoiceGroups.clear();}
    renderComposerScope();renderDeckProgress();
  }

  async function sendMessage(text, options = {}) {
    if (ui.posting) return;
    if(design.dirty || editor.busy){toast('请先保存页面修改，再发送消息。');return;}
    const value = (text === undefined ? $('message-input').value : text).trim();
    const attachments = options.retry?.attachments || ui.uploads.filter(a=>a.status==='ready').map(a=>({assetId:a.assetId,filename:a.filename,mime:a.mime}));
    if (!value && !attachments.length) return;
    if (!ui.connected) { toast('工作台尚未连接，输入内容已保留。'); return; }
    const target=options.choiceMessageId?{kind:'deck-question',scope:'deck',pageId:null,objectId:null,choiceMessageId:options.choiceMessageId,replyToDeckPage:true,deckId:options.deckId,deckPageIndex:options.deckPageIndex}:options.pageEdit?pageMessageTarget():currentMessageTarget();
    const local = options.retry || { id:'local-'+requestId(), clientMessageId:requestId(), text:value || '我补充了这些资料。', role:'user', status:'sending', local:true, createdAt:new Date().toISOString(), sentAt:Date.now(), ...target, isDeckAnswer:target.kind==='deck-question', attachments };
    local.status='sending'; local.error=null;
    if (!options.retry) ui.optimistic.push(local);
    ui.posting=true; updateSend(); renderMessages(true);
    if (text===undefined) { $('message-input').value='';ui.stagedChoiceGroups.clear(); if(!ui.uploads.length)ui.draftTarget=null;resizeComposer();renderComposerScope(); }
    try {
      const payload={message:local.text,slideId:local.pageId || null,objectId:local.objectId || null,clientMessageId:local.clientMessageId,attachments:attachments.map(a=>a.assetId || a),scope:local.scope || (local.kind==='page'?'page':'deck')};
      if(local.choiceMessageId)payload.choiceMessageId=local.choiceMessageId;
      if(local.replyToDeckPage){payload.replyToDeckPage=true;payload.autoResume=true;}
      const result = await api('/api/chat','POST',payload);
      local.accepted=true; local.jobId=result.jobId; local.status=result.status==='complete'?'complete':'queued';
      if (text === undefined && loadedGuideHandoff) { try { localStorage.removeItem(loadedGuideHandoff); } catch {} loadedGuideHandoff = null; }
      if (!options.retry) { ui.uploads=[]; renderUploads(); saveComposerDraft(); }
      await refreshState(true);
    } catch (error) { local.status='failed'; local.error=error.message; renderMessages(true); }
    finally { ui.posting=false; updateSend(); $('message-input').focus(); }
  }

  function clearObject() { ui.object=null;if(!design.dirty){design.edit=null;$('text-editor').hidden=true;}renderComposerScope();renderEditorTools();ui.activeFrame?.contentWindow.postMessage?.({type:'ppt-highlight',objectId:null},'*'); }
  function clearObjectSelection(){if(hasComposerDraft() && ui.draftTarget?.objectId){toast('当前输入已绑定所选对象，请先发送或保存，再取消选择。');return;}clearObject();}
  function selectObject(id,label,sourceFrame) {
    if(!canSelectFrame(sourceFrame))return;
    const slideId=sourceFrame.dataset.slideId,target=currentMessageTarget();
    if(hasComposerDraft() && (target.kind!=='page' || target.pageId!==slideId || target.objectId!==id)){toast('当前输入已绑定编辑目标，请先发送或保存，再选择其他对象。');return;}
    if(!design.dirty && design.edit?.objectId!==id){design.edit=null;$('text-editor').hidden=true;}
    ui.pinnedSlideId=slideId;ui.explicitPageEditing=true;ui.object={id,label:label||id,pageId:slideId};renderComposerScope();renderDeckProgress();renderEditorTools();
    // Keep focus in the preview so a second click can begin direct editing.
  }

  async function selectSlide(slideId) {
    if(hasComposerDraft()){toast('当前还有未发送的输入，请先发送或保存，再切换编辑目标。');return;}
    if (activeSlide()?.id===slideId) {ui.pinnedSlideId=slideId;ui.explicitPageEditing=true;renderComposerScope();renderDeckProgress();return;}
    try { await api('/api/select','POST',{slideId});ui.pinnedSlideId=slideId;ui.explicitPageEditing=true;clearObject();await refreshState(true); } catch(error) { toast(error.message); }
  }

  function switchMobile(view) { ui.mobileView=view; document.querySelector('.workspace').dataset.mobileView=view; document.querySelectorAll('[data-mobile-tab]').forEach(b=>b.classList.toggle('active',b.dataset.mobileTab===view)); requestAnimationFrame(fitCanvas); }

  async function openDemo() {
    if (!ui.connected) { toast('请先连接本地工作台。'); return; }
    const buttons=[$('demo-button'),$('empty-demo-button')]; buttons.forEach(b=>b.disabled=true);
    try { await api('/api/demo','POST',{}); clearObject(); await refreshState(true); toast('已打开示例项目。示例内容不会当作你的真实业务资料。'); if(innerWidth<=760) switchMobile('preview'); }
    catch(error){toast(error.message);} finally{buttons.forEach(b=>b.disabled=false);}
  }

  async function reviewPage() {
    const slide=activeSlide(); if (!slide?.hasPreview || ui.reviewBusy) return;
    if(hasComposerDraft()){toast('还有未发送的反馈，请先发送或保存，再认可页面。');return;}
    ui.reviewBusy=true; $('review-button').disabled=true;
    const submission={slideId:slide.id,sceneRevision:slide.sceneRevision,statement:'通过当前页面预览，认可这一页的当前版本。'};
    try { const result=await api('/api/review','POST',{...submission,clientMessageId:operatorRequestId('review-page',submission)});if(result?.slides || result?.state?.slides)applyState(result);else await refreshState();toast('已记录当前页认可，并计入一轮用户输入。'); }
    catch(error){toast(error.message);} finally{ui.reviewBusy=false;if(ui.state)renderState();}
  }

  async function undoPage() {
    const slide=activeSlide(); if(!slide || !slide.sceneRevision || ui.undoBusy)return;
    if(hasComposerDraft()){toast('还有未发送的反馈，请先发送或保存，再撤销页面。');return;}
    ui.undoBusy=true;
    $('undo-button').disabled=true;
    const submission={slideId:slide.id,sceneRevision:slide.sceneRevision};
    try{const result=await api('/api/undo','POST',{...submission,clientMessageId:operatorRequestId('undo-page',submission)});clearObject();if(result?.slides || result?.state?.slides)applyState(result);else await refreshState(true);toast('已恢复上一版，并计入一轮用户输入。历史记录保留。');}catch(error){toast(error.message);}finally{ui.undoBusy=false;if(ui.state)renderState();}
  }

  function renderUploads() {
    const host=$('attachments');host.replaceChildren();host.hidden=!ui.uploads.length;
    ui.uploads.forEach(asset=>{const chip=node('div',`attachment ${asset.status==='error'?'error':''}`);chip.append(icon(asset.status==='uploading'?'paperclip':'file','small'),node('span','',asset.filename+(asset.status==='uploading'?' · 上传中':asset.status==='error'?' · 未完成':'')));chip.title=asset.error||asset.filename;const remove=node('button');remove.type='button';remove.setAttribute('aria-label','移除 '+asset.filename);remove.append(icon('close','small'));remove.addEventListener('click',()=>{ui.uploads=ui.uploads.filter(a=>a.localId!==asset.localId);renderUploads();updateSend();});chip.append(remove);host.append(chip);});protectDraftTarget();updateSend();
  }

  async function uploadFiles(files) {
    const accepted=['image/png','image/jpeg','text/plain','text/markdown','application/pdf'];
    for (const file of [...files]) {
      if(ui.uploads.length>=10){toast('每条消息最多添加 10 个文件。可以先发送这些资料，再继续补充。');break;}
      let mime=file.type;if(!mime&&/\.md$/i.test(file.name))mime='text/markdown';if(!mime&&/\.txt$/i.test(file.name))mime='text/plain';
      if(!accepted.includes(mime)&&!/\.(md|txt)$/i.test(file.name)){toast('目前支持 PNG、JPG、TXT、Markdown 和 PDF。');continue;}
      if(!accepted.includes(mime)&&/\.(md|txt)$/i.test(file.name))mime=/\.md$/i.test(file.name)?'text/markdown':'text/plain';
      const limit=mime.startsWith('image/')?8:20;
      if(!file.size||file.size>limit*1024*1024){toast(!file.size?`${file.name} 是空文件。`:`${file.name} 超过 ${limit} MB，请压缩或拆分后再添加。`);continue;}
      const asset={localId:requestId(),filename:file.name,mime:mime||'text/plain',status:'uploading'};ui.uploads.push(asset);renderUploads();
      try {
        if(asset.mime.startsWith('text/')){
          let decoded;try{decoded=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());}catch{throw new Error('文本资料需要 UTF-8 编码，请转换编码后重试。');}
          let count=0;for(const character of decoded){if(++count>50000)throw new Error('文本资料超过 50,000 字，请拆分材料。');}
        }
        const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('无法读取文件。'));reader.readAsDataURL(file);});const result=await api('/api/assets','POST',{filename:asset.filename,mime:asset.mime,base64});asset.assetId=result.assetId||result.id||result.asset?.id;if(!asset.assetId)throw new Error('服务没有返回有效的素材记录。');asset.status='ready';
        if(asset.mime==='application/pdf')toast('PDF 已保存；这一版仅登记文件，尚未自动读取其中内容。',6000);
      }
      catch(error){asset.status='error';asset.error=error.message;toast(`${asset.filename}：${error.message}`);}renderUploads();
    }
    $('file-input').value='';
  }

  async function download(format,mode='draft') {
    closeExport();
    const button=$('export-button');button.disabled=true;
    try { const response=await fetch(exportRequestUrl(format,mode),{credentials:'same-origin',cache:'no-store'});const contentType=response.headers.get('content-type')||'';if(!response.ok||contentType.includes('application/json')){let data;try{data=await response.json();}catch{}throw new Error(messageError(data,'当前页面尚不能导出，请先完成页面生成。'));}const blob=await response.blob();const name=response.headers.get('content-disposition')?.match(/filename\*=UTF-8''([^;]+)|filename="([^"]+)"|filename=([^;]+)/i);let filename=`${ui.state?.project?.title||'presentation'}.${format}`;if(name){try{filename=decodeURIComponent(name[1]||name[2]||name[3]);}catch{}}const url=URL.createObjectURL(blob),link=node('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),15000);toast(mode==='release'?'正式稿文件已准备好。':'草稿已准备好；它不表示正式交付检查已通过。'); }
    catch(error){toast(error.message,6000);}finally{updateExport();}
  }

  function closeExport(){$('export-menu').hidden=true;$('export-button').setAttribute('aria-expanded','false');}
  function updateConnectionDialog(){
    const agent=ui.state?.agent||{},mode=agent.mode;
    const names={manual:'Coding Agent 协作',claude:'Claude Code',codex:'Codex',api:'模型 API',outline:'按大纲本地排版'};
    const profiles=ui.state?.modelProfiles || [], chosen=ui.state?.selectedModelProfile;
    $('model-picker').hidden=!profiles.length;
    const signature=JSON.stringify([profiles,chosen?.id]);
    if($('model-profile').dataset.signature!==signature){
      $('model-profile').replaceChildren();
      const placeholder=node('option','','请选择模型');placeholder.value='';$('model-profile').append(placeholder);
      for(const p of profiles){const option=node('option','',`${p.label}${p.available?'':' · 未配置'}`);option.value=p.id;option.disabled=!p.available;$('model-profile').append(option);}
      $('model-profile').value=chosen?.id || ''; $('model-profile').dataset.signature=signature;
    }
    const busy=ui.agentBusy || !ui.connected || ui.state?.jobs?.some(j=>['queued','running'].includes(j.status)) || ui.state?.backgroundTasks?.some(j=>['queued','running'].includes(j.status));
    $('model-profile').disabled=!!busy;$('choose-model').disabled=!!busy;
    $('image-mode').checked=(ui.state?.imageMode || 'auto')==='auto';$('image-mode').disabled=!!ui.agentBusy || !ui.connected || !!ui.state?.imageModeLocked;
    $('image-mode').title=ui.state?.imageModeLocked?'服务器已关闭自动配图':'';
    if(chosen)$('model-help').textContent=`当前：${chosen.model} · ${names[chosen.mode] || chosen.mode}。${profiles.find(p=>p.id===chosen.id)?.vision?'支持模板原图理解。':'模板适配使用布局结构；此通道不读取图片像素。'}切换用于新任务。`;
    $('connection-title').textContent=chosen?.label || names[mode] || '选择执行方式';
    const descriptions={
      manual:'在 Claude Code 或 Codex 中直接对话，让浏览器显示结果。网页消息会保留，需由 Agent 主动领取。',
      claude:'网页消息交给本机 Claude Code。先保存整稿计划，再逐页生成和显示预览。',
      codex:'网页消息交给本机 Codex。先保存整稿计划，再逐页生成和显示预览。',
      outline:'将你提供的逐页标题和正文排成页面。不调用模型，不代写观点或事实；需要先写好完整大纲。'
    };
    descriptions.api='通过模型 API 生成大纲、页面和编辑建议。';
    $('connection-description').textContent=descriptions[mode] || '选择后保留当前项目、页面和对话。';
    let detail=agent.message || agent.connectionHint || '';
    if(['claude','codex'].includes(mode))detail+=(detail?'\n':'')+(agent.available?'已找到客户端；实际请求时才确认登录状态和调用是否成功。':'请在运行工作台的电脑上安装并登录对应客户端。消息会保留，也可切换到本地大纲排版。');
    if(mode==='outline')detail='本地排版可用。以“按大纲排版”开头粘贴逐页内容，页面会自动依次生成。';
    $('connection-detail').textContent=detail;
    document.querySelectorAll('[data-agent-mode]').forEach(button=>{const selected=button.dataset.agentMode===mode;button.setAttribute('aria-pressed',String(selected));button.classList.toggle('selected',selected);button.disabled=!!busy;button.hidden=profiles.length>0 && ['claude','codex'].includes(button.dataset.agentMode);});
    $('handoff-card').hidden=mode==='outline';
    $('connection-outline-starter').hidden=mode!=='outline' || !!ui.state?.deck || !!ui.state?.slides?.length;
    const p=ui.state?.projectId||'<项目 ID>',s=activeSlide()?.id;
    $('handoff-text').textContent=`使用已连接的 PPT 工作台，继续项目 ${p}${s?' 的 '+s:''}。先读取待处理对话与整稿计划。按我的原话逐页制作，完成一页后继续计划中的下一页；指定对象的修改只作用于该对象，保留其他页面。`;
  }

  async function chooseModel() {
    const profileId=$('model-profile').value;
    if(!profileId || ui.agentBusy || !ui.connected)return;
    ui.agentBusy=true;$('connection-error').hidden=true;updateConnectionDialog();
    try{applyState(await api('/api/model','POST',{profileId}));toast('模型已保存，后续任务使用此模型。');}
    catch(error){$('connection-error').textContent=error.message;$('connection-error').hidden=false;}
    finally{ui.agentBusy=false;updateConnectionDialog();}
  }

  async function chooseImageMode() {
    if(ui.agentBusy || !ui.connected)return;
    const mode=$('image-mode').checked?'auto':'off';
    ui.agentBusy=true;$('connection-error').hidden=true;updateConnectionDialog();
    try{applyState(await api('/api/image-mode','POST',{mode}));toast(mode==='auto'?'已开启自动配图：整稿完成后为最多 3 页生成配图。':'已关闭自动配图，新整稿只使用原生色块与图形。');}
    catch(error){$('connection-error').textContent=error.message;$('connection-error').hidden=false;}
    finally{ui.agentBusy=false;updateConnectionDialog();}
  }

  async function chooseAgent(mode) {
    if(ui.agentBusy || !ui.connected || (ui.state?.agent?.mode===mode && !ui.state?.selectedModelProfile))return;
    ui.agentBusy=true;$('connection-error').hidden=true;updateConnectionDialog();
    try{const result=await api('/api/agent','POST',{mode});applyState(result);const agent=ui.state?.agent||{};toast(mode==='outline'?'已选择本地大纲排版。使用你提供的文字，不调用模型。':['claude','codex'].includes(mode)&&!agent.available?'模式已保存，但客户端尚未就绪。消息会保留。':'执行方式已保存，当前内容保留。');}
    catch(error){$('connection-error').textContent=error.message;$('connection-error').hidden=false;}
    finally{ui.agentBusy=false;updateConnectionDialog();}
  }

  async function controlDeck(action) {
    if(ui.deckBusy || !ui.state?.deck || !ui.connected)return;
    ui.deckBusy=true;renderDeckProgress();
    try{applyState(await api('/api/deck/control','POST',{action}));}
    catch(error){toast(error.message,6000);}
    finally{ui.deckBusy=false;renderDeckProgress();}
  }

  function fillOutlineTemplate() {
    if($('message-input').value.trim()) {toast('输入框已有内容，请先保存或发送，再填写逐页大纲。');$('message-input').focus();return;}
    if($('connection-dialog').open)$('connection-dialog').close();
    clearObject();$('message-input').value=outlineTemplate;resizeComposer();protectDraftTarget();switchMobile('chat');$('message-input').focus();
    toast('请用真实内容替换方括号后再发送。要显示在页上的公司、日期等信息，请放到该页正文。此步骤尚未提交。',8000);
  }

  const templateRoles={cover:'封面',toc:'目录',chapter:'章节页',content:'正文内容页',ending:'结束页',appendix:'附录页'};
  function currentPageRole() {
    const slide=activeSlide(),title=slide?.title || '';
    if(/附录|来源说明|参考资料/.test(title))return 'appendix';
    if(slide?.role==='compare'||slide?.role==='parallel'||slide?.role==='process')return 'content';
    if(templateRoles[slide?.role])return slide.role;
    if(!slide || slideIndex()===0)return 'cover';
    return 'content';
  }
  function templateScore(template) {
    const text=`${activeSlide()?.title || ''} ${$('message-input').value} ${ui.state?.project?.title || ''}`;
    const groups={compare:/对比|比较|竞品|友商|差异/,parallel:/并列|三个|三项|优势|特点/,process:/流程|步骤|计划|阶段|时间/,argument:/观点|背景|问题|原因/,product:/产品|功能|界面|演示/,proof:/团队|人物|案例|证据/,structure:/架构|关系|组织/,data:/数据|指标|趋势|收入/};
    let score=template.roles?.includes(currentPageRole())?20:0;
    if(groups[template.family]?.test(text))score+=10;
    if(groups[template.id]?.test(text))score+=8;
    for(const tag of template.tags || [])if(tag.length>1&&text.includes(tag))score+=3;
    const recommendedIndex=(design.recommendations || []).findIndex(item=>item.id===template.id);
    if(recommendedIndex>=0)score+=1000-recommendedIndex;

    if(ui.state?.selectedTemplateId===template.id)score+=2;
    return score;
  }
  function uniqueTemplateLayouts(templates,limit=6) {
    const seen=new Set();
    return templates.filter(template=>{const key=template.baseTemplateId || template.id;if(seen.has(key))return false;seen.add(key);return true;}).slice(0,limit);
  }
  const STRIP_CATEGORIES=[['recommended','推荐'],['cover','封面'],['toc','目录'],['chapter','章节'],['content','正文'],['compare','对比'],['process','流程'],['data','数据'],['ending','结束']];
  const STRIP_CATEGORY_IDS=new Set(['cover','toc','chapter','compare','process','data','ending']);
  const STRIP_FILTERS={cover:t=>t.browseCategory==='cover',toc:t=>t.browseCategory==='toc',chapter:t=>t.browseCategory==='chapter',compare:t=>t.browseCategory==='compare',process:t=>t.browseCategory==='process',data:t=>t.browseCategory==='data',ending:t=>t.browseCategory==='ending',content:t=>(t.roles||[]).includes('content')&&!STRIP_CATEGORY_IDS.has(t.browseCategory)};
  function updateStripNav(){const strip=$('template-strip');$('template-strip-prev').disabled=strip.scrollLeft<=1;$('template-strip-next').disabled=strip.scrollLeft>=strip.scrollWidth-strip.clientWidth-1;}
  function renderTemplates() {
    $('template-smart').disabled=!design.smartAvailable || !activeSlide()?.hasPreview || design.smartBusy;
    $('template-smart').textContent=design.smartBusy?'正在选版…':'智能选版';
    const grid=$('template-grid');
    const roles=$('template-roles');roles.replaceChildren();
    const available=design.templates.filter(template=>!template.legacy && !template.archived);
    const source=available.filter(t=>(design.filter==='reference'?t.reference:true) && (design.role==='all'||t.roles?.includes(design.role)));
    const categories=new Map([['all','全部用途'],...available.slice().sort((a,b)=>a.browseCategoryOrder-b.browseCategoryOrder).map(t=>[t.browseCategory,t.browseCategoryName])]);
    categories.forEach((title,id)=>{const count=id==='all'?source.length:source.filter(t=>t.browseCategory===id).length;const button=node('button','',`${title} · ${count}`);button.type='button';button.dataset.category=id;button.disabled=count===0;button.setAttribute('aria-pressed',String(design.category===id));button.addEventListener('click',()=>{design.category=id;renderTemplates();});roles.append(button);});
    const terms=design.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const isUser=design.filter==='user';
    const ranked=isUser?[]:source.filter(template=>(design.category==='all'||template.browseCategory===design.category) && terms.every(term=>`${template.name} ${template.browseCategoryName} ${template.description} ${(template.tags||[]).join(' ')} ${template.use||''}`.toLowerCase().includes(term))).sort((a,b)=>templateScore(b)-templateScore(a));
    const strip=$('template-strip');
    const chips=$('template-categories');chips.replaceChildren();
    STRIP_CATEGORIES.forEach(([id,label])=>{
      const count=id==='recommended'?null:available.filter(t=>t.current && STRIP_FILTERS[id](t)).length;
      const chip=node('button','',count===null?label:`${label} · ${count}`);chip.type='button';chip.disabled=count===0;
      chip.setAttribute('aria-pressed',String(design.stripCategory===id));
      chip.addEventListener('click',()=>{design.stripCategory=id;renderTemplates();});chips.append(chip);
    });
    if((design.userTemplates||[]).length){
      const chip=node('button','',`我的模板 · ${design.userTemplates.length}`);chip.type='button';
      chip.setAttribute('aria-pressed',String(design.stripCategory==='user'));
      chip.addEventListener('click',()=>{design.stripCategory='user';renderTemplates();});chips.append(chip);
    }
    const stripPool=design.stripCategory==='recommended'?available.filter(template=>template.current && template.roles?.includes(currentPageRole())):design.stripCategory==='user'?(design.userTemplates||[]):available.filter(t=>t.current && STRIP_FILTERS[design.stripCategory](t));
    const recommendations=uniqueTemplateLayouts(stripPool.sort((a,b)=>templateScore(b)-templateScore(a)),design.stripCategory==='recommended'?6:8);
    updateStripNav();
    const stripKey=JSON.stringify(recommendations.map(t=>[t.id,t.previewUrl,t.referencePreviewUrl]));
    if(strip.dataset.previewKey!==stripKey){
    strip.dataset.previewKey=stripKey;clearPreviews(strip);strip.replaceChildren();
    if(!recommendations.length)strip.append(node('span','', '暂无推荐样式'));
    recommendations.forEach(template=>{
      const card=node('button','ribbon-template');card.type='button';card.disabled=design.applying;card.title=`预览 ${template.name}`;card.setAttribute('aria-label',`预览样式 ${template.name}`);
      const preview=node('div','template-card-preview'),frame=node(template.reference?'img':'iframe');if(template.reference){frame.alt=template.name+'原稿参考';}else{frame.title=template.name+'模板预览';frame.tabIndex=-1;frame.setAttribute('sandbox','allow-scripts');}lazyPreview(frame,template.reference?template.referencePreviewUrl:template.previewUrl);preview.append(frame);
      card.append(preview,node('span','',template.name));card.addEventListener('click',()=>previewTemplate(template));strip.append(card);
    });
    }
    const templates=isUser?(design.userTemplates||[]):design.filter==='recommended'?uniqueTemplateLayouts(ranked.filter(t=>design.category!=='all'||design.role!=='all'||t.roles?.includes(currentPageRole()))):ranked;
    let countNote=$('template-count');if(!countNote){countNote=node('p','dialog-note');countNote.id='template-count';grid.before(countNote);}countNote.textContent=isUser?`我的上传 · ${templates.length} 页`: `精选案例 · ${categories.get(design.category)} · 当前展示 ${templates.length} 项`;
    $('templates-title').textContent=isUser?'我的上传模板':'精选设计案例';
    document.querySelector('[data-template-filter="all"]').textContent=`精选案例 · ${available.length}`;
    document.querySelector('[data-template-filter="reference"]').textContent='精选案例';
    document.querySelector('[data-template-filter="user"]').textContent=`我的模板 · ${(design.userTemplates||[]).length}`;
    const gridKey=(isUser?'user':'')+JSON.stringify(templates.map(t=>[t.id,t.previewUrl,t.referencePreviewUrl]));
    if(grid.dataset.previewKey!==gridKey){
    grid.dataset.previewKey=gridKey;clearPreviews(grid);grid.replaceChildren();
    if(isUser){
      const uploadCard=node('button','template-card template-upload-card');uploadCard.type='button';
      const up=node('div','template-card-preview');up.append(node('span','upload-plus','＋'));
      uploadCard.append(up,node('p','','上传模板页 · PNG/JPG 一张图一页，或 PPTX（前 10 页）'));
      uploadCard.addEventListener('click',()=>$('user-template-input').click());grid.append(uploadCard);
    }
    if(!templates.length)grid.append(node('p','',isUser?'还没有上传的模板页。':'没有匹配的模板，试试其他用途、关键词或页面位置。'));
    templates.forEach((template,index)=>{
      const card=node('button','template-card');card.type='button';card.disabled=design.applying;
      const preview=node('div','template-card-preview'),frame=node(template.reference?'img':'iframe');if(template.reference){frame.alt=template.name+'原稿参考';}else{frame.title=template.name+'模板预览';frame.tabIndex=-1;frame.setAttribute('sandbox','allow-scripts');}lazyPreview(frame,template.reference?template.referencePreviewUrl:template.previewUrl);preview.append(frame);
      const label=node('div','template-card-label');label.append(node('strong','',template.name),node('span','',template.referenceOnly?'查看案例':template.reference?'参考适配':'预览'));
      card.append(preview,label,node('p','',template.description));
      if(template.sourceLabel)card.append(node('small','',template.sourceLabel));
      if(template.capacityLabel)card.append(node('small','',template.capacityLabel));
      if(template.tasteMatch)card.append(node('small','taste-tag','贴近你的风格'));
      const detail=node('details','template-rules'),summary=node('summary','','适用场景与规则');detail.append(summary,node('p','',template.use || template.description));
      if(template.reference && !template.userTemplate && !template.referenceOnly)detail.append(node('p','',`${template.source} · 第 ${template.sourcePage} 页；按原页结构生成内容适配预览`));
      if(template.checks?.length){const list=node('ul');template.checks.forEach(check=>list.append(node('li','',check)));detail.append(list);}
      if(template.userTemplate){
        const tools=node('div','template-user-tools');
        const rename=node('button','','重命名');rename.type='button';rename.addEventListener('click',async event=>{event.stopPropagation();const name=prompt('模板名称',template.name);if(name?.trim()){await api('/api/user-templates/rename','POST',{id:template.userId,name:name.trim()}).catch(e=>toast(e.message));await refreshUserTemplates();}});
        const del=node('button','','删除');del.type='button';del.addEventListener('click',async event=>{event.stopPropagation();await api('/api/user-templates/delete','POST',{id:template.userId}).catch(e=>toast(e.message));await refreshUserTemplates();});
        tools.append(rename,del);detail.append(tools);
      }
      detail.addEventListener('click',event=>event.stopPropagation());
      const item=node('div','template-item');item.append(card,detail);card.addEventListener('click',()=>previewTemplate(template));grid.append(item);
    });
    }
    for(const button of document.querySelectorAll('#template-grid .template-card, #template-strip .ribbon-template'))button.disabled=design.applying;
    document.querySelectorAll('[data-template-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.templateFilter===design.filter)));
  }
  function syncTemplateTarget() {
    const slide=activeSlide(), target=slide?{slideId:slide.id,sceneRevision:slide.sceneRevision}:null;
    const key=JSON.stringify([ui.state?.projectId,target,currentPageRole()]);
    if(key===design.targetKey)return;
    closeTemplateMatches();
    design.targetKey=key;design.target=target;design.role='all';design.category='all';design.recommendations=[];
    design.smartRequestId++;design.smartBusy=false;design.smartRanked=false;
    $('template-smart-status').textContent='';
    loadRecommendations(key,slide?.id);
    $('template-position').value='all';
    $('template-target').textContent=design.filter==='user'?'你的上传模板页，先预览再应用。':'共50套精选案例。把喜欢的名称告诉AI，确认文案后按内容排版。';
    if(design.templates.length)renderTemplates();
  }
  async function loadRecommendations(key,slideId) {
    try {
      const result=await api(`/api/templates/recommendations${slideId?'?slideId='+encodeURIComponent(slideId):''}`);
      if(design.targetKey!==key)return;
      design.smartAvailable=result.smartAvailable===true;
      if(!design.smartRanked)design.recommendations=Array.isArray(result.recommendations)?result.recommendations:[];
      design.tasteSummary=result.tasteSummary||null;
      if(design.templates.length)renderTemplates();
    } catch { /* Local role and content matching remain available. */ }
  }
  async function requestSmartTemplates() {
    if(design.smartBusy || !design.smartAvailable || !design.target)return;
    const key=design.targetKey,requestId=++design.smartRequestId,target={...design.target};
    design.smartBusy=true;$('template-smart-status').textContent='正在根据本页内容选择版式…';renderTemplates();
    try {
      const result=await api('/api/templates/recommendations','POST',target);
      if(design.targetKey!==key || design.smartRequestId!==requestId)return;
      if(result.slideId!==target.slideId || result.sceneRevision!==target.sceneRevision)throw Error('页面已变化，请重新选版。');
      design.recommendations=Array.isArray(result.recommendations)?result.recommendations:[];
      design.tasteSummary=result.tasteSummary||design.tasteSummary;
      design.smartRanked=true;design.filter='recommended';design.role='all';design.category='all';design.query='';
      $('template-position').value='all';$('template-search').value='';
      const notes={single_candidate:'没有其他匹配版式，已保留当前推荐。',uncertain:'没有明确优选，已保留快速匹配结果。',busy:'智能选版正在处理其他请求，已保留快速匹配结果。',too_large:'本页内容较多，已保留快速匹配结果。',not_configured:'智能选版暂未配置，已保留快速匹配结果。'};
      $('template-smart-status').textContent=result.recommendationEngine==='jev'?'智能选版完成，先预览再应用。':notes[result.recommendationStatus] || '智能选版暂时不可用，已保留快速匹配结果。';
    } catch(error) {
      if(design.targetKey===key && design.smartRequestId===requestId)$('template-smart-status').textContent=error.message;
    } finally {
      if(design.targetKey===key && design.smartRequestId===requestId){design.smartBusy=false;renderTemplates();}
    }
  }
  async function loadTemplates() {
    if(design.loading || design.templates.length)return;
    design.loading=true;$('template-error').hidden=true;$('template-grid').textContent='正在读取推荐样式…';
    try{const result=await api('/api/templates');design.templates=result.templates || [];renderTemplates();if(ui.state)renderState();}
    catch(error){$('template-grid').textContent='';$('template-strip').textContent='样式加载失败，请打开更多样式重试。';$('template-error').textContent=error.message;$('template-error').hidden=false;}
    finally{design.loading=false;if(ui.state)renderChatTemplate(ui.state,activeSlide());}
    loadUserTemplates();
  }
  async function loadUserTemplates() {
    try{
      const result=await api('/api/user-templates');
      design.userTemplates=(result.templates||[]).filter(t=>t.kind==='page').map(t=>({id:'user-'+t.id,userId:t.id,name:t.name,reference:true,userTemplate:true,referencePreviewUrl:t.previewUrl,roles:['content'],browseCategory:'user',use:'用户上传的模板页',fitRule:'只模仿版式与视觉语言，不复制模板页上的文字、数据、Logo 或人物。',description:'用户上传的模板页'}));
      design.styleTemplates=(result.templates||[]).filter(t=>t.kind==='style');
      renderTemplates();
    }catch{}
  }
  async function refreshUserTemplates() {
    try{const result=await api('/api/user-templates');
      design.userTemplates=(result.templates||[]).filter(t=>t.kind==='page').map(t=>({id:'user-'+t.id,userId:t.id,name:t.name,reference:true,userTemplate:true,referencePreviewUrl:t.previewUrl,roles:['content'],browseCategory:'user',use:'用户上传的模板页',fitRule:'只模仿版式与视觉语言，不复制模板页上的文字、数据、Logo 或人物。',description:'用户上传的模板页'}));
      design.styleTemplates=(result.templates||[]).filter(t=>t.kind==='style');renderTemplates();renderStyleBadge();
    }catch{}
  }
  async function uploadUserTemplates(files,kind='page'){
    const items=[];
    const PPTX='application/vnd.openxmlformats-officedocument.presentationml.presentation';
    const pptx=kind==='page'?[...files].find(f=>f.type===PPTX||/\.pptx$/i.test(f.name)):null;
    for(const file of pptx?[pptx]:[...files].slice(0,kind==='style'?3:5)){
      const mime=file===pptx?PPTX:file.type;
      if(file!==pptx&&!['image/png','image/jpeg'].includes(mime)){toast(kind==='page'?'只接受 PNG、JPEG 或 PPTX。':'只接受 PNG 或 JPEG。');continue;}
      if(file.size>(file===pptx?20:8)*1024*1024){toast(`${file.name} 超过 ${file===pptx?20:8} MB。`);continue;}
      const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('无法读取文件。'));reader.readAsDataURL(file);});
      items.push({filename:file.name,mime,base64});
    }
    if(!items.length)return;
    if(pptx)toast('正在导入 PPTX 页面，请稍候…');
    try{const result=await api('/api/user-templates','POST',{kind,files:items});await refreshUserTemplates();
      if(pptx)toast(`已导入 ${result.templates.length} 页模板${result.slideCount>result.importedLimit?`（共 ${result.slideCount} 页，只导入前 ${result.importedLimit} 页）`:''}${result.skippedPages?.length?`；第 ${result.skippedPages.join('、')} 页无法导入`:''}。`,6000);
      else if(kind==='page')toast('已保存我的模板页。');return result;}
    catch(error){toast(error.message);throw error;}
  }
  let templateProposal=null,templatePreviewSequence=0;
  function loadTemplateFrame(id,html,url=null) {
    // Replace the browsing context: Chromium may retain a suspended srcdoc after
    // its containing dialog was closed and reopened.
    const previous=$(id),frame=node('iframe');
    frame.id=id;frame.title=previous.title;frame.setAttribute('sandbox','allow-scripts');
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('预览加载超时，请重新打开。')),90000);
      frame.addEventListener('load',()=>{clearTimeout(timer);resolve();},{once:true});
      if(url)frame.src=url;else frame.srcdoc=html;previous.replaceWith(frame);
    });
  }
  async function previewTemplate(template) {
    if(template.referenceOnly){window.open(template.detailUrl,'_blank','noopener');return;}
    if(design.applying)return;
    if(design.dirty || design.saving){toast('请先保存当前文字修改，再预览样式。');return;}
    const sequence=++templatePreviewSequence,target=design.target?{...design.target}:null;
    templateProposal={template,target,key:design.targetKey,proposalId:null};$('template-preview-apply').disabled=true;
    $('template-preview-title').textContent=template.name;
    $('template-preview-description').textContent=template.reference
      ?`${template.source} · 第 ${template.sourcePage} 页。${template.fitRule}`:template.use || template.description;
    $('template-preview-note').textContent='生成预览后再应用。保留全部原文和图片，可撤销。';
    $('template-before-label').textContent='选中的模板 · 示例内容';
    $('template-after-label').textContent=target?'当前页面 · 等待适配':'版式示例 · 尚未选定';
    $('template-original').hidden=!template.reference;$('template-before').hidden=!!template.reference;
    if(template.reference)$('template-original').src=template.referencePreviewUrl;
    $('template-adaptation-controls').hidden=!target || !!template.current;$('template-generate').disabled=!target;$('template-adaptation-approach').disabled=false;
    $('template-preview-apply').textContent=target?'应用这版':'选为新页设计参考';
    $('template-preview-status').textContent=target?'选择适配方式，让 AI 按模板重新组织当前页。原稿在确认前保持不变。':'选定后作为新页面的设计参考。';
    if(!$('template-preview-dialog').open)$('template-preview-dialog').showModal();
    try{
      if(target && template.current){
        const original=new URL('/api/preview/'+encodeURIComponent(target.slideId),location.origin);
        original.searchParams.set('project',ui.state.projectId);original.searchParams.set('rev',target.sceneRevision);
        $('template-before-label').textContent='当前页面';
        $('template-after-label').textContent='换版预览 · 尚未应用';
        await loadTemplateFrame('template-before',null,original.href);
        const result=await api('/api/templates/preview?'+new URLSearchParams({template:template.id,format:'json',...target}));
        if(sequence!==templatePreviewSequence)return;
        await loadTemplateFrame('template-after',result.html);
        if(sequence!==templatePreviewSequence || !$('template-preview-dialog').open)return;
        $('template-preview-status').textContent='核对预览后应用；原文、原图与图表保留。';
        $('template-preview-note').textContent='可撤销。需要进一步调整时，可使用 AI 助手。';
        $('template-preview-apply').disabled=false;
        return;
      }
      if(!template.reference || !target){
        const result=await api('/api/templates/preview?'+new URLSearchParams({template:template.id,format:'json'}));
        if(sequence!==templatePreviewSequence)return;
        if(!template.reference)await loadTemplateFrame('template-before',result.html);
        if(!target)await loadTemplateFrame('template-after',result.html);
      }
      if(target){
        const url=new URL('/api/preview/'+encodeURIComponent(target.slideId),location.origin);url.searchParams.set('project',ui.state.projectId);url.searchParams.set('rev',target.sceneRevision);
        await loadTemplateFrame('template-after',null,url.href);
      }
      if(sequence!==templatePreviewSequence || !$('template-preview-dialog').open)return;
      $('template-preview-apply').disabled=!!target;
    }catch(error){if(sequence===templatePreviewSequence)$('template-preview-status').textContent=error.message;}
  }
  async function generateTemplatePreview(){
    const captured=templateProposal,sequence=templatePreviewSequence;
    if(!captured?.target || $('template-generate').disabled)return;
    if(captured.key!==design.targetKey){$('template-preview-status').textContent='页面已变化，请重新打开模板。';return;}
    captured.proposalId=null;$('template-preview-apply').disabled=true;$('template-generate').disabled=true;
    $('template-adaptation-approach').disabled=true;
    $('template-preview-status').textContent='AI 正在借鉴模板设计新页面，再检查表达、绘图和排版；必要时修正一轮。原稿保持不变…';
    try{
      const result=await api('/api/templates/adapt','POST',{templateId:captured.template.id,...captured.target,approach:$('template-adaptation-approach').value});
      if(sequence!==templatePreviewSequence || !$('template-preview-dialog').open)return;
      await loadTemplateFrame('template-after',result.html);
      if(sequence!==templatePreviewSequence || !$('template-preview-dialog').open)return;
      templateProposal={...captured,proposalId:result.proposalId};
      $('template-after-label').textContent='AI 适配结果 · 尚未应用';
      const review=result.designLoop,checked=review && ['reviewed','revised_and_reviewed'].includes(review.status);
      const reviewDetails=(review?.passes || []).filter(pass=>pass.reply).map((pass,index)=>`第 ${index+1} 次设计检查\n${pass.reply}`);
      if(review?.error?.message)reviewDetails.push(`检查说明：${review.error.message}`);
      $('template-preview-status').textContent=[result.reply,...reviewDetails].filter(Boolean).join('\n\n');
      const reviewText=review?(checked?(review.reviewMode==='image-and-structure'?'已完成看图检查':'已完成结构检查，未看图'):'自动设计检查有待确认，请查看预览'):'原文完整，渲染无文字溢出';
      $('template-preview-note').textContent=`${result.modelBinding?.label || '当前模型'} · ${reviewText} · 原文与原图保留。`;
      $('template-preview-apply').disabled=false;
    }catch(error){if(sequence===templatePreviewSequence)$('template-preview-status').textContent=error.message;}
    finally{if(sequence===templatePreviewSequence){$('template-generate').disabled=false;$('template-adaptation-approach').disabled=false;}}
  }
  $('template-generate').addEventListener('click',generateTemplatePreview);
  $('template-adaptation-approach').addEventListener('change',()=>{if(templateProposal)templateProposal.proposalId=null;$('template-preview-apply').disabled=true;$('template-preview-status').textContent='适配方式已改变，请重新生成预览。';});
  function closeTemplatePreview(){templatePreviewSequence++;templateProposal=null;$('template-preview-dialog').close();}
  for(const id of ['template-preview-close','template-preview-cancel'])$(id).addEventListener('click',closeTemplatePreview);
  $('template-preview-dialog').addEventListener('cancel',()=>{templatePreviewSequence++;templateProposal=null;});
  $('template-preview-apply').addEventListener('click',async()=>{
    const proposal=templateProposal;if(!proposal)return;
    if(proposal.key!==design.targetKey){$('template-preview-status').textContent='页面或版本已变化，请重新预览。';$('template-preview-apply').disabled=true;return;}
    $('template-preview-apply').disabled=true;
    if(!proposal.target){const applied=await applyTemplate(proposal.template,null);if(applied)closeTemplatePreview();return;}
    if(proposal.template.current){const applied=await applyTemplate(proposal.template,proposal.target);if(applied)closeTemplatePreview();return;}
    if(!proposal.proposalId){$('template-preview-status').textContent='请先生成适配预览。';return;}
    design.applying=true;
    try{await api('/api/templates/apply','POST',{proposalId:proposal.proposalId});await refreshState(true);closeTemplatePreview();toast('已应用刚才的适配预览，可撤销。');}
    catch(error){$('template-preview-status').textContent=error.message;}
    finally{design.applying=false;renderTemplates();}
  });
  async function applyTemplate(template,capturedTarget=design.target) {
    if(design.applying)return;if(design.dirty || design.saving){toast('请先保存当前文字修改，再更换样式。');return;}
    const target=capturedTarget ? {...capturedTarget} : null;design.applying=true;renderTemplates();
    try{await api('/api/template','POST',{...(target || {}),templateId:template.id});await refreshState(true);toast(target?'页面样式已更新。':'已选定模板，下一次生成时使用。');return true;}
    catch(error){$('template-error').textContent=error.message;$('template-error').hidden=false;toast(error.message);}
    finally{design.applying=false;renderTemplates();}
  }
  const PALETTE_PRESETS=[{name:'商务蓝',primary:'#1F4E9E',secondary:['#2BB3C0','#F2A541']},{name:'科技紫',primary:'#5B3FD9',secondary:['#22C1C3','#FF6B8B']},{name:'沉稳墨绿',primary:'#1E6B52',secondary:['#C9A227','#7FB7A4']},{name:'活力橙',primary:'#E8590C',secondary:['#1C7ED6','#FAB005']},{name:'学术红',primary:'#A61E4D',secondary:['#364FC7','#868E96']},{name:'极简黑',primary:'#212529',secondary:['#E03131','#ADB5BD']},{name:'清新青',primary:'#0CA678',secondary:['#4DABF7','#FFD43B']},{name:'高级金',primary:'#B08D57',secondary:['#2F3E46','#84A98C']}];
  const paletteDraft={primary:'#1F4E9E',secondary:['#2BB3C0'],busy:false};
  function palettePresets(){return ui.state?.palettePresets?.length?ui.state.palettePresets:PALETTE_PRESETS;}
  function renderPalettePreview(){const host=$('palette-preview');host.replaceChildren();[paletteDraft.primary,...paletteDraft.secondary].filter(Boolean).forEach(colour=>{const swatch=node('i');swatch.style.background=colour;swatch.title=colour;host.append(swatch);});}
  function renderPaletteDialog(){
    const presets=$('palette-presets');presets.replaceChildren();
    for(const preset of palettePresets()){
      const row=node('button','palette-preset');row.type='button';
      const swatches=node('span','palette-swatches');
      [preset.primary,...(preset.secondary||[])].forEach(colour=>{const swatch=node('i');swatch.style.background=colour;swatches.append(swatch);});
      row.append(swatches,node('span','',preset.name));
      row.addEventListener('click',()=>{paletteDraft.primary=preset.primary;paletteDraft.secondary=[...(preset.secondary||[])].slice(0,2);renderPaletteDialog();});
      presets.append(row);
    }
    $('palette-primary').value=paletteDraft.primary;
    const list=$('palette-secondary-list');list.replaceChildren();
    paletteDraft.secondary.forEach((colour,index)=>{
      const row=node('div','palette-secondary'),input=node('input');input.type='color';input.value=colour;input.setAttribute('aria-label',`辅色 ${index+1}`);
      input.addEventListener('input',()=>{paletteDraft.secondary[index]=input.value;renderPalettePreview();});
      const remove=node('button','icon-button','×');remove.type='button';remove.setAttribute('aria-label','移除辅色');
      remove.addEventListener('click',()=>{paletteDraft.secondary.splice(index,1);renderPaletteDialog();});
      row.append(input,remove);list.append(row);
    });
    $('palette-secondary-add').disabled=paletteDraft.secondary.length>=2 || paletteDraft.busy;
    $('palette-apply-page').disabled=paletteDraft.busy || !activeSlide()?.hasPreview;
    $('palette-apply-deck').disabled=paletteDraft.busy;
    $('palette-apply-deck').textContent=(ui.state?.slides||[]).length?'应用到整稿':'使用此配色';
    $('palette-save').disabled=paletteDraft.busy;$('palette-clear').disabled=paletteDraft.busy || !ui.state?.palette;
    renderPalettePreview();
  }
  function openPalette(){
    const saved=ui.state?.palette;
    if(saved){paletteDraft.primary=saved.primary;paletteDraft.secondary=[...(saved.secondary||[])].slice(0,2);}
    $('palette-error').hidden=true;renderPaletteDialog();$('palette-dialog').showModal();
  }
  function paletteDraftValue(){
    const primary=String(paletteDraft.primary||'').toUpperCase(),secondary=paletteDraft.secondary.map(c=>String(c||'').toUpperCase()).filter(c=>/^#[0-9A-F]{6}$/.test(c));
    if(!/^#[0-9A-F]{6}$/.test(primary)||!secondary.length||new Set([primary,...secondary]).size!==1+secondary.length)return null;
    return {primary,secondary};
  }
  async function savePalette(apply){
    const value=paletteDraftValue();
    if(!value){$('palette-error').textContent='请选择一个主色和 1–2 个互不相同的辅色。';$('palette-error').hidden=false;return;}
    paletteDraft.busy=true;$('palette-error').hidden=true;renderPaletteDialog();
    try{
      if(!apply || !ui.state.slides.length){applyState(await api('/api/palette','POST',value));toast('配色已保存，生成时自动使用。');$('palette-dialog').close();return;}
      const slide=activeSlide(),result=await api('/api/palette/apply','POST',{palette:value,projectRevision:ui.state.projectRevision,...(apply==='deck'?{scope:'deck'}:{scope:'page',slideId:slide.id,sceneRevision:slide.sceneRevision})});
      if(result?.state)applyState(result.state);else await refreshState(true);
      const skipped=(result?.skipped||[]).length;
      toast(`已为 ${result?.changedSlides?.length||0} 页应用配色，可撤销。${skipped?`另有 ${skipped} 页未变化或需要先更新预览。`:''}`,6000);
      $('palette-dialog').close();
    }catch(error){$('palette-error').textContent=error.message;$('palette-error').hidden=false;}
    finally{paletteDraft.busy=false;if($('palette-dialog').open)renderPaletteDialog();}
  }
  async function clearPalette(){
    paletteDraft.busy=true;renderPaletteDialog();
    try{applyState(await api('/api/palette','POST',{clear:true}));toast('已清除配色。');$('palette-dialog').close();}
    catch(error){$('palette-error').textContent=error.message;$('palette-error').hidden=false;}
    finally{paletteDraft.busy=false;if($('palette-dialog').open)renderPaletteDialog();}
  }

  const STYLE_FIELDS=[['summary','风格定位'],['ui.grid','UI · 网格与对齐'],['ui.whitespace','UI · 留白与密度'],['ui.hierarchy','UI · 层级'],['ui.containers','UI · 容器'],['elements.shapes','元素 · 图形'],['elements.lines','元素 · 线条'],['elements.imagery','元素 · 图像'],['elements.dataViz','元素 · 数据呈现'],['typography.title','字体 · 标题'],['typography.body','字体 · 正文'],['typography.accent','字体 · 强调'],['color.usage','配色 · 用法'],['designStyle.keywords','设计风格 · 关键词（每行一个）'],['designStyle.mood','设计风格 · 气质'],['designStyle.pageRhythm','设计风格 · 页面节奏'],['avoid','避免（每行一个）']];
  const style={list:[],editing:null,profile:null,busy:false};
  function profileGet(p,path){return path.split('.').reduce((o,k)=>o?.[k],p);}
  function profileSet(p,path,v){const keys=path.split('.');let o=p;keys.slice(0,-1).forEach(k=>o=o[k]??={});o[keys.at(-1)]=v;}
  function renderStyleBadge(){const ref=ui.state?.styleReference;$('style-badge').hidden=!ref;if(ref)$('style-badge').textContent=' · '+ref.name;}
  function renderStyleList(){
    const host=$('style-list');host.replaceChildren();
    const ref=ui.state?.styleReference;
    for(const t of style.list){
      const item=node('div','style-item');
      const thumbs=node('div','style-thumbs');(t.previews||[t.previewUrl]).slice(0,3).forEach(url=>{const img=node('img');img.alt=t.name;img.src=url;thumbs.append(img);});
      const info=node('div','style-info');info.append(node('strong','',t.name),node('p','',t.profile?.summary||'尚未解析风格'));
      if(ref?.id===t.id)info.append(node('span','style-active-badge','使用中'));
      const actions=node('div','style-actions');
      const analyze=node('button','button quiet compact',t.profile?'重新解析':'解析风格');analyze.type='button';analyze.disabled=style.busy;
      analyze.addEventListener('click',()=>analyzeStyle(t));
      const use=node('button','button primary compact',ui.state?.slides?.length?'整稿改版':'使用此风格');use.type='button';use.disabled=style.busy;
      use.addEventListener('click',()=>startStyleWorkflow(t.id));
      const del=node('button','button quiet compact','删除');del.type='button';del.disabled=style.busy;
      del.addEventListener('click',async()=>{await api('/api/user-templates/delete','POST',{id:t.id}).catch(e=>toast(e.message));await refreshUserTemplates();renderStyleList();});
      actions.append(analyze,use,del);item.append(thumbs,info,actions);host.append(item);
      if(style.editing===t.id){const edit=node('button','button quiet compact','编辑档案');edit.type='button';edit.addEventListener('click',()=>{style.profile=JSON.parse(JSON.stringify(t.profile));renderStyleForm();});actions.prepend(edit);}
    }
    if(!style.list.length)host.append(node('p','','上传或粘贴参考图，即可使用它的设计风格。'));
  }
  function renderStyleForm(){
    const form=$('style-form');form.replaceChildren();$('style-editor').hidden=false;
    if(!style.profile){form.append(node('p','','解析后可编辑档案。'));return;}
    for(const [path,label] of STYLE_FIELDS){
      const row=node('label','style-field');row.append(node('span','',label));
      const value=profileGet(style.profile,path);
      const input=node('textarea');input.rows=2;input.value=Array.isArray(value)?value.join('\n'):(value||'');
      input.dataset.path=path;row.append(input);form.append(row);
    }
    const colours=node('div','style-colours');colours.append(node('span','','配色（#RRGGBB）'));
    for(const key of ['background','ink','primary']){const l=node('label','palette-field',({background:'背景',ink:'文字',primary:'主色'})[key]);const input=node('input');input.type='color';input.value=style.profile.color[key];input.dataset.colorKey=key;l.append(input);colours.append(l);}
    const sec=node('div','palette-field');sec.append(node('span','','辅色'));
    style.profile.color.secondary.forEach((c,i)=>{const input=node('input');input.type='color';input.value=c;input.dataset.secondary=i;sec.append(input);});
    colours.append(sec);form.append(colours);
  }
  function collectStyleForm(){
    const profile=JSON.parse(JSON.stringify(style.profile));
    $('style-form').querySelectorAll('textarea').forEach(input=>{
      const path=input.dataset.path;
      if(path==='designStyle.keywords'||path==='avoid')profileSet(profile,path,input.value.split('\n').map(s=>s.trim()).filter(Boolean));
      else profileSet(profile,path,input.value.trim());
    });
    $('style-form').querySelectorAll('input[data-color-key]').forEach(i=>profile.color[i.dataset.colorKey]=i.value.toUpperCase());
    profile.color.secondary=[...$('style-form').querySelectorAll('input[data-secondary]')].map(i=>i.value.toUpperCase()).slice(0,2);
    return profile;
  }
  async function openPacks() {
    const dialog=$('packs-dialog'),host=$('packs-list'),status=$('packs-status');
    host.replaceChildren();status.textContent='正在加载模板';dialog.showModal();
    const revision=ui.state.projectRevision;
    try {
      const data=await api('/api/template-packs');
      status.textContent='';
      const hasSlides=(ui.state?.slides||[]).length>0;
      for(const pack of data.packs){
        const card=node('section','pack-card');card.dataset.packId=pack.id;
        const heading=node('div','pack-heading');heading.append(node('h3','',pack.name));
        const button=node('button','button',hasSlides?'生成整套改版副本':data.selectedPack===pack.id?'已选择':'使用这套');button.type='button';
        heading.append(button);card.append(heading);
        const previews=node('div','pack-previews');
        for(const [role,label] of [['cover','封面'],['chapter','章节标题'],['content','正文']]){
          const figure=node('figure','');const frame=document.createElement('iframe');frame.title=pack.name+' · '+label;
          frame.src='/api/template-packs/preview?pack='+encodeURIComponent(pack.id)+'&role='+role+'&project='+encodeURIComponent(ui.state.projectId);
          frame.setAttribute('sandbox','allow-scripts');frame.setAttribute('loading','lazy');
          figure.append(frame,node('figcaption','',label));previews.append(figure);
        }
        card.append(previews);host.append(card);
        button.addEventListener('click',async()=>{
          host.querySelectorAll('button').forEach(b=>b.disabled=true);status.textContent=hasSlides?'正在创建改版副本':'正在应用模板';
          try{
            const result=await api(hasSlides?'/api/template-packs/apply':'/api/template-packs/select','POST',{packId:pack.id,projectRevision:revision});
            if(result.projectId){openProject(result.projectId);return;}
            dialog.close();toast('已选择「'+pack.name+'」，输入大纲即可生成整套。');
          }catch(error){status.textContent=error.message;host.querySelectorAll('button').forEach(b=>b.disabled=false);}
        });
      }
    }catch(error){status.textContent=error.message;}
  }

  async function openStyle(){
    style.busy=false;$('style-error').hidden=true;$('style-editor').hidden=true;
    await refreshUserTemplates();style.list=design.styleTemplates||[];renderStyleList();$('style-dialog').showModal();
  }
  async function analyzeStyle(t){
    style.busy=true;$('style-editor').hidden=false;$('style-analyzing').hidden=false;renderStyleList();
    try{const result=await api('/api/style-templates/analyze','POST',{id:t.id});
      style.editing=t.id;style.profile=result.template.profile;await refreshUserTemplates();style.list=design.styleTemplates||[];
      $('style-analyzing').hidden=true;renderStyleList();renderStyleForm();toast('已提炼设计风格，可编辑后用于本项目。');
    }catch(error){$('style-analyzing').hidden=true;$('style-error').textContent=error.message;$('style-error').hidden=false;}
    finally{style.busy=false;renderStyleList();}
  }
  async function selectStyle(id){
    try{applyState(await api('/api/style-templates/select','POST',{id}));renderStyleBadge();renderStyleList();toast(id?'已选定对标风格，之后生成的整稿会使用。':'已取消对标风格。');}
    catch(error){$('style-error').textContent=error.message;$('style-error').hidden=false;}
  }

  const AUDIENCES=[['employee','员工版','真实进展与问题，去掉融资信息'],['customer','客户版','突出产品力与优势，附报价，去掉融资与财务'],['leader','领导同行版','适度包装，减少财务'],['investor','投资人版','产品包装、规划、财务与融资']];
  let audienceChoice='employee';
  function openAudience(){
    $('audience-error').hidden=true;$('audience-note').value='';
    const host=$('audience-cards');host.replaceChildren();
    for(const [id,label,line] of AUDIENCES){
      const card=node('button','audience-card'+(id===audienceChoice?' active':''));card.type='button';
      card.append(node('strong','',label),node('span','',line));
      card.addEventListener('click',()=>{audienceChoice=id;openAudience();});
      host.append(card);
    }
    $('audience-generate').disabled=!(ui.state?.slides||[]).length||!!(ui.state?.jobs||[]).some(j=>['queued','running'].includes(j.status));
    $('audience-dialog').showModal();
  }
  async function derive(mode,extra){
    try{const result=await api('/api/derive','POST',{mode,...extra});
      toast(`已创建新项目，正在按「${result.audienceLabel}」重新组织整稿；原稿保持不变。`);
      openProject(result.projectId);
    }catch(error){return error.message;}
  }
  function renderDerivedLine(){
    const d=ui.state?.derivedFrom,el=$('derived-line');
    el.hidden=!d;if(d)$('derived-text').textContent=`由《${d.title}》生成 · ${d.audienceLabel||''}`;
  }
  async function openMapping(){
    const status=$('mapping-status'),source=$('mapping-source'),added=$('mapping-added');
    source.replaceChildren();added.replaceChildren();status.textContent='正在比对…';$('mapping-dialog').showModal();
    try{
      const m=await api('/api/derive/mapping');
      if(m.status==='pending'){status.textContent='生成计划完成后可查看对照。';return;}
      status.textContent='按文字相似度比对原稿与新版本，结果仅供核对。';
      for(const e of m.source){const li=node('li');li.append(node('span','mapping-page',`原第 ${e.index} 页 · ${e.title}`),node('b',`mapping-chip ${e.status}`,e.targetIndex?`${e.status} → 第 ${e.targetIndex} 页`:e.status));source.append(li);}
      for(const e of m.added){const li=node('li');li.append(node('span','mapping-page',`新第 ${e.index} 页 · ${e.title}`),node('b','mapping-chip 新增','新增'));if(e.placeholder)li.append(node('b','mapping-chip 待补充','待补充'));added.append(li);}
    }catch(error){status.textContent=error.message;}
  }
  $('derived-mapping').addEventListener('click',openMapping);
  $('mapping-close').addEventListener('click',()=>$('mapping-dialog').close());
  function renderNoSpace(skipped){
    const list=$('logo-nospace'),pages=ui.state?.slides||[];list.replaceChildren();
    const blocked=(skipped||[]).filter(s=>s.reason==='no-space');list.hidden=!blocked.length;
    for(const item of blocked){
      const index=pages.findIndex(s=>s.id===item.slideId),li=node('li','',`第 ${index+1} 页没有空位`),button=node('button','button quiet compact','仍然放置，稍后手动拖动');button.type='button';
      button.addEventListener('click',async()=>{
        const slide=(ui.state?.slides||[]).find(s=>s.id===item.slideId);if(!slide)return;button.disabled=true;
        try{const result=await api('/api/logo/place','POST',{slideId:slide.id,sceneRevision:slide.sceneRevision});if(result.state)applyState(result.state);else await refreshState(true);li.remove();list.hidden=!list.children.length;toast(`已在第 ${index+1} 页放置 Logo，可在画布中拖动调整，可撤销。`);}
        catch(error){button.disabled=false;toast(error.message);}
      });
      li.append(button);list.append(li);
    }
  }
  function renderLogoPanel(){
    const logo=ui.state?.logo;const has=!!logo;
    $('logo-result').hidden=!has;
    if(!has)return;
    $('logo-preview-light').src=logo.preview;$('logo-preview-dark').src=logo.preview;
    const badges=$('logo-badges');badges.replaceChildren();
    [logo.hasAlpha?'透明底':null,logo.removedBackground?'已自动去除底色':null,!logo.hasAlpha&&!logo.removedBackground?'保留原图背景':null]
      .filter(Boolean).forEach(text=>badges.append(node('span','palette-badge',text)));
    $('logo-position').value=logo.settings.position;$('logo-size').value=logo.settings.size;$('logo-pages').value=logo.settings.pages;
  }
  function openLogo(){$('logo-error').hidden=true;renderLogoPanel();$('logo-dialog').showModal();}
  async function uploadLogo(file){
    if(!file)return;
    if(!['image/png','image/jpeg'].includes(file.type)){$('logo-error').textContent='只接受 PNG 或 JPEG。';$('logo-error').hidden=false;return;}
    if(file.size>5*1024*1024){$('logo-error').textContent='Logo 图片上限为 5 MB。';$('logo-error').hidden=false;return;}
    $('logo-status').textContent='正在处理…';$('logo-error').hidden=true;
    try{const base64=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result).split(',')[1]);r.onerror=()=>rej(new Error('无法读取文件。'));r.readAsDataURL(file);});
      const result=await api('/api/logo','POST',{filename:file.name,mime:file.type,base64});
      applyState(result.state);renderLogoPanel();$('logo-status').textContent='';
    }catch(error){$('logo-status').textContent='';$('logo-error').textContent=error.message;$('logo-error').hidden=false;}
  }
  async function logoSettings(){try{const result=await api('/api/logo/settings','POST',{position:$('logo-position').value,size:$('logo-size').value,pages:$('logo-pages').value});applyState(result.state);}catch(e){toast(e.message);}}

  async function editText(objectId,frame,text) {
    if(!canSelectFrame(frame) || design.saving || editor.busy || ui.object?.id!==objectId)return;
    if(($('message-input').value.trim() || ui.uploads.length) && ui.object?.id!==objectId){toast('请先发送或保存对话框中的内容。');return;}
    if(design.dirty && design.edit?.objectId!==objectId){toast('请先保存当前文字修改。');return;}
    const slide=activeSlide(),key=previewIdentity(slide);
    if(design.edit?.key!==key || design.edit.objectId!==objectId){
      try{const result=editor.key===key?{scene:editor.scene,sceneRevision:slide.sceneRevision}:await api(`/api/scene?slide=${encodeURIComponent(slide.id)}&metadata=1`);if(!canSelectFrame(frame)||key!==previewIdentity(activeSlide())||ui.object?.id!==objectId)return;const object=result.scene.objects.find(item=>item.id===objectId);if(object?.type!=='text')return;design.edit={objectId,slideId:slide.id,sceneRevision:result.sceneRevision,key};$('object-text').value=object.text;design.dirty=false;}
      catch(error){toast(error.message);return;}
    }
    $('text-editor').hidden=false;showAssistant();
    if(text!==undefined){$('object-text').value=text;design.dirty=true;}
    $('text-save-status').textContent=design.dirty?'尚未保存':'修改后点击保存';
  }
  async function saveText() {
    if(!design.edit||design.saving)return;design.saving=true;$('save-object-text').disabled=true;$('object-text').disabled=true;
    try{await api('/api/edit','POST',{slideId:design.edit.slideId,sceneRevision:design.edit.sceneRevision,changes:[{objectId:design.edit.objectId,properties:{text:$('object-text').value}}]});design.dirty=false;design.edit=null;ui.draftTarget=null;editor.key='';$('text-editor').hidden=true;await refreshState(true);toast('文字已保存，预览和导出同步更新。');}
    catch(error){$('text-save-status').textContent=error.message;}
    finally{design.saving=false;$('save-object-text').disabled=false;$('object-text').disabled=false;}
  }

  let restoredDraftProject=null,presentationBusy=false;
  function saveComposerDraft(){
    if(!ui.state?.projectId)return;
    try{localStorage.setItem('weppt-draft:'+ui.state.projectId,JSON.stringify({text:$('message-input').value,target:currentMessageTarget(),uploads:ui.uploads.filter(a=>a.status==='ready')}));}catch{}
  }
  function restoreComposerDraft(){
    if(!ui.state?.projectId||restoredDraftProject===ui.state.projectId)return;
    restoredDraftProject=ui.state.projectId;
    try{const saved=JSON.parse(localStorage.getItem('weppt-draft:'+ui.state.projectId)||'null');if(saved&&(!$('message-input').value)&&((saved.text||'').length||(saved.uploads||[]).length)){$('message-input').value=saved.text||'';ui.draftTarget=saved.target||null;ui.uploads=(saved.uploads||[]).filter(a=>(ui.state.assets||[]).some(b=>b.assetId===a.assetId));resizeComposer();renderUploads();renderComposerScope();updateSend();}}catch{}
    if(new URL(location.href).searchParams.get('action')==='audience'){openAudience();const url=new URL(location.href);url.searchParams.delete('action');history.replaceState(null,'',url);}
  }
  function renderSourceStatus(){
    const host=$('source-status'),source=ui.state?.importSource;host.replaceChildren();host.hidden=!source;if(!source)return;
    const link=node('a','',source.filename);const url=new URL('/api/source',location.origin);url.searchParams.set('project',ui.state.projectId);link.href=url.href;link.textContent='下载原稿 · '+source.filename;host.append(link);
    if(source.warnings){const details=node('details');details.append(node('summary','',`导入说明 · ${source.warnings} 项`));const list=node('ul');for(const page of source.pages||[])for(const item of page.limitations||[])list.append(node('li','',`第 ${page.page} 页：${item.detail}`));details.append(list);host.append(details);}
  }
  async function openPresentation(file,audience=false){
    if(!file||presentationBusy)return;
    if(!/\.pptx$/i.test(file.name)){toast('请选择 .pptx 文件。');return;}
    if(file.size>20*1024*1024){toast('PPTX 文件上限为 20 MB；原文件不会被压缩。');return;}
    presentationBusy=true;$('ribbon-open').disabled=true;toast('正在打开完整 PPT，原文件会保留。',60000);saveComposerDraft();
    try{const encoded=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(Error('无法读取文件'));r.readAsDataURL(file);});
      const result=await api('/api/projects/import','POST',{filename:file.name,base64:encoded});const url=new URL(location.href);url.searchParams.set('project',result.projectId);url.searchParams.delete('token');if(audience)url.searchParams.set('action','audience');location.assign(url);
    }catch(error){toast(error.message,12000);}finally{presentationBusy=false;$('ribbon-open').disabled=false;}
  }
  let importForAudience=false;
  $('ribbon-open').addEventListener('click',()=>{importForAudience=false;$('presentation-input').click();});
  $('audience-open-file').addEventListener('click',()=>{importForAudience=true;$('presentation-input').click();});
  $('presentation-input').addEventListener('change',()=>{openPresentation($('presentation-input').files[0],importForAudience);$('presentation-input').value='';});
  $('message-input').addEventListener('input',saveComposerDraft);
  window.addEventListener('pagehide',saveComposerDraft);

  function openProject(projectId) {
    if(ui.uploads.some(a=>a.status==='uploading')){toast('资料正在上传，完成后即可切换。');return;}
    if(design.dirty){toast('请先保存正在编辑的文字。');return;}
    saveComposerDraft();
    const url=new URL(location.href);url.searchParams.set('project',projectId);url.searchParams.delete('token');location.assign(url);
  }

  async function openProjects() {
    $('projects-error').hidden=true;$('projects-list').textContent='正在读取项目…';$('projects-dialog').showModal();
    try {
      const result=await api('/api/projects');$('projects-list').replaceChildren();
      $('space-panel').hidden=!result.personalSpace;
      if(result.personalSpace){const me=await api('/api/me');$('space-code').value=me.code||'';}
      const sorted=result.personalSpace?[...result.projects.filter(p=>!p.shared),...result.projects.filter(p=>p.shared)]:result.projects;
      let section=null;
      sorted.forEach(project=>{
        const group=!result.personalSpace?null:project.shared?'共享的旧项目（所有访客可见）':'我的项目';
        if(group&&group!==section){section=group;$('projects-list').append(node('p','projects-section',group));}
        const button=node('button','project-item');button.type='button';
        const current=project.projectId===ui.state?.projectId;button.setAttribute('aria-current',String(current));
        const label=node('span','',project.title);label.append(node('small','',`${project.slideCount} 页 · ${project.activity||'已保存'} · ${new Date(project.updatedAt).toLocaleDateString('zh-CN')}`));
        button.append(label,node('b','',current?'当前项目':'打开'));button.addEventListener('click',()=>{if(current)$('projects-dialog').close();else openProject(project.projectId);});$('projects-list').append(button);
      });
    } catch(error){$('projects-list').textContent='';$('projects-error').textContent=error.message;$('projects-error').hidden=false;}
  }

  $('space-copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('space-code').value);toast('空间码已复制。');}catch{$('space-code').select();}});
  $('space-adopt').addEventListener('click',async()=>{
    const code=$('space-adopt-code').value.trim();if(!code)return;
    if(!confirm('切换后，这个浏览器将进入该空间；当前空间的项目可用当前空间码找回。继续吗？'))return;
    try{await api('/api/me/adopt','POST',{code});const url=new URL(location.href);url.searchParams.delete('project');location.assign(url);}
    catch(error){$('projects-error').textContent=error.message;$('projects-error').hidden=false;}
  });
  async function createProject(event) {
    event.preventDefault();saveComposerDraft();
    $('create-project-button').disabled=true;$('projects-error').hidden=true;
    try{const result=await api('/api/projects','POST',{title:$('new-project-title').value});openProject(result.projectId);}
    catch(error){$('projects-error').textContent=error.message;$('projects-error').hidden=false;}
    finally{$('create-project-button').disabled=false;}
  }

  function openConnectionDialog(){updateConnectionDialog();$('connection-dialog').showModal();}

  async function copyHandoff(){const text=$('handoff-text').textContent;try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);else{const field=node('textarea');field.value=text;field.style.position='fixed';field.style.opacity='0';document.body.append(field);field.select();const ok=document.execCommand('copy');field.remove();if(!ok)throw new Error();}toast('指令已复制。');}catch{toast('未能自动复制，请选中指令文字复制。');}}

  async function toggleFullscreen(){const panel=$('preview-panel');try{if(document.fullscreenElement)await document.exitFullscreen();else if(panel.requestFullscreen)await panel.requestFullscreen();else panel.classList.toggle('preview-fullscreen');}catch{panel.classList.toggle('preview-fullscreen');}}

  $('template-search').addEventListener('input',()=>{design.query=$('template-search').value;renderTemplates();});
  $('template-position').addEventListener('change',()=>{design.role=$('template-position').value;design.category='all';renderTemplates();});
  $('template-smart').addEventListener('click',requestSmartTemplates);
  $('diagram-image')?.addEventListener('click',async()=>{
    const slide=activeSlide();if(!slide?.hasDiagram || !editorReady() || ui.posting)return;
    ui.posting=true;renderEditorTools();
    try{
      await api('/api/diagram/image','POST',{slideId:slide.id,sceneRevision:slide.sceneRevision,
        requestId:'diagram-'+ui.state.projectId+'-'+slide.id+'-'+slide.sceneRevision});
      toast('正在生成替代图解，原版保留，可撤销。');await refreshState(true);
    }catch(error){toast(error.message);}finally{ui.posting=false;renderEditorTools();}
  });
  const ribbonTabs = [...document.querySelectorAll('.ribbon-tabs [role="tab"]')];
  function selectRibbonTab(tab) {
    ribbonTabs.forEach(item => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      $(item.getAttribute('aria-controls')).hidden = !selected;
      if(selected && item.id==='ribbon-design-tab'){syncTemplateTarget();loadTemplates();}
    });
  }
  ribbonTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectRibbonTab(tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? ribbonTabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + ribbonTabs.length) % ribbonTabs.length;
      selectRibbonTab(ribbonTabs[next]); ribbonTabs[next].focus();
    });
  });
  for(const id of ['slide-add','ribbon-add-slide'])$(id).addEventListener('click',()=>documentAction('insert',{afterId:activeSlide()?.id||null}));
  $('slide-copy').addEventListener('click',()=>documentAction('duplicate',{afterId:activeSlide()?.id||null}));
  $('slide-remove').addEventListener('click',()=>documentAction('remove'));
  $('slide-up').addEventListener('click',()=>{const i=slideIndex();if(i>0)documentAction('move',{afterId:i>1?ui.state.slides[i-2].id:null});});
  $('slide-down').addEventListener('click',()=>{const i=slideIndex();if(i<ui.state.slides.length-1)documentAction('move',{afterId:ui.state.slides[i+1].id});});
  $('ribbon-new').addEventListener('click', () => { openProjects(); $('new-project-title').focus(); });
  $('ribbon-page').addEventListener('click', () => {
    if ($('scope-page').disabled) { toast('请先选择页面，并完成或发送当前输入。'); return; }
    $('scope-page').click(); switchMobile('chat'); $('message-input').focus();
  });
  $('ribbon-fullscreen').addEventListener('click', () => { switchMobile('preview'); toggleFullscreen(); });
  $('ribbon-styles').addEventListener('click', () => {
    syncTemplateTarget(); loadTemplates(); $('templates-panel').showModal();
  });
  $('ribbon-palette').addEventListener('click',openPalette);
  $('palette-close').addEventListener('click',()=>$('palette-dialog').close());
  $('palette-primary').addEventListener('input',()=>{paletteDraft.primary=$('palette-primary').value;renderPalettePreview();});
  $('palette-secondary-add').addEventListener('click',()=>{if(paletteDraft.secondary.length<2){paletteDraft.secondary.push('#22C1C3');renderPaletteDialog();}});
  $('palette-save').addEventListener('click',()=>savePalette(false));
  $('palette-apply-page').addEventListener('click',()=>savePalette('page'));
  $('palette-apply-deck').addEventListener('click',()=>savePalette('deck'));
  $('palette-clear').addEventListener('click',clearPalette);
  $('template-strip-prev').addEventListener('click',()=>{const strip=$('template-strip');strip.scrollBy({left:-strip.clientWidth,behavior:'smooth'});});
  $('template-strip-next').addEventListener('click',()=>{const strip=$('template-strip');strip.scrollBy({left:strip.clientWidth,behavior:'smooth'});});
  $('template-strip').addEventListener('scroll',updateStripNav);
  $('user-template-input').addEventListener('change',async()=>{await uploadUserTemplates($('user-template-input').files);$('user-template-input').value='';});
  $('ribbon-style').addEventListener('click',openStyle);
  $('ribbon-packs').addEventListener('click',openPacks);
  $('packs-close').addEventListener('click',()=>$('packs-dialog').close());
  $('style-close').addEventListener('click',()=>$('style-dialog').close());
  $('style-upload').addEventListener('click',()=>$('style-file-input').click());
  async function startStyleWorkflow(id){
    style.busy=true;renderStyleList();
    try{const result=await api('/api/style-templates/start','POST',{id,projectRevision:ui.state.projectRevision});applyState(result.state);$('style-dialog').close();toast('已开始处理，完成后可打开改版稿。');}
    catch(error){$('style-error').textContent=error.message;$('style-error').hidden=false;}
    finally{style.busy=false;renderStyleList();}
  }
  async function uploadStyleReferences(files){
    if(style.busy)return;
    const images=[...files].filter(f=>['image/png','image/jpeg'].includes(f.type));
    if(images.length<1||images.length>3){toast('请添加 1–3 张 PNG 或 JPEG 参考图。');return;}
    style.busy=true;renderStyleList();$('style-error').hidden=true;
    try{const result=await uploadUserTemplates(images,'style');style.list=design.styleTemplates||[];if(result?.templates?.[0])await startStyleWorkflow(result.templates[0].id);}
    catch(error){$('style-error').textContent=error.message;$('style-error').hidden=false;}
    finally{style.busy=false;renderStyleList();}
  }
  $('style-file-input').addEventListener('change',async()=>{await uploadStyleReferences($('style-file-input').files);$('style-file-input').value='';});
  document.addEventListener('paste',event=>{
    const files=[...(event.clipboardData?.files||[])];if(!files.length)return;
    if($('style-dialog').open){event.preventDefault();uploadStyleReferences(files);}
    else if($('templates-panel').open){event.preventDefault();uploadUserTemplates(files);}
    else if(document.activeElement===$('message-input')){event.preventDefault();uploadFiles(files);}
  });
  $('style-save').addEventListener('click',async()=>{
    if(!style.editing||!style.profile)return;style.busy=true;
    try{await api('/api/style-templates/update','POST',{id:style.editing,profile:collectStyleForm()});await refreshUserTemplates();style.list=design.styleTemplates||[];renderStyleList();toast('风格档案已保存。');}
    catch(error){$('style-error').textContent=error.message;$('style-error').hidden=false;}
    finally{style.busy=false;}
  });
  $('style-use').addEventListener('click',async()=>{if(style.editing)await selectStyle(ui.state?.styleReference?.id===style.editing?null:style.editing);});
  $('style-derive').addEventListener('click',()=>{if(ui.state?.styleReference)startStyleWorkflow(ui.state.styleReference.id);});
  const restyle={queue:[],index:0,proposal:null,token:0,busy:false};
  async function restyleNext(){
    const token=restyle.token,ref=ui.state?.styleReference;
    restyle.proposal=null;$('restyle-apply').disabled=true;$('restyle-skip').disabled=true;$('restyle-reply').textContent='';
    if(restyle.index>=restyle.queue.length){$('restyle-progress').textContent=`已处理全部 ${restyle.queue.length} 页。`;return;}
    const slide=(ui.state?.slides||[]).find(s=>s.id===restyle.queue[restyle.index]);
    if(!slide?.hasPreview){restyle.index++;return restyleNext();}
    const label=`第 ${restyle.index+1}/${restyle.queue.length} 页`;
    $('restyle-progress').textContent=`${label}：正在按「${ref.name}」生成改版预览，约需 1–2 分钟…`;
    const url=new URL('/api/preview/'+encodeURIComponent(slide.id),location.origin);url.searchParams.set('project',ui.state.projectId);url.searchParams.set('rev',slide.sceneRevision);
    loadTemplateFrame('restyle-before',null,url.href).catch(()=>{});
    try{
      const result=await api('/api/templates/adapt','POST',{templateId:'style-'+ref.id,slideId:slide.id,sceneRevision:slide.sceneRevision,approach:'creative'});
      if(token!==restyle.token)return;
      await loadTemplateFrame('restyle-after',result.html);
      if(token!==restyle.token)return;
      restyle.proposal=result.proposalId;$('restyle-apply').disabled=false;$('restyle-skip').disabled=false;
      $('restyle-progress').textContent=`${label}：改版预览已生成，确认后应用。`;$('restyle-reply').textContent=result.reply||'';
    }catch(error){if(token!==restyle.token)return;$('restyle-progress').textContent=`${label}：${error.message}`;$('restyle-skip').disabled=false;}
  }
  function stopRestyle(){restyle.token++;$('restyle-dialog').close();}
  $('style-restyle').addEventListener('click',()=>{
    if(!ui.state?.styleReference){$('style-error').textContent='请先「用于本项目」选定一个已解析的对标风格。';$('style-error').hidden=false;return;}
    restyle.queue=(ui.state.slides||[]).filter(s=>s.hasPreview).map(s=>s.id);restyle.index=0;restyle.token++;
    $('style-dialog').close();$('restyle-dialog').showModal();restyleNext();
  });
  $('restyle-skip').addEventListener('click',()=>{restyle.index++;restyleNext();});
  $('restyle-apply').addEventListener('click',async()=>{
    if(!restyle.proposal)return;$('restyle-apply').disabled=true;
    try{await api('/api/templates/apply','POST',{proposalId:restyle.proposal});await refreshState(true);restyle.index++;restyleNext();}
    catch(error){$('restyle-progress').textContent=error.message;$('restyle-apply').disabled=false;}
  });
  for(const id of ['restyle-stop','restyle-close'])$(id).addEventListener('click',stopRestyle);
  $('restyle-dialog').addEventListener('cancel',()=>{restyle.token++;});
  $('ribbon-audience').addEventListener('click',openAudience);
  $('audience-close').addEventListener('click',()=>$('audience-dialog').close());
  $('audience-generate').addEventListener('click',async()=>{
    const error=await derive('audience',{audience:audienceChoice,note:$('audience-note').value});
    if(error){$('audience-error').textContent=error;$('audience-error').hidden=false;}
  });
  $('ribbon-logo').addEventListener('click',openLogo);
  $('logo-close').addEventListener('click',()=>$('logo-dialog').close());
  $('logo-upload').addEventListener('click',()=>$('logo-file-input').click());
  $('logo-file-input').addEventListener('change',async()=>{await uploadLogo($('logo-file-input').files[0]);$('logo-file-input').value='';});
  ['logo-position','logo-size','logo-pages'].forEach(id=>$(id).addEventListener('change',logoSettings));
  $('logo-apply').addEventListener('click',async()=>{
    try{const result=await api('/api/logo/apply','POST',{});
      applyState(result.state);renderLogoPanel();renderNoSpace(result.skipped);
      const skipped=(result.skipped||[]).filter(s=>s.reason!=='unchanged');
      toast(`已为 ${result.changedSlides.length} 页添加 Logo，可撤销${skipped.length?'，跳过 '+skipped.length+' 页':''}`);
    }catch(e){$('logo-error').textContent=e.message;$('logo-error').hidden=false;}
  });
  $('logo-remove').addEventListener('click',async()=>{
    try{const result=await api('/api/logo/remove','POST',{});applyState(result.state);renderLogoPanel();toast(`已从 ${result.changedSlides.length} 页移除 Logo，可撤销`);}
    catch(e){$('logo-error').textContent=e.message;$('logo-error').hidden=false;}
  });
  $('close-templates').addEventListener('click',()=>$('templates-panel').close());
  document.querySelectorAll('[data-template-filter]').forEach(button=>button.addEventListener('click',()=>{design.filter=button.dataset.templateFilter;renderTemplates();}));
  $('object-text').addEventListener('input',()=>{design.dirty=true;$('text-save-status').textContent='尚未保存';});
  $('save-object-text').addEventListener('click',saveText);
  $('close-text-editor').addEventListener('click',()=>{if(design.dirty){toast('请先保存文字修改。');return;}design.edit=null;$('text-editor').hidden=true;});
  window.addEventListener('beforeunload',event=>{if(design.dirty){event.preventDefault();event.returnValue='';}});
  $('projects-button').addEventListener('click',openProjects);
  $('close-projects').addEventListener('click',()=>$('projects-dialog').close());
  $('create-project-form').addEventListener('submit',createProject);
  $('composer').addEventListener('submit',event=>{event.preventDefault();sendMessage();});
  document.querySelector('.chat-panel').insertBefore($('text-editor'),$('chat-feed'));
  arrangeEditorPanels();
  $('font-size').addEventListener('change',()=>commitProperties({fontSize:Number($('font-size').value)}));
  $('font-family').addEventListener('change',()=>commitProperties({fontFamily:$('font-family').value}));
  $('font-color').addEventListener('change',()=>commitProperties({color:$('font-color').value}));
  $('font-grow').addEventListener('click',()=>{const o=selectedEditorObject();if(o)commitProperties({fontSize:Math.min(160,o.fontSize+2)});});
  $('font-shrink').addEventListener('click',()=>{const o=selectedEditorObject();if(o)commitProperties({fontSize:Math.max(10,o.fontSize-2)});});
  $('font-bold').addEventListener('click',()=>{const o=selectedEditorObject();if(o)commitProperties({bold:!o.bold});});
  $('font-italic').addEventListener('click',()=>{const o=selectedEditorObject();if(o)commitProperties({italic:!o.italic});});
  document.querySelectorAll('[data-align]').forEach(b=>b.addEventListener('click',()=>commitProperties({align:b.dataset.align})));
  $('redo-button').addEventListener('click',()=>editorHistory('redo'));
  $('toggle-assistant').addEventListener('click',()=>showAssistant($('toggle-assistant').getAttribute('aria-expanded')!=='true'));
  $('close-assistant').addEventListener('click',()=>showAssistant(false));
  $('ribbon-recommend').addEventListener('click',requestTemplateMatches);
  document.querySelectorAll('[data-ai-action]').forEach(b=>b.addEventListener('click',()=>requestSuggestion(b.dataset.aiAction)));
  $('ai-custom').addEventListener('click',()=>requestSuggestion('custom'));
  $('ai-instruction').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();requestSuggestion('custom');}});
  $('ai-apply').addEventListener('click',applySuggestion);
  function closeSuggestion(){if(!editor.busy){$('ai-preview-dialog').close();editor.proposal=null;$('ai-status').textContent='未应用的建议不会修改原稿。';}}
  $('ai-preview-close').addEventListener('click',closeSuggestion);$('ai-preview-cancel').addEventListener('click',closeSuggestion);
  $('ai-preview-dialog').addEventListener('cancel',event=>{if(editor.busy)event.preventDefault();});
  $('canvas-zoom').addEventListener('input',()=>setZoom(Number($('canvas-zoom').value)/100));
  $('zoom-in').addEventListener('click',()=>setZoom(editor.zoom+.1));$('zoom-out').addEventListener('click',()=>setZoom(editor.zoom-.1));$('zoom-fit').addEventListener('click',()=>setZoom(1));
  document.addEventListener('keydown',editorShortcut);
  window.addEventListener('resize',arrangeEditorPanels);

  $('message-input').addEventListener('input',()=>{resizeComposer();protectDraftTarget();});
  $('message-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendMessage();}});
  $('clear-object').addEventListener('click',clearObjectSelection);
  $('scope-deck').addEventListener('click',()=>chooseScope('deck'));$('scope-page').addEventListener('click',()=>chooseScope('page'));
  $('quality-check').addEventListener('click',checkQuality);
  $('deck-review-button').addEventListener('click',openDeckReview);$('submit-deck-review').addEventListener('click',confirmDeck);$('close-deck-review').addEventListener('click',closeDeckReview);$('cancel-deck-review').addEventListener('click',closeDeckReview);
  $('deck-review-dialog').addEventListener('cancel',event=>{if(ui.deckReviewBusy)event.preventDefault();else ui.deckReviewSnapshot=null;});
  $('reply-question').addEventListener('click',()=>{if(hasComposerDraft() || !pendingDeckQuestion())return;ui.explicitPageEditing=false;ui.draftTarget=null;clearObject();renderDeckProgress();$('message-input').focus();});
  $('retry-button').addEventListener('click',()=>refreshState(true));
  $('new-messages-button').addEventListener('click',()=>scrollChat());
  $('chat-feed').addEventListener('scroll',()=>{const feed=$('chat-feed');if(feed.scrollHeight-feed.scrollTop-feed.clientHeight<60)$('new-messages-button').hidden=true;});
  document.querySelectorAll('[data-starter]').forEach(button=>button.addEventListener('click',()=>{if(hasComposerDraft()){toast('输入框已有内容，请先发送或保存。');return;}$('message-input').value=button.dataset.starter;resizeComposer();protectDraftTarget();$('message-input').focus();}));
  $('outline-starter').addEventListener('click',fillOutlineTemplate);$('connection-outline-starter').addEventListener('click',fillOutlineTemplate);
  document.querySelectorAll('[data-deck-action]').forEach(button=>button.addEventListener('click',()=>controlDeck(button.dataset.deckAction)));
  $('deck-follow').addEventListener('click',()=>{if(hasComposerDraft())return;ui.pinnedSlideId=null;ui.explicitPageEditing=false;ui.draftTarget=null;clearObject();if(ui.state)renderState(true);});
  $('choose-model').addEventListener('click',chooseModel);
  document.querySelectorAll('[data-agent-mode]').forEach(button=>button.addEventListener('click',()=>chooseAgent(button.dataset.agentMode)));
  $('image-mode').addEventListener('change',chooseImageMode);
  document.querySelectorAll('[data-demo-command]').forEach(button=>button.addEventListener('click',()=>{if(hasComposerDraft()){toast('输入框已有内容，请先发送或保存，再执行快捷修改。');return;}ui.explicitPageEditing=true;clearObject();sendMessage(button.dataset.demoCommand,{pageEdit:true});}));
  document.querySelectorAll('[data-mobile-tab]').forEach(button=>button.addEventListener('click',()=>switchMobile(button.dataset.mobileTab)));
  $('demo-button').addEventListener('click',openDemo);$('empty-demo-button').addEventListener('click',openDemo);
  $('previous-page').addEventListener('click',()=>{const slide=ui.state?.slides?.[slideIndex()-1];if(slide)selectSlide(slide.id);});
  $('next-page').addEventListener('click',()=>{const slide=ui.state?.slides?.[slideIndex()+1];if(slide)selectSlide(slide.id);});
  $('review-button').addEventListener('click',reviewPage);$('undo-button').addEventListener('click',()=>editorHistory('undo'));
  $('fullscreen-button').addEventListener('click',toggleFullscreen);
  $('attach-button').addEventListener('click',()=>$('file-input').click());$('file-input').addEventListener('change',()=>uploadFiles($('file-input').files));
  $('export-button').addEventListener('click',()=>{const open=$('export-menu').hidden;$('export-menu').hidden=!open;$('export-button').setAttribute('aria-expanded',String(open));});
  document.querySelectorAll('[data-export]').forEach(button=>button.addEventListener('click',()=>download(button.dataset.export,button.dataset.exportMode || 'draft')));
  document.addEventListener('click',event=>{if(!event.target.closest('.export-wrap'))closeExport();});
  $('connection-button').addEventListener('click',openConnectionDialog);$('mode-notice-action').addEventListener('click',openConnectionDialog);$('close-connection').addEventListener('click',()=>$('connection-dialog').close());
  $('connection-dialog').addEventListener('click',event=>{if(event.target===$('connection-dialog')){const r=$('connection-dialog').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('connection-dialog').close();}});
  $('copy-handoff').addEventListener('click',copyHandoff);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){closeExport();document.querySelector('.preview-panel').classList.remove('preview-fullscreen');clearObjectSelection();}});
  window.addEventListener('message',event=>{
    if(event.data?.type==='ppt-ready' && ui.pendingFrame && event.source===ui.pendingFrame.contentWindow){ui.pendingFrame.markReady?.();return;}
    if(event.data?.type==='ppt-quality'){handleQualityMessage(event);return;}
    const frame=event.source===ui.activeFrame?.contentWindow?ui.activeFrame:event.source===ui.pendingFrame?.contentWindow?ui.pendingFrame:null;
    if(!frame)return;
    const data=event.data;
    if(data && data.type==='ppt-select' && canSelectFrame(frame) && typeof data.objectId==='string' && data.objectId.length<200){selectObject(data.objectId,typeof data.label==='string'?data.label.slice(0,100):undefined,frame);}
    if(data?.type==='ppt-clear' && canSelectFrame(frame))clearObjectSelection();
    if(data?.type==='ppt-save' && canSelectFrame(frame) && design.dirty)saveText();
    if(data?.type==='ppt-history' && canSelectFrame(frame) && ['undo','redo'].includes(data.action))editorHistory(data.action);
    if(data?.type==='ppt-geometry' && canSelectFrame(frame) && typeof data.objectId==='string'){
      const keys=Object.keys(data.properties || {});
      if(keys.length && keys.every(key=>['x','y','w','h'].includes(key)) && ui.object?.id===data.objectId){
        commitProperties(data.properties,data.objectId,frame).then(saved=>{if(!saved)frame.contentWindow.postMessage({type:'ppt-reset-geometry',objectId:data.objectId},'*');});
      }else frame.contentWindow.postMessage({type:'ppt-reset-geometry',objectId:data.objectId},'*');
    }
    if(data?.type==='ppt-edit' && canSelectFrame(frame) && typeof data.objectId==='string' && typeof data.text==='string' && data.text.length<=20000)editText(data.objectId,frame,data.text);
    if(data && data.type==='ppt-overflow' && Array.isArray(data.objectIds) && frameMatchesSelection(frame)){
      frame.overflowIds=data.objectIds.filter(x=>typeof x==='string' && x.length<200).slice(0,300);
      if(canSelectFrame(frame))setOverflow(frame.overflowIds);
    }
  });
  window.addEventListener('dragenter',event=>{if(event.dataTransfer?.types?.includes('Files')){event.preventDefault();ui.dragDepth++;$('drop-overlay').hidden=false;}});
  window.addEventListener('dragover',event=>{if(event.dataTransfer?.types?.includes('Files'))event.preventDefault();});
  window.addEventListener('dragleave',event=>{if(event.dataTransfer?.types?.includes('Files')){event.preventDefault();ui.dragDepth=Math.max(0,ui.dragDepth-1);if(!ui.dragDepth)$('drop-overlay').hidden=true;}});
  window.addEventListener('drop',event=>{if(event.dataTransfer?.files?.length){event.preventDefault();ui.dragDepth=0;$('drop-overlay').hidden=true;if($('style-dialog').open)uploadStyleReferences(event.dataTransfer.files);else if($('templates-panel').open)uploadUserTemplates(event.dataTransfer.files);else {const pptx=[...event.dataTransfer.files].find(f=>/\.pptx$/i.test(f.name));if(pptx)openPresentation(pptx);else uploadFiles(event.dataTransfer.files);}}});
  window.addEventListener('focus',()=>refreshState());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshState();});
  if (globalThis.ResizeObserver) new ResizeObserver(fitCanvas).observe(document.querySelector('.preview-center'));
  window.addEventListener('resize',fitCanvas);
  resizeComposer();loadTemplates();refreshState(true);setInterval(()=>{if(!document.hidden)refreshState();},1000);
})();
