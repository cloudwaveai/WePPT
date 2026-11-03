"""Read-only, zero-model-call search of the user's original template library."""
import re
from .core import EngineError
from .templates import catalog
from .semantic_planning import plan_page_expression, template_score

RELATIONS = {'compare': '并列与对比', 'cause': '问题与解决思路', 'process': '流程与计划',
             'evidence': '案例与证据', 'data': '数据与指标', 'structure': '架构与关系',
             'product': '产品说明', 'parallel': '多项说明', 'general': '观点说明',
             'people': '人物与团队', 'gallery': '照片与标识'}
CATEGORIES = {'compare': 'compare', 'cause': 'argument', 'process': 'process',
              'evidence': 'case', 'data': 'data', 'structure': 'structure',
              'product': 'product', 'parallel': 'compare', 'general': 'argument',
              'people': 'people', 'gallery': 'gallery'}


def content_plan(scene, page, instruction):
    texts = [o['text'] for o in scene['objects'] if o['type'] == 'text' and o.get('text', '').strip()]
    title = next((o['text'] for o in scene['objects'] if o['type'] == 'text' and o.get('binding') == 'title'), scene.get('title', ''))
    images = sum(o['type'] == 'image' for o in scene['objects'])
    content = {'title': title, 'keyPoints': [t for t in texts if t != title],
               'userIntent': page.get('userIntent', ''), 'assets': [{'type': 'image'}] * images}
    plan = plan_page_expression(content)
    units = {o['binding'].split(':')[1] for o in scene['objects']
             if o['type'] == 'text' and isinstance(o.get('binding'), str)
             and re.match(r'^keyPoints:\d+$', o['binding'])}
    plan['content']['unitCount'] = len(units) if units else None
    # Explicit expression preferences outrank incidental vocabulary in body copy.
    intent = plan_page_expression(text=instruction)
    if instruction and intent['relationship'] != 'general':
        plan['relationship'] = intent['relationship']
    source = instruction if instruction else '\n'.join(texts)
    if re.search(r'痛点|问题|挑战', source) and re.search(r'解决|方案|承接|应对', source):
        plan['relationship'] = 'compare'
    if re.search(r'人物|履历|成员|团队介绍', source):
        plan['relationship'] = 'people'
    if re.search(r'照片|相册|伙伴|标识墙|logo墙', source, re.I):
        plan['relationship'] = 'gallery'
    return plan


def match(studio, slide_id, revision, instruction=''):
    if not isinstance(slide_id, str) or not slide_id or type(revision) is not int:
        raise EngineError('INVALID_REQUEST', '请选择当前页面后找模板。')
    if not isinstance(instruction, str) or len(instruction) > 4000:
        raise EngineError('INVALID_REQUEST', '模板要求须为不超过 4000 字的文字。')
    current = studio.get_scene(slide_id)
    studio.wb._revision(current['sceneRevision'], revision)
    if current['stale']:
        raise EngineError('SCENE_STALE', '请先更新当前页，再匹配模板。')
    page = studio.wb.get_slide(studio.project_id, slide_id)['slide']
    role = page.get('role', 'content')
    if role not in {'cover', 'toc', 'chapter', 'ending'}:
        role = 'content'
    plan = content_plan(current['scene'], page, instruction)
    relation = plan['relationship']
    category = CATEGORIES[relation]
    candidates = [t for t in catalog() if t.get('reference') and role in t.get('roles', [])]
    def score(card):
        value = template_score(dict(card, id=card.get('baseTemplateId', card['id'])), plan)
        if card['browseCategory'] == category:
            value += 40
        units = plan['content']['unitCount']
        if relation == 'process' and units is not None:
            value += 24 if card.get('capacity') == units else -min(30, abs(card.get('capacity', 0) - units) * 8)
        if relation == 'process' and card['baseTemplateId'] == 'swimlane' and not re.search(r'角色|协作|泳道', instruction):
            value -= 10
        # Distinct original designs are retained, never deduplicated by their old generic mapping.
        if relation in {'parallel', 'general', 'product'} and plan['assets']['imageCount'] == 0:
            if card['browseCategory'] in {'argument', 'compare'}:
                value += 25
            if card['browseCategory'] in {'product', 'gallery', 'case', 'people'}:
                value -= 35
        if instruction:
            value += sum(3 for term in re.findall(r'[A-Za-z]+|[\u4e00-\u9fff]{2}', instruction)
                         if term.lower() in (card['name'] + card['use']).lower())
        return value
    ranked = sorted(candidates, key=score, reverse=True)[:3]
    for card in ranked:
        direct = card['browseCategory'] == category
        card['recommendationReason'] = ('适合表达' + RELATIONS[relation] + '。' if direct else '可作为另一种内容组织方式。') + card['use']
        card['adaptationNote'] = card.get('fitRule', '')
    latest = studio.get_scene(slide_id)
    studio.wb._revision(latest['sceneRevision'], revision)
    if latest['stale'] or latest['contentRevision'] != current['contentRevision']:
        raise EngineError('SCENE_STALE', '页面内容已变化，请重新匹配。')
    return {'slideId': slide_id, 'sceneRevision': revision, 'recommendationEngine': 'local-library',
            'modelCalls': 0, 'expressionPlan': plan, 'recommendations': ranked,
            'summary': '按当前页文字、表达关系和图片情况，从原稿模板库筛选。先选模板，再生成适配预览。'}
