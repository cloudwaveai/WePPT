"""Authored archetype exemplars: few-shot structure for page authoring, never content."""
import copy
import functools
import json
from pathlib import Path

_PATH = Path(__file__).with_name('data') / 'design-exemplars.json'
_BY_RELATIONSHIP = {'process': 'timeline', 'comparison': 'comparison', 'parallel': 'grid-cards',
                    'hub': 'diagram', 'layers': 'ordered-rows', 'summary': 'full-bleed-band',
                    'hero': 'hero-statement', 'evidence': 'split-asymmetric'}


@functools.lru_cache(maxsize=1)
def library():
    return json.loads(_PATH.read_text(encoding='utf-8'))


def resolved_scene(exemplar):
    """The exemplar rendered with its own sample words, exactly as a model page would be."""
    from .page_design import prepare_scene
    sample = exemplar['sample']
    action = {'title': sample['title'], 'scene': copy.deepcopy(exemplar['scene']),
              'composition': {'purpose': exemplar['principle'], 'relationship': 'hero', 'blocks': copy.deepcopy(sample['blocks'])}}
    return prepare_scene(action)


def archetype_for(page, previous=None):
    brief = page.get('designBrief') or {}
    if brief.get('layoutArchetype'):
        return brief['layoutArchetype']
    composition = page.get('composition') or {}
    if page.get('role') in ('cover', 'chapter', 'ending'):
        choice = 'hero-statement'
    elif composition.get('relationship') == 'evidence' and any(b.get('metric') for b in composition.get('blocks', [])):
        choice = 'big-number'
    else:
        choice = _BY_RELATIONSHIP.get(composition.get('relationship'), 'split-asymmetric')
    return 'split-asymmetric' if choice == previous and choice != 'split-asymmetric' else choice


def for_page(page, previous=None):
    """One exemplar matching the page's planned archetype, with the shared instruction."""
    data = library()
    archetype = archetype_for(page, previous)
    exemplar = next((e for e in data['exemplars'] if e['archetype'] == archetype), None)
    if exemplar is None:
        return None
    return {'instruction': data['instruction'], 'colorRoles': data['colorRoles'],
            'archetype': exemplar['archetype'], 'principle': exemplar['principle'],
            'sampleBlockIds': [b['id'] for b in exemplar['sample']['blocks']],
            'scene': copy.deepcopy(exemplar['scene'])}
