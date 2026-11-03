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
    from .reference_templates import base_id
    tid = base_id(scene.get('templateId', '')) or scene.get('templateId', '')
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


def text_height(obj, size=None):
    """Conservative estimate of the wrapped height of a text object."""
    size = obj['fontSize'] if size is None else size
    width = max(1, obj['w'] - 4) / 1.08
    lines = 0
    for paragraph in obj.get('text', '').split('\n'):
        units = sum(1.05 if ord(c) >= 0x2e80 else .36 if c.isspace() else .68 for c in paragraph)
        lines += max(1, math.ceil(units * size / width))
    return lines * size * max(1.22, obj.get('lineHeight', 1.2)) + 4


def fit_text(obj):
    """Fit supplied words inside a source slot without truncation or rewriting."""
    if obj['type'] != 'text' or not obj.get('text'):
        return
    size = obj['fontSize']
    while size > 10 and text_height(obj, size) > obj['h']:
        size = max(10, size - .5)
    obj['fontSize'] = size


def reflow_overlapping_text(scene):
    """Use a content ledger when source caption slots cannot hold user text."""
    text = [o for o in scene['objects'] if o['type'] == 'text' and o.get('text') and o.get('opacity', 1) > 0]
    def overlap(a, b):
        return (a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and
                a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h'])
    if not any(text_height(o) > o['h'] for o in text) and not any(
            overlap(a, b) for i, a in enumerate(text) for b in text[i + 1:]):
        return
    width, height = scene['width'], scene['height']
    # The source ornaments correspond to the old slots and can obscure the
    # reflowed text; hide only generated visuals, retaining user objects.
    for obj in scene['objects']:
        if is_template_decoration(obj):
            # Opening backgrounds establish the page's actual contrast. Retain
            # their original bytes even when text needs a different arrangement.
            opening_background = obj['id'].startswith('opening.fixed.') and (
                (obj['type'] == 'rect' and obj['w'] >= width * .95 and obj['h'] >= height * .95)
                or (obj['type'] == 'image' and obj['w'] >= width * .65 and obj['h'] >= height * .4))
            if opening_background:
                if obj['type'] == 'rect':
                    scene['background'] = obj['fill']
            else:
                obj['opacity'] = 0
    background = scene.get('background', '#FFFFFF').lstrip('#')
    try:
        light = sum(int(background[i:i+2], 16) * weight for i, weight in ((0, .299), (2, .587), (4, .114))) > 145
    except (ValueError, IndexError):
        light = True
    for obj in text:
        obj['color'] = '#173B53' if light else '#F0F5FA'
    titles = [o for o in text if o.get('binding') == 'title']
    footers = [o for o in text if o['id'].startswith('footer.') and o not in titles]
    body = [o for o in text if o not in titles and o not in footers]
    title_offset = min(.04, max(0, titles[0]['y'] / height * .1)) if titles else 0
    for i, obj in enumerate(titles):
        obj.update(x=width * .05, y=height * (.04 + .14 * i / len(titles)),
                   w=width * .9, h=height * .13 / len(titles), fontSize=min(42, height * .058),
                   align='left', valign='top', lineHeight=1.2)
        fit_text(obj)
    for i, obj in enumerate(footers):
        obj.update(x=width * (.05 + .9 * i / len(footers)), y=height * .94,
                   w=width * .9 / len(footers), h=height * .04, fontSize=12,
                   align='left', valign='top')
        fit_text(obj)
    if not body:
        return
    images = [o for o in scene['objects'] if o['type'] == 'image' and not is_template_decoration(o)]
    left, top = width * .05, height * ((.2 + title_offset) if titles else .05)
    area_w, area_h = width * (.55 if images else .9), height * ((.72 if footers else .75) - title_offset)
    if images:
        for i, obj in enumerate(images):
            obj.update(x=width * .65, y=top + area_h * i / len(images),
                       w=width * .3, h=area_h / len(images) - 4)
    columns = min(3, max(1, math.ceil(len(body) / 6)))
    rows = math.ceil(len(body) / columns)
    cell_w = area_w / columns
    # Allocate each row enough space for its longest block, while retaining order.
    weights = []
    for row in range(rows):
        group = body[row * columns:(row + 1) * columns]
        for obj in group:
            obj.update(w=cell_w - 6, lineHeight=1.25)
        weights.append(max(text_height(obj, 14) for obj in group))
    total = sum(weights)
    y = top
    for row, weight in enumerate(weights):
        row_h = area_h * weight / total
        for col, obj in enumerate(body[row * columns:(row + 1) * columns]):
            obj.update(x=left + col * cell_w, y=y, h=max(1, row_h - 3),
                       fontSize=min(20, height * .028), align='left', valign='top', opacity=1)
            fit_text(obj)
        y += row_h
