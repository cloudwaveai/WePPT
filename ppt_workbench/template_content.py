"""Shared content handling when replacing a template's visual layer."""
import base64
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from .core import EngineError


@lru_cache(maxsize=1)
def _template_image_hashes():
    """Payload provenance survives geometry, alt-text and ID edits."""
    data = Path(__file__).with_name('data')
    hashes = set()
    for folder in ('opening-templates', 'design-map-scenes'):
        for path in (data / folder).glob('*.json'):
            entry = json.loads(path.read_text(encoding='utf-8'))
            scene = entry.get('scene', entry)
            if not isinstance(scene, dict):
                continue
            for obj in scene.get('objects', []):
                if obj.get('type') == 'image':
                    hashes.add(_image_hash(obj.get('src', '')))
    hashes.discard(None)
    return frozenset(hashes)


def _image_hash(src):
    try:
        payload = base64.b64decode(src.split(',', 1)[1], validate=False)
    except (ValueError, IndexError):
        return None
    return hashlib.sha256(payload).digest()


def is_template_decoration(obj):
    """Recognize emitted fixed layers without trusting an image ID or alt label.

    A user may replace a fixed image in place, keeping its reserved ID and alt.
    Only a payload from our bundled source assets proves image ownership.
    Bound text is always content, even when its ID uses an emitted prefix.
    """
    if obj.get('binding'):
        return False
    if not obj['id'].startswith(('opening.fixed.', 'design-map.decoration.')):
        return False
    return obj['type'] != 'image' or _image_hash(obj.get('src', '')) in _template_image_hashes()


_LOCAL_VISUAL = re.compile(
    r'^(?:cover\.(?:frame|ornament\..+)|toc\.sidebar\..+|'
    r'(?:kpi|lane|matrix|funnel|grid|vs|proof|pillar|guide|feature|score|bac|land)\..+|'
    r'item\.\d+\.(?:title|number|accent|divider|rule)|step\.\d+\.(?:dot|number)|process\.rule)$'
)


def strip_template_decoration(scene):
    """Retire owned visual layers before any destination classifies content.

    Existing ordinary shapes keep their stable IDs. Local renderers also emit
    visual copies of bound words: retire those copies only when a bound ledger
    exists, keeping arbitrary user text and every user image.
    """
    from . import opening_templates
    tid = scene.get('templateId', '')
    source_fixed = {}
    if opening_templates.has_template(tid):
        source_fixed = {o['id']: o for o in opening_templates.sample_scene(tid)['objects']
                        if not o.get('binding')}
    # Raw bundled previews have source IDs rather than emitted fixed prefixes.
    # Match the actual source object too; an arbitrary user image sharing an ID
    # is retained unless its payload proves it is that source asset.
    from . import design_map
    if not source_fixed and design_map.has_template(tid):
        source_fixed = {o['id']: o for o in design_map.sample_scene(tid)['objects']
                        if o['type'] != 'text'}
    # The local renderer uses a distinctive near-invisible binding ledger.
    local_ledger = any(o.get('binding', '').startswith('keyPoints:') and
                       o.get('opacity', 1) == .02 for o in scene['objects'])
    # Some local layouts render visible bound text beside an unbound heading
    # or number instead of the near-invisible ledger convention.
    local_ledger = local_ledger or (tid in {
        'parallel', 'case-compare', 'toc-sidebar', 'toc-side', 'process',
        'timeline', 'roadmap', 'user-journey', 'cover', 'chapter',
    } and any(o.get('binding', '').startswith('keyPoints:') for o in scene['objects']))
    local_copies = {}
    if local_ledger:
        from .local_renderer import scene_from_slide
        bound = {o['binding']: o['text'] for o in scene['objects'] if o.get('binding')}
        points = sorted((k for k in bound if k.startswith('keyPoints:')),
                        key=lambda k: int(k.split(':')[1]))
        # Reconstruct display copies from the retained content rather than
        # treating a local-looking text ID as proof of template ownership.
        try:
            source = scene_from_slide(dict(id=scene['slideId'], templateId=tid,
                title=bound.get('title', scene.get('title', '')),
                takeaway=bound.get('takeaway', ''),
                keyPoints=scene.get('bindingSeparator', '\n').join(bound[k] for k in points)), {})
            local_copies = {o['id']: o for o in source['objects'] if not o.get('binding')}
        except (EngineError, ValueError, KeyError):
            pass
    retained = []
    for obj in scene['objects']:
        if is_template_decoration(obj):
            continue
        source = source_fixed.get(obj['id'])
        if source and not obj.get('binding') and obj['type'] == source['type']:
            if obj['type'] in {'rect', 'line'} and obj == source:
                continue
            if obj['type'] == 'image' and _image_hash(obj['src']) == _image_hash(source['src']):
                continue
            if obj['type'] == 'text' and obj['text'] == source['text']:
                continue
        local_source = local_copies.get(obj['id'])
        if (local_source and not obj.get('binding') and obj['type'] != 'image'
                and obj['type'] == local_source['type'] and _LOCAL_VISUAL.fullmatch(obj['id'])
                and (obj['type'] != 'text' or obj['text'] == local_source['text'])):
            continue
        if obj['type'] == 'text' and obj.get('binding') and obj.get('opacity') == .02:
            obj['opacity'] = 1
        retained.append(obj)
    scene['objects'] = retained
    return scene


def strip_opening_decoration(scene):
    """Compatibility alias for callers predating shared decoration ownership."""
    return strip_template_decoration(scene)


def fit_text(obj):
    """Fit supplied words inside a source slot without truncation or rewriting."""
    if obj['type'] != 'text' or not obj.get('text'):
        return
    width = max(1, obj['w'] - 4) / 1.08
    def height(size):
        lines = 0
        for paragraph in obj['text'].split('\n'):
            units = sum(1.05 if ord(c) >= 0x2e80 else .36 if c.isspace() else .68 for c in paragraph)
            lines += max(1, math.ceil(units * size / width))
        return lines * size * max(1.22, obj.get('lineHeight', 1.2)) + 4
    size = obj['fontSize']
    while size > 10 and height(size) > obj['h']:
        size = max(10, size - .5)
    obj['fontSize'] = size
