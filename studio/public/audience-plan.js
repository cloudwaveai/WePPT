/** Shared, side-effect-free contract for a reviewable audience adaptation. */
const ROLES = ['cover', 'toc', 'content', 'data', 'flow', 'chapter', 'ending'];
const ACTIONS = ['keep', 'edit', 'delete', 'add'];
const ENTRY_FIELDS = ['action', 'sourcePageId', 'title', 'body', 'role', 'reason', 'questions'];
const LIMITS = { title: 500, body: 100000, reason: 4000, message: 6000, question: 2000, text: 1000000 };
const idPattern = /^[\w-]{1,100}$/;
const boundedString = (maxLength, minLength = 0) => ({ type: 'string', minLength, maxLength });

export const AUDIENCE_PLAN_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['message', 'narrative', 'entries'],
  properties: {
    message: boundedString(LIMITS.message),
    narrative: boundedString(LIMITS.message, 1),
    entries: {
      type: 'array', minItems: 1, maxItems: 200,
      items: {
        type: 'object', additionalProperties: false, required: ENTRY_FIELDS,
        properties: {
          action: { type: 'string', enum: ACTIONS },
          sourcePageId: boundedString(100),
          title: boundedString(LIMITS.title), body: boundedString(LIMITS.body),
          role: { type: 'string', enum: ROLES }, reason: boundedString(LIMITS.reason, 1),
          questions: { type: 'array', maxItems: 20, items: boundedString(LIMITS.question, 1) }
        }
      }
    }
  }
};

function invalid(message) {
  const error = new Error(message);
  error.status = 400;
  throw error;
}
function record(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid(`${label}格式不正确。`);
}
function exactFields(value, fields, label) {
  record(value, label);
  if (Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value, key)) || Object.keys(value).some(key => !fields.includes(key))) {
    invalid(`${label}包含未知字段或缺少必填字段。`);
  }
}
function text(value, max, label, nonempty = false) {
  if (typeof value !== 'string' || value.length > max || (nonempty && !value.trim())) invalid(`${label}必须是${nonempty ? '非空' : ''}文字，且不能超过 ${max} 字。`);
  return value;
}
function role(value, label) {
  if (!ROLES.includes(value)) invalid(`${label}的页面类型不正确。`);
  return value;
}

function mappedText(page, field) {
  const mapped = value => value && (value.sourceField === field || value.layoutField === field);
  return [
    ...(Array.isArray(page.objects) ? page.objects.filter(value => value?.type === 'text' && mapped(value)) : []),
    ...(Array.isArray(page.sourceTextRuns) ? page.sourceTextRuns.filter(mapped) : [])
  ];
}

// The canvas editor changes object.text without updating page.body. Recover only edits
// with a known baseline. An explicitly changed canonical field still takes precedence,
// matching templates.js recoverContent without trusting invalid/overlapping ranges.
function pageText(page, field) {
  const refs = mappedText(page, field), canonical = page[field], baseline = page.layoutSource?.[field];
  if (canonical !== undefined && canonical !== null && typeof canonical !== 'string') invalid(`原稿页面的 ${field} 格式不正确。`);
  if (typeof canonical !== 'string') {
    return refs.map(ref => typeof ref.text === 'string' ? ref.text : (typeof ref.sourceText === 'string' ? ref.sourceText : '')).filter(Boolean).join('\n');
  }
  // Canonical copy edited after layout must not be replaced by stale canvas metadata.
  if (typeof baseline === 'string' && canonical !== baseline) return canonical;
  const edits = refs.filter(ref => typeof ref.text === 'string' && typeof ref.sourceText === 'string' && ref.text !== ref.sourceText);
  if (!edits.length) return canonical;
  if (field === 'title') {
    const values = new Set();
    for (const ref of edits) {
      if (canonical !== ref.sourceText && canonical !== ref.text) invalid('原稿标题与画布文字存在冲突，请先同步标题后重新生成方案。');
      values.add(ref.text);
    }
    if (values.size !== 1) invalid('原稿有多个互相冲突的标题文字框，请先确认当前标题。');
    return [...values][0];
  }
  const ranges = edits.map(ref => {
    const range = ref.sourceRange;
    if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isSafeInteger) || range[0] < 0 || range[1] < range[0] || range[1] > canonical.length) {
      invalid('原稿中已编辑的正文文字框缺少有效文案范围，请先同步该页正文后重新生成方案。');
    }
    const [start, end] = range;
    if (canonical.slice(start, end) !== ref.sourceText) invalid('原稿正文与画布文字范围存在冲突，请先同步该页正文后重新生成方案。');
    return { start, end, value: ref.text };
  }).sort((a, b) => a.start - b.start || a.end - b.end);
  for (let index = 1; index < ranges.length; index++) {
    const previous = ranges[index - 1], current = ranges[index];
    if (current.start < previous.end || current.start === previous.start) invalid('原稿正文文字框的编辑范围重叠，请先同步该页正文后重新生成方案。');
  }
  let body = canonical;
  for (const { start, end, value } of ranges.reverse()) body = body.slice(0, start) + value + body.slice(end);
  return body;
}

/** Project -> only the current copy and stable identity, never objects or SVG markup. */
export function audienceSource(project) {
  record(project, '原稿');
  if (typeof project.id !== 'string' || !idPattern.test(project.id)) invalid('原稿项目标识不正确。');
  if (!Number.isSafeInteger(project.revision) || project.revision < 0) invalid('原稿版本不正确，请先保存项目。');
  const title = text(project.title, LIMITS.title, '原稿标题');
  if (!Array.isArray(project.pages) || project.pages.length < 1 || project.pages.length > 100) invalid('原稿需要包含 1 至 100 页。');
  const ids = new Set();
  let length = title.length;
  const pages = project.pages.map((page, index) => {
    record(page, `原稿第 ${index + 1} 页`);
    if (typeof page.id !== 'string' || !idPattern.test(page.id) || ids.has(page.id)) invalid('原稿页面标识无效或重复。');
    ids.add(page.id);
    const title = text(pageText(page, 'title'), LIMITS.title, `原稿第 ${index + 1} 页标题`);
    const body = text(pageText(page, 'body'), LIMITS.body, `原稿第 ${index + 1} 页正文`);
    length += title.length + body.length;
    return { id: page.id, title, body, role: role(page.role, `原稿第 ${index + 1} 页`) };
  });
  if (length > LIMITS.text) invalid('原稿文案总量超过 100 万字，请拆分文稿后继续。');
  return { id: project.id, revision: project.revision, title, pages };
}

/** Validate every proposed operation before either review or application. */
export function validateAudiencePlan(raw, inputSource) {
  const source = audienceSource(inputSource);
  record(raw, '受众改编计划');
  exactFields(raw, Object.hasOwn(raw, 'narrative') ? ['message', 'narrative', 'entries'] : ['message', 'entries'], '受众改编计划');
  text(raw.message, LIMITS.message, '计划说明');
  const narrative = Object.hasOwn(raw, 'narrative') ? text(raw.narrative, LIMITS.message, '整体叙事理由') : '';
  if (!Array.isArray(raw.entries) || raw.entries.length < 1 || raw.entries.length > 200) invalid('改编计划需要包含 1 至 200 个逐页条目。');
  const summary = { keep: 0, edit: 0, delete: 0, add: 0, total: 0, changed: 0, moved: 0 };
  const pages = new Map(source.pages.map(page => [page.id, page]));
  const seen = new Set();
  let length = raw.message.length + narrative.length;
  const entries = raw.entries.map((entry, index) => {
    const label = `改编计划第 ${index + 1} 项`;
    exactFields(entry, ENTRY_FIELDS, label);
    if (!ACTIONS.includes(entry.action)) invalid(`${label}的操作不正确。`);
    text(entry.sourcePageId, 100, `${label}的原页标识`);
    text(entry.title, LIMITS.title, `${label}标题`);
    text(entry.body, LIMITS.body, `${label}正文`);
    role(entry.role, label);
    text(entry.reason, LIMITS.reason, `${label}原因`, true);
    if (!Array.isArray(entry.questions) || entry.questions.length > 20) invalid(`${label}的问题列表不正确或超过 20 项。`);
    for (const question of entry.questions) text(question, LIMITS.question, `${label}待确认问题`, true);
    length += entry.title.length + entry.body.length + entry.reason.length + entry.questions.reduce((sum, value) => sum + value.length, 0);
    let { action, title, body, role: pageRole, reason } = entry;
    if (action === 'add') {
      if (entry.sourcePageId !== '') invalid(`${label}新增页不能引用原页，sourcePageId 必须为空。`);
    } else {
      const original = pages.get(entry.sourcePageId);
      if (!original) invalid(`${label}引用了不存在的原页。`);
      if (seen.has(entry.sourcePageId)) invalid(`${label}重复引用了原页。`);
      seen.add(entry.sourcePageId);
      const same = entry.title === original.title && entry.body === original.body && entry.role === original.role;
      if (action === 'keep' && !same) {
        action = 'edit';
        reason = `原建议标为保留，但内容有变化，已按改写展示。${reason}`.slice(0, LIMITS.reason);
      }
      if (action === 'delete' && !same) {
        ({ title, body, role: pageRole } = original);
        reason = `原删除建议中的文案与原稿不一致；此处已恢复原稿原文，仅保留删除建议。${reason}`.slice(0, LIMITS.reason);
      }
      if (action === 'edit' && same) action = 'keep';
    }
    summary[action]++;
    if (action !== 'delete') summary.total++;
    return { action, sourcePageId: entry.sourcePageId, title, body, role: pageRole, reason, questions: [...entry.questions] };
  });
  if (seen.size !== source.pages.length) invalid('改编计划遗漏了原页；每个原页都必须恰好说明一次。');
  if (summary.total < 1 || summary.total > 100) invalid('改编后需要保留 1 至 100 页。');
  length = Math.max(length, raw.message.length + narrative.length + entries.reduce((sum, entry) => sum + entry.title.length + entry.body.length + entry.reason.length + entry.questions.reduce((n, value) => n + value.length, 0), 0));
  if (length > LIMITS.text) invalid('改编计划文案总量超过 100 万字，请拆分文稿后继续。');
  // Compare only surviving original pages. Insertions/deletions may change a page
  // number without changing narrative order, so they are not counted as moves.
  const retainedIds = entries.filter(entry => entry.action !== 'add' && entry.action !== 'delete').map(entry => entry.sourcePageId);
  const retained = new Set(retainedIds);
  const originalRanks = new Map(source.pages.filter(page => retained.has(page.id)).map((page, index) => [page.id, index]));
  const sourceIndices = new Map(source.pages.map((page, index) => [page.id, index + 1]));
  let targetIndex = 0, retainedRank = 0;
  const positions = entries.map(entry => {
    const moved = entry.action !== 'add' && entry.action !== 'delete' && originalRanks.get(entry.sourcePageId) !== retainedRank;
    if (entry.action !== 'add' && entry.action !== 'delete') retainedRank++;
    if (entry.action !== 'delete') targetIndex++;
    if (moved) summary.moved++;
    if (entry.action !== 'keep' || moved) summary.changed++;
    return { sourceIndex: sourceIndices.get(entry.sourcePageId) ?? null, targetIndex: entry.action === 'delete' ? null : targetIndex, moved };
  });
  const message = summary.changed
    ? '请逐页确认改编建议；最终页数和增删改数量以当前选择的统计为准。'
    : '当前方案没有实际改动，尚未完成受众改编。请补充受众需求后重新生成方案。';
  return { message, narrative, entries, summary, positions };
}
