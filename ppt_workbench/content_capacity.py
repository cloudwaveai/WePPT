"""Advisory copy/layout evidence; never truncate text or impose a template."""
import math
import unicodedata


def _units(text):
    return sum(1 if unicodedata.east_asian_width(c) in ('W', 'F') else .55
               for c in text if c not in '\r\n')


BODY_FONT_PX = 20  # Middle of the 18-22px body range in the visual toolbox.


def page_capacity(page):
    blocks = page.get('composition', {}).get('blocks', [])
    count = len(blocks)
    # A comparison scenario, not a prescribed layout or font specification.
    width = (1120 - 28 * max(0, count - 1)) / max(1, count)
    groups = []
    for block in blocks:
        body = block.get('body', '')
        lines = sum(max(1, math.ceil(_units(p) * BODY_FONT_PX / max(1, width)))
                    for p in body.split('\n')) if body else 0
        groups.append({'id': block['id'], 'headingCharacters': len(block.get('heading', '')),
                       'bodyCharacters': len(body), 'estimatedBodyLinesIfEqualColumns': lines})
    pressure = count >= 4 and any(g['estimatedBodyLinesIfEqualColumns'] > 6 for g in groups)
    return {'blockCount': count, 'groups': groups,
            'equalColumnScenario': {'bodyFontPx': BODY_FONT_PX, 'columnWidthPx': round(width, 1),
                                    'narrowColumnPressure': pressure},
            'scope': 'heuristic-not-font-measurement',
            'guidance': ('等宽多栏会产生长而窄的段落。考虑纵向步骤、宽说明区与短节点分离、'
                         '或有明确顺序的多行布局；先比较内容容量，再选构图。' if pressure else
                         '按内容主次分配区域，不要求每组面积相同。') +
                        '这是容量提示，不是模板或字号硬限制；保留全部事实、原文和同页要求，最终用实际渲染核验。'}


def plan_capacity(plan):
    return [{'page': i + 1, **page_capacity(page)} for i, page in enumerate(plan.get('pages', []))]


# Runs on the rendered DOM after fonts load. Range geometry observes actual line
# breaks, including mixed CJK/Latin text; explicit short paragraphs are excluded.
TEXT_FLOW_SCRIPT = r"""
const textFlow = [...document.querySelectorAll('.text')].map(el => {
  const content = el.querySelector('.text-content') || el;
  const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
  const rows = []; let node;
  while ((node = walker.nextNode())) {
    let offset = 0;
    for (const char of node.textContent) {
      const end = offset + char.length;
      if (char.trim()) {
        const range = document.createRange(); range.setStart(node, offset); range.setEnd(node, end);
        const rect = range.getBoundingClientRect();
        if (rect.width && rect.height) {
          let row = rows.find(r => Math.abs(r.top - rect.top) < 2);
          if (!row) { row = {top: rect.top, text: ''}; rows.push(row); }
          row.text += char;
        }
      }
      offset = end;
    }
  }
  rows.sort((a,b) => a.top-b.top);
  const tail = rows.at(-1)?.text || '';
  const paragraph = content.textContent.trimEnd().split(/\r?\n/).at(-1)?.trim() || '';
  return {objectId: el.dataset.objectId, lineCount: rows.length,
          lastLine: tail, fontSizePx: parseFloat(getComputedStyle(el).fontSize),
          orphanCandidate: rows.length >= 3 && [...tail].length <= 2 && tail.length > 0 && paragraph !== tail};
});
"""
