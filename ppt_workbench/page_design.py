"""Structured page intent and complete editable authoring, before publication."""
import copy
import re
from .core import EngineError
from .rendering import validate_scene


BLOCK_REQUIRED = ('id', 'heading', 'body')
# Short visual anchors drawn large: a role label and a number quoted from the user's materials.
BLOCK_OPTIONAL = ('kicker', 'metric')
ANCHOR_LIMITS = {'kicker': 16, 'metric': 24}


def _compact(text):
    import unicodedata
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


_CHINESE_NUMERALS = set('零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億')


def _joins_number(edge, neighbour):
    """True when the metric's edge character continues a longer number in the source."""
    if edge.isdigit():
        return neighbour.isdigit() or neighbour == '.'
    return edge in _CHINESE_NUMERALS and neighbour in _CHINESE_NUMERALS


def metric_supported(metric, corpus):
    """A metric must appear verbatim (ignoring spaces/width) in the user's materials,
    and must not be cut out of a longer number: "80" is not sourced by "180个",
    "八亿元" not by "十八亿元", "十万元" not by "三十万元"."""
    needle, haystack = _compact(metric), _compact(corpus)
    if not needle:
        return False
    start = haystack.find(needle)
    while start >= 0:
        before = haystack[start - 1] if start else ''
        after = haystack[start + len(needle)] if start + len(needle) < len(haystack) else ''
        if not _joins_number(needle[0], before) and not _joins_number(needle[-1], after):
            return True
        start = haystack.find(needle, start + 1)
    return False


def drop_unsupported_metrics(plan, sources):
    """Remove model-drafted metrics that are not quoted verbatim from the user's materials.

    A metric is drawn as a large anchor, so an invented or re-united figure
    ("3亿元" from "3个模块", "八成" from nothing) would read as a sourced claim.
    Dropping the optional anchor keeps every planned sentence.
    """
    corpus = '\n'.join(s for s in sources if isinstance(s, str))
    dropped = []
    for index, page in enumerate(plan.get('pages', [])):
        for block in (page.get('composition') or {}).get('blocks', []):
            metric = block.get('metric')
            if metric is not None and not metric_supported(metric, corpus):
                del block['metric']
                dropped.append({'page': index + 1, 'block': block['id'], 'metric': metric})
    return dropped


RELATIONSHIPS = ('hero', 'parallel', 'comparison', 'process', 'layers', 'hub', 'evidence', 'summary')
# Layout hints that models write instead of the supported names. The relationship
# only steers layout, so mapping a clear synonym is safe; unknown values still fail.
RELATIONSHIP_ALIASES = {alias: name for name, aliases in {
    'process': ('sequence', 'sequential', 'timeline', 'steps', 'step', 'flow', 'workflow', 'procedure', 'stages',
                'phases', 'journey', 'roadmap', 'cycle', 'loop', '流程', '步骤', '时间线', '阶段', '路径'),
    'comparison': ('compare', 'contrast', 'versus', 'vs', 'before-after', 'tradeoff', 'trade-off', 'pros-cons',
                   '对比', '比较', '对照'),
    'parallel': ('list', 'grid', 'cards', 'items', 'points', 'pillars', 'categories', 'options', 'features',
                 'agenda', 'overview', '并列', '列表', '要点', '目录'),
    'layers': ('hierarchy', 'pyramid', 'stack', 'levels', 'tiers', 'structure', 'framework', 'tree',
               '层级', '层次', '金字塔', '框架', '结构'),
    'hub': ('center', 'centre', 'radial', 'network', 'ecosystem', 'core', 'hub-spoke', 'hub-and-spoke', 'mindmap',
            '中心', '辐射', '生态'),
    'evidence': ('data', 'metrics', 'stats', 'statistics', 'proof', 'case', 'case-study', 'example', 'examples',
                 'chart', 'testimonial', '证据', '数据', '案例', '事实'),
    'summary': ('conclusion', 'recap', 'closing', 'takeaway', 'takeaways', 'ending', 'next-steps', 'call-to-action',
                'cta', '总结', '结论', '回顾', '收尾', '结尾'),
    'hero': ('cover', 'title', 'statement', 'opening', 'intro', 'introduction', 'section', 'chapter', 'headline',
             'quote', '封面', '标题', '主张', '开场', '章节', '引言'),
}.items() for alias in aliases}
# Models confuse composition.relationship with designBrief.layoutArchetype (both are
# layout words), e.g. relationship "ordered-rows". Map each archetype to its closest relationship.
RELATIONSHIP_ALIASES.update({'hero-statement': 'hero', 'big-number': 'evidence', 'split-asymmetric': 'comparison',
                             'full-bleed-band': 'hero', 'grid-cards': 'parallel', 'ordered-rows': 'process',
                             'diagram': 'hub', 'ordered': 'process', 'ordered-list': 'process',
                             'numbered': 'process', 'numbered-list': 'process', 'sequence-list': 'process'})


REF_FIELD_ALIASES = {'title': 'heading', 'name': 'heading', 'header': 'heading', 'headline': 'heading',
                     'text': 'body', 'content': 'body', 'description': 'body', 'desc': 'body', 'detail': 'body',
                     'details': 'body', 'label': 'kicker', 'tag': 'kicker', 'number': 'metric', 'stat': 'metric'}


def _planned_ref(ref, references):
    """Resolve harmless spelling variants of a textRef ("blocks.A.Title", "A.content"),
    but only to a reference that really exists in the plan."""
    if not isinstance(ref, str):
        return None
    if ref in references:
        return ref
    parts = ref.strip().split('.')
    if len(parts) == 1 and parts[0].lower() == 'title':
        return 'title'
    if parts and parts[0].lower() in ('block', 'blocks'):
        parts = parts[1:]
    if len(parts) != 2:
        return None
    candidate = f'block.{parts[0]}.{REF_FIELD_ALIASES.get(parts[1].lower(), parts[1].lower())}'
    return candidate if candidate in references else None


def _title_color(scene):
    from .quality import _luminance
    return '#FFFFFF' if _luminance(scene.get('background', '#FFFFFF')) < .35 else '#12243C'


def _relationship(value):
    if not isinstance(value, str):
        return None
    key = re.sub(r'[\s_]+', '-', value.strip().lower())
    return key if key in RELATIONSHIPS else RELATIONSHIP_ALIASES.get(key)


def validate_composition(value):
    if not isinstance(value, dict) or set(value) != {'purpose', 'relationship', 'blocks'}:
        raise EngineError('INVALID_COMPOSITION', '页面方案需要 purpose、relationship、blocks。')
    if not isinstance(value['purpose'], str) or not 1 <= len(value['purpose']) <= 600:
        raise EngineError('INVALID_COMPOSITION', '请说明这一页要让读者理解什么。')
    relationship = _relationship(value['relationship'])
    if relationship is None:
        raise EngineError('INVALID_COMPOSITION', f'页面关系类型无效：{str(value["relationship"])[:40]!r}，'
                          '只能是 ' + '、'.join(RELATIONSHIPS) + ' 之一。')
    value['relationship'] = relationship
    if not isinstance(value['blocks'], list) or not 1 <= len(value['blocks']) <= 12:
        raise EngineError('INVALID_COMPOSITION', '页面需要 1–12 个完整内容分组。')
    ids = set()
    for block in value['blocks']:
        if (not isinstance(block, dict) or not set(BLOCK_REQUIRED) <= set(block)
                or set(block) - set(BLOCK_REQUIRED) - set(BLOCK_OPTIONAL)):
            raise EngineError('INVALID_COMPOSITION', '每组需要 id、heading、body，可选 kicker、metric。')
        for field, limit in ANCHOR_LIMITS.items():
            if field in block and (not isinstance(block[field], str) or not block[field].strip() or len(block[field]) > limit):
                raise EngineError('INVALID_COMPOSITION', f'{field} 是 1–{limit} 字的短锚点。')
        if not isinstance(block['id'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,30}',block['id']) or block['id'] in ids:
            raise EngineError('INVALID_COMPOSITION', '内容组 ID 必须唯一。')
        ids.add(block['id'])
        for field in ('heading','body'):
            if not isinstance(block[field],str) or len(block[field]) > 3000:
                raise EngineError('INVALID_COMPOSITION', '内容组文字无效。')
        if not (block['heading'] + block['body']).strip():
            raise EngineError('INVALID_COMPOSITION', '内容组不能为空。')
    return copy.deepcopy(value)


DESIGN_REQUIRED = ('background', 'ink', 'accent', 'fontFamily')
# Optional colour roles: secondary accents, panel fill, and dark-page background.
DESIGN_OPTIONAL = ('secondary', 'tertiary', 'surface', 'inverse')


def validate_design(value):
    if (not isinstance(value,dict) or not set(DESIGN_REQUIRED) <= set(value)
            or set(value) - set(DESIGN_REQUIRED) - set(DESIGN_OPTIONAL)):
        raise EngineError('INVALID_DESIGN', '整稿风格需要 background、ink、accent、fontFamily，可选 secondary、tertiary、surface、inverse。')
    for field in ('background','ink','accent') + tuple(f for f in DESIGN_OPTIONAL if f in value):
        if not isinstance(value[field],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value[field]):
            raise EngineError('INVALID_DESIGN', '整稿颜色需要 #RRGGBB。')
    if not isinstance(value['fontFamily'],str) or not re.fullmatch(r'[\w \-\u3400-\u9fff]{1,80}',value['fontFamily']):
        raise EngineError('INVALID_DESIGN', '整稿字体无效。')
    return copy.deepcopy(value)


def prepare_scene(action, slide_id='S001', resolve_images=None):
    """Use an authored scene without reapplying a generic template over it."""
    if action.get('diagram'):
        from .diagram_design import build_scene
        scene = build_scene({'id':slide_id,'title':action['title'],'takeaway':action.get('takeaway','')},action['diagram'])
    elif action.get('scene'):
        scene = copy.deepcopy(action['scene'])
        scene['slideId'] = slide_id
        # The planner owns words; the layout model can position references instead
        # of retyping (and accidentally shortening) approved content groups.
        references={'title':action['title']}
        if action.get('composition'):
            for block in validate_composition(action['composition'])['blocks']:
                for key in BLOCK_REQUIRED[1:] + BLOCK_OPTIONAL:
                    if key in block:
                        references[f'block.{block["id"]}.{key}']=block[key]
        if isinstance(scene.get('objects'),list):
            absent=[]
            for obj in scene['objects']:
                if isinstance(obj,dict) and obj.get('type')=='text' and 'textRef' in obj:
                    given=obj['textRef']
                    ref=_planned_ref(given, references)
                    if ref is None:
                        if isinstance(given,str) and given.rsplit('.',1)[-1].lower() in ('kicker','metric'):
                            absent.append(obj)  # Optional anchor the plan does not have: no words to lose.
                            continue
                        raise EngineError('INVALID_SCENE', f'textRef {str(given)[:60]!r} 不在计划中，只能引用：'
                                          + '、'.join(list(references)[:40]) + '。')
                    obj.pop('text', None)  # The planned (protected) words win over a retyped copy.
                    source = references[ref]
                    if 'textRange' in obj:
                        span = obj.pop('textRange')
                        if (not ref.endswith(('.heading', '.body')) or not isinstance(span, list) or len(span) != 2
                                or any(type(n) is not int for n in span) or not 0 <= span[0] < span[1] <= len(source)):
                            raise EngineError('INVALID_SCENE', 'textRange 必须完整引用合法的正文字符范围。')
                        obj['text'] = source[span[0]:span[1]]
                        obj['textSource'] = {'ref': ref, 'start': span[0], 'end': span[1]}
                    else:
                        obj['text'] = source
                    del obj['textRef']
            scene['objects']=[obj for obj in scene['objects'] if not any(obj is gone for gone in absent)]
        if resolve_images:
            scene = resolve_images(scene)
        scene = validate_scene(scene)
    else:
        return None
    title = next((o for o in scene['objects'] if o['type']=='text' and o.get('binding')=='title'),None)
    if title is None:
        squash = lambda t: re.sub(r'\s+', '', t)
        texts = [o for o in scene['objects'] if o['type']=='text' and not o.get('binding')]
        # Exact text first, then the same words with different spaces / line breaks;
        # the bound object always receives the exact planned title.
        candidates = ([o for o in texts if o['text']==action['title']]
                      or [o for o in texts if squash(o['text'])==squash(action['title'])])
        if candidates:
            title=max(candidates, key=lambda o: o['fontSize'])
            title['binding']='title'
            title['text']=action['title']
        elif not any(o.get('binding')=='title' or (o['type']=='text' and o['fontSize']>=32) for o in scene['objects']):
            # Only when the title is truly absent: a large unbound heading is more likely
            # a rewritten title, which must still fail so the retry restores the planned words.
            # The model forgot the planned title entirely: add it as a normal editable
            # text object at the top; the design review can still reposition it.
            title={'id':'title','type':'text','text':action['title'],'binding':'title','x':80,'y':36,'w':1120,'h':72,
                   'fontSize':40,'bold':True,'color':_title_color(scene)}
            if any(o['id']=='title' for o in scene['objects']):
                title['id']='planned-title'
            scene['objects'].append(title)
            scene = validate_scene(scene)
            title = next(o for o in scene['objects'] if o.get('binding')=='title')
    if not title or title['text'] != action['title']:
        raise EngineError('DESIGN_CONTENT_MISMATCH','页面必须完整呈现计划标题，并将该文本对象 binding 设为 title。',
                          {'expectedTitle':action['title'],'boundTitle':title.get('text') if title else None})
    if any(o['id'].startswith('footer.') for o in scene['objects']):
        raise EngineError('DESIGN_REPEATED_FOOTER','新设计不应添加重复页脚；必要的来源说明使用独立内容对象。')
    if action.get('composition'):
        composition = validate_composition(action['composition'])
        text = '\n'.join(o['text'] for o in scene['objects'] if o['type']=='text' and o.get('opacity',1)>=.9)
        compact = lambda t: re.sub(r'\s+','',t)
        def covered(ref, original):
            fragments = [o for o in scene['objects'] if o['type'] == 'text' and o.get('textSource', {}).get('ref') == ref]
            if not fragments:
                page = compact(text)
                if compact(original) in page:
                    return True
                # Tables laid out as separate cells drop the "｜" separators: every cell
                # must still appear verbatim and in order; only separators are ignored.
                cursor = 0
                for cell in (c for c in re.split(r'[｜|\t\n]+', original) if c.strip()):
                    found = page.find(compact(cell), cursor)
                    if found < 0:
                        return False
                    cursor = found + len(compact(cell))
                return True
            cursor = 0
            for obj in sorted(fragments, key=lambda o: o['textSource']['start']):
                source = obj['textSource']
                if (source['start'] != cursor or source['end'] > len(original)
                        or obj['text'] != original[source['start']:source['end']] or obj.get('opacity', 1) < .9):
                    return False
                cursor = source['end']
            return cursor == len(original)
        missing = [b['id'] for b in composition['blocks'] if any(
            not covered(f'block.{b["id"]}.{k}', b[k]) for k in ('heading', 'body') if b[k].strip())]
        if missing:
            raise EngineError('DESIGN_CONTENT_MISMATCH','页面没有完整呈现内容组，不能以缩写或遗漏替代。若图解协议无法容纳这些文字，提交完整 scene，不能重复提交不完整 diagram。',
                              {'missingBlocks':missing,'requiredText':[b for b in composition['blocks'] if b['id'] in missing]})
    return scene
