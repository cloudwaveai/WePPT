"""Automatic illustrations for finished agent decks.

The planner marks at most MAX_AUTO_IMAGES pages with designBrief.imagePrompt and
the page author reserves an ``image-slot`` rectangle. Only after the deck and
its review are complete are image batches queued, so generated pictures never
race with page repairs. A failed generation leaves the slot as a colour field.
"""
import json

from .deck_design import MAX_AUTO_IMAGES

SLOT_PREFIX = 'image-slot'
MIN_SLOT_AREA = .04


def find_slot(scene):
    area = scene['width'] * scene['height']
    return next((o for o in scene['objects'] if o['type'] == 'rect' and o['id'].startswith(SLOT_PREFIX)
                 and not o.get('rotation') and o['w'] * o['h'] >= area * MIN_SLOT_AREA), None)


def image_prompt(brief, strategy, design, slot):
    ratio = slot['w'] / slot['h']
    shape = '横向' if ratio > 1.2 else '竖向' if ratio < .83 else '近方形'
    palette = '、'.join(design[k] for k in ('background', 'ink', 'accent', 'secondary', 'surface', 'inverse') if design.get(k))
    language = (strategy.get('visualLanguage') or '')[:300]
    return (f'为演示文稿生成一张{shape}配图，画面宽高比约 {ratio:.2f}:1。\n'
            f'画面内容：{brief["imagePrompt"]}\n'
            + (f'整体视觉语言：{language}\n' if language else '')
            + (f'配色参考（十六进制）：{palette}\n' if palette else '')
            + '要求：画面中不出现任何文字、字母、数字、标志、水印或软件界面；不出现可识别的真实人物或品牌；'
              '构图简洁、主体明确，适合作为幻灯片中的大面积配图。')


def queue_auto_images(studio, db, deck):
    """Queue one image batch per marked page; returns the queued page numbers."""
    if deck['execution'] != 'agent' or studio.image_mode() != 'auto':
        return []
    from .image_generation import ImageJobs
    plan = json.loads(deck['plan'])
    strategy, design = plan.get('strategy') or {}, plan.get('design') or {}
    rows = db.execute("SELECT page_index,slide_id FROM studio_deck_pages WHERE deck_id=? AND status='complete' "
                      "ORDER BY page_index", (deck['id'],)).fetchall()
    jobs, queued = ImageJobs(studio), []
    for row in rows:
        brief = plan['pages'][row['page_index']].get('designBrief') or {}
        if len(queued) >= MAX_AUTO_IMAGES or not brief.get('imagePrompt') or not row['slide_id']:
            continue
        current = studio.get_scene(row['slide_id'])
        slot = None if current['stale'] else find_slot(current['scene'])
        if slot is None:
            continue
        jobs.enqueue_batch('auto-image:' + deck['id'][2:18] + ':' + str(row['page_index']), row['slide_id'], [{
            'object_id': slot['id'], 'replace_object_id': slot['id'], 'auto': True, 'slot': dict(slot),
            'prompt': image_prompt(brief, strategy, design, slot),
            **{k: slot[k] for k in ('x', 'y', 'w', 'h')}}])
        queued.append(row['page_index'] + 1)
    if queued:
        studio._message(db, 'assistant', '已为第 ' + '、'.join(map(str, queued)) + ' 页排队自动配图。图片生成后会放入页面预留区域；'
                        '生成失败时保留当前色块版式。可在“执行方式”中关闭自动配图。', deckId=deck['id'])
    return queued


def slots_unchanged(scene, entries):
    """An automatic batch may land on a newer revision only if every reserved slot is
    exactly as queued: any user edit to it (fill, rotation, shadow, size...) wins."""
    if not entries or not all(entry.get('auto') and entry.get('slot') for entry in entries):
        return False
    objects = {o['id']: o for o in scene['objects']}
    return all(objects.get(entry['slot']['id']) == entry['slot'] for entry in entries)


def acknowledge_review(studio, db, slide_id, before, after):
    """Filling a reserved slot is not an edit to the reviewed layout: carry the
    deck review forward only when it was current right before the image landed."""
    deck = studio._deck_row(db)
    row = deck and db.execute('SELECT id,result FROM studio_jobs WHERE project_id=? AND client_message_id=?',
                              (studio.project_id, 'deck-review:' + deck['id'])).fetchone()
    result = json.loads(row['result']) if row and row['result'] else None
    revisions = ((result or {}).get('deckDesignReview') or {}).get('revisions') or {}
    if revisions.get(slide_id) != before:
        return False
    revisions[slide_id] = after
    result['deckDesignReview'].setdefault('autoImageRevisions', {})[slide_id] = after
    db.execute('UPDATE studio_jobs SET result=? WHERE id=?', (json.dumps(result, ensure_ascii=False), row['id']))
    return True
