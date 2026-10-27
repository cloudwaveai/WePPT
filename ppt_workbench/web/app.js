(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const icon = (name, extra = '') => { const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('class',`icon ${extra}`); const use = document.createElementNS('http://www.w3.org/2000/svg','use'); use.setAttribute('href',`#i-${name}`); svg.append(use); return svg; };
  const node = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text !== undefined) e.textContent = text; return e; };
  const ui = { state: null, connected: false, fetching: false, posting: false, previewKey: '', slideKey: '', messageKey: '', deckKey: '', revisionKey: '', deliveryKey: '', qualityKey: '', releaseKey: '', pinnedSlideId: null, explicitPageEditing: false, draftTarget: null, stagedChoiceGroups:new Map(), activeFrame: null, pendingFrame: null, object: null, uploads: [], optimistic: [], dragDepth: 0, mobileView: 'chat', reviewBusy: false, undoBusy: false, deckReviewBusy: false, deckReviewSnapshot: null, operatorIds:new Map(), agentBusy: false, deckBusy: false, deliveryBusy: false, qualityBusy: false, progressOpen: new Set(), measure: { projectId:null, active:null, entries:new Map(), timer:null }, toastTimer: null, failures: 0 };
  const design = { templates:[], filter:'recommended', role:'cover', family:'all', query:'', edit:null, dirty:false, saving:false, applying:false, target:null };
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
    $('preview-instruction').replaceChildren(icon('cursor','small'),document.createTextNode(target.objectId?`已选中「${target.objectLabel || target.objectId}」，在对话里描述修改`:'点击文字或图形，把修改范围说清楚'));
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
    const timer = setTimeout(() => controller.abort(), method === 'GET' ? 9000 : 90000);
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

  async function refreshState(force = false) {
    if (ui.fetching) return;
    ui.fetching = true;
    try {
      const state = await api('/api/state');
      applyState(state, force);
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

  function renderState(force = false) {
    const state = ui.state, slide = activeSlide();
    $('project-title').textContent = state.project?.title || '新的演示稿';
    $('guide-link').href = `/guide.html?project=${encodeURIComponent(state.projectId)}`;
    $('review-guide-draft').href = $('guide-link').href;
    renderGuideDraft();
    const preferred=design.templates.find(template=>template.id===state.selectedTemplateId);
    $('template-suggestion-text').textContent=preferred?`已选样式：${preferred.name}`:activeSlide()?'想换个排法？根据这页内容选一个样式。':'先选一个喜欢的样子，再放入你的内容。';
    if(design.edit && !design.dirty && design.edit.key!==previewIdentity(activeSlide())){design.edit=null;$('text-editor').hidden=true;}
    const demo = !!(state.demo || state.isDemo || state.project?.isDemo || state.projectId === 'demo');
    $('demo-badge').hidden = !demo;
    const localOutline = state.agent?.mode === 'outline' || (state.agent?.mode === 'manual' && state.deck?.execution === 'outline');
    $('demo-controls').hidden = !((demo && state.agent?.mode === 'manual') || (localOutline && state.slides.length));
    $('local-controls-label').textContent = localOutline ? '本地排版 · 支持这些精确修改' : '本地演示 · 这些指令可直接运行';
    $('demo-button').hidden = state.slides.length > 0 || !!state.deck;
    document.title = `${state.project?.title || 'WePPT'} · 对话与预览`;
    $('mobile-page-count').textContent = state.slides.length ? String(state.slides.length) : '';
    $('slide-count').textContent = `${state.slides.length} 页`;
    updateExport();
    $('preview-heading').textContent = slide?.title || '页面预览';
    $('preview-kicker').textContent = slide ? `第 ${slideIndex() + 1} 页 · 根据当前内容生成` : '把想法变成看得见的一页';
    renderComposerScope();
    $('page-review-row').hidden = !slide;
    $('page-position-label').textContent = slide ? `${slideIndex() + 1} / ${state.slides.length}` : '';
    $('previous-page').disabled = slideIndex() <= 0;
    $('next-page').disabled = slideIndex() >= state.slides.length - 1;
    $('undo-button').disabled = ui.undoBusy || !slide || Number(slide.sceneRevision || 0) < 2;
    const reviewed = slide && (slide.reviewedSceneRevision === slide.sceneRevision || slide.approvedSceneRevision === slide.sceneRevision || slide.reviewed === true);
    $('review-button').classList.toggle('reviewed', !!reviewed);
    $('review-button').querySelector('span').textContent = reviewed ? '本页已认可' : '认可这一页';
    $('review-button').disabled = ui.reviewBusy || !slide?.hasPreview || !!slide?.stale || reviewed;
    updateAgent(); renderDelivery(); renderDeckProgress(); renderQuality(); renderRelease(); renderMessages(force); renderSlides(force); renderPreview(); updateJobStatus(); updateSend(); updateConnectionDialog(); updateReviewDialog(); fitCanvas(); scheduleMeasurements();
  }

  function updateAgent() {
    const agent = ui.state?.agent || {};
    const modes = { claude:'Claude Code', codex:'Codex', manual:'Coding Agent', outline:'本地大纲排版' };
    const localWork=ui.state?.deck?.execution==='outline' && ui.state?.deck?.status==='running';
    let label = modes[agent.mode] || agent.label || 'Coding Agent', dot = '';
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
    const count=Math.max(0,Number(delivery?.inputCount)||0),target=Math.max(1,Number(delivery?.targetRounds)||3);
    const exceeded=delivery?.withinTarget===false || count>target;
    $('delivery-panel').classList.toggle('exceeded',exceeded);
    $('delivery-round-count').textContent=`${count} / ${target} 轮${exceeded?' · 已超出目标':''}`;
    document.querySelectorAll('[data-round-stage]').forEach(item=>{const n=Number(item.dataset.roundStage);item.classList.toggle('reached',count>=n);item.classList.toggle('current',count===n);});
    const current=delivery?.activeRound,status=current?.status || delivery?.status;
    let text=count?`已接收 ${count} 轮输入，已输出 ${Math.max(0,Number(delivery?.outputCount)||0)} 轮结果。`:'用途、逐页想法和资料可以一起提交。';
    if(current)text=`第 ${current.number} 轮 · ${roundStatusLabels[current.status] || '处理中'}。后台逐页制作和检查，完成后集中给出结果。`;
    else if(status==='needs_input')text='本轮有待补充内容。请把答案和其他反馈一起发送，补充也计入下一轮。';
    else if(status==='failed')text='本轮没有完成。可重试原任务，重试不另算用户输入。';
    $('delivery-status').textContent=text;
    $('delivery-budget-note').textContent=exceeded?'已超过三轮目标。可以继续修改，实际轮次会保留；不将它标记为三轮达标。':'首次需求、补充回答和修改反馈都计入轮次；后台制作和检查不计。次数不代表质量已通过。';
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
      task.timer=setTimeout(()=>{if(ui.measure.active!==task)return;if(task.lastReport)submitMeasurement(task,task.lastReport);else finishMeasurement(task,false,'未收到当前页面的真实测量');},10000);
      frame.src=url;$('quality-measure-host').append(frame);renderQuality();return;
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
    $('revision-budget-note').textContent = '这里记录实际页面变更；用户输入轮次以上方三轮记录为准。';
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
    $('deck-review-round-note').textContent=round<=3?`确认将作为第 ${round} 轮输入，系统记录本轮结果。`:`确认将作为第 ${round} 轮输入，超过三轮目标。可以继续，但不会标记为三轮完成。`;
    $('deck-review-round-note').classList.toggle('exceeded',round>3);
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
    const key = JSON.stringify([messages,(ui.state?.delivery?.rounds || []).map(r=>[r.id,r.status,r.snapshotStale])]);
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
      const pageId = message.pageId || message.slideId;
      if (pageId) { const n = ui.state?.slides?.findIndex(s => s.id === pageId); author.append(node('span','message-page', n >= 0 ? `第 ${n + 1} 页` : pageId)); }
      else if(message.deckPageIndex)author.append(node('span','message-page',`第 ${message.deckPageIndex} 页${message.isDeckQuestion?' · 待补充':message.isDeckAnswer?' · 补充材料':''}`));
      author.append(node('time','message-time',time(message.createdAt))); article.append(author, node('div','message-body',message.text || message.message || ''));
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

  function renderSlides(force = false) {
    const slides = ui.state?.slides || [];
    const key = JSON.stringify([activeSlide()?.id,slides.map(s => [s.id,s.title,s.sceneRevision,s.hasPreview,s.previewUrl])]);
    if (!force && key === ui.slideKey) return;
    ui.slideKey = key;
    const strip = $('filmstrip'), oldScroll = strip.scrollLeft; strip.replaceChildren();
    if (!slides.length) { strip.append(node('div','filmstrip-empty','逐页大纲确认后，页面会出现在这里。')); return; }
    slides.forEach((slide,index) => {
      const selected = slide.id === activeSlide()?.id;
      const button = node('button',`slide-thumb ${selected?'active':''}`); button.type = 'button'; button.setAttribute('aria-label',`第 ${index+1} 页：${slide.title || '未命名页面'}`); button.setAttribute('aria-current',selected?'page':'false');
      const canvas = node('div','thumb-canvas');
      if (slide.hasPreview && previewUrl(slide)) { const frame = node('iframe','thumb-frame'); frame.title = `第 ${index+1} 页缩略图`; frame.setAttribute('aria-hidden','true'); frame.tabIndex = -1; frame.setAttribute('sandbox','allow-scripts'); frame.loading = 'lazy'; frame.src = previewUrl(slide); canvas.append(frame); }
      else canvas.append(node('div','thumb-empty',String(index+1).padStart(2,'0')));
      canvas.append(node('span','thumb-index',String(index+1).padStart(2,'0')));
      const caption = node('div','thumb-caption'); caption.append(node('span','',slide.title || '未命名页面'),node('span','thumb-revision',slide.sceneRevision?`v${slide.sceneRevision}`:''));
      button.append(canvas,caption); button.addEventListener('click',() => selectSlide(slide.id)); strip.append(button);
    });
    strip.scrollLeft = oldScroll;
  }

  function renderPreview() {
    const slide = activeSlide();
    const hasPreview = !!slide?.hasPreview;
    const nextKey = previewIdentity(slide);
    $('preview-version').textContent = hasPreview ? `v${slide.sceneRevision || 1}${slide.stale ? ' · 对应旧内容' : slide.updatedAt ? ' · '+time(slide.updatedAt) : ''}` : '';
    if (nextKey === ui.previewKey) return;
    ui.previewKey = nextKey;
    setFrameInteractive(ui.activeFrame,false);
    setOverflow([]);
    ui.pendingFrame?.remove(); ui.pendingFrame = null;
    if (!hasPreview || !previewUrl(slide)) {
      ui.activeFrame?.remove(); ui.activeFrame = null;
      $('empty-preview').hidden = false;
      setOverflow([]);
      $('empty-preview').querySelector('h3').textContent = slide ? '这一页的内容已记录' : '这一页，等你的第一个想法';
      $('empty-preview').querySelector('p').textContent = slide ? '等待生成页面预览。你可以继续补充原话和资料，或在 Coding Agent 中继续制作。' : '在对话里讲内容，预览会在这里更新。\n选中页面里的对象，再说出你想改的地方。';
      $('empty-demo-button').hidden = !!slide;
      return;
    }
    const candidate = node('iframe','page-frame'); candidate.title = slide.title || '当前页面预览'; candidate.setAttribute('sandbox','allow-scripts');
    candidate.dataset.slideId=slide.id;candidate.dataset.previewKey=nextKey;setFrameInteractive(candidate,false);
    ui.pendingFrame = candidate;
    candidate.addEventListener('load',() => {
      if (ui.pendingFrame !== candidate) return;
      if(!frameMatchesSelection(candidate)){ui.pendingFrame=null;candidate.remove();renderPreview();updateJobStatus();return;}
      ui.activeFrame?.remove(); ui.activeFrame = candidate; ui.pendingFrame = null;
      $('empty-preview').hidden = true; candidate.classList.add('active');setFrameInteractive(candidate,true);setOverflow(candidate.overflowIds || []);updateJobStatus();
    });
    candidate.addEventListener('error',() => { if (ui.pendingFrame === candidate) { ui.pendingFrame = null; candidate.remove(); toast('新预览载入失败。旧预览仅供查看，暂不能选择对象。'); updateJobStatus(); } });
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
    const fittedWidth = Math.max(0,Math.min(width,height * 16 / 9));
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
    $('preview-update-text').textContent = ui.pendingFrame ? '正在载入新版本，稍后可选择对象' : supersededPreview ? '当前显示旧预览，暂不可选择对象' : waiting && ['running','processing','claimed'].includes(targetJob.status) ? '正在更新这一页' : slide?.stale ? '内容已更新，等待新预览' : '任务已保存，当前页面仍保留';
  }

  function updateSend() { $('send-button').disabled = !ui.connected || ui.posting || ui.uploads.some(a=>a.status==='uploading') || (!$('message-input').value.trim() && !ui.uploads.some(a=>a.status==='ready')); }
  function resizeComposer() { const input = $('message-input'); input.style.height='auto'; input.style.height=Math.min(190,Math.max(innerWidth<=760?74:76,input.scrollHeight))+'px'; updateSend(); }
  function protectDraftTarget(){
    if(hasComposerDraft()){
      if(!ui.draftTarget)ui.draftTarget={...currentMessageTarget()};
      if(ui.draftTarget.pageId)ui.pinnedSlideId=ui.draftTarget.pageId;
    }else {ui.draftTarget=null;ui.stagedChoiceGroups.clear();}
    renderComposerScope();renderDeckProgress();
  }

  async function sendMessage(text, options = {}) {
    if (ui.posting) return;
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
      if (!options.retry) { ui.uploads=[]; renderUploads(); }
      await refreshState(true);
    } catch (error) { local.status='failed'; local.error=error.message; renderMessages(true); }
    finally { ui.posting=false; updateSend(); $('message-input').focus(); }
  }

  function clearObject() { ui.object=null;renderComposerScope(); }
  function clearObjectSelection(){if(hasComposerDraft() && ui.draftTarget?.objectId){toast('当前输入已绑定所选对象，请先发送或保存，再取消选择。');return;}clearObject();}
  function selectObject(id,label,sourceFrame) {
    if(!canSelectFrame(sourceFrame))return;
    const slideId=sourceFrame.dataset.slideId,target=currentMessageTarget();
    if(hasComposerDraft() && (target.kind!=='page' || target.pageId!==slideId || target.objectId!==id)){toast('当前输入已绑定编辑目标，请先发送或保存，再选择其他对象。');return;}
    ui.pinnedSlideId=slideId;ui.explicitPageEditing=true;ui.object={id,label:label||id,pageId:slideId};renderComposerScope();renderDeckProgress();
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
    const names={manual:'Coding Agent 协作',claude:'Claude Code',codex:'Codex',outline:'按大纲本地排版'};
    $('connection-title').textContent=names[mode] || '选择执行方式';
    const descriptions={
      manual:'在 Claude Code 或 Codex 中直接对话，让浏览器显示结果。网页消息会保留，需由 Agent 主动领取。',
      claude:'网页消息交给本机 Claude Code。先保存整稿计划，再逐页生成和显示预览。',
      codex:'网页消息交给本机 Codex。先保存整稿计划，再逐页生成和显示预览。',
      outline:'将你提供的逐页标题和正文排成页面。不调用模型，不代写观点或事实；需要先写好完整大纲。'
    };
    $('connection-description').textContent=descriptions[mode] || '选择后保留当前项目、页面和对话。';
    let detail=agent.message || agent.connectionHint || '';
    if(['claude','codex'].includes(mode))detail+=(detail?'\n':'')+(agent.available?'已找到客户端；实际请求时才确认登录状态和调用是否成功。':'请在运行工作台的电脑上安装并登录对应客户端。消息会保留，也可切换到本地大纲排版。');
    if(mode==='outline')detail='本地排版可用。以“按大纲排版”开头粘贴逐页内容，页面会自动依次生成。';
    $('connection-detail').textContent=detail;
    document.querySelectorAll('[data-agent-mode]').forEach(button=>{const selected=button.dataset.agentMode===mode;button.setAttribute('aria-pressed',String(selected));button.classList.toggle('selected',selected);button.disabled=ui.agentBusy || !ui.connected;});
    $('handoff-card').hidden=mode==='outline';
    $('connection-outline-starter').hidden=mode!=='outline' || !!ui.state?.deck || !!ui.state?.slides?.length;
    const p=ui.state?.projectId||'<项目 ID>',s=activeSlide()?.id;
    $('handoff-text').textContent=`使用已连接的 PPT 工作台，继续项目 ${p}${s?' 的 '+s:''}。先读取待处理对话与整稿计划。按我的原话逐页制作，完成一页后继续计划中的下一页；指定对象的修改只作用于该对象，保留其他页面。`;
  }

  async function chooseAgent(mode) {
    if(ui.agentBusy || !ui.connected || ui.state?.agent?.mode===mode)return;
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

  let loadedGuideHandoff = null;
  function guideHandoffKey() {
    const id = new URLSearchParams(location.search).get('guideDraft');
    return id && ui.state?.projectId ? `weppt:guide-handoff:${ui.state.projectId}:${id}` : null;
  }
  function renderGuideDraft() {
    const key = guideHandoffKey();
    if (!key) return;
    try {
      const raw = localStorage.getItem(key);
      $('guide-draft-notice').hidden = !raw || loadedGuideHandoff === key;
      if (raw) $('load-guide-draft').disabled = hasComposerDraft();
    } catch { $('guide-draft-notice').hidden = false; $('guide-draft-note').textContent = '无法读取交接草稿，请打开内容引导复制简报。'; $('load-guide-draft').disabled = true; }
  }
  $('load-guide-draft').addEventListener('click', () => {
    if (hasComposerDraft()) { toast('请先保存或发送输入框中的内容，再载入引导草稿。'); return; }
    try {
      const key = guideHandoffKey(), draft = JSON.parse(localStorage.getItem(key) || 'null');
      if (typeof draft?.text !== 'string' || !draft.text.trim() || draft.text.length > 20000) { toast('交接草稿无法读取，请从内容引导复制。'); return; }
      clearObject(); ui.explicitPageEditing = false;
      ui.draftTarget = { kind:'deck', scope:'deck', pageId:null, objectId:null };
      $('message-input').value = draft.text; resizeComposer(); renderComposerScope(); updateSend(); switchMobile('chat'); $('message-input').focus();
      // Keep the stored handoff so a reload can recover the unsent text.
      loadedGuideHandoff = key;
      $('guide-draft-notice').hidden = true;
      toast('简报已载入整稿草稿，请检查后手动发送。', 6500);
    } catch { toast('无法读取交接草稿，请从内容引导复制。'); }
  });

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
    let score=template.roles?.includes(design.role)?20:0;
    if(groups[template.family]?.test(text))score+=10;
    if(groups[template.id]?.test(text))score+=8;
    for(const tag of template.tags || [])if(tag.length>1&&text.includes(tag))score+=3;
    if(template.opening)score+=12;
    if(ui.state?.selectedTemplateId===template.id)score+=2;
    return score;
  }
  function renderTemplates() {
    const grid=$('template-grid');grid.replaceChildren();
    const roles=$('template-roles');roles.replaceChildren();
    const available=design.templates.filter(template=>!template.legacy);
    Object.entries({all:'全库',...templateRoles}).forEach(([id,title])=>{const count=id==='all'?available.length:available.filter(t=>t.roles?.includes(id)).length;const button=node('button','',`${title} · ${count}`);button.type='button';button.setAttribute('aria-pressed',String(design.role===id));button.addEventListener('click',()=>{design.role=id;design.family='all';$('template-family').value='all';renderTemplates();});roles.append(button);});
    $('template-family').hidden=!['all','content','appendix'].includes(design.role);
    const terms=design.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const ranked=design.templates.filter(template=>!template.legacy && (design.role==='all' || !template.roles || template.roles.includes(design.role)) && (design.family==='all'||template.family===design.family) && terms.every(term=>`${template.name} ${template.description} ${(template.tags||[]).join(' ')} ${template.use||''}`.toLowerCase().includes(term))).sort((a,b)=>templateScore(b)-templateScore(a));
    const templates=design.filter==='recommended'?ranked.slice(0,6):ranked;
    let countNote=$('template-count');if(!countNote){countNote=node('p','dialog-note');countNote.id='template-count';grid.before(countNote);}countNote.textContent=`已接入 ${available.length} 项 · 当前${templateRoles[design.role] || '全库'}匹配 ${ranked.length} 项 · 展示 ${templates.length} 项`;
    document.querySelector('[data-template-filter="all"]').textContent=design.role==='all'?'全库样式':'本类全部';
    if(!templates.length)grid.append(node('p','','没有匹配的模板，试试其他关键词或页面位置。'));
    templates.forEach((template,index)=>{
      const card=node('button','template-card');card.type='button';card.disabled=design.applying;
      const preview=node('div','template-card-preview'),frame=node('iframe');frame.title=template.name+'模板预览';frame.tabIndex=-1;frame.setAttribute('sandbox','allow-scripts');frame.src=template.previewUrl;preview.append(frame);
      const label=node('div','template-card-label');label.append(node('strong','',template.name),node('span','',design.filter==='recommended'&&index===0?'推荐':'选择'));
      frame.loading=index<8?'eager':'lazy';card.append(preview,label,node('p','',template.description));
      if(template.sourceLabel)card.append(node('small','',template.sourceLabel));
      const detail=node('details','template-rules'),summary=node('summary','','适用场景与规则');detail.append(summary,node('p','',template.use || template.description));
      if(template.checks?.length){const list=node('ul');template.checks.forEach(check=>list.append(node('li','',check)));detail.append(list);}
      detail.addEventListener('click',event=>event.stopPropagation());
      const item=node('div','template-item');item.append(card,detail);card.addEventListener('click',()=>applyTemplate(template));grid.append(item);
    });
    document.querySelectorAll('[data-template-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.templateFilter===design.filter)));
  }
  async function openTemplates() {
    if(design.dirty){toast('请先保存当前文字修改。');return;}
    const slide=activeSlide();design.role=currentPageRole();design.query='';design.family='all';$('template-search').value='';design.target=slide?{slideId:slide.id,sceneRevision:slide.sceneRevision}:null;
    $('template-target').textContent=slide?`替换第 ${slideIndex()+1} 页的样式，保留现有文字。`:'选定后用于接下来生成的页面。';
    $('template-error').hidden=true;$('template-grid').textContent='正在读取模板…';$('templates-dialog').showModal();
    try{const result=await api('/api/templates');design.templates=result.templates;const select=$('template-family');select.replaceChildren(new Option('全部表达任务','all'));const families=new Map(design.templates.filter(t=>!t.legacy&&t.family!=='golden').map(t=>[t.family,t.familyName || t.family]));families.forEach((name,id)=>select.add(new Option(name,id)));renderTemplates();}catch(error){$('template-grid').textContent='';$('template-error').textContent=error.message;$('template-error').hidden=false;}
  }
  async function applyTemplate(template) {
    if(design.applying)return;design.applying=true;renderTemplates();
    try{await api('/api/template','POST',{...(design.target || {}),templateId:template.id});$('templates-dialog').close();await refreshState(true);toast(design.target?'页面样式已更新。':'已选定模板，下一次生成时使用。');}
    catch(error){$('template-error').textContent=error.message;$('template-error').hidden=false;}
    finally{design.applying=false;renderTemplates();}
  }
  async function editText(objectId,frame,text) {
    if(!canSelectFrame(frame) || design.saving)return;
    if(($('message-input').value.trim() || ui.uploads.length) && ui.object?.id!==objectId){toast('请先发送或保存对话框中的内容。');return;}
    if(design.dirty && design.edit?.objectId!==objectId){toast('请先保存当前文字修改。');return;}
    const slide=activeSlide(),key=previewIdentity(slide);
    if(design.edit?.key!==key || design.edit.objectId!==objectId){
      try{const result=await api(`/api/scene?slide=${encodeURIComponent(slide.id)}`);if(!canSelectFrame(frame)||key!==previewIdentity(activeSlide()))return;const object=result.scene.objects.find(item=>item.id===objectId);if(object?.type!=='text')return;design.edit={objectId,slideId:slide.id,sceneRevision:result.sceneRevision,key};$('object-text').value=object.text;design.dirty=false;}
      catch(error){toast(error.message);return;}
    }
    $('text-editor').hidden=false;
    if(text!==undefined){$('object-text').value=text;design.dirty=true;}
    $('text-save-status').textContent=design.dirty?'尚未保存':'修改后点击保存';
  }
  async function saveText() {
    if(!design.edit||design.saving)return;design.saving=true;$('save-object-text').disabled=true;
    try{await api('/api/edit','POST',{slideId:design.edit.slideId,sceneRevision:design.edit.sceneRevision,changes:[{objectId:design.edit.objectId,properties:{text:$('object-text').value}}]});design.dirty=false;design.edit=null;$('text-editor').hidden=true;await refreshState(true);toast('文字已保存，预览和导出同步更新。');}
    catch(error){$('text-save-status').textContent=error.message;}
    finally{design.saving=false;$('save-object-text').disabled=false;}
  }

  function openProject(projectId) {
    if(hasComposerDraft()){ $('projects-error').textContent='请先发送或保存输入框中的内容，再切换项目。';$('projects-error').hidden=false;return; }
    const url=new URL(location.href);url.searchParams.set('project',projectId);url.searchParams.delete('token');location.assign(url);
  }

  async function openProjects() {
    $('projects-error').hidden=true;$('projects-list').textContent='正在读取项目…';$('projects-dialog').showModal();
    try {
      const result=await api('/api/projects');$('projects-list').replaceChildren();
      result.projects.forEach(project=>{
        const button=node('button','project-item');button.type='button';
        const current=project.projectId===ui.state?.projectId;button.setAttribute('aria-current',String(current));
        const label=node('span','',project.title);label.append(node('small','',`${project.slideCount} 页 · ${new Date(project.updatedAt).toLocaleDateString('zh-CN')}`));
        button.append(label,node('b','',current?'当前项目':'打开'));button.addEventListener('click',()=>{if(current)$('projects-dialog').close();else openProject(project.projectId);});$('projects-list').append(button);
      });
    } catch(error){$('projects-list').textContent='';$('projects-error').textContent=error.message;$('projects-error').hidden=false;}
  }

  async function createProject(event) {
    event.preventDefault();if(hasComposerDraft()){ $('projects-error').textContent='请先发送或保存输入框中的内容，再新建项目。';$('projects-error').hidden=false;return; }
    $('create-project-button').disabled=true;$('projects-error').hidden=true;
    try{const result=await api('/api/projects','POST',{title:$('new-project-title').value});openProject(result.projectId);}
    catch(error){$('projects-error').textContent=error.message;$('projects-error').hidden=false;}
    finally{$('create-project-button').disabled=false;}
  }

  function openConnectionDialog(){updateConnectionDialog();$('connection-dialog').showModal();}

  async function copyHandoff(){const text=$('handoff-text').textContent;try{if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);else{const field=node('textarea');field.value=text;field.style.position='fixed';field.style.opacity='0';document.body.append(field);field.select();const ok=document.execCommand('copy');field.remove();if(!ok)throw new Error();}toast('指令已复制。');}catch{toast('未能自动复制，请选中指令文字复制。');}}

  async function toggleFullscreen(){const panel=$('preview-panel');try{if(document.fullscreenElement)await document.exitFullscreen();else if(panel.requestFullscreen)await panel.requestFullscreen();else panel.classList.toggle('preview-fullscreen');}catch{panel.classList.toggle('preview-fullscreen');}}

  $('template-search').addEventListener('input',()=>{design.query=$('template-search').value;renderTemplates();});
  $('template-family').addEventListener('change',()=>{design.family=$('template-family').value;renderTemplates();});
  $('templates-button').addEventListener('click',openTemplates);$('recommended-templates').addEventListener('click',openTemplates);
  $('close-templates').addEventListener('click',()=>{if(!design.applying)$('templates-dialog').close();});
  document.querySelectorAll('[data-template-filter]').forEach(button=>button.addEventListener('click',()=>{design.filter=button.dataset.templateFilter;renderTemplates();}));
  $('object-text').addEventListener('input',()=>{design.dirty=true;$('text-save-status').textContent='尚未保存';});
  $('save-object-text').addEventListener('click',saveText);
  $('close-text-editor').addEventListener('click',()=>{if(design.dirty){toast('请先保存文字修改。');return;}design.edit=null;$('text-editor').hidden=true;});
  window.addEventListener('beforeunload',event=>{if(design.dirty){event.preventDefault();event.returnValue='';}});
  $('projects-button').addEventListener('click',openProjects);
  $('close-projects').addEventListener('click',()=>$('projects-dialog').close());
  $('create-project-form').addEventListener('submit',createProject);
  $('composer').addEventListener('submit',event=>{event.preventDefault();sendMessage();});
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
  document.querySelectorAll('[data-agent-mode]').forEach(button=>button.addEventListener('click',()=>chooseAgent(button.dataset.agentMode)));
  document.querySelectorAll('[data-demo-command]').forEach(button=>button.addEventListener('click',()=>{if(hasComposerDraft()){toast('输入框已有内容，请先发送或保存，再执行快捷修改。');return;}ui.explicitPageEditing=true;clearObject();sendMessage(button.dataset.demoCommand,{pageEdit:true});}));
  document.querySelectorAll('[data-mobile-tab]').forEach(button=>button.addEventListener('click',()=>switchMobile(button.dataset.mobileTab)));
  $('demo-button').addEventListener('click',openDemo);$('empty-demo-button').addEventListener('click',openDemo);
  $('previous-page').addEventListener('click',()=>{const slide=ui.state?.slides?.[slideIndex()-1];if(slide)selectSlide(slide.id);});
  $('next-page').addEventListener('click',()=>{const slide=ui.state?.slides?.[slideIndex()+1];if(slide)selectSlide(slide.id);});
  $('review-button').addEventListener('click',reviewPage);$('undo-button').addEventListener('click',undoPage);
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
    if(event.data?.type==='ppt-quality'){handleQualityMessage(event);return;}
    const frame=event.source===ui.activeFrame?.contentWindow?ui.activeFrame:event.source===ui.pendingFrame?.contentWindow?ui.pendingFrame:null;
    if(!frame)return;
    const data=event.data;
    if(data && data.type==='ppt-select' && canSelectFrame(frame) && typeof data.objectId==='string' && data.objectId.length<200){selectObject(data.objectId,typeof data.label==='string'?data.label.slice(0,100):undefined,frame);editText(data.objectId,frame);}
    if(data?.type==='ppt-edit' && canSelectFrame(frame) && typeof data.objectId==='string' && typeof data.text==='string' && data.text.length<=20000)editText(data.objectId,frame,data.text);
    if(data && data.type==='ppt-overflow' && Array.isArray(data.objectIds) && frameMatchesSelection(frame)){
      frame.overflowIds=data.objectIds.filter(x=>typeof x==='string' && x.length<200).slice(0,300);
      if(canSelectFrame(frame))setOverflow(frame.overflowIds);
    }
  });
  window.addEventListener('dragenter',event=>{if(event.dataTransfer?.types?.includes('Files')){event.preventDefault();ui.dragDepth++;$('drop-overlay').hidden=false;}});
  window.addEventListener('dragover',event=>{if(event.dataTransfer?.types?.includes('Files'))event.preventDefault();});
  window.addEventListener('dragleave',event=>{if(event.dataTransfer?.types?.includes('Files')){event.preventDefault();ui.dragDepth=Math.max(0,ui.dragDepth-1);if(!ui.dragDepth)$('drop-overlay').hidden=true;}});
  window.addEventListener('drop',event=>{if(event.dataTransfer?.files?.length){event.preventDefault();ui.dragDepth=0;$('drop-overlay').hidden=true;uploadFiles(event.dataTransfer.files);}});
  window.addEventListener('focus',()=>refreshState());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshState();});
  if (globalThis.ResizeObserver) new ResizeObserver(fitCanvas).observe(document.querySelector('.preview-center'));
  window.addEventListener('resize',fitCanvas);
  resizeComposer();refreshState(true);setInterval(()=>{if(!document.hidden)refreshState();},1000);
})();
