"""Whole-deck creative decisions, separate from immutable words and geometry."""
import copy
import math
import re
from .core import EngineError

STRATEGY_FIELDS = ('audience', 'outcome', 'storyArc', 'visualLanguage', 'typography',
                   'imagePolicy', 'rhythm', 'alternatives', 'selectedDirection', 'selectionReason')
STRATEGY_OPTIONAL = ('signatureMotif', 'scaleContrast')
BRIEF_FIELDS = ('claim', 'visualForm', 'visualReason', 'evidence', 'readingPath', 'density', 'continuity')
BRIEF_OPTIONAL = ('layoutArchetype', 'focalElement', 'backgroundTreatment', 'imagePrompt')
LAYOUT_ARCHETYPES = ('hero-statement', 'big-number', 'split-asymmetric', 'full-bleed-band', 'grid-cards',
                     'ordered-rows', 'timeline', 'diagram', 'quote', 'comparison')
BACKGROUND_TREATMENTS = ('paper', 'surface', 'inverse', 'split')
MAX_AUTO_IMAGES = 3


def _texts(value, fields, name, optional=()):
    if not isinstance(value, dict) or not set(fields) <= set(value) or set(value) - set(fields) - set(optional):
        raise EngineError('INVALID_DESIGN_BRIEF', f'{name} 需要字段：' + '、'.join(fields)
                          + ('；可选：' + '、'.join(optional) if optional else ''))
    for key in value:
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 2400:
            raise EngineError('INVALID_DESIGN_BRIEF', f'{name}.{key} 必须是 1–2400 字的说明。')


def validate_strategy(value):
    fields = STRATEGY_FIELDS
    if not isinstance(value, dict) or not set(fields) <= set(value) or set(value) - set(fields) - set(STRATEGY_OPTIONAL):
        raise EngineError('INVALID_DESIGN_BRIEF', '整稿 strategy 字段不完整。',
                          {'fields': list(fields), 'optional': list(STRATEGY_OPTIONAL)})
    _texts({k: v for k, v in value.items() if k != 'alternatives'},
           [k for k in fields if k != 'alternatives'], 'strategy', STRATEGY_OPTIONAL)
    choices = value['alternatives']
    if not isinstance(choices, list) or not 2 <= len(choices) <= 3:
        raise EngineError('INVALID_DESIGN_BRIEF', '请比较 2–3 个不同的视觉方向。')
    for choice in choices:
        _texts(choice, ('id', 'concept', 'rationale'), 'alternative')
    ids = [c['id'] for c in choices]
    if len(set(ids)) != len(ids) or value['selectedDirection'] not in ids:
        raise EngineError('INVALID_DESIGN_BRIEF', '选定方向必须对应唯一的候选方向。')
    return copy.deepcopy(value)


def _vocabulary_key(value):
    return re.sub(r'[\s_]+', '-', value.strip().lower()) if isinstance(value, str) else None


# Optional layout hints: a recognisable synonym (including a relationship name written in
# the wrong field) is mapped; anything else drops the optional hint instead of failing the plan.
ARCHETYPE_ALIASES = {'hero': 'hero-statement', 'statement': 'hero-statement', 'cover': 'hero-statement',
                     'parallel': 'grid-cards', 'cards': 'grid-cards', 'grid': 'grid-cards', 'list': 'ordered-rows',
                     'rows': 'ordered-rows', 'process': 'timeline', 'steps': 'timeline', 'sequence': 'timeline',
                     'layers': 'diagram', 'hub': 'diagram', 'evidence': 'big-number', 'metric': 'big-number',
                     'number': 'big-number', 'summary': 'full-bleed-band', 'band': 'full-bleed-band',
                     'split': 'split-asymmetric', 'asymmetric': 'split-asymmetric', 'compare': 'comparison'}
BACKGROUND_ALIASES = {'dark': 'inverse', 'inverted': 'inverse', 'light': 'paper', 'white': 'paper', 'plain': 'paper',
                      'panel': 'surface', 'card': 'surface', 'tinted': 'surface', 'half': 'split', 'two-tone': 'split'}
DENSITY_ALIASES = {'focus': 'anchor', 'focal': 'anchor', 'hero': 'anchor', 'sparse': 'breathing', 'airy': 'breathing',
                   'light': 'breathing', 'detailed': 'dense', 'heavy': 'dense', 'rich': 'dense'}


def normalize_brief(brief, composition, title=''):
    """Design notes guide layout and never reach a slide. For long decks models often
    omit or misname a few; fill those from the page's own content instead of failing."""
    brief = {k: v for k, v in (brief if isinstance(brief, dict) else {}).items()
             if k in BRIEF_FIELDS + BRIEF_OPTIONAL and isinstance(v, str) and v.strip()}
    blocks = (composition or {}).get('blocks') or []
    defaults = {'claim': (composition or {}).get('purpose') or title or '本页要点',
                'visualForm': f"{(composition or {}).get('relationship', 'parallel')} 关系版式",
                'visualReason': '按内容关系组织版面', 'evidence': '本页内容分组',
                'readingPath': '从标题到各内容分组', 'continuity': '延续整稿视觉语言',
                'density': 'anchor' if len(blocks) <= 1 else 'dense' if len(blocks) >= 4 else 'breathing'}
    for key, value in defaults.items():
        brief.setdefault(key, value)
    return {k: v[:2400] for k, v in brief.items()}


def validate_brief(value):
    _texts(value, BRIEF_FIELDS, 'designBrief', BRIEF_OPTIONAL)
    density = _vocabulary_key(value['density'])
    value['density'] = DENSITY_ALIASES.get(density, density)
    if value['density'] not in {'anchor', 'dense', 'breathing'}:
        raise EngineError('INVALID_DESIGN_BRIEF', '页面节奏为 anchor、dense 或 breathing。')
    for field, allowed, aliases in (('layoutArchetype', LAYOUT_ARCHETYPES, ARCHETYPE_ALIASES),
                                    ('backgroundTreatment', BACKGROUND_TREATMENTS, BACKGROUND_ALIASES)):
        if field in value:
            key = _vocabulary_key(value[field])
            key = key if key in allowed else aliases.get(key)
            if key:
                value[field] = key
            else:
                del value[field]
    if len(value.get('imagePrompt', '')) > 600:
        raise EngineError('INVALID_DESIGN_BRIEF', 'imagePrompt 不超过 600 字。')
    return copy.deepcopy(value)


def plan_rhythm(plan, image_mode='off'):
    """Deterministic rhythm evidence for the plan reviewer; advisory, never a gate."""
    if not isinstance(plan, dict) or not plan.get('strategy'):
        return []
    briefs = [p.get('designBrief') or {} for p in plan.get('pages', [])]
    count, findings = len(briefs), []
    missing = [i + 1 for i, b in enumerate(briefs) if not b.get('layoutArchetype')]
    if missing:
        findings.append({'code': 'ARCHETYPE_MISSING', 'pages': missing,
                         'message': '这些页缺少 designBrief.layoutArchetype，无法核对版式节奏。'})
    repeats = [[i + 1, i + 2] for i in range(count - 1)
               if briefs[i].get('layoutArchetype') and briefs[i].get('layoutArchetype') == briefs[i + 1].get('layoutArchetype')]
    if repeats:
        findings.append({'code': 'ARCHETYPE_REPEAT', 'pages': repeats,
                         'message': '相邻页使用相同骨架；结合内容判断是否单调，连续证据可以保持同一布局。'})
    if count >= 4:
        toned = [i + 1 for i, b in enumerate(briefs) if b.get('backgroundTreatment') in ('inverse', 'split')]
        required = max(1, math.ceil(count * .2))
        if len(toned) < required:
            findings.append({'code': 'TONE_FLAT', 'pages': toned, 'required': required,
                             'message': f'当前深色或分割底页为 {len(toned)} 页；检查疏密和主次节奏，统一浅色风格不必补深色页。'})
    images = [i + 1 for i, b in enumerate(briefs) if b.get('imagePrompt')]
    if image_mode == 'auto' and len(images) > MAX_AUTO_IMAGES:
        findings.append({'code': 'IMAGE_PAGES_EXCEED', 'pages': images,
                         'message': f'自动配图最多 {MAX_AUTO_IMAGES} 页；只保留最需要图像的页面的 imagePrompt。'})
    return findings


def _insertable(path):
    """Optional design fields a sparse plan review may add, never other keys."""
    from .page_design import DESIGN_OPTIONAL, BLOCK_OPTIONAL
    pages = len(path) >= 2 and path[0] == 'pages' and type(path[1]) is int
    return ((len(path) == 2 and path[0] == 'design' and path[1] in DESIGN_OPTIONAL)
            or (len(path) == 2 and path[0] == 'strategy' and path[1] in STRATEGY_OPTIONAL)
            or (pages and len(path) == 4 and path[2] == 'designBrief' and path[3] in BRIEF_OPTIONAL)
            or (pages and len(path) == 6 and path[2:4] == ['composition', 'blocks']
                and type(path[4]) is int and path[5] in BLOCK_OPTIONAL))


def validate_plan_patch(action):
    """Internal draft-only replacements; never a published scene mutation."""
    if set(action) != {'type', 'changes'} or not isinstance(action['changes'], list) or not 1 <= len(action['changes']) <= 80:
        raise EngineError('INVALID_DESIGN_BRIEF', '策划修改需要 1–80 项 changes。')
    paths = []
    for change in action['changes']:
        if not isinstance(change, dict) or set(change) != {'path', 'value'}:
            raise EngineError('INVALID_DESIGN_BRIEF', '策划修改仅接受 path 和 value。')
        path = change['path']
        if (not isinstance(path, list) or not path or len(path) > 8
                or path[0] not in ('title', 'design', 'strategy', 'pages')
                or (path[0] == 'pages' and (len(path) < 3 or type(path[1]) is not int))
                or any(type(part) not in (str, int) for part in path)
                or any(type(part) is int and part < 0 for part in path)):
            raise EngineError('INVALID_DESIGN_BRIEF', '策划路径必须指向现有字段，页码从 0 开始，不能替换整份 pages。')
        if any(path[:len(old)] == old or old[:len(path)] == path for old in paths):
            raise EngineError('INVALID_DESIGN_BRIEF', '策划修改路径不能重复或相互覆盖。')
        paths.append(path)


def apply_plan_patch(draft, action):
    validate_plan_patch(action)
    revised = copy.deepcopy(draft)
    try:
        for change in action['changes']:
            target = revised
            for part in change['path'][:-1]:
                target = target[part]
            key = change['path'][-1]
            if not (isinstance(target, dict) and key not in target and _insertable(change['path'])):
                target[key]  # Only replace existing fields; no implicit insert/delete.
            target[key] = copy.deepcopy(change['value'])
    except (KeyError, IndexError, TypeError) as exc:
        raise EngineError('INVALID_DESIGN_BRIEF', '策划修改引用了不存在的字段。') from exc
    return revised


def review_plan(studio, job, proposal, context, mode, runner):
    """Review model-authored copy before freezing it into the editable page plan."""
    import json
    starts = [a for a in proposal.get('actions', []) if a['type'] == 'deck_start' and a.get('strategy')]
    if not starts or starts[0].get('execution') != 'agent':
        return proposal
    folder = studio.wb.project_dir(studio.project_id) / 'plan-reviews' / job['id']
    folder.mkdir(parents=True, exist_ok=True)
    final_path, report_path = folder / 'final.json', folder / 'report.json'
    if final_path.exists():
        return json.loads(final_path.read_text())
    if report_path.exists():
        raise EngineError('DESIGN_PLAN_REVIEW_FAILED', '本次策划复核已调用但未完成，原始方案已保留。')
    (folder / 'draft.json').write_text(json.dumps(proposal, ensure_ascii=False, indent=2))
    report = {'status': 'running', 'modelCalls': 1, 'humanAccepted': False}
    report_path.write_text(json.dumps(report))
    try:
        review_context = copy.deepcopy(context)
        from .content_capacity import plan_capacity
        rhythm = plan_rhythm(starts[0], context.get('imageMode', 'off'))
        report['rhythmFindings'] = rhythm
        review_context.update(generationTask={'kind': 'deck_plan_review'}, draftDeckPlan=starts[0],
                              contentCapacity=plan_capacity(starts[0]), rhythmFindings=rhythm)
        result = runner(mode,
            '在生成任何页面之前复核这份模型草拟的整稿方案。先对照用户原始输入逐项检查事实、数字、'
            '限定条件、指定文字、页数、顺序和同页要求，再检查叙事、视觉方向、每页设计和可读容量。'
            '用户制作要求是约束，不是观众正文：不要把“几页初稿、面向某受众、不编造数据、阅读约定、'
            '请确认”等写在页面上，不重复标题，不添加无必要的小字与页脚。案例本身仍必须明确标为示意，'
            '真实来源、数据口径、边界和不确定性必须保留。证据应是具体事实、例子或材料，不是“用户要求”。'
            '以设计目的组织正文，允许重新分组模型草稿，但不得删除或改写用户要求保留的内容。'
            '结合 contentCapacity 比较正文长度与拟定构图：长说明不要硬塞等宽多栏；'
            '先选择宽说明区、纵向流程或有序多行，再同步调整 designBrief 和内容分组。'
            '模型自行撰写的标题、组标题与正文应各自增加信息；不要把同一句话换词重复，'
            '不要添加“不是X而是Y”的口号、页底导读或收尾填充。用户明确提供的原文和必要边界仍须完整保留。'
            '不能为凑模板省略事实、缩成小字或擅自拆分用户指定的同页内容。不要编造素材或引用。'
            '再核对视觉节奏：rhythmFindings 是机械提示，结合统一设计规则判断，不为消除告警强改合理布局或添加深色页。'
            '自动配图不超过限额；改版式时同步 visualForm 与 focalElement。'
            '选择理由不能是"更安全""更少装饰"，必须说明该方向如何制造视觉焦点。'
            'metric 只能是用户材料中原样出现的数字或数量，否则删除该字段；模型撰写的正文保持一句话一个要点。'
            '合理时 reply 第一行 PASS，actions=[]；需要修正时第一行 REVISE，仅返回一个 deck_plan_patch，'
            'changes=[{"path":["pages",0,"composition","blocks",0,"body"],"value":"修订正文"}]。'
            'path 用数组指向 draftDeckPlan 中已有字段，页码从0开始；可替换某页 blocks 整组以调整分组。'
            '可选字段缺失时可直接新增：pages[i].designBrief 的 layoutArchetype、focalElement、backgroundTreatment、imagePrompt，'
            'blocks[j] 的 kicker、metric，design 的 secondary、tertiary、surface、inverse，strategy 的 signatureMotif、scaleContrast。'
            '只输出变化字段，不重复整稿、未改页面或设计说明，不改变页数、执行方式及用户指定内容。'
            '不执行实际页面修改，不增加其他动作，不提问普通审美选择。',
            review_context, timeout=120, workdir=studio.wb.project_dir(studio.project_id),
            selected_ids=job['payload'].get('attachments', []),
            asset_records=[studio.asset(aid) for aid in job['payload'].get('attachments', [])] if mode == 'codex' else [])
        from .design_loop import review_verdict
        (folder / 'response.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        verdict = review_verdict(result.get('reply', ''))
        actions = result.get('actions', [])
        final = copy.deepcopy(proposal)
        if verdict == 'REVISE' and len(actions) == 1 and actions[0]['type'] in ('deck_start', 'deck_plan_patch'):
            from .outline import validate_deck_plan
            revised = apply_plan_patch(starts[0], actions[0]) if actions[0]['type'] == 'deck_plan_patch' else actions[0]
            validate_deck_plan({k: v for k, v in revised.items() if k != 'type'})
            if (not revised.get('strategy') or revised['execution'] != starts[0]['execution']
                    or len(revised['pages']) != len(starts[0]['pages'])
                    or any(not p.get('composition') for p in revised['pages'])):
                raise EngineError('DESIGN_PLAN_REVIEW_FAILED', '策划复核不能改变已确定页数或省略设计方案。')
            final['actions'] = [copy.deepcopy(revised) if a is starts[0] else copy.deepcopy(a) for a in proposal['actions']]
        elif verdict != 'PASS' or actions:
            raise EngineError('DESIGN_PLAN_REVIEW_FAILED', '策划复核未返回有效结论，未开始制作页面。')
        final_start = next(a for a in final['actions'] if a['type'] == 'deck_start')
        report.update(status='revised' if actions else 'reviewed', reply=result.get('reply'),
                      finalRhythmFindings=plan_rhythm(final_start, context.get('imageMode', 'off')))
        final_path.write_text(json.dumps(final, ensure_ascii=False, indent=2))
        return final
    except EngineError as exc:
        # The draft already passed full validation. A broken review patch must not
        # block the deck: keep the original plan and record why the review failed.
        report.update(status='failed-kept-draft', error=exc.to_dict())
        kept = copy.deepcopy(proposal)
        kept['reply'] = (kept.get('reply') or '') + '\n策划复核未完成，已按原方案继续。'
        final_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2))
        return kept
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))


def generation_context(studio, deck, page_index):
    """Carry design decisions and actual preceding geometry, without image bytes."""
    import json
    from .templates import recommend_templates
    plan = json.loads(deck['plan'])
    pages = plan['pages']
    page = pages[page_index]
    from .reference_templates import visual_guidance
    from .templates import catalog
    references = recommend_templates(page['role'], page={**page,
        'keyPoints': '\n'.join(b['heading'] + '\n' + b['body']
            for b in page.get('composition', {}).get('blocks', []))}, limit=3)
    recent = []
    with studio.wb._connection() as db:
        rows = db.execute('SELECT slide_id FROM studio_deck_pages WHERE deck_id=? AND page_index<? '
                          'AND status=? ORDER BY page_index DESC LIMIT 2',
                          (deck['id'], page_index, 'complete')).fetchall()
    for row in reversed(rows):
        scene = studio.get_scene(row['slide_id'])['scene']
        recent.append({'slideId': scene['slideId'], 'background': scene['background'],
                       'objects': [{k: v for k, v in o.items() if k not in {'src'}}
                                   for o in scene['objects']]})
    from .content_capacity import page_capacity
    from .design_exemplars import for_page, archetype_for
    previous = archetype_for(pages[page_index - 1]) if page_index else None
    return {'deckStrategy': plan.get('strategy'),
            'contentCapacity': page_capacity(page),
            'designRoster': [{'index': i + 1, 'title': p['title'],
                              'designBrief': p.get('designBrief')} for i, p in enumerate(pages)],
            'previousPageDesigns': recent,
            'designReferences': [visual_guidance(t['id'], catalog()) for t in references],
            'designExemplar': for_page(page, previous),
            'designInstruction': '按内容选择表达方式；参考库提供构图原则。结合相邻页安排节奏，'
                                 '通过主次、密度与图文比例组织节奏，连续证据允许复用构图；不能用装饰配额代替设计。'
                                 '用户原文、事实、图片和同页要求保持。'}
