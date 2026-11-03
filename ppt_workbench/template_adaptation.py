"""Reference-led model proposals. Preview is immutable; application is explicit."""
from collections import Counter
import copy
import json
from pathlib import Path
import shutil
import uuid
import time

from .core import EngineError
from .rendering import validate_scene
from .templates import catalog, sample_scene


def initialize(studio):
    with studio.wb._connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS studio_template_proposals (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, slide_id TEXT NOT NULL,
            scene_revision INTEGER NOT NULL, content_revision INTEGER NOT NULL,
            template_id TEXT NOT NULL, body TEXT NOT NULL, applied_revision INTEGER)''')


def source_layout(template_id):
    data=Path(__file__).with_name('data')/'reference-layouts.json'
    return json.loads(data.read_text()).get(template_id) if data.exists() else None


def _content(scene):
    from .design_loop import connector_glyph
    return {o['id']:o for o in scene['objects'] if o['type'] in ('text','image') and not connector_glyph(o)}


def _iou(a, b):
    iw = max(0, min(a['x'] + a['w'], b['x'] + b['w']) - max(a['x'], b['x']))
    ih = max(0, min(a['y'] + a['h'], b['y'] + b['h']) - max(a['y'], b['y']))
    inter = iw * ih
    union = a['w'] * a['h'] + b['w'] * b['h'] - inter
    return inter / union if union > 0 else 1


def layout_unchanged(before, candidate):
    """Mean box IoU over shared content objects; >=0.7 means same skeleton."""
    original, proposed = _content(before), _content(candidate)
    shared = [(_iou(original[oid], proposed[oid])) for oid in original.keys() & proposed.keys()]
    if len(shared) < 2:
        return False
    return sum(shared) / len(shared) >= 0.7


def _layout_iou(before, candidate):
    original, proposed = _content(before), _content(candidate)
    shared = [(_iou(original[oid], proposed[oid])) for oid in original.keys() & proposed.keys()]
    return sum(shared) / len(shared) if shared else 0


def _validate_candidate(studio, before, candidate, template_id):
    candidate=copy.deepcopy(candidate)
    if candidate.get('slideId')!=before['slideId']:
        raise EngineError('SCOPE_VIOLATION','适配方案的目标页面不一致。')
    if (candidate.get('width'),candidate.get('height'))!=(before['width'],before['height']):
        raise EngineError('TEMPLATE_CONTENT_MISMATCH','适配方案不能改变页面尺寸。')
    original=_content(before)
    proposed=_content(candidate)
    if set(original)!=set(proposed):
        raise EngineError('TEMPLATE_CONTENT_MISMATCH','适配方案必须完整保留当前页的文字与图片对象，不得加入模板示例内容。',
                          {'missingIds':sorted(set(original)-set(proposed)), 'unexpectedIds':sorted(set(proposed)-set(original))})
    # Content is server-owned. The model arranges whole content units, not facts.
    for oid,obj in original.items():
        target=proposed[oid]
        if obj['type']!=target['type']:
            raise EngineError('TEMPLATE_CONTENT_MISMATCH','内容对象类型发生变化。')
        if obj['type']=='text':
            if target.get('text')!=obj['text']:
                raise EngineError('TEMPLATE_CONTENT_MISMATCH','适配方案改变或省略了原文；请保留完整文本。',{'objectId':oid})
            minimum=28 if obj.get('binding')=='title' or oid=='title' else min(16,obj.get('fontSize',16))
            if target.get('fontSize',0)<minimum or target.get('opacity',1)<.9:
                raise EngineError('TEMPLATE_CONTENT_MISMATCH','不得缩成小字或隐藏原文来适配模板。',{'objectId':oid})
            target.pop('binding',None)
            if 'binding' in obj:target['binding']=obj['binding']
        else:
            token='scene-image:'+before['slideId']+'/'+oid
            if target.get('src') not in (token,obj['src']):
                raise EngineError('TEMPLATE_CONTENT_MISMATCH','适配方案不能替换原图或复制模板中的示例图片。')
            target.update(src=obj['src'],fit='contain',alt=obj.get('alt',oid))
            if target.get('opacity',1)<.9 or target.get('w',0)<min(24,obj['w']) or target.get('h',0)<min(24,obj['h']):
                raise EngineError('TEMPLATE_CONTENT_MISMATCH','适配方案不能隐藏原有图片。')
    candidate.update(templateId=template_id,title=before.get('title',''))
    if before.get('diagram'):
        candidate['diagram']=copy.deepcopy(before['diagram'])
    return validate_scene(candidate)


def propose(studio, template_id, sid, revision, approach='creative'):
    from .agent_bridge import run_turn
    from .model_profiles import selected, resolve
    from .design_review import render_candidate
    if approach not in ('faithful','content','creative'):
        raise EngineError('INVALID_REQUEST','请选择贴近模板或按内容适配。')
    user_template=None
    if isinstance(template_id,str) and template_id.startswith('user-'):
        from .user_templates import template_card
        card,user_image=template_card(studio,template_id[5:])
        user_template=True
    else:
        card=next((t for t in catalog() if t['id']==template_id),None)
    if not card:raise EngineError('UNKNOWN_TEMPLATE','未找到模板。')
    if not studio.suggestion_lock.acquire(blocking=False):
        raise EngineError('SUGGESTION_BUSY','正在生成预览，请稍后再试。')
    try:
        deadline=time.monotonic()+480
        with studio.wb.atomic():
            current=studio.get_scene(sid)
            studio.wb._revision(current['sceneRevision'],revision)
            if current['stale']:raise EngineError('SCENE_STALE','当前内容与预览不一致，请更新预览后重试。')
            chosen=selected(studio);mode=studio.agent_mode
            profile=resolve(chosen) if chosen else None
            if mode not in ('codex','claude','api'):
                raise EngineError('AGENT_REQUIRED','请先在右上角选择模型，再生成适配预览。')
            full=studio.context({'slideId':sid,'scope':'page'})
            context={k:copy.deepcopy(full[k]) for k in ('project','currentPage','scene','sceneSpec','rules','pageExpression','diagramDesign','visualGuidance','designExperiences')}
        from .semantic_planning import plan_page_expression
        from .diagram_design import guidance_for_page
        from .design_loop import experiences, semantic_source
        content_page=copy.deepcopy(full['currentPage']['slide'])
        content_page.update(title=current['scene'].get('title',''),
            keyPoints=[o['text'] for o in current['scene']['objects'] if o['type']=='text'],
            notes=current['scene'].get('notes',''))
        context['pageExpression']=plan_page_expression(content_page)
        context['diagramDesign']=guidance_for_page(content_page,context['pageExpression'])
        context['designExperiences']=experiences(studio,context['pageExpression']['relationship'])
        context['semanticSource']=semantic_source(current['scene'])
        proposal_id=uuid.uuid4().hex
        folder=studio.wb.project_dir(studio.project_id)/'template-proposals'/proposal_id
        folder.mkdir(parents=True,exist_ok=False)
        visual=mode=='codex' or (mode=='api' and bool(profile and profile.get('vision')))
        if user_template and not visual:
            raise EngineError('TEMPLATE_NEEDS_VISION','这个模板是图片，需要支持看图的模型；请在右上角切换模型后重试。')
        context.update(proposalOnly=True,generationTask={'kind':'template_adaptation'},
            previewPurpose='选中模板的原页设计参考。只模仿设计，不复制示例事实、人物、Logo、数据或截图。',
            templateReference={k:card.get(k) for k in ('id','name','role','use','capacity','fixed','editable','fitRule','source','sourcePage')},
            referenceLayout=None if user_template else source_layout(template_id),adaptationApproach=approach)
        image=None
        if user_template:
            image=folder/'reference.png';shutil.copyfile(user_image,image)
            context['referenceReadMode']='image-only'
        elif card.get('reference'):
            source=Path(__file__).parent/'web/reference-library/previews'/f"{card['referenceId']}.png"
            if visual:
                image=folder/'reference.png';shutil.copyfile(source,image)
        else:
            example=sample_scene(template_id)
            # Layout/color data remain available to non-vision providers.
            context['referenceLayout']={'scene':copy.deepcopy(example),'exampleOnly':True}
            for o in context['referenceLayout']['scene']['objects']:
                if o['type']=='image':o['src']='template-example-image-not-for-reuse'
            if visual:image,_=render_candidate(example,folder/'reference')
        if context.get('referenceReadMode')!='image-only':
            context['referenceReadMode']='image-and-layout' if image else 'layout-only'
        context['requiredContent']=[{k:o[k] for k in ('id','type','text','binding') if k in o} |
            ({'src':'scene-image:'+sid+'/'+o['id'],'alt':o.get('alt','')} if o['type']=='image' else {})
            for o in _content(current['scene']).values()]
        instruction=(
            '为当前页生成完整的新布局预览，只返回一个 scene_replace，使用准确 slide_id 和 currentPage.revision。'
            '这是模板适配，不是原页面元素的平移或整体缩放。以 templateReference、原图和 referenceLayout 为设计依据，'
            '重新组织标题层级、内容分组、图文区域、背景和装饰。先从模板提取配色、字体层级、对比和图形语言，再按实际内容决定构图。'
            'diagramDesign 是实际绘图指导，流程、关系、循环图要表达真实语义，不受四种固定编译器布局限制。'
            '先根据 semanticSource 的原文和备注确定操作步骤、存储实体、主路径和反馈返回点，再选择布局；语义优先于图型参考。不要把操作步骤变成共享仓库，不要为对称补不存在的连接。'
            '自由设计时 referenceLayout 的坐标仅供理解参考；不要把当前内容硬塞进示例的固定栏数或槽位。'
            'requiredContent 中的每个文字和图片对象必须恰好出现一次，id/type/完整文字保持一致；图片使用给定的 scene-image 引用并完整显示。'
            '可以改变布局和文字格式，替换旧装饰；连接方向用线条的startArrow/endArrow布尔属性，不添加漂浮文字箭头。不可加入业务文字或图片，不得复制模板示例业务内容、Logo、网址、人物、截图或数据。'
            '同一页保留全部内容，不截断、不合并删除、不藏到备注、不缩成小字。新装饰不要遮盖正文，内容对象放在其上。'
            '标题明确醒目，结论次一级。不要添加页脚、口号或额外小字。不能满足完整性时说明冲突并返回空 actions。'
            'reply 说明如何把当前内容匹配到模板，以及必要的结构调整。'
            '本次目标是换版式，而不是换颜色：新方案必须改变当前页的构图骨架，内容分组方式、主要区域的位置与比例、阅读路径至少改变其中两项；'
            '只改颜色、字体或微调位置不算完成。服务端会比较内容对象的位置，构图基本未变的方案会被退回重做。'
            + ('尽量贴近原模板：保留分区比例、标题位置、品牌色和图形语言，按语义将原文放入最匹配区域。'
               if approach=='faithful' else '内容优先自由设计：允许改变栏数、节点形态、信息路径、图文比例和连接方式，保留参考中有价值的视觉语言。给出适合本页的独立构图，简要说明借鉴了什么、为什么改变结构。'))
        for attempt in range(3):
            try:
                remaining=deadline-time.monotonic()
                if remaining<5:raise EngineError('DESIGN_BUDGET_EXHAUSTED','本次设计时间已用完，原稿保持不变。')
                plan=run_turn(mode,instruction,context,timeout=min(150,remaining),workdir=studio.wb.project_dir(studio.project_id),
                    **({'model_binding':chosen} if chosen else {}),**({'preview_png':image} if image else {}))
                actions=plan.get('actions',[])
                if not actions:raise EngineError('TEMPLATE_NOT_FIT',plan.get('reply') or '当前内容无法完整适配此模板，请换一个模板。')
                if len(actions)!=1 or actions[0]['type']!='scene_replace' or actions[0]['slide_id']!=sid:
                    raise EngineError('TEMPLATE_CONTENT_MISMATCH','模板适配只能生成当前页的完整方案。')
                studio.wb._revision(actions[0]['base_revision'],current['contentRevision'])
                candidate=_validate_candidate(studio,current['scene'],actions[0]['scene'],'custom' if user_template else template_id)
                if layout_unchanged(current['scene'],candidate):
                    raise EngineError('TEMPLATE_LAYOUT_UNCHANGED','适配方案只改了颜色或细节，构图没有变化。',
                                      {'meanIoU':round(_layout_iou(current['scene'],candidate),3)})
                png,measurement=render_candidate(candidate,folder/f'candidate-{attempt+1}')
                if measurement.get('overflow'):
                    raise EngineError('TEMPLATE_OVERFLOW','适配后的文字超出文本框，需要重新排版。',{'objects':measurement['overflow']})
                break
            except EngineError as exc:
                if exc.code=='TEMPLATE_LAYOUT_UNCHANGED' and attempt==2:
                    raise EngineError('TEMPLATE_LAYOUT_UNCHANGED',
                        '当前页已与该模板构图接近，或模型三次都只换了颜色；可以换一个模板，或改用“借鉴模板，重新构图”。',
                        exc.details) from exc
                if attempt==2 or exc.code not in {'INVALID_AGENT_OUTPUT','INVALID_SCENE','SCENE_OUT_OF_BOUNDS','TEMPLATE_CONTENT_MISMATCH','TEMPLATE_OVERFLOW','REVISION_MISMATCH','TEMPLATE_LAYOUT_UNCHANGED'}:raise
                correction='重新生成完整 scene_replace；保留全部 requiredContent 和当前页范围，修正内容完整性、几何或渲染问题，不改变用户原文。'
                if exc.code=='TEMPLATE_LAYOUT_UNCHANGED':
                    correction='上一版构图与原页几乎相同。请重新组织版面：改变内容分组、主要区域位置和比例或阅读路径中的至少两项，再返回完整 scene_replace。'
                context['revisionCorrection']={'code':exc.code,'message':exc.message,'details':exc.details,
                    'instruction':correction}
        from .design_loop import review_candidate
        def validate_repair(action, base=None):
            if action.get('slide_id')!=sid:
                raise EngineError('DESIGN_REVIEW_SCOPE','检查修正只能重排当前候选页。')
            if action.get('type') in ('scene_patch','scene_objects'):
                from .design_loop import patch_candidate
                repaired=patch_candidate(candidate if base is None else base,action,current['sceneRevision'])
            elif action.get('type')=='scene_replace':
                studio.wb._revision(action.get('base_revision'),current['contentRevision'])
                repaired=action['scene']
            else:
                raise EngineError('DESIGN_REVIEW_SCOPE','检查修正只能重排当前候选页。')
            repaired=_validate_candidate(studio,current['scene'],repaired,'custom' if user_template else template_id)
            if layout_unchanged(current['scene'],repaired):
                raise EngineError('TEMPLATE_LAYOUT_UNCHANGED','修正后的候选构图与原页几乎相同，保留原候选。',
                                  {'meanIoU':round(_layout_iou(current['scene'],repaired),3)})
            return repaired
        def reviewer(review_mode,prompt,review_context,**kwargs):
            return run_turn(review_mode,prompt,review_context,workdir=studio.wb.project_dir(studio.project_id),
                            **({'model_binding':chosen} if chosen else {}),**kwargs)
        candidate,measurement,loop=review_candidate(candidate,folder/'design-loop',context,mode,reviewer,validate_repair,
            '返回一个完整 scene_replace，使用当前页 ID 和 currentPage.revision。',
            model_binding=chosen,initial_render=(png,measurement),deadline=deadline)
        payload={'scene':candidate,'reply':plan['reply'],'approach':approach,'modelBinding':chosen,
                 'designLoop':loop,'relationship':(context.get('pageExpression') or {}).get('relationship','general'),
                 'referenceReadMode':context['referenceReadMode'],'measurement':measurement}
        with studio.wb.atomic() as db:
            latest=studio.get_scene(sid)
            studio.wb._revision(latest['sceneRevision'],revision)
            studio.wb._revision(latest['contentRevision'],current['contentRevision'])
            if latest['stale']:raise EngineError('SCENE_STALE','生成期间页面内容已改变，请重新预览。')
            db.execute('INSERT INTO studio_template_proposals VALUES (?,?,?,?,?,?,?,NULL)',
                (proposal_id,studio.project_id,sid,revision,current['contentRevision'],template_id,json.dumps(payload,ensure_ascii=False)))
        return {'proposalId':proposal_id,'slideId':sid,'sceneRevision':revision,'templateId':template_id,**payload}
    finally:studio.suggestion_lock.release()


def apply(studio, proposal_id):
    from .editor import replace_scene
    with studio.wb.atomic() as db:
        row=db.execute('SELECT * FROM studio_template_proposals WHERE id=? AND project_id=?',(proposal_id,studio.project_id)).fetchone()
        if not row:raise EngineError('PROPOSAL_NOT_FOUND','未找到适配预览，请重新生成。')
        if row['applied_revision'] is not None:return {'alreadyApplied':True,'slideId':row['slide_id'],'sceneRevision':row['applied_revision']}
        current=studio.get_scene(row['slide_id'])
        studio.wb._revision(current['sceneRevision'],row['scene_revision'])
        studio.wb._revision(current['contentRevision'],row['content_revision'])
        saved=json.loads(row['body'])
        result=replace_scene(studio,row['slide_id'],row['scene_revision'],saved['scene'],'应用已确认的模板适配：'+row['template_id'])
        if not str(row['template_id']).startswith('user-'):
            db.execute('INSERT INTO studio_template_preferences VALUES (?,?) ON CONFLICT(project_id) DO UPDATE SET template_id=excluded.template_id',(studio.project_id,row['template_id']))
        db.execute('UPDATE studio_template_proposals SET applied_revision=? WHERE id=?',(result['sceneRevision'],proposal_id))
        studio._message(db,'assistant','已应用你确认的模板适配预览。'+saved['reply'],row['slide_id'],modelBinding=saved.get('modelBinding'))
        return {'slideId':row['slide_id'],'sceneRevision':result['sceneRevision'],'selectedTemplateId':row['template_id']}
