"""Bounded draft review with evidence. Model approval is never human acceptance."""
import copy
import hashlib
import json
import re
from pathlib import Path
import time
from .core import EngineError
from .quality import audit_scene, visual_stats, visual_findings, previous_page_findings


def review_verdict(reply):
    """Read the explicit verdict, allowing Markdown and an inline explanation."""
    first = reply.splitlines()[0] if isinstance(reply, str) and reply.splitlines() else ''
    match = re.match(r'^[\s*`_#]*(PASS|REVISE|NEEDS_ATTENTION)(?=$|[\s:：,，。.!！—\-*`_])', first)
    return match[1] if match else 'UNKNOWN'


def vision_available(mode, binding=None):
    if mode == 'codex':
        return True
    if mode == 'api' and binding:
        from .model_profiles import resolve
        return bool(resolve(binding).get('vision'))
    return False


def scene_for_model(scene):
    result = copy.deepcopy(scene)
    for obj in result['objects']:
        if obj['type'] == 'image':
            obj['src'] = 'scene-image:' + scene['slideId'] + '/' + obj['id']
    return result


def connector_glyph(obj):
    return obj.get('type')=='text' and obj.get('text') in {'←','→','↑','↓','↔','↕'}


def semantic_source(scene):
    """Keep original content distinct from the generated candidate's geometry."""
    return {'authority':'original-page-content', 'title':scene.get('title',''),
            'notes':scene.get('notes',''),
            'text':[{'id':o['id'],'text':o['text']} for o in scene.get('objects',[])
                    if o['type']=='text' and not connector_glyph(o)],
            'instruction':'以这些原文和备注判断关系，不把候选页连线当成正确事实；对象存储顺序本身不是流程顺序。'}


def patch_candidate(scene, action, revision):
    from .rendering import patch_scene, validate_scene
    if action.get('slide_id') != scene['slideId'] or action.get('base_scene_revision') != revision:
        raise EngineError('DESIGN_REVIEW_SCOPE','修正的候选页或版本不一致。')
    if action['type']=='scene_patch':
        return patch_scene(scene,action['changes'])
    if action['type']!='scene_objects':
        raise EngineError('DESIGN_REVIEW_SCOPE','候选修改类型无效。')
    # Declarative operations on this isolated candidate, never on the saved page.
    result=copy.deepcopy(scene)
    for op in action['operations']:
        objects=result['objects']
        if op['op']=='add':
            if op['object']['type'] not in ('rect','ellipse','line') and not connector_glyph(op['object']):
                raise EngineError('DESIGN_REVIEW_SCOPE','检查只能新增图形或单个方向箭头，不能新增正文或图片。')
            objects.insert(min(op.get('index',len(objects)),len(objects)),copy.deepcopy(op['object']))
        else:
            found=next((o for o in objects if o['id']==op['objectId']),None)
            if found is None:raise EngineError('DESIGN_REVIEW_SCOPE','修正对象不存在。')
            objects.remove(found)
            if op['op']=='reorder':objects.insert(min(op['index'],len(objects)),found)
            elif op['op']!='delete':raise EngineError('DESIGN_REVIEW_SCOPE','修正操作无效。')
    return validate_scene(result)


def _fit_overflow(scene, measurement, folder, render_candidate, rounds=5):
    """Shrink only the text objects the browser reported as overflowing (font size and
    line height), re-rendering after each step. Words, positions and boxes are unchanged."""
    current = copy.deepcopy(scene)
    for step in range(rounds):
        ids = set(measurement.get('overflow') or [])
        if not ids:
            break
        for obj in current['objects']:
            if obj['id'] in ids and obj['type'] == 'text':
                obj['fontSize'] = max(12, round(obj['fontSize'] * .9, 1))
                obj['lineHeight'] = max(1.1, round(obj.get('lineHeight', 1.35) - .05, 2))
        _, measurement = render_candidate(current, Path(folder) / f'fit-{step + 1}')
    return current, measurement


def review_candidate(scene, folder, context, mode, runner, validate_action, action_contract,
                     *, model_binding=None, initial_render=None, deadline=None):
    from .design_review import render_candidate
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    deadline = deadline or time.monotonic() + 240
    visual = vision_available(mode, model_binding)
    report = {'status':'not_reviewed', 'reviewMode':'image-and-structure' if visual else 'structure-only',
              'humanAccepted':False, 'modelCalls':0, 'passes':[], 'lessons':[],
              'skill':{'name':'diagram-design','selectedType':context.get('diagramDesign',{}).get('selectedType'),
                       'source':context.get('diagramDesign',{}).get('source'),
                       'runtimeReference':context.get('diagramDesign',{}).get('runtimeReference')}}
    current = copy.deepcopy(scene)
    png, measurement = initial_render or render_candidate(current, folder/'initial')
    initial_codes = {f['code'] for f in audit_scene(current)}
    try:
        # At most one repair and one verification of that repair, with no recursive retries.
        for index in range(2):
            findings = audit_scene(current)
            stats = visual_stats(current)
            record = {'pass':index+1, 'measurement':measurement, 'findings':findings,
                      'visualStats':stats, 'visualFindings':visual_findings(stats) + (
                          previous_page_findings(context['previousPageStats'], stats) if context.get('previousPageStats') else []),
                      'previewSHA256':hashlib.sha256(png.read_bytes()).hexdigest()}
            report['passes'].append(record)
            review_context = copy.deepcopy(context)
            if index:
                review_context['previousReview']={'reply':report['passes'][index-1].get('reply',''),
                    'repairAccepted':report['passes'][index-1].get('repairAccepted',False),
                    'instruction':'逐项复核上轮问题是否已解决，同时检查修正有没有造成新问题。'}
            review_context.update(generationTask={'kind':'design_loop_review'},
                previewPurpose='当前候选页的实际渲染截图；请判断表达关系与可读性，而不是复刻参考图坐标。',
                candidateScene=scene_for_model(current), mechanicalFindings=findings, renderMeasurement=measurement,
                visualStats=stats, visualFindings=record['visualFindings'],
                reviewStage='verify-repair' if index else 'critique-and-repair',
                reviewTarget={'slideId':current['slideId'],'sceneRevision':(context.get('scene') or {}).get('sceneRevision',1),'ephemeral':True})
            prompt = ('检查候选页是否完成表达目的：内容关系和连线是否正确、信息是否分组清楚、主次与留白是否合理，'
                      '是否机械照搬参考槽位。遵循 diagramDesign 的绘图方法与当前项目配色。'
                      '若提供 deckReviewInstruction，必须逐项处理该整稿检查意见，并结合 deckStrategy 与 designRoster 判断节奏。'
                      '保留全部原文和原图；语义以 semanticSource 或 currentDeckPage 的原始内容为准，候选连线可能错误，必须允许纠正。'
                      '先核对操作步骤与存储实体、主路径、反馈返回点，再核对版式。不要把操作步骤强行变成中心仓库，不要默认最后一步返回第一步。'
                      '原文或备注已明确的关系直接在候选中修正，不把已知事实变成需要用户再次确认的选择；只有真实内容歧义才标记待确认。'
                      '一次修正处理所有已发现的关系问题，必要时重新布局并删除错误装饰连线；只给错误连线补箭头不算修正。'
                      '再检查视觉张力：页面必须有唯一明确的视觉焦点（大字号关键词或数字、大面积色块、图解或图片）。'
                      'visualStats 与 visualFindings 是按几何计算的客观度量：LOW_SCALE_CONTRAST 表示最大字号与正文之比不足 2.5，'
                      'FLAT_PAGE 表示整页只有文字与细线，SIMILAR_TO_PREVIOUS 表示与上一页（previousPageStats）版式骨架几乎相同。'
                      '出现这些问题或画面平淡时判 REVISE，优先放大焦点文字、'
                      '用 scene_objects 增加承载内容的底板色块或椭圆、改为非对称分区；单调同样是需要修正的问题。'
                      '对照 currentDeckPage.designBrief 的 layoutArchetype 与 focalElement 判断是否兑现了计划。'
                      'id 以 image-slot 开头的矩形是自动配图预留区，保留其位置与尺寸，不在其上放正文。'
                      '不增加示例文字或页脚。'
                      'renderMeasurement.textFlow 给出实际行数与末行；orphanCandidate 是需结合画面判断的孤行候选，'
                      '不是必须修正的规则。重点检查末行单字、窄长段落和正文过小。'
                      '优先加宽正文、重新分配区域或调整阅读路径，保留全部文字；不要用持续缩字凑进原槽位。'
                      '布局合理时返回空 actions；有具体问题时返回一个 scene_patch 修改候选对象，或一个 scene_objects 增删装饰及连线，'
                      '需要同时调整已有对象并新增底板时，可返回一个 scene_patch 加一个 scene_objects（按顺序作用于候选页）。'
                      '优先将箭头绑定在线条：line.startArrow=true 指向(x,y)，用于向左或向上；line.endArrow=true 指向(x+w,y+h)，用于向右或向下。折线仅在抵达目标节点的末段设箭头。'
                      '可删除旧的单个方向符号文字，替换成线条自身的箭头；原有正文不可删改。'
                      '使用 reviewTarget 的 slideId 与 sceneRevision，操作针对 candidateScene，不会直接应用到用户页面。'
                      '只有局部操作无法表达修正时，' + action_contract +
                      'reply 第一行必须是 PASS、REVISE、NEEDS_ATTENTION 之一，其余行用中文简述具体发现。'
                      'PASS 仅表示本次自动检查未发现问题；REVISE 必须附修正动作；NEEDS_ATTENTION 表示仍需用户检查。'
                      + ('本轮仅复核，不再改稿；仍有问题只在 reply 说明，返回空 actions。' if index else ''))
            from .design_direction import DESIGN_RULES
            prompt += '\n' + DESIGN_RULES
            remaining = deadline-time.monotonic()
            if remaining < 5:
                report['status']='budget_exhausted';break
            report['modelCalls'] += 1
            result = runner(mode,prompt,review_context,timeout=min(100,remaining),
                            **({'preview_png':png} if visual else {}))
            record['reply'] = result.get('reply','')
            verdict = review_verdict(record['reply'])
            record['verdict'] = verdict if verdict in {'PASS','REVISE','NEEDS_ATTENTION'} else 'UNKNOWN'
            actions = result.get('actions',[])
            record['proposedActions']=actions
            if not actions:
                report['status']=('reviewed' if index == 0 else 'revised_and_reviewed') if verdict=='PASS' else 'needs_attention'
                break
            if verdict != 'REVISE':
                report['status']='needs_attention';break
            if index == 1:
                report['status']='needs_attention';record['remainingProposal']=True;break
            if len(actions) == 1:
                revised = validate_action(actions[0])
            elif len(actions) == 2 and sorted(a.get('type') for a in actions) == ['scene_objects', 'scene_patch']:
                # A visual repair usually restyles existing objects AND adds a panel.
                # Apply both in order; each validator re-checks words against the original.
                revised = validate_action(actions[1], base=validate_action(actions[0]))
            else:
                raise EngineError('DESIGN_REVIEW_SCOPE','设计检查只能修改当前候选页。')
            next_png, next_measurement = render_candidate(revised, folder/'repair')
            if next_measurement.get('overflow'):
                raise EngineError('DESIGN_OVERFLOW','设计修正仍存在文字溢出，保留原候选。')
            # A correction must not introduce more concrete mechanical errors.
            errors=lambda s:{(f['code'],tuple(f.get('objectIds',[]))) for f in audit_scene(s) if f['severity']=='error'}
            if errors(revised)-errors(current):
                raise EngineError('DESIGN_REVIEW_REGRESSION','设计修正引入新的几何或可读性问题，保留原候选。')
            current,png,measurement=revised,next_png,next_measurement
            record['repairAccepted']=True
        unresolved = [f for f in audit_scene(current) if f['severity']=='error']
        if measurement.get('overflow'):
            raise EngineError('DESIGN_OVERFLOW','候选页仍有文字溢出。',measurement)
        report['unresolvedFindings'] = unresolved
        if unresolved:
            report['status']='needs_attention'
        final_codes={f['code'] for f in audit_scene(current)}
        report['lessons']=[{'kind':'mechanical_correction','code':code,'evidence':'initial-present-final-absent'}
                           for code in sorted(initial_codes-final_codes)]
    except EngineError as exc:
        report.update(status='needs_attention',error={'code':exc.code,'message':exc.message})
        if measurement.get('overflow'):
            # Last resort that never touches words: shrink only the overflowing text
            # and re-measure in the browser; fail the page only if it still overflows.
            fitted, fitted_measurement = _fit_overflow(current, measurement, folder, render_candidate)
            if fitted_measurement.get('overflow'):
                raise EngineError('DESIGN_OVERFLOW', '候选页仍有文字溢出。', fitted_measurement) from exc
            current, measurement = fitted, fitted_measurement
            report['overflowFitted'] = True
    finally:
        report['finalMeasurement']=measurement
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        (folder/'final-scene.json').write_text(json.dumps(current,ensure_ascii=False,indent=2))
    return current, measurement, report


def experiences(studio, relationship):
    """Reuse observed, user-applied outcomes only within this project and relation.

    No model-authored instructions or preference claims. Undone/replaced outcomes
    are excluded by comparing the current page with the exact applied candidate.
    """
    with studio.wb._connection() as db:
        rows=db.execute('SELECT id,slide_id,template_id,body FROM studio_template_proposals '
                        'WHERE project_id=? AND applied_revision IS NOT NULL ORDER BY rowid DESC LIMIT 20',
                        (studio.project_id,)).fetchall()
    items=[]
    for row in rows:
        body=json.loads(row['body']);loop=body.get('designLoop',{})
        if body.get('relationship') != relationship or loop.get('status') not in {'reviewed','revised_and_reviewed'}:
            continue
        try:current=studio.get_scene(row['slide_id'])
        except EngineError:continue
        if current['stale'] or current['scene'] != body['scene']:
            continue
        items.append({'proposalId':row['id'],'templateId':row['template_id'],'relationship':relationship,
                      'evidence':'user-applied-current-scene','reviewMode':loop['reviewMode'],
                      'correctedIssues':loop.get('lessons',[]),
                      'style':{'background':body['scene']['background'],
                               'textSizes':sorted({o['fontSize'] for o in body['scene']['objects'] if o['type']=='text'})}})
        if len(items)==3:break
    return {'scope':'current-project','instruction':'仅作同类内容设计的历史参考；不代表永久偏好，不覆盖本次要求或模板选择。','items':items}
