"""diagram-design semantic layouts compiled to editable WePPT scene primitives.

Adapted from Cathryn Lavery's MIT licensed skill; pinned originals and license
live in data/diagram-design. Model supplies content; this module supplies geometry.
"""
from __future__ import annotations
import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from .core import EngineError

ROOT = Path(__file__).parent / 'data/diagram-design'
KINDS = {'process': (2, 6), 'layers': (2, 6), 'hub': (3, 5), 'comparison': (2, 6)}
REFERENCES = {'process': 'type-process.md', 'layers': 'type-layers.md',
              'hub': 'type-architecture.md', 'comparison': 'type-architecture-delta.md'}


def validate_spec(value):
    def bad(message):
        raise EngineError('INVALID_DIAGRAM', message)
    if not isinstance(value, dict) or set(value) - {'kind','nodes','edges','purpose','accent'}:
        bad('图解需要 kind、nodes、edges、purpose，可选 accent。')
    kind, nodes, edges = value.get('kind'), value.get('nodes'), value.get('edges', [])
    if not isinstance(kind, str) or kind not in KINDS:
        bad('当前原生图解支持 process、layers、hub、comparison。')
    low, high = KINDS[kind]
    if not isinstance(nodes, list) or not low <= len(nodes) <= high:
        bad(f'{kind} 需要 {low}–{high} 个完整节点；不会自动删减内容。')
    ids = set()
    for n in nodes:
        if not isinstance(n, dict) or set(n) - {'id','label','detail','focus'}:
            bad('节点字段无效。')
        if not isinstance(n.get('id'), str) or not re.fullmatch(r'[a-zA-Z][A-Za-z0-9_-]{0,30}', n['id']) or n['id'] in ids:
            bad('节点 ID 必须唯一。')
        ids.add(n['id'])
        for key, limit in [('label',24),('detail',100)]:
            text=n.get(key,'')
            if not isinstance(text,str) or (key=='label' and not text.strip()) or len(text)>limit:
                bad('节点文字超出可读容量；请选择其他表达方式，不能截断原文。')
        if type(n.get('focus',False)) is not bool: bad('focus 必须为布尔值。')
    if sum(n.get('focus',False) for n in nodes)>2: bad('图解最多突出两个焦点。')
    if not isinstance(value.get('purpose',''),str) or len(value.get('purpose',''))>500:
        bad('图解目的字段无效。')
    if 'accent' in value and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(value['accent'])):
        bad('图解强调色必须为 #RRGGBB。')
    if not isinstance(edges,list) or len(edges)>10: bad('图解连线最多 10 条。')
    positions={n['id']:i for i,n in enumerate(nodes)}
    seen=set()
    for e in edges:
        if not isinstance(e,dict) or set(e)-{'from','to','label'} or not isinstance(e.get('from'),str) or not isinstance(e.get('to'),str) or e.get('from') not in ids or e.get('to') not in ids or e['from']==e['to']:
            bad('每条连线必须引用两个已存在的不同节点。')
        a,b=positions[e['from']],positions[e['to']]
        if (a,b) in seen: bad('不能重复绘制同一条连线。')
        seen.add((a,b))
        if kind=='comparison' or (kind in {'process','layers'} and abs(a-b)!=1) or (kind=='hub' and 0 not in (a,b)):
            bad('此连线不适合所选原生布局，请换图型；不会隐去关系。')
        if not isinstance(e.get('label',''),str) or len(e.get('label',''))>12: bad('连线说明最多 12 字。')
    if kind=='comparison' and len(nodes)%2: bad('对照图需要两组数量相同的节点。')
    return copy.deepcopy(value)


@lru_cache(maxsize=8)
def guidance(kind='process'):
    selected = kind if kind in {*KINDS, 'loop', 'cycle', 'architecture'} else 'process'
    filename = {'loop':'type-loop.md', 'architecture':'type-architecture.md'}.get(selected, REFERENCES.get(selected))
    reference = ROOT/'adaptations/feedback-flow.md' if selected == 'cycle' else ROOT/'references'/filename
    return {'engine':'diagram-design','source':json.loads((ROOT/'SOURCE.json').read_text()),
            'selectedType':selected, 'supportedKinds':list(KINDS),
            'selectedTypeReference':reference.read_text(),
            'runtimeReference':str(reference.relative_to(ROOT)),
            'authoringMode':'content-led-editable-scene',
            'rules': ['先确定语义关系，再选择图型；图型参考描述方法，不规定页面坐标和固定槽位。',
                      '正文与备注中的真实关系优先于图型建议。先区分操作步骤与存储实体，列清主路径和反馈返回点；不因模板槽位创造中心仓库或连接。',
                      '优先用完整 scene 自行编排节点、分区与正交连线，保持可编辑；简单且匹配时才选固定 diagram 编译器。',
                      '循环可以用正交折线表现反馈路径；复杂拓扑用完整 scene，不受固定编译器四类布局限制。',
                      '沿用项目或选中参考的配色与字体，不照搬 skill 默认英文标签、珊瑚色或画布规格。',
                      '节点面积体现主次，避免所有节点等大；只强调一两个焦点。连接必须有内容依据。',
                      '连线不得穿过无关节点；标签与线条分离；保留完整原文和原始图片，不删节点、不擅自拆页。',
                      '输出仅为 scene 支持的原生对象，不输出 SVG/HTML。只在用户否定图解或明确要求后使用生图。']}


def guidance_for_page(page=None, expression=None):
    page=page or {};expression=expression or {}
    relation=(page.get('composition') or {}).get('relationship') or expression.get('relationship','process')
    text=' '.join(str(page.get(k) or '') for k in ('title','takeaway','userIntent','user_intent','composition','keyPoints','key_points','notes'))
    if re.search(r'循环|闭环|反馈回路|反馈.{0,24}返回|飞轮|再次.*取用|loop|cycle',text,re.I):
        # A cycle is not evidence of a shared state hub. The upstream Loop
        # reference mandates one, so use it only when content names shared state.
        kind='loop' if re.search(r'共享(?:存储|记忆库|状态|记录)|shared\s+(?:memory|state|store|record)',text,re.I) else 'cycle'
    else:
        kind={'structure':'architecture','hub':'architecture','compare':'comparison','comparison':'comparison','layers':'layers'}.get(relation,'process')
    return guidance(kind)


def build_scene(slide, spec, template_id=None):
    from .rendering import validate_scene, _text_obj, _rect, _line
    spec=validate_spec(spec)
    nodes=spec['nodes'];n=len(nodes);kind=spec['kind']
    ink='#142D50';muted='#5E7088';accent=spec.get('accent','#C49A2B');blue='#2460C4';paper='#FFFFFF'
    boxes=[]
    if kind=='process':
        cols=min(n,3); rows=(n+cols-1)//cols
        w=336;h=184 if rows>1 else 220
        for i in range(n):
            row,col=divmod(i,cols)
            if row%2: col=cols-1-col
            boxes.append((72+col*400,224+row*244,w,h))
    elif kind=='layers':
        h=min(100,432/n-12)
        boxes=[(152,200+i*(h+16),976,h) for i in range(n)]
    elif kind=='hub':
        boxes=[(476,312,328,176)]
        slots=[(64,188,300,176),(916,188,300,176),(64,492,300,176),(916,492,300,176)]
        boxes+=slots[:n-1]
    else:
        cols=n//2;w=(1136-(cols-1)*48)/cols
        boxes=[(72+(i%cols)*(w+48),212+(i//cols)*244,w,188) for i in range(n)]
    objects=[_text_obj('title',slide['title'],64,44,1152,76,42,ink,True,binding='title')]
    takeaway=slide.get('takeaway','')
    if takeaway:objects.append(_text_obj('takeaway',takeaway,64,158,1152,44,23,muted,binding='takeaway'))
    diagram=[]
    def line(oid,a,b):
        x,y=min(a[0],b[0]),min(a[1],b[1]);w,h=abs(a[0]-b[0]),abs(a[1]-b[1])
        if w or h:diagram.append(_line(oid,x,y,w,h,blue,2))
    positions={node['id']:i for i,node in enumerate(nodes)}
    for i,e in enumerate(spec.get('edges',[])):
        a,b=positions[e['from']],positions[e['to']];x,y,w,h=boxes[a];xx,yy,ww,hh=boxes[b]
        if kind=='hub':
            right=xx>x;start=(x+w if right else x,y+h/2);end=(xx if right else xx+ww,yy+hh/2)
            mid=(start[0]+end[0])/2;points=[start,(mid,start[1]),(mid,end[1]),end]
        elif abs(yy-y)<1:
            right=xx>x;start=(x+w if right else x,y+h/2);end=(xx if right else xx+ww,yy+hh/2);points=[start,end]
        else:
            down=yy>y;start=(x+w/2,y+h if down else y);end=(xx+ww/2,yy if down else yy+hh)
            points=[start,end] if start[0]==end[0] else [start,(start[0],(start[1]+end[1])/2),(end[0],(start[1]+end[1])/2),end]
        for j in range(len(points)-1):line(f'dg-edge-{i}-{j}',points[j],points[j+1])
        end=points[-1];prev=points[-2];horizontal=end[1]==prev[1]
        arrow=('→' if end[0]>prev[0] else '←') if horizontal else ('↓' if end[1]>prev[1] else '↑')
        ax=end[0]-28 if arrow=='→' else end[0] if arrow=='←' else end[0]-14
        ay=end[1]-17 if horizontal else end[1]-32 if arrow=='↓' else end[1]
        diagram.append(_text_obj(f'dg-arrow-{i}',arrow,ax,ay,28,34,28,blue,align='center',lineHeight=1))
        label=e.get('label','')
        if label:
            mx=(points[0][0]+points[1][0])/2;my=(points[0][1]+points[1][1])/2
            if horizontal: lx,ly=mx-76,my-54
            else:lx,ly=mx+14,my-18
            # Labels have an opaque separate field, never sit on a stroke.
            diagram.append(_rect(f'dg-mask-{i}',lx,ly,152,32,paper))
            diagram.append(_text_obj(f'dg-label-{i}',label,lx,ly,152,32,18,muted,align='center'))
    for i,(node,box) in enumerate(zip(nodes,boxes)):
        x,y,w,h=box;focus=node.get('focus',False)
        fill='#142D50' if focus else '#F3F6FA'
        diagram.append(_rect('dg-box-'+node['id'],x,y,w,h,fill,radius=8,stroke=accent if focus else '#D7E0EA',strokeWidth=2 if focus else 1))
        label_color='#FFFFFF' if focus else ink;detail_color='#E0E7EF' if focus else muted
        if kind=='layers':
            diagram.append(_text_obj('dg-title-'+node['id'],node['label'],x+24,y+14,300,h-24,24,label_color,True))
            diagram.append(_text_obj('dg-detail-'+node['id'],node.get('detail',''),x+344,y+14,w-372,h-24,20,detail_color))
        else:
            diagram.append(_text_obj('dg-title-'+node['id'],node['label'],x+24,y+20,w-48,68,27,label_color,True,lineHeight=1.15))
            if node.get('detail'):diagram.append(_text_obj('dg-detail-'+node['id'],node['detail'],x+24,y+86,w-48,h-96,20,detail_color,lineHeight=1.25))
    # Reject dense input before publishing; never clip or shorten supplied text.
    import unicodedata
    for obj in diagram:
        if obj['type'] != 'text': continue
        lines = 1; used = 0
        for char in obj['text']:
            if char == '\n': lines += 1; used = 0; continue
            width = obj['fontSize'] * (1 if unicodedata.east_asian_width(char) in 'WF' else .65)
            if used + width > obj['w']: lines += 1; used = 0
            used += width
        if lines * obj['fontSize'] * obj.get('lineHeight', 1.25) > obj['h'] + 2:
            raise EngineError('INVALID_DIAGRAM', '图解文字超出所选布局容量，请使用空间更大的普通原生场景，保留完整内容。')
    objects+=diagram
    scene={'schema':'ppt-scene','schemaVersion':1,'slideId':slide['id'],'width':1280,'height':720,'background':paper,
           'title':slide['title'],'objects':objects,'notes':spec.get('purpose',''),
           'templateId':template_id or 'clean','diagram':{'engine':'diagram-design','kind':kind,
           'objectIds':[o['id'] for o in diagram], 'source':spec}}
    return validate_scene(scene)


def validate_metadata(value, objects):
    if not isinstance(value,dict) or set(value)!={'engine','kind','objectIds','source'} or value['engine']!='diagram-design':
        raise EngineError('INVALID_DIAGRAM','图解元数据无效。')
    spec=validate_spec(value['source'])
    ids=value['objectIds'];by_id={o['id']:o for o in objects}
    if (value['kind']!=spec['kind'] or not isinstance(ids,list) or not ids or
        any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)) or
        any(i not in by_id or not i.startswith('dg-') or by_id[i]['type']=='image' or by_id[i].get('binding') for i in ids)):
        raise EngineError('INVALID_DIAGRAM','图解对象集合已变化，请先更新图解。')


def fallback(studio, slide_id, revision, request_id, feedback='图解效果不满意，请换成 AI 图解。'):
    from .image_generation import ImageJobs
    from .core import _json
    if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request_id):
        raise EngineError('INVALID_REQUEST','请求标识无效。')
    with studio.wb.atomic() as db:
        batch_id=request_id
        existing=db.execute('SELECT id,slide_id FROM image_generation_batches WHERE project_id=? AND id=?',(studio.project_id,batch_id)).fetchone()
        if existing:
            if existing['slide_id']!=slide_id:raise EngineError('INVALID_REQUEST','请求标识已用于其他页面。')
            return {'jobId':batch_id,'deduplicated':True}
        current=studio.get_scene(slide_id);studio.wb._revision(current['sceneRevision'],revision)
        if current['stale']:raise EngineError('SCENE_STALE','页面已变化，请刷新。')
        scene=current['scene'];meta=scene.get('diagram')
        if not meta:raise EngineError('DIAGRAM_NOT_FOUND','当前页没有可替换的原生图解。')
        validate_metadata(meta,scene['objects'])
        selected=[o for o in scene['objects'] if o['id'] in meta['objectIds']]
        x=min(o['x'] for o in selected);y=min(o['y'] for o in selected)
        w=max(o['x']+o['w'] for o in selected)-x;h=max(o['y']+o['h'] for o in selected)-y
        # Current visible text/geometry takes precedence over the initial specification.
        prompt='请将以下原生图解重新设计为一张精美中文图解。白底、深蓝文字、金色重点，保持所有当前文字、关系和顺序。只画图解，不重复页面标题。不编造数字或真实系统界面。\n用户反馈：'+feedback+'\n当前图解对象：'+_json(selected)
        if len(prompt)>30000:raise EngineError('DIAGRAM_TOO_LARGE','图解内容过长，不能安全转换。')
        ImageJobs(studio).enqueue_batch(batch_id,slide_id,[{'object_id':'diagram-image-'+request_id[:24],
           'prompt':prompt,'x':x,'y':y,'w':w,'h':h,'replace_diagram':True}])
        studio._touch(db,slide_id)
        return {'jobId':batch_id,'status':'pending'}


def submit_fallback(studio, slide_id, revision, request_id):
    if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request_id):
        raise EngineError('INVALID_REQUEST','请求标识无效。')
    with studio.wb.atomic() as db:
        existing=db.execute('SELECT id,payload FROM studio_jobs WHERE project_id=? AND client_message_id=?',
            (studio.project_id,'diagram-'+request_id)).fetchone()
        if existing:
            if json.loads(existing['payload'])['slideId']!=slide_id:
                raise EngineError('INVALID_REQUEST','请求标识已用于其他页面。')
            return {'jobId':existing['id'],'deduplicated':True}
        current=studio.get_scene(slide_id);studio.wb._revision(current['sceneRevision'],revision)
        if current['stale'] or not current['scene'].get('diagram'):
            raise EngineError('DIAGRAM_NOT_FOUND','当前页没有可替换的最新原生图解。')
        job=studio.enqueue('图解效果不满意，请换成 AI 图解。',slide_id,client_message_id='diagram-'+request_id)
        return studio.apply_plan(job['jobId'],{'reply':'正在生成替代图解，原版保留，可撤销。','actions':[
            {'type':'diagram_image','slide_id':slide_id,'base_scene_revision':revision}]})
