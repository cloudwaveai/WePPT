"""Reviewed visual references, not executable masters or source business content."""
import copy
import json
from functools import lru_cache
from pathlib import Path

from .core import EngineError

INSTRUCTION = (
    '先讨论并确认文案，再按内容关系和篇幅设计。案例提供视觉语言，不提供必填槽位。'
    '整稿保持同一视觉方向，逐页可改变栏数、图文比和构图；保留原文、原图、顺序与同页要求。'
    '容量不足时提出重排或拆页建议，不擅自删字、缩成小字或拆开同页要求。'
    '排版主库优先用于正文；视觉增强用于封面、章节等关键页，不要求每页加阴影。'
    '案例中的文字、数据、品牌、人物和图片不是本项目素材；预览链接仅用于查看，不可作为scene图片。'
    '优先服从用户配色、上传对标风格和明确选择的固定模板。'
    '截图只能支持视觉观察，不能声称已测得准确透明度、阴影参数或导入原始PPT。'
)


@lru_cache(maxsize=1)
def _library():
    return json.loads((Path(__file__).parent / 'data/curated-designs.json').read_text(encoding='utf-8'))


def catalog():
    return copy.deepcopy(_library()['templates'])


def get(reference_id):
    record = next((r for r in _library()['templates'] if r['id'] == reference_id), None)
    if record is None:
        raise EngineError('INVALID_DESIGN_REFERENCE', '请选择精选案例库中存在的参考编号。')
    return copy.deepcopy(record)


def planning_context():
    """Compact full index lets the planner choose any of the 50 reviewed sets."""
    return {'mode': 'content-led-curated-v1', 'instruction': INSTRUCTION,
            'scope': _library()['audit']['scope'],
            'references': [{k: r[k] for k in ('id', 'name', 'category', 'use', 'reason',
                                              'caution', 'adaptation_proposal', 'preview_url')}
                           for r in _library()['templates']]}


def for_page(page, strategy=None):
    """A persisted deck choice wins; otherwise provide a small advisory shortlist."""
    strategy = strategy or {}
    chosen = strategy.get('curatedReferenceId')
    if chosen:
        records = [get(chosen)]
    else:
        hero = page.get('role') in {'cover', 'chapter', 'ending'}
        words = ' '.join(str(strategy.get(k, '')) for k in ('visualLanguage', 'signatureMotif'))
        words += ' ' + str((page.get('designBrief') or {}).get('visualForm', ''))
        def score(r):
            keywords = {r['category'], *r['name'].replace('·', ' ').split()}
            return (sum(len(k) for k in keywords if k in words),
                    r['use'] == ('视觉增强' if hero else '排版主库'), -r['rank'])
        records = sorted(catalog(), key=score, reverse=True)[:3]
    keys = ('id', 'name', 'category', 'use', 'reason', 'caution', 'adaptation_proposal', 'source_url', 'preview_url')
    return {'instruction': INSTRUCTION, 'selectedReferenceId': chosen,
            'references': [{k: r[k] for k in keys} for r in records],
            'pageRelationship': (page.get('composition') or {}).get('relationship'),
            'roleAdvice': '保持整稿视觉语言，用清楚的信息区承载正文；材质可退到边缘。'
                          if page.get('role') not in {'cover', 'chapter', 'ending'} else
                          '可用主视觉强化空间层次，正文仍保持原生可编辑。'}


def template_contract(studio, payload):
    """New unbound projects use adaptive authoring; explicit/legacy packs retain it."""
    from . import template_packs
    contract = template_packs.contract(studio)
    if not contract or contract.get('selectedPack'):
        return contract
    with studio.wb._connection() as db:
        deck = studio._deck_row(db)
    if deck and any(template_packs.split(p.get('template_id')) for p in json.loads(deck['plan'])['pages']):
        return contract
    return None
