"""Bounded whole-deck visual review; repairs remain isolated until atomic adoption."""
import copy
import hashlib
import json
import math
from pathlib import Path

from .core import EngineError, _json, _now
from .design_loop import review_candidate, scene_for_model, semantic_source, patch_candidate, vision_available, review_verdict
from .design_review import render_candidate, _inventory
from .rendering import validate_scene
from .quality import audit_scene, boost_anchors, deck_rhythm

# Model-side failures of a review call: the finished pages stay as they are.
REVIEW_MODEL_FAILURES = {'AGENT_TIMEOUT', 'AGENT_FAILED', 'MODEL_OUTPUT_TRUNCATED', 'INVALID_AGENT_OUTPUT',
                         'MODEL_REQUEST_FAILED', 'MODEL_UNAVAILABLE'}


def queue_review(studio, db, deck):
    """Use one durable job; old decks and local outline mode keep their workflow."""
    import uuid
    if deck['execution'] != 'agent' or not json.loads(deck['plan']).get('strategy'):
        return False
    key = 'deck-review:' + deck['id']
    old = db.execute('SELECT id,status FROM studio_jobs WHERE project_id=? AND client_message_id=?',
                     (studio.project_id, key)).fetchone()
    if old:
        if old['status'] == 'complete':
            return False
        if old['status'] == 'failed':
            db.execute("UPDATE studio_jobs SET status='queued',updated_at=? WHERE id=?", (_now(), old['id']))
        return True
    source = db.execute('SELECT payload FROM studio_jobs WHERE message_id=? ORDER BY created_at LIMIT 1',
                        (deck['source_message_id'],)).fetchone()
    payload = {'kind': 'deck_review', 'deckId': deck['id'], 'message': deck['source_message'],
               'scope': 'deck', 'slideId': None, 'attachments': []}
    if source and json.loads(source['payload']).get('modelBinding'):
        payload['modelBinding'] = json.loads(source['payload'])['modelBinding']
    jid = 'J-' + uuid.uuid4().hex
    db.execute('INSERT INTO studio_jobs VALUES (?,?,?,?,?,?,?,?,?)',
               (jid, studio.project_id, key, deck['source_message_id'], 'queued', _json(payload), None, _now(), _now()))
    studio._bind_round_job(db, studio._deck_round_id(db, deck['id']), jid)
    studio._message(db, 'assistant', '所有页面已生成，正在检查整稿叙事、视觉节奏和重复布局。', deckId=deck['id'])
    return True


def review_state(studio, db, deck):
    row = db.execute('SELECT status,result FROM studio_jobs WHERE project_id=? AND client_message_id=?',
                     (studio.project_id, 'deck-review:' + deck['id'])).fetchone()
    if not row:
        return None
    result = json.loads(row['result']) if row['result'] else {}
    report = result.get('deckDesignReview', {})
    status, summary = report.get('status', row['status']), report.get('summary')
    if report.get('revisions'):
        for sid, revision in report['revisions'].items():
            current = studio.get_scene(sid)
            if current['stale'] or current['sceneRevision'] != revision:
                status, summary = 'stale', '页面已修改，上次整稿设计检查不代表当前版本。'
                break
    return {'jobStatus': row['status'], 'status': status,
            'reviewMode': report.get('reviewMode'), 'summary': summary,
            'repairedPages': report.get('repairedPages', []), 'humanAccepted': False}


def contact_sheets(scenes, folder):
    """Paste native-resolution renders. No image resampling or source recompression."""
    import base64
    from .design_review import render_document
    folder = Path(folder)
    pages, measurements = [], []
    for index, scene in enumerate(scenes):
        png, measure = render_candidate(scene, folder / ('page-%02d' % (index + 1)))
        pages.append(png)
        measurements.append(measure)
    sheets = []
    for start in range(0, len(pages), 4):
        batch = pages[start:start + 4]
        images = ''.join('<img width="1280" height="720" src="data:image/png;base64,'
                         + base64.b64encode(path.read_bytes()).decode('ascii') + '">' for path in batch)
        markup = ('<!doctype html><html><head><meta charset="utf-8"><style>'
                  'html,body{margin:0;background:#E2E8F0}body{display:grid;grid-template-columns:1280px 1280px;'
                  'grid-auto-rows:720px}img{display:block;width:1280px;height:720px}</style></head><body>'
                  + images + '</body></html>')
        path, _ = render_document(markup, folder / ('sheet-%02d' % (start // 4 + 1)), 2560, 1440)
        sheets.append((start, len(batch), path))
    return sheets, measurements


def run_review(studio, job, mode, runner):
    folder = studio.wb.project_dir(studio.project_id) / 'deck-reviews' / job['id']
    folder.mkdir(parents=True, exist_ok=True)
    checkpoint = folder / 'report.json'
    # Interrupted runs preserve spent calls. A restart never silently resets the budget.
    previous = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    with studio.wb._connection() as db:
        deck = studio._deck_row(db)
        rows = db.execute('SELECT slide_id FROM studio_deck_pages WHERE deck_id=? ORDER BY page_index',
                          (deck['id'],)).fetchall()
    plan = json.loads(deck['plan'])
    original = [studio.get_scene(row['slide_id']) for row in rows]
    scenes = [copy.deepcopy(row['scene']) for row in original]
    project_revision = studio.wb.get_project(studio.project_id)['revision']
    visual = vision_available(mode, job['payload'].get('modelBinding'))
    report = {'status': 'running', 'reviewMode': 'image-and-structure' if visual else 'structure-only',
              'humanAccepted': False, 'modelCalls': previous.get('modelCalls', 0),
              'pageRepairCalls': previous.get('pageRepairCalls', len(previous.get('repairs', []))),
              'repairRounds': previous.get('repairRounds', 0),
              'passes': [], 'repairedPages': [], 'summary': ''}
    page_cap = min(6, max(3, math.ceil(len(scenes) / 3)))
    # Initial check, at most two repair rounds (page_cap page repairs total), final check.
    call_limit = 3 * ((len(scenes) + 3) // 4) + 2 * page_cap + 2

    def save():
        temporary = checkpoint.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        temporary.replace(checkpoint)

    def ensure_current():
        with studio.wb._connection() as db:
            current = studio._deck_row(db)
            if current['status'] != 'running' or studio.job(job['id'])['status'] != 'running':
                raise EngineError('DECK_REVIEW_STOPPED', '整稿检查已暂停或取消，候选未应用。')
        studio.wb._revision(studio.wb.get_project(studio.project_id)['revision'], project_revision)
        for old in original:
            now = studio.get_scene(old['scene']['slideId'])
            if now['stale'] or now['contentRevision'] != old['contentRevision'] or now['sceneRevision'] != old['sceneRevision']:
                raise EngineError('STALE_REVISION', '检查期间页面已修改，自动修正未覆盖用户编辑。')

    def call(*args, **kwargs):
        ensure_current()
        if report['modelCalls'] >= call_limit:
            raise EngineError('DECK_REVIEW_BUDGET', '整稿自动检查已达到调用上限。')
        report['modelCalls'] += 1
        save()
        try:
            return runner(*args, workdir=studio.wb.project_dir(studio.project_id), **kwargs)
        except EngineError as exc:
            if exc.code not in REVIEW_MODEL_FAILURES:
                raise
            # The pages are already finished: a failed review call leaves them as they
            # are and is reported, instead of blocking the whole deck.
            report.setdefault('modelFailures', []).append(exc.code)
            return {'reply': f'NEEDS_ATTENTION\n自动检查未完成（{exc.code}），页面保持原样。', 'actions': []}

    report['anchorBoosts'] = boost_anchors(scenes, plan)
    boosted_ids = {b['slideId']: b for b in report['anchorBoosts']}

    def inspect(stage, allow_repairs=True):
        sheets, measurements = contact_sheets(scenes, folder / stage)
        reverted = len(report.get('anchorBoostReverted', []))
        # A boosted anchor that now overflows is restored; later passes re-measure.
        for scene, measure in zip(scenes, measurements):
            boost = boosted_ids.get(scene['slideId'])
            if boost and boost['objectId'] in set(measure.get('overflow') or []):
                obj = next((o for o in scene['objects'] if o['id'] == boost['objectId']), None)
                if obj:
                    obj.update(boost['before'])
                    report.setdefault('anchorBoostReverted', []).append({'slideId': scene['slideId'], 'objectId': boost['objectId']})
        if len(report.get('anchorBoostReverted', [])) > reverted:
            sheets, measurements = contact_sheets(scenes, folder / (stage + '-reverted'))
        rhythm = deck_rhythm(scenes)
        edits, passed = {}, True
        for start, count, png in sheets:
            context = {'generationTask': {'kind': 'deck_review'}, 'reviewStage': stage,
                       'sourceRequest': deck['source_message'], 'deckStrategy': plan['strategy'],
                       'designRoster': plan['pages'],
                       'sheetReadingOrder': '左上、右上、左下、右下；空白格不属于幻灯片。',
                       'pages': [{'index': i + 1, 'scene': scene_for_model(scenes[i]),
                                  'measurement': measurements[i], 'mechanicalFindings': audit_scene(scenes[i]),
                                  'visualStats': rhythm['pages'][i]} for i in range(start, start + count)],
                       'deckRhythmFindings': rhythm['findings'],
                       'anchorBoosts': report['anchorBoosts'],
                       'previousFindings': report['passes'][-1:]}
            result = call(mode,
                '检查整套PPT的叙事与视觉节奏，结合完整设计清单及当前连续页面。核对是否兑现原始需求、'
                '证据边界、层级、可读性及图解关系。指出不服务内容的重复卡片；合理的连续图解可以保留。'
                '连续两页版式骨架相同、整稿缺少深浅或疏密节奏、页面没有视觉焦点时，指出具体页面并给出修改方向；'
                '单调同样是需要修正的问题。deckRhythmFindings 与 pages[].visualStats 是按几何计算的客观度量'
                '（LAYOUT_MONOTONY、LOW_SCALE_CONTRAST、FLAT_PAGE、NO_TONAL_RHYTHM、FEW_ANCHORS），请结合截图判断；'
                'FEW_ANCHORS 时，系统已先自动放大部分短序号或原文数字（见 anchorBoosts）；仍不足时，把已有的序号、kicker、原文数字或核心关键词放大到 72px 以上作为焦点，不新增文字；'
                '原稿缺少的事实已用“待补充”等方式明确标注时，属于正常的内容缺口，不作为 NEEDS_ATTENTION 的理由，可在 reply 中提醒；只有视觉、可读性、层级、版式节奏或证据越界的问题才判 REVISE 或 NEEDS_ATTENTION。'
                '对照 designRoster 中每页 layoutArchetype、focalElement、backgroundTreatment 核对计划是否兑现。'
                'id 以 image-slot 开头的矩形是自动配图预留区，不要建议删除。只建议当前图片内具体问题页。'
                'measurement.textFlow 包含实际断行信息，核对孤行候选、过窄正文和字号层级；'
                '优先改变区域分配解决容量问题，不通过删字或整体缩字维持等宽栏。'
                'reply 第一行必须是 PASS、REVISE 或 NEEDS_ATTENTION。'
                '需要修正时返回一个 deck_feedback，edits 中给出 slide_id 与具体 instruction，保留全部文字和图片；'
                '最多三个问题页；内容事实存在歧义时说明问题，不擅自补写。'
                + ('本轮仅复核，必须 actions=[]，仍有问题写 NEEDS_ATTENTION。' if not allow_repairs else
                   '先核对每条连线是否有原始内容依据，再检查可读性、分组和视觉节奏。不要只处理最显眼的装饰问题。'),
                context, timeout=180, **({"preview_png": png} if visual else {}))
            verdict = review_verdict(result.get('reply', ''))
            actions = result.get('actions', [])
            allowed = {s['slideId'] for s in scenes}
            rejected = []
            if actions:
                # An out-of-scope suggestion is never applied; it no longer blocks a
                # finished deck. It is recorded and the review cannot pass.
                if not allow_repairs or len(actions) != 1 or actions[0]['type'] != 'deck_feedback' or verdict != 'REVISE':
                    rejected = [{'reason': 'invalid-action', 'actionTypes': [a.get('type') for a in actions]}]
                else:
                    for edit in actions[0]['edits']:
                        if edit['slide_id'] not in allowed or edit.get('object_id'):
                            rejected.append({'reason': 'out-of-scope', 'slideId': edit['slide_id']})
                        else:
                            edits[edit['slide_id']] = edit['instruction']
            passed = passed and verdict == 'PASS' and not actions
            report['passes'].append({'stage': stage, 'pages': list(range(start + 1, start + count + 1)),
                'reply': result.get('reply', ''), 'verdict': verdict, 'rejectedSuggestions': rejected,
                'deckRhythmFindings': rhythm['findings'],
                'previewSHA256': hashlib.sha256(png.read_bytes()).hexdigest(), 'measurements': measurements[start:start + count]})
            if (any(m.get('overflow') for m in measurements[start:start + count])
                    or any(f['severity'] == 'error' for scene in scenes[start:start + count] for f in audit_scene(scene))):
                passed = False
            save()
        return edits, passed

    try:
        remaining_repairs = report['pageRepairCalls'] < page_cap and report['repairRounds'] < 2
        edits, passed = inspect('initial', allow_repairs=remaining_repairs)
        repairs_used = report['pageRepairCalls']
        for repair_round in range(report['repairRounds'], 2):
            budget = page_cap - repairs_used
            if len(edits) > budget:
                # Repair what the budget allows, in page order; keep the rest as
                # recorded findings instead of discarding every repair.
                ordered = list(edits)
                report.setdefault('deferredEdits', []).extend(
                    {'slideId': sid, 'instruction': edits[sid]} for sid in ordered[budget:])
                edits = {sid: edits[sid] for sid in ordered[:budget]}
                report['summary'] = f'问题页超过 {page_cap} 次页面修正上限：已按页序修正可修的页面，其余检查意见保留待处理。'
                passed = False
            if not edits:
                break
            report['repairRounds'] = repair_round + 1
            save()
            for sid, instruction in edits.items():
                index = next(i for i, scene in enumerate(scenes) if scene['slideId'] == sid)
                source = scenes[index]
                def validate(action, source=source, index=index, base=None):
                    if action['type'] in {'scene_patch', 'scene_objects'}:
                        candidate = patch_candidate(source if base is None else base, action, original[index]['sceneRevision'])
                    elif (action['type'] == 'scene_replace' and action['slide_id'] == source['slideId']
                          and action['base_revision'] == original[index]['contentRevision']):
                        candidate = copy.deepcopy(action['scene'])
                        for obj in candidate.get('objects', []):
                            old = next((o for o in source['objects'] if o['id'] == obj.get('id')), None)
                            if old and old['type'] == 'image' and obj.get('src') == 'scene-image:' + sid + '/' + old['id']:
                                obj['src'] = old['src']
                        candidate = validate_scene(candidate)
                    else:
                        raise EngineError('DECK_REVIEW_SCOPE', '修正只能改变指定候选页。')
                    if (candidate['slideId'] != source['slideId'] or _inventory(candidate) != _inventory(source)
                            or candidate.get('diagram') != source.get('diagram')
                            or candidate.get('notes') != source.get('notes')
                            or [(o.get('binding'), o.get('text')) for o in candidate['objects'] if o.get('binding') == 'title']
                            != [(o.get('binding'), o.get('text')) for o in source['objects'] if o.get('binding') == 'title']):
                        raise EngineError('DECK_REVIEW_SCOPE', '修正不能改写原文、原图或图解语义。')
                    return candidate
                context = {'deckStrategy': plan['strategy'], 'designRoster': plan['pages'],
                           'currentDeckPage': plan['pages'][index], 'semanticSource': semantic_source(source),
                           'scene': {'sceneRevision': original[index]['sceneRevision']},
                           'deckReviewInstruction': instruction,
                           'diagramDesign': __import__('ppt_workbench.diagram_design', fromlist=['guidance_for_page']).guidance_for_page(plan['pages'][index])}
                repairs_used += 1
                report['pageRepairCalls'] = repairs_used
                save()
                revised, _, detail = review_candidate(source, folder / ('repair-%d-' % (repair_round + 1) + sid), context, mode, call, validate,
                    '返回 scene_replace，slide_id 为当前页，base_revision=' + str(original[index]['contentRevision']) + '。',
                    model_binding=job['payload'].get('modelBinding'))
                report.setdefault('repairs', []).append({'slideId': sid, 'instruction': instruction, 'review': detail})
                scenes[index] = revised
            more = repair_round == 0 and repairs_used < page_cap
            edits, passed = inspect('verify' if more else 'final', allow_repairs=more)
        ensure_current()
        report['status'] = 'reviewed' if passed else 'needs_attention'
        report['summary'] = report['summary'] or ('整稿自动检查完成。' if passed else '整稿已生成，自动检查仍有待确认问题。')
        if not visual:
            report['summary'] += '当前模型仅检查结构，未读取页面图片。'
        # Commit all repairs together, guarded by every original revision.
        with studio.wb.atomic() as db:
            ensure_current()
            with studio._operation(job['id'], generation=True, automatic=True, description='整稿自动设计修正'):
                for index, scene in enumerate(scenes):
                    if scene != original[index]['scene']:
                        studio.put_scene(scene['slideId'], original[index]['contentRevision'], scene,
                                         '整稿检查后的局部修正', preserve_layout=True)
                        report['repairedPages'].append(scene['slideId'])
            report['revisions'] = {scene['slideId']: studio.get_scene(scene['slideId'])['sceneRevision'] for scene in scenes}
            stage = report['passes'][-1]['stage']
            details = '\n\n'.join('第 ' + '、'.join(map(str, p['pages'])) + ' 页：\n' + p['reply']
                                  for p in report['passes'] if p['stage'] == stage)
            reply = report['summary'] + ('\n\n' + details if details else '')
            result = {'reply': reply, 'deckDesignReview': report, 'changes': report['repairedPages']}
            db.execute("UPDATE studio_jobs SET status='complete',result=?,updated_at=? WHERE id=?", (_json(result), _now(), job['id']))
            db.execute("UPDATE studio_decks SET status='complete',initial_completed_at=COALESCE(initial_completed_at,?),last_error=NULL,updated_at=? WHERE id=?",
                       (_now(), _now(), deck['id']))
            studio._message(db, 'assistant', reply, jobId=job['id'], deckId=deck['id'])
            from .auto_images import queue_auto_images
            try:
                report['autoImagePages'] = queue_auto_images(studio, db, deck)
            except (EngineError, ValueError) as exc:
                report['autoImageError'] = getattr(exc, 'code', 'IMAGE_QUEUE_FAILED')
            from .logo import apply_to_deck
            try:
                report['logoPages'] = apply_to_deck(studio, db, deck)
            except (EngineError, ValueError) as exc:
                report['logoError'] = getattr(exc, 'code', 'LOGO_APPLY_FAILED')
            studio._touch(db)
            round_id = studio._round_for_job(db, job['id'])
        studio._finish_round(round_id)
    except EngineError as exc:
        report.update(status='failed', error=exc.to_dict())
        raise
    finally:
        save()
