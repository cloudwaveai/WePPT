"""Connect approved POTX references to supported editable layouts.

The original previews are never used as a flattened slide or business evidence.
Mappings are explicit editorial choices, not claims of lossless POTX import.
"""
from functools import lru_cache
import copy
import hashlib
import json
from pathlib import Path

# Match relationships, not merely the number of text blocks.
LAYOUTS = {
    '01-01': 'opening-01-01-cover', '01-02': 'before-after', '01-03': 'photo-story',
    '01-04': 'process', '01-05': 'uneven-images', '01-06': 'photo-story',
    '01-07': 'roadmap', '01-08': 'grid', '01-09': 'multidevice', '01-10': 'ending',
    '02-01': 'opening-05-02-chapter', '02-02': 'focus',
    '03-01': 'compare', '03-02': 'team-two', '03-03': 'grid', '03-04': 'multidevice',
    '03-05': 'case', '03-06': 'case', '03-07': 'process', '03-08': 'photo-story',
    '03-09': 'uneven-images', '03-10': 'case', '03-11': 'grid',
    '03-12': 'chapter-image', '03-13': 'chapter', '03-14': 'ending',
    '04-01': 'opening-04-02-toc', '04-02': 'hub', '04-03': 'chapter',
    '04-04': 'evidence-wall', '04-05': 'photo-story', '04-06': 'case-compare',
    '04-07': 'timeline', '04-08': 'table', '04-09': 'compare', '04-10': 'claim-proof',
    '04-11': 'hub', '04-12': 'swimlane', '04-13': 'process', '04-14': 'parallel-priority',
    '04-15': 'case-compare', '04-16': 'roadmap', '04-17': 'photo-story', '04-18': 'ending',
}
ROLE = {'封面': 'cover', '目录': 'toc', '章节': 'chapter', '结束': 'ending'}


@lru_cache(maxsize=128)
def preview_version(preview):
    root = Path(__file__).parent / 'web/reference-library'
    file = root / preview
    if not file.resolve().is_relative_to(root.resolve()) or not file.is_file():
        raise ValueError('Unknown bundled preview')
    return hashlib.sha256(file.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _references():
    return json.loads((Path(__file__).parent / 'web/reference-library/catalog.json').read_text())['templates']


def base_id(template_id):
    return LAYOUTS.get(template_id.removeprefix('reference-')) if isinstance(template_id, str) and template_id.startswith('reference-') else None


def catalog(base_catalog):
    by_id = {t['id']: t for t in base_catalog}
    result = []
    for source in _references():
        base = by_id[LAYOUTS[source['template_id']]]
        exact_source = base.get('source') == source['source_file'] and base.get('sourcePage') == source['source_page']
        role = ROLE.get(source['category'], 'content')
        item = copy.deepcopy(base)
        # Do not carry unrelated source/example/variant metadata into the reference.
        for key in ('variantOf', 'local', 'opening', 'example', 'legacy', 'sourceLabel'):
            item.pop(key, None)
        item.update(id='reference-' + source['template_id'], title=source['name'], name=source['name'],
            role=role, roles=[role], legacy=False, reference=True,
            description=source['usage'], use=source['usage'], tags=[source['category'], source['name']],
            referenceId=source['template_id'], sourceCategory=source['category'], baseTemplateId=base['id'], baseTemplateName=base['name'],
            source=source['source_file'], sourcePage=source['source_page'],
            sourceLabel='原稿模板 · AI 适配预览',
            adaptation='source-layout' if exact_source else 'related-layout',
            referencePreviewUrl='/reference-library/' + source['preview'] + '?v=' + preview_version(source['preview']),
            capacity=source['content_count'], capacityLabel=source['capacity_label'],
            fixed=source['fixed'], editable=source['editable'], fitRule=source['fit_rule'],
            checks=[source['fit_rule'], '原稿中的示例事实、人物、Logo 和截图不作为新稿内容。'] + base.get('checks', []))
        result.append(item)
    return result


def visual_guidance(template_id, entries):
    card = next((t for t in entries if t['id'] == template_id), None)
    return {
        'selectedReference': {k: card.get(k) for k in ('id', 'title', 'source', 'sourcePage', 'baseTemplateId',
            'adaptation', 'capacity', 'capacityLabel', 'fixed', 'editable', 'fitRule', 'use')} if card else None,
        'principles': [
            '先按内容身份、数量和关系决定表达结构。原稿只提供配色、字体、主次和图形语言的参考；自由设计可改变栏数、分区与布局，不照抄坐标。',
            '沿用当前模板的背景、品牌色、对齐和留白。章节标题一级，结论次一级；正文保持清晰可读。',
            '容量是原稿主要内容单位的提示，不等于当前段落数。不能把流程、并列、案例仅按数量互换。',
            '容量不足时建议更合适的版式，保留全部内容、顺序与同页要求；不得删减或缩成小字来凑版。',
            '不新增重复主题页脚、口号、解释性小字或无事实支撑的三段排比。保留必要条件、单位与状态。',
            '图片提示词以当前原稿的配色、构图、材质和留白区为依据，只生成背景或插画；正文保持可编辑。',
            '真实截图、人物、案例与数据必须来自用户素材。原图字节和比例保持，不能用生成图伪造证据。',
        ],
    }
