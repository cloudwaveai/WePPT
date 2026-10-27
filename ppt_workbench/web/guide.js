(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, text, className) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; };
  const clone = value => JSON.parse(JSON.stringify(value));
  const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const emptyDraft = () => ({ fields: {}, task: 'compare', branches: {}, followups: {}, role: 'content', family: 'compare', selected: null, brief: '', previousBrief: '', stale: false, pages: [], pageTitle: '', editingPage: null });
  let projectId, experience, templates = [], visibleCount = 8, storageFailed = false, draft = emptyDraft(), personal = { records: [], favorites: [] }, editingQA = null;
  const stores = Object.fromEntries(['draft', 'experience'].map(kind => [kind, { revision: 0, ready: false, dirty: false, busy: false, conflict: false, timer: null, error: '' }]));
  const key = () => `weppt:guide:v1:${projectId}`;
  const backupKey = kind => `weppt:guide:backup:${projectId}:${kind}`;
  const status = text => { $('guide-status').textContent = text; };
  const home = () => `/?project=${encodeURIComponent(projectId)}`;
  const documentFor = kind => kind === 'draft' ? draft : personal;
  const roleName = role => ({ content: '正文内容页', cover: '封面', toc: '目录', chapter: '章节页', ending: '结束页', appendix: '附录页' }[role] || role);
  function updateSaveStatus(kind) {
    const s = stores[kind];
    $(kind === 'draft' ? 'draft-save' : 'experience-save').textContent = `${kind === 'draft' ? '草稿' : '个人经验'}：${s.conflict ? '版本冲突，已停止覆盖' : s.error ? s.error : !s.ready ? '读取中' : s.busy || s.dirty ? '浏览器已备份，等待服务器保存' : `服务器已保存 · 版本 ${s.revision}`}${storageFailed ? ' · 浏览器备份不可用' : ''}`;
    $('save-conflict').hidden = !Object.values(stores).some(s => s.conflict);
  }
  function backup(kind) {
    try {
      localStorage.setItem(backupKey(kind), JSON.stringify({ revision: stores[kind].revision, pending: stores[kind].dirty || stores[kind].busy, document: documentFor(kind) }));
      if (kind === 'draft') localStorage.setItem(key(), JSON.stringify(draft));
      storageFailed = false;
    } catch { storageFailed = true; }
  }
  function updateBriefNote() {
    $('brief-note').textContent = draft.stale ? '回答、大纲或模板已改变；当前简报仍保留原稿，点击“整理整套简报”可更新。' : '请检查事实、来源和待补项，再带回工作台。';
    $('restore-brief').hidden = !draft.previousBrief;
  }
  function save(changed = false, kind = 'draft') {
    if (changed && draft.brief) draft.stale = true;
    const s = stores[kind]; s.dirty = true; backup(kind); updateSaveStatus(kind); updateBriefNote();
    clearTimeout(s.timer); s.timer = setTimeout(() => flush(kind), 450);
  }
  async function request(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(12000), ...options, headers: { ...(projectId ? { 'X-WePPT-Project': projectId } : {}), ...options.headers } });
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.error?.message || '读取或保存失败'); error.code = data.error?.code; error.httpStatus = response.status; throw error; }
    return data;
  }
  const endpoint = kind => `/api/guide/${kind}?project=${encodeURIComponent(projectId)}`;
  async function flush(kind) {
    const s = stores[kind]; if (!s.ready || s.busy || s.conflict || !s.dirty) return;
    s.busy = true; s.dirty = false; s.error = ''; const snapshot = clone(documentFor(kind)); updateSaveStatus(kind);
    try {
      const result = await request(endpoint(kind), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: s.revision, document: snapshot }) });
      s.revision = result.revision;
    } catch (error) {
      s.dirty = true;
      if (error.code === 'STALE_REVISION') s.conflict = true;
      else s.error = '仅浏览器备份，服务器保存失败；请重试';
    } finally {
      s.busy = false; backup(kind); updateSaveStatus(kind);
      if (s.dirty && !s.error && !s.conflict) void flush(kind);
    }
  }
  function normalize(kind, value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('保存记录格式错误');
    if (kind === 'experience') return { ...value, records: Array.isArray(value.records) ? value.records : [], favorites: Array.isArray(value.favorites) ? value.favorites : [] };
    const d = { ...emptyDraft(), ...value };
    if (!d.fields || !d.branches || typeof d.fields !== 'object' || typeof d.branches !== 'object') throw new Error('草稿格式错误');
    d.pages = Array.isArray(d.pages) ? d.pages : []; d.followups ||= {};
    if (!experience.tasks[d.task]) d.task = 'compare';
    return d;
  }
  async function loadStore(kind, force = false) {
    const s = stores[kind]; let local = null;
    try {
      const raw = localStorage.getItem(backupKey(kind));
      if (raw) local = JSON.parse(raw);
      else if (kind === 'draft' && localStorage.getItem(key())) local = { revision: 0, pending: true, document: JSON.parse(localStorage.getItem(key())) };
    } catch { status('浏览器备份无法读取；服务器记录仍可使用。'); }
    try {
      const result = await request(endpoint(kind)); s.revision = result.revision; s.ready = true; s.error = ''; s.conflict = false; s.dirty = false;
      let value = result.document;
      if (!force && local?.document && (local.pending || !Object.keys(value).length)) {
        value = local.document; s.dirty = true;
        if (Object.keys(result.document).length && local.revision !== result.revision) s.conflict = true;
      }
      if (kind === 'draft') draft = normalize(kind, value); else personal = normalize(kind, value);
      backup(kind);
    } catch (error) {
      s.ready = false; s.error = '服务器读取失败，当前仅浏览器备份；请重试';
      if (local?.document && !force) { if (kind === 'draft') draft = normalize(kind, local.document); else personal = normalize(kind, local.document); }
    }
    updateSaveStatus(kind);
  }
  function followupRules(page = draft) {
    return (experience.followups || []).filter(rule => Object.entries(rule.when).every(([field, values]) => values.includes(field === 'task' ? page.task : page.fields[field] || (field === 'materials' ? 'partial' : ''))));
  }
  function renderFollowups() {
    $('followup-slots').replaceChildren();
    followupRules().forEach(rule => {
      const label = make('label', rule.label), input = make('textarea'); input.id = `followup-${rule.id}`; input.rows = 2; input.maxLength = 3000; input.placeholder = rule.hint;
      input.value = draft.followups[rule.id] || ''; input.addEventListener('input', () => { draft.followups[rule.id] = input.value; save(true); });
      label.append(input, make('small', '内置追问 · 隐藏后仍保留原回答')); $('followup-slots').append(label);
    });
  }
  const mismatch = page => page.selected && (page.selected.role !== page.role || (page.role === 'content' && page.selected.family !== 'opening' && page.selected.family !== page.task));
  function renderTask() {
    $('task-options').replaceChildren();
    Object.entries(experience.tasks).forEach(([id, task]) => {
      const button = make('button'); button.type = 'button'; button.dataset.task = id; button.setAttribute('aria-pressed', String(draft.task === id));
      button.append(make('strong', task.name), make('span', task.description));
      button.addEventListener('click', () => { draft.task = id; draft.family = id; $('family').value = id; visibleCount = 8; renderTask(); renderCatalog(); renderQA(); save(true); }); $('task-options').append(button);
    });
    const task = experience.tasks[draft.task]; $('task-tip').textContent = '内置经验：' + task.tip; $('content-slots').replaceChildren();
    task.slots.forEach(slot => {
      const label = make('label', slot.label), input = make('textarea'); input.id = `slot-${slot.id}`; input.rows = 3; input.maxLength = 6000; input.placeholder = slot.hint; input.value = draft.branches[draft.task]?.[slot.id] || '';
      input.addEventListener('input', () => { (draft.branches[draft.task] ||= {})[slot.id] = input.value; save(true); }); label.append(input); $('content-slots').append(label);
    });
    renderFollowups();
  }
  const styleGroup = template => template.styleId || (template.local ? 'local' : 'design-map');
  const styleLabel = template => template.styleId ? (template.sourceLabel || template.styleId) : template.local ? '本地补充版式 · 视觉风格待核对' : '设计地图 · 版式目录（非独立视觉风格计数）';
  function templateInfo(template) {
    return { id: template.id, name: template.name, family: template.family, familyName: template.familyName, role: draft.role, roleName: roleName(draft.role), use: template.use || template.description, source: [template.sourceLabel, template.source, template.sourcePage ? `原文件第 ${template.sourcePage} 页` : ''].filter(Boolean).join(' · ') || '模板目录', style: styleLabel(template), styleId: styleGroup(template), variantOf: template.variantOf || null };
  }
  function button(text, action, className = 'button quiet compact') { const b = make('button', text, className); b.type = 'button'; b.addEventListener('click', action); return b; }
  function renderCatalog() {
    const grid = $('guide-template-grid'); grid.replaceChildren();
    const terms = $('catalog-search').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const filtered = templates.filter(t => !t.legacy && t.roles?.includes(draft.role) && ($('style-group').value === 'all' || styleGroup(t) === $('style-group').value) && (draft.family === 'all' || t.family === draft.family) && (!$('curated-only').checked || personal.favorites.some(f => f.template.id === t.id)) && terms.every(term => `${t.name} ${t.description} ${t.use || ''}`.toLowerCase().includes(term)));
    $('catalog-status').textContent = templates.length ? `${filtered.length} 个匹配模板 · 当前展示 ${Math.min(visibleCount, filtered.length)} 个${filtered.length ? '' : '，可调整筛选或先加入精选'}` : '模板尚未加载，内容仍可填写。';
    $('catalog-more').hidden = filtered.length <= visibleCount;
    const chosen = draft.selected; $('selected-template').textContent = chosen ? `已选：${chosen.name}（${chosen.id}） · ${chosen.roleName || roleName(chosen.role)} / ${chosen.familyName || chosen.family}` : '尚未选择模板，可先完成内容。';
    $('clear-template').hidden = !chosen; $('template-warning').hidden = !mismatch(draft);
    $('template-warning').textContent = '当前模板与页面位置或表达分支不匹配。请重新选择或清除；加入大纲与生成简报已暂停，原选择保留供核对。';
    filtered.slice(0, visibleCount).forEach(template => {
      const item = make('div', undefined, 'template-item'), card = make('button', undefined, 'template-card'); card.type = 'button'; card.dataset.templateId = template.id; card.setAttribute('aria-pressed', String(chosen?.id === template.id));
      const preview = make('div', undefined, 'template-card-preview'), frame = make('iframe'); frame.title = template.name + '模板预览'; frame.loading = 'lazy'; frame.tabIndex = -1; frame.setAttribute('sandbox', 'allow-scripts');
      try { const url = new URL(template.previewUrl, location.origin); if (url.origin === location.origin && url.pathname === '/api/templates/preview') frame.src = url.pathname + url.search; } catch { /* Catalog can still show textual details. */ }
      preview.append(frame); const label = make('div', undefined, 'template-card-label'); label.append(make('strong', template.name), make('span', chosen?.id === template.id ? '已选择' : '选择')); card.append(preview, label, make('p', template.description));
      card.addEventListener('click', () => { draft.selected = templateInfo(template); renderCatalog(); renderQA(); save(true); });
      const details = make('details', undefined, 'template-rules'); details.append(make('summary', '适用场景、来源与风格'), make('p', template.use || template.description)); const list = make('ul'); (template.checks || []).forEach(check => list.append(make('li', check))); details.append(list);
      const info = templateInfo(template); details.append(make('p', `来源：${info.source}。风格：${info.style}。`), make('p', '模板只承载中性槽位；请用自己的主题、姓名与领域资料替换示例内容，不将示例视作事实。'));
      const favorite = personal.favorites.find(f => f.template.id === template.id);
      item.append(card, details, button(favorite ? '已精选 · 编辑理由' : '加入精选', () => { if (!favorite) { personal.favorites.push({ id: uid(), template: info, reason: '' }); save(false, 'experience'); renderFavorites(); renderCatalog(); } $('favorite-records').scrollIntoView({ block: 'center', behavior: 'smooth' }); const input = Array.from($('favorite-records').querySelectorAll('textarea')).find(e => e.dataset.templateId === template.id); input?.focus(); })); grid.append(item);
    });
  }
  async function loadCatalog() {
    $('catalog-retry').hidden = true;
    try {
      templates = (await request('/api/templates')).templates;
      const groups = new Map(templates.filter(t => !t.legacy).map(t => [styleGroup(t), styleLabel(t)])); const previousGroup = $('style-group').value; $('style-group').replaceChildren(new Option('全部来源与风格', 'all')); groups.forEach((name, id) => $('style-group').add(new Option(name, id))); $('style-group').value = groups.has(previousGroup) ? previousGroup : 'all';
      const families = new Map(templates.filter(t => !t.legacy).map(t => [t.family, t.familyName || t.family])); $('family').replaceChildren(new Option('全部表达任务', 'all')); families.forEach((name, id) => $('family').add(new Option(name, id))); $('family').value = draft.family;
      if (!$('family').value) { draft.family = 'all'; $('family').value = 'all'; }
      const previous = $('qa-template').value; $('qa-template').replaceChildren(new Option('不关联模板', '')); templates.filter(t => !t.legacy).forEach(t => $('qa-template').add(new Option(`${t.name} · ${t.id}`, t.id))); $('qa-template').value = previous;
      renderCatalog();
    } catch (error) { $('catalog-status').textContent = '模板加载失败：' + error.message; $('catalog-retry').hidden = false; }
  }
  function pageSnapshot() { return clone({ id: draft.editingPage || uid(), title: draft.pageTitle.trim() || draft.fields.conclusion?.trim().slice(0, 80) || `${roleName(draft.role)} · ${experience.tasks[draft.task].name}`, task: draft.task, branches: draft.branches, followups: draft.followups, fields: draft.fields, role: draft.role, selected: draft.selected }); }
  function renderOutline() {
    $('restore-editor').hidden = !draft.editorBackup;
    $('deck-outline').replaceChildren(); $('page-edit-note').textContent = draft.editingPage ? '正在编辑大纲中的页面；修改后点击“保存当前页修改”。' : '正在填写新页面'; $('add-page').textContent = draft.editingPage ? '保存当前页修改' : '将当前页加入大纲'; $('restore-page').hidden = !draft.removedPage;
    if (!draft.pages.length) $('deck-outline').append(make('li', '大纲还没有页面。先填写当前页，再点击加入；也可直接整理当前页简报。'));
    draft.pages.forEach((page, index) => {
      const item = make('li'); item.append(make('strong', `${index + 1}. ${page.title}`), make('p', `${roleName(page.role)} · ${experience.tasks[page.task]?.name || page.task} · ${page.selected?.name || '模板待选'}`)); const actions = make('div', undefined, 'guide-actions');
      const move = delta => { const target = index + delta; if (target < 0 || target >= draft.pages.length) return; [draft.pages[index], draft.pages[target]] = [draft.pages[target], draft.pages[index]]; renderOutline(); save(true); };
      const up = button('上移', () => move(-1)), down = button('下移', () => move(1)); up.disabled = index === 0; down.disabled = index === draft.pages.length - 1;
      actions.append(up, down, button('载入编辑', () => { if (draft.editingPage !== page.id) draft.editorBackup = pageSnapshot(); Object.assign(draft, clone({ fields: { ...draft.fields, ...page.fields }, task: page.task, branches: page.branches, followups: page.followups || {}, role: page.role, selected: page.selected, pageTitle: page.title, editingPage: page.id, family: page.task })); hydrate(); save(); $('content').scrollIntoView({ behavior: 'smooth' }); }), button('移除', () => { draft.removedPage = { page: clone(page), index }; draft.pages.splice(index, 1); if (draft.editingPage === page.id) draft.editingPage = null; renderOutline(); save(true); })); item.append(actions); $('deck-outline').append(item);
    });
  }
  function renderQA() {
    const container = $('qa-records'); container.replaceChildren();
    const records = personal.records.filter(r => !$('related-only').checked || r.task === draft.task || (draft.selected && r.templateId === draft.selected.id));
    if (!records.length) container.append(make('p', '还没有匹配的个人问答。上方填写的是你的原始记录；内置规则不会充当个人经验。'));
    records.forEach(record => {
      const item = make('article', undefined, 'guide-record'); item.append(make('strong', record.question), make('p', `原始回答：${record.answer}`), make('p', `提炼规则：${record.rule}`), make('small', `个人输入 · 来源：${record.source} · ${experience.tasks[record.task]?.name || '未关联任务'} · 模板：${record.templateId || '无'}`));
      const actions = make('div', undefined, 'guide-actions'); actions.append(button('编辑', () => { editingQA = record.id; for (const field of ['question', 'answer', 'rule', 'source', 'task']) $('qa-' + field).value = record[field] || ''; $('qa-template').value = record.templateId || ''; $('qa-edit-note').textContent = '正在编辑个人记录'; $('cancel-qa').hidden = false; $('qa-question').focus(); }), button('删除', () => { personal.records = personal.records.filter(r => r.id !== record.id); if (editingQA === record.id) resetQA(); renderQA(); save(false, 'experience'); })); item.append(actions); container.append(item);
    });
  }
  function resetQA() { editingQA = null; $('qa-form').reset(); $('qa-task').value = draft.task; $('qa-edit-note').textContent = '新增个人记录'; $('cancel-qa').hidden = true; }
  function renderFavorites() {
    const container = $('favorite-records'); container.replaceChildren(); if (!personal.favorites.length) container.append(make('p', '尚无个人精选。模板目录是产品提供的候选，加入这里才成为你的精选。'));
    personal.favorites.forEach(favorite => {
      const item = make('article', undefined, 'guide-record'); item.append(make('strong', favorite.template.name), make('small', `个人精选 · ${favorite.template.id} · 来源：${favorite.template.source || '模板目录'}`)); const label = make('label', '为什么值得复用？'), input = make('textarea'); input.rows = 2; input.maxLength = 2000; input.value = favorite.reason; input.dataset.templateId = favorite.template.id; input.placeholder = '写明内容结构、视觉风格、适合与不适合的场景'; input.addEventListener('input', () => { favorite.reason = input.value; save(false, 'experience'); }); label.append(input); item.append(label, button('移出精选', () => { personal.favorites = personal.favorites.filter(f => f.id !== favorite.id); renderFavorites(); renderCatalog(); save(false, 'experience'); })); container.append(item);
    });
  }
  function buildBrief() {
    if (mismatch(draft)) { status('请先处理当前页的模板分支不匹配。'); $('library').scrollIntoView(); return; }
    let pages = clone(draft.pages);
    if (!pages.length) pages = [pageSnapshot()];
    if (pages.some(mismatch)) { status('大纲中存在不匹配的模板，请载入对应页并重新选择。'); return; }
    const value = id => draft.fields[id]?.trim() || '待补';
    if (!pages.some(p => p.role === 'cover')) pages.unshift({ role: 'cover', title: value('topic'), automatic: true });
    if (!pages.some(p => p.role === 'toc')) pages.splice(pages.findIndex(p => p.role === 'cover') + 1, 0, { role: 'toc', title: '目录', automatic: true });
    if (!pages.some(p => p.role === 'ending')) pages.push({ role: 'ending', title: '下一步与预期行动', automatic: true });
    const lines = [`# 整套内容简报：${value('topic')}`, '', `用途：${value('purpose')}`, `听众：${value('audience')}`, `预期行动：${value('action')}`, '', '## 逐页大纲', ...pages.map((p, i) => `${i + 1}. ${roleName(p.role)}：${p.title}`)];
    pages.forEach((page, i) => {
      lines.push('', `## 第 ${i + 1} 页 · ${roleName(page.role)}：${page.title}`);
      if (page.automatic) { lines.push('结构占位，尚未填写或选择模板。'); if (page.role === 'cover') lines.push(`主题：${value('topic')}；副标题、作者、日期：待补`); if (page.role === 'toc') lines.push(...pages.filter(p => !['cover', 'toc', 'ending'].includes(p.role)).map(p => `- ${p.title}`)); if (page.role === 'ending') lines.push(`预期行动：${value('action')}；负责人、时间：待补`); return; }
      const task = experience.tasks[page.task]; lines.push(`表达任务：${task.name}`, `结论：${page.fields.conclusion || '待补'}`); task.slots.forEach(slot => lines.push(`### ${slot.label}`, page.branches[page.task]?.[slot.id] || '待补'));
      followupRules(page).forEach(rule => lines.push(`### ${rule.label}`, page.followups?.[rule.id] || '待补'));
      lines.push('### 资料来源与待补信息', page.fields.sources || '待补');
      const t = page.selected; lines.push('### 模板偏好', t ? `已选模板：${t.name}\n模板 ID：${t.id}\n页面位置：${roleName(page.role)}\n表达分类：${t.familyName || t.family}\n来源：${t.source || '模板目录'}\n风格：${t.style || '待核对'}\n适用场景：${t.use}` : '模板待选择，不自动应用。');
    });
    const related = personal.records.filter(r => pages.some(p => p.task === r.task || (p.selected && p.selected.id === r.templateId)));
    if (related.length) { lines.push('', '## 用户提供的相关经验（供判断，不替代事实）'); related.forEach(r => lines.push(`- ${r.rule}（来源：${r.source}；原始问题：${r.question}）`)); }
    lines.push('', '## 制作说明', '这是用户填写的整套内容简报草稿。请先确认内容与逐页安排；不要将待补项或模板示例编造为事实。模板仅为偏好，尚未应用。仅带回工作台输入框，不自动发送或生成。', '问题提示来自产品内置规则；个人问答与精选理由来自用户输入。本次产品反馈单独注明来源，非虚构访谈。');
    const text = lines.join('\n'); if (text.length > 20000) { status('简报超过工作台 20,000 字限制，请精简大纲或回答；当前编辑稿已保留。'); return; }
    if (draft.brief) draft.previousBrief = draft.brief; draft.brief = text; draft.stale = false; $('brief').value = text; save();
    status(draft.pages.length ? '已按已保存大纲整理；当前页未保存的修改请先保存进大纲后再整理。' : '已用当前页整理整套简报，缺失的结构页标记待补。');
  }
  function requireBrief() { if (!draft.brief.trim()) { status('请先整理或填写内容简报。'); return false; } return true; }
  function download(text, name, type) { const url = URL.createObjectURL(new Blob([text], { type })); const link = make('a'); link.href = url; link.download = name; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 15000); }
  function hydrate() {
    document.querySelectorAll('[data-field]').forEach(input => { input.value = draft.fields[input.id] ?? (input.id === 'purpose' ? '方案决策' : input.id === 'materials' ? 'partial' : ''); draft.fields[input.id] = input.value; });
    $('purpose-tip').textContent = experience.purposeTips[draft.fields.purpose]; $('role').value = draft.role; $('family').value = draft.family; $('brief').value = draft.brief; $('page-title').value = draft.pageTitle; renderTask(); renderOutline(); renderCatalog(); renderQA(); renderFavorites(); updateBriefNote();
  }
  async function init() {
    document.querySelector('.guide-sections').inert = true;
    try {
      const requested = new URLSearchParams(location.search).get('project');
      const [state, rules] = await Promise.all([request('/api/state' + (requested ? '?project=' + encodeURIComponent(requested) : '')), request('/guide-experience.json')]);
      projectId = state.projectId; experience = rules; $('guide-project').textContent = state.project?.title || projectId; $('guide-home').href = home(); $('back-workbench').href = home();
      await Promise.all(['draft', 'experience'].map(kind => loadStore(kind)));
      Object.entries(experience.tasks).forEach(([id, task]) => $('qa-task').add(new Option(task.name, id)));
      const feedback = make('details', undefined, 'guide-feedback'); feedback.append(make('summary', '本次产品反馈 · 与个人问答分开记录')); (experience.productFeedback || []).forEach(item => { feedback.append(make('p', `“${item.question}”`), make('p', item.rule), make('small', item.source)); }); $('personal').insertBefore(feedback, $('qa-form'));
      document.querySelectorAll('[data-field]').forEach(input => input.addEventListener('input', () => { draft.fields[input.id] = input.value; if (['purpose', 'materials'].includes(input.id)) { $('purpose-tip').textContent = experience.purposeTips[draft.fields.purpose]; renderFollowups(); } save(true); }));
      $('brief').addEventListener('input', () => { draft.brief = $('brief').value; save(); }); $('page-title').addEventListener('input', () => { draft.pageTitle = $('page-title').value; save(true); });
      $('role').addEventListener('change', () => { draft.role = $('role').value; draft.family = 'all'; $('family').value = 'all'; visibleCount = 8; renderCatalog(); save(true); });
      $('family').addEventListener('change', () => { draft.family = $('family').value; visibleCount = 8; renderCatalog(); save(); });
      $('style-group').addEventListener('change', () => { visibleCount = 8; renderCatalog(); }); $('catalog-search').addEventListener('input', () => { visibleCount = 8; renderCatalog(); }); $('curated-only').addEventListener('change', renderCatalog); $('related-only').addEventListener('change', renderQA);
      $('catalog-more').addEventListener('click', () => { visibleCount += 8; renderCatalog(); }); $('catalog-retry').addEventListener('click', loadCatalog); $('clear-template').addEventListener('click', () => { draft.selected = null; renderCatalog(); save(true); });
      $('add-page').addEventListener('click', () => { if (mismatch(draft)) { status('请重新选择或清除不匹配的模板，再保存页面。'); $('library').scrollIntoView(); return; } const page = pageSnapshot(), index = draft.pages.findIndex(p => p.id === draft.editingPage); if (index >= 0) draft.pages[index] = page; else draft.pages.push(page); draft.editingPage = page.id; renderOutline(); save(true); });
      $('new-page').addEventListener('click', () => { draft.editorBackup = pageSnapshot(); draft.editingPage = null; draft.pageTitle = ''; draft.branches = {}; draft.followups = {}; draft.selected = null; draft.fields.conclusion = ''; draft.fields.sources = ''; hydrate(); save(true); });
      $('restore-editor').addEventListener('click', () => { const previous = draft.editorBackup; if (!previous) return; draft.editorBackup = pageSnapshot(); Object.assign(draft, clone({ fields: previous.fields, task: previous.task, branches: previous.branches, followups: previous.followups || {}, role: previous.role, selected: previous.selected, pageTitle: previous.title, editingPage: draft.pages.some(p => p.id === previous.id) ? previous.id : null, family: previous.task })); hydrate(); save(true); });
      $('restore-page').addEventListener('click', () => { const removed = draft.removedPage; if (!removed) return; draft.pages.splice(Math.min(removed.index, draft.pages.length), 0, removed.page); draft.removedPage = null; renderOutline(); save(true); });
      $('qa-form').addEventListener('submit', event => { event.preventDefault(); const record = { id: editingQA || uid(), templateId: $('qa-template').value }; for (const field of ['question', 'answer', 'rule', 'source', 'task']) record[field] = $('qa-' + field).value.trim(); if (['question', 'answer', 'rule', 'source'].some(f => !record[f])) return; const index = personal.records.findIndex(r => r.id === editingQA); if (index >= 0) personal.records[index] = record; else personal.records.push(record); resetQA(); renderQA(); save(false, 'experience'); }); $('cancel-qa').addEventListener('click', resetQA);
      let pendingImport = null;
      $('export-experience').addEventListener('click', () => download(JSON.stringify({ schema: 'weppt-guide-experience-v1', projectId, document: personal }, null, 2), 'weppt-personal-experience.json', 'application/json'));
      $('import-experience').addEventListener('change', async () => {
        pendingImport = null; $('confirm-import').disabled = true;
        try {
          const file = $('import-experience').files[0]; if (!file) return;
          if (file.size > 450000) throw new Error('文件超过 450 KB，请拆分后导入');
          const data = JSON.parse(await file.text()), value = data.document;
          const text = (v, max) => typeof v === 'string' && v.length <= max;
          if (data.schema !== 'weppt-guide-experience-v1' || !value || !Array.isArray(value.records) || !Array.isArray(value.favorites)) throw new Error('不是有效的个人经验文件');
          if (!value.records.every(r => r && text(r.id, 200) && text(r.question, 3000) && text(r.answer, 6000) && text(r.rule, 3000) && text(r.source, 1000) && experience.tasks[r.task] && text(r.templateId || '', 300))) throw new Error('问答字段或任务格式不正确');
          if (!value.favorites.every(f => f && text(f.id, 200) && f.template && text(f.template.id, 300) && text(f.template.name, 1000) && text(f.reason, 2000))) throw new Error('精选模板格式不正确');
          pendingImport = { records: value.records.filter(r => !personal.records.some(existing => existing.id === r.id)), favorites: value.favorites.filter(f => !personal.favorites.some(existing => existing.template.id === f.template.id)) };
          const merged = { records: [...personal.records, ...pendingImport.records], favorites: [...personal.favorites, ...pendingImport.favorites] };
          if (new Blob([JSON.stringify(merged)]).size > 480000) throw new Error('追加后超过保存容量，请减少记录');
          $('import-preview').textContent = `待追加 ${pendingImport.records.length} 条问答、${pendingImport.favorites.length} 个精选；相同记录 ID 或模板已跳过。来源项目：${typeof data.projectId === 'string' ? data.projectId : '未注明'}。`;
          $('confirm-import').disabled = false;
        } catch (error) { pendingImport = null; $('import-preview').textContent = '无法导入：' + error.message; }
      });
      $('confirm-import').addEventListener('click', () => { if (!pendingImport) return; personal.records.push(...pendingImport.records); personal.favorites.push(...pendingImport.favorites); pendingImport = null; $('confirm-import').disabled = true; $('import-preview').textContent = '已追加，原有记录未覆盖。'; renderQA(); renderFavorites(); renderCatalog(); save(false, 'experience'); });
      $('build-brief').addEventListener('click', buildBrief); $('restore-brief').addEventListener('click', () => { [draft.brief, draft.previousBrief] = [draft.previousBrief, draft.brief]; $('brief').value = draft.brief; draft.stale = true; save(); });
      $('copy-brief').addEventListener('click', async () => { if (!requireBrief()) return; try { await navigator.clipboard.writeText(draft.brief); status('已复制内容简报。'); } catch { $('brief').focus(); $('brief').select(); status('无法自动复制，已选中简报，请手动复制。'); } });
      $('download-brief').addEventListener('click', () => { if (requireBrief()) download(draft.brief, 'weppt-content-brief.md', 'text/markdown;charset=utf-8'); });
      $('handoff-brief').addEventListener('click', () => { if (!requireBrief()) return; const id = uid(); try { localStorage.setItem(`weppt:guide-handoff:${projectId}:${id}`, JSON.stringify({ text: draft.brief })); location.assign(home() + '&guideDraft=' + encodeURIComponent(id)); } catch { status('无法保存交接草稿，请复制简报后返回工作台粘贴。'); } });
      $('retry-save').addEventListener('click', async () => { for (const kind of ['draft', 'experience']) { const s = stores[kind]; if (!s.ready) { backup(kind); await loadStore(kind); hydrate(); } s.error = ''; if (!s.conflict) { s.dirty = true; void flush(kind); } } });
      $('download-backup').addEventListener('click', () => download(JSON.stringify({ projectId, draft, experience: personal }, null, 2), 'weppt-guide-backup.json', 'application/json'));
      $('reload-server').addEventListener('click', async () => { $('reload-server').disabled = true; document.querySelector('.guide-sections').inert = true; try { for (const kind of ['draft', 'experience']) if (stores[kind].conflict) { try { localStorage.setItem(`${backupKey(kind)}:before-reload:${Date.now()}`, JSON.stringify(documentFor(kind))); } catch { /* Download remains available. */ } await loadStore(kind, true); } hydrate(); } finally { $('reload-server').disabled = false; document.querySelector('.guide-sections').inert = false; } });
      hydrate(); resetQA(); document.querySelector('.guide-sections').inert = false; $('handoff-brief').disabled = false;
      status('按项目保存草稿与个人经验；服务器版本冲突时会停止覆盖。仅手动点击才把简报带回工作台。'); await loadCatalog(); ['draft', 'experience'].forEach(kind => { if (stores[kind].dirty) void flush(kind); });
    } catch (error) { status('引导页加载失败：' + error.message + ' 请刷新重试，已存草稿不会清除。'); }
  }
  window.addEventListener('beforeunload', event => { if (storageFailed || Object.values(stores).some(s => s.busy || s.dirty)) { event.preventDefault(); event.returnValue = ''; } });
  init();
})();
