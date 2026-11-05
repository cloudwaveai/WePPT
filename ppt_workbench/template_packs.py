"""Versioned source-derived masters. AI organizes content; these rules place it.

No template example text/images enter the scene. Capacity failures preserve the
plan instead of silently truncating, shrinking or splitting the user's page.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import unicodedata
from functools import lru_cache
from pathlib import Path
from .core import EngineError, _json

DATA = Path(__file__).parent / 'data/template-packs/catalog.json'
DEFAULT = 'spatial-offset-crossing-v1'

@lru_cache(maxsize=1)
def _catalog():
    return {p['id']: p for p in json.loads(DATA.read_text(encoding='utf-8'))['packs']}

def get(pack_id):
    if pack_id not in _catalog():
        raise EngineError('TEMPLATE_PACK_NOT_FOUND', '这套模板不存在，请重新选择。')
    return copy.deepcopy(_catalog()[pack_id])

def split(template_id):
    if not isinstance(template_id, str) or ':' not in template_id:
        return None
    pid, master = template_id.split(':', 1)
    if pid in _catalog() and master in _catalog()[pid]['masters']:
        return pid, master
    return None

def selected(studio):
    with studio.wb._connection() as db:
        row = db.execute('SELECT pack_id FROM studio_pack_preferences WHERE project_id=?', (studio.project_id,)).fetchone()
    return row['pack_id'] if row else None

def _available(studio):
    chosen = selected(studio)
    return [p for p in _catalog().values() if p.get('spatialMethod') or p['id'] == chosen]

def select(studio, pack_id, revision):
    get(pack_id)
    with studio.wb.atomic() as db:
        project = studio.wb.get_project(studio.project_id)
        studio.wb._revision(project['revision'], revision)
        if project['workspace']['slides'] or studio._deck_row(db):
            raise EngineError('TEMPLATE_PACK_COPY_REQUIRED', '已有页面请生成整套改版副本。')
        if db.execute("SELECT 1 FROM studio_jobs WHERE project_id=? AND status IN ('queued','running')", (studio.project_id,)).fetchone():
            raise EngineError('TEMPLATE_PACK_BUSY', '生成已开始，请完成后再更换整套模板。')
        db.execute('INSERT OR REPLACE INTO studio_pack_preferences VALUES (?,?)', (studio.project_id, pack_id))
        # An explicit pack choice replaces a previous style-reference preference.
        db.execute('DELETE FROM studio_style_preferences WHERE project_id=?', (studio.project_id,))
        studio._touch(db)
    return {'packId': pack_id}

def contract(studio):
    from .user_templates import selected_style
    if selected_style(studio):
        return None
    return {'mode': 'template-pack-v1', 'selectedPack': selected(studio), 'defaultPack': DEFAULT,
            'instruction': '按内容关系、数量、篇幅与原图条件选择一个空间设计套系用于整稿。只组织 composition、选择 template_id 和绑定本项目真实图片；不编写场景坐标。保持原文、顺序与同页要求。流程用 process、层级用 layers、有明确中心对象才用 hub。每页最多6组；超出容量不删字或擅自拆页。不要用参考品牌、人物和示例数值作内容。',
            'packs': [{'id': p['id'], 'name': p['name'], 'principles': p['principles'],
                       'spatialMethod': p.get('spatialMethod'),
                       'masters': [{'template_id': p['id'] + ':' + mid, 'roles': m['roles'],
                                    'relationships': m.get('relationships', ['hero']), 'capacity': m['capacity']}
                                   for mid, m in p['masters'].items()]} for p in _available(studio)]}

def cards(studio):
    return {'selectedPack': selected(studio), 'defaultPack': DEFAULT,
            'packs': [{'id': p['id'], 'name': p['name'], 'principles': p['principles'],
                       'sources': p['sources'], 'spatialMethod': p.get('spatialMethod'),
                       'masterCount': len(p['masters'])} for p in _available(studio)]}

def _height(text, width, size, line_height=1.35):
    """Conservative preflight; actual Chrome measurement is still required."""
    total = 0
    for line in text.split('\n'):
        used, lines = 0, 1
        for ch in line:
            unit = size * (1 if unicodedata.east_asian_width(ch) in 'WF' else .62)
            if used + unit > width and used:
                lines += 1
                used = 0
            used += unit
        total += lines
    return math.ceil(total * size * line_height + 8) if text else 0

def _text(oid, text, box, style, **extra):
    return {'id': oid, 'type': 'text', 'text': text, **box,
            'fontFamily': 'Microsoft YaHei', **style, **extra}

def _rect(oid, box, color):
    return {'id': oid, 'type': 'rect', **box, 'fill': color}

def _capacity(page, reason):
    raise EngineError('TEMPLATE_CAPACITY', f'《{page["title"]}》超出本套模板的可读容量：{reason}。原文已保留，请选择更大容量版式或确认拆页。')

def _render(page, pack, master_id, images=()):
    if pack.get('spatialMethod'):
        from .spatial_templates import render
        return render(page, pack, master_id, images)
    m = pack['masters'][master_id]
    blocks = (page.get('composition') or {}).get('blocks', [])
    if not m['capacity'][0] <= len(blocks) <= m['capacity'][1]:
        _capacity(page, f'该版式支持 {m["capacity"][0]}–{m["capacity"][1]} 组内容')
    c, form = pack['colors'], m['form']
    title = copy.deepcopy(m['title'])
    if _height(page['title'], title['w'], title['fontSize'], title['lineHeight']) > title['h']:
        # Only the documented title slot grows, never beyond the content baseline.
        limit = m['contentRegion']['y'] - title['y'] - 24
        if _height(page['title'], title['w'], title['fontSize'], title['lineHeight']) > limit:
            _capacity(page, '标题超过标题区')
        title['h'] = limit
    objects = copy.deepcopy(m['fixed'])
    objects.append(_text('title', page['title'], title, {}, binding='title'))
    r = copy.deepcopy(m['contentRegion'])
    if images:
        if len(images) > 3:
            _capacity(page, '图文变体每页最多容纳 3 张原图')
        if form == 'hero':
            # Same family: text on the left, full original image on the right.
            title.update(x=72, y=190, w=660, h=220, align='left')
            if _height(page['title'],660,title['fontSize'],title['lineHeight']) > 220:
                _capacity(page, '带图封面的标题过长')
            objects[-1].update(title)
            r = {'x':72,'y':446,'w':660,'h':206}
            photo = {'x':788,'y':190,'w':420,'h':462}
        elif form == 'photo':
            r['w'] = 536
            photo = {'x':676,'y':174,'w':532,'h':470}
        else:
            _capacity(page, '此版式不承载图片')
        gap = 16
        for i, src in enumerate(images):
            h = (photo['h'] - gap * (len(images)-1)) / len(images)
            objects.append({'id': f'image.{i}', 'type':'image', 'x':photo['x'], 'y':photo['y']+i*(h+gap),
                            'w':photo['w'],'h':h,'src':src,'fit':'contain','alt':''})
    elif form == 'photo':
        _capacity(page, '图文版式需要真实图片')

    if not blocks:
        return _scene(page, pack, master_id, objects)
    if form == 'hub':
        return _render_hub(page,pack,master_id,objects,r,blocks)
    gap = 20
    columns = form == 'columns'
    w = (r['w'] - gap*(len(blocks)-1)) / len(blocks) if columns else r['w']
    rows = []
    for i,b in enumerate(blocks):
        # Keep every field, including repeated status labels, in its own group.
        hs = copy.deepcopy(m.get('headingStyle', {'fontSize':30,'bold':True,'color':c['ink'],'lineHeight':1.2}))
        bs = copy.deepcopy(m.get('bodyStyle', {'fontSize':24,'color':c['ink'],'lineHeight':1.4}))
        if form in {'rows','process'}: bs['lineHeight'] = 1.3
        if form == 'hero': hs['fontSize'] = 28
        horizontal = not columns and form not in {'hero','photo'}
        pad = 20 if columns else 0
        hw = 246 if horizontal else w-2*pad
        bw = w-282 if horizontal else w-2*pad
        heading_parts = [b[k] for k in ('kicker','metric','heading') if b.get(k)]
        heading = '\n'.join(heading_parts)
        hh = _height(heading,hw,hs['fontSize'],hs['lineHeight'])
        bh = _height(b.get('body',''),bw,bs['fontSize'],bs['lineHeight'])
        h = max(hh,bh)+8 if horizontal else hh+bh+32
        if columns: h = r['h']
        if columns and hh+bh+64 > h:
            _capacity(page, '分栏中的正文过长')
        rows.append((b,heading,hh,bh,h,hs,bs,hw,bw))
    if columns:
        panel_h = max(240, max(row[2]+row[3]+88 for row in rows))
        rows = [(b,head,hh,bh,min(r['h'],panel_h),hs,bs,hw,bw) for b,head,hh,bh,h,hs,bs,hw,bw in rows]
    total = max(row[4] for row in rows) if columns else sum(row[4] for row in rows)+8*(len(rows)-1)
    if total > r['h']:
        _capacity(page, '完整正文超过阅读区')
    if form in {'rows','process','layers'} and total < r['h']:
        extra=(r['h']-total)/len(rows)
        rows=[(b,head,hh,bh,h+extra,hs,bs,hw,bw) for b,head,hh,bh,h,hs,bs,hw,bw in rows]
    y = r['y'] + (r['h']-total)/2 if columns else r['y']
    for i,(b,heading,hh,bh,h,hs,bs,hw,bw) in enumerate(rows):
        x = r['x'] + i*(w+gap) if columns else r['x']
        prefix = f'group.{i}'
        if form == 'layers':
            # Layer membership, not an invented process: bands carry depth.
            objects.append(_rect(prefix+'.layer',dict(x=x,y=y-4,w=w,h=h+4),c['surface']))
            hx,hy,bx,by=x+16,y,x+282,y
            hw-=16;bw-=16
        elif columns:
            if m.get('groupStyle',{}).get('panel'):
                objects.append(_rect(prefix+'.panel',dict(x=x,y=y,w=w,h=h),c['surface']))
            elif i:
                objects.append({'id':prefix+'.divider','type':'line','x':x-gap/2,'y':y,'w':0,'h':h,'stroke':c['accent'],'strokeWidth':1})
            if m.get('groupStyle',{}).get('headingBand'):
                objects.append(_rect(prefix+'.band',dict(x=x,y=y,w=w,h=hh+32),c['accent']))
                hs['color'] = c['inverse']
            hx,hy,bx,by = x+20,y+16,x+20,y+hh+40
        elif form in {'hero','photo'}:
            hx,hy,bx,by = x,y,x,y+hh+12
            if title.get('align') == 'center': hs['align']=bs['align']='center'
        else:
            hx,hy,bx,by = x,y,x+282,y
            if form == 'process':
                # Ordered lanes with an independent connector channel.
                hx += 28; hw -= 28
                if i < len(rows)-1:
                    objects.append({'id':prefix+'.next','type':'line','x':x+6,'y':y+30,'w':0,'h':h-14,
                                    'stroke':c['accent'],'strokeWidth':2,'endArrow':True})
            if i:
                objects.append({'id':prefix+'.rule','type':'line','x':x,'y':y-8,'w':w,'h':0,
                                'stroke':c['accent'],'strokeWidth':1})
        if heading:
            objects.append(_text(prefix+'.heading',heading,dict(x=hx,y=hy,w=hw,h=hh),hs))
        if b.get('body'):
            objects.append(_text(prefix+'.body',b['body'],dict(x=bx,y=by,w=bw,h=bh),bs))
        if not columns:y += h+8
    return _scene(page,pack,master_id,objects)

def _render_hub(page,pack,mid,objects,r,blocks):
    """First planned block is the centre; every other block belongs to it."""
    c=pack['colors'];right=blocks[1:];gap=16
    row_h=(r['h']-gap*(len(right)-1))/len(right)
    core=blocks[0]
    def group(index,b,x,y,w,h,accent=False):
        head='\n'.join(b[k] for k in ('kicker','metric','heading') if b.get(k))
        hh=_height(head,w-40,30,1.2);bh=_height(b['body'],w-40,24,1.3)
        if hh+bh+44>h:_capacity(page,'中心关系图的内容区不足')
        objects.append(_rect(f'hub.{index}.panel',dict(x=x,y=y,w=w,h=h),c['accent'] if accent else c['surface']))
        color=c['inverse'] if accent else c['ink']
        objects.append(_text(f'hub.{index}.heading',head,dict(x=x+20,y=y+18,w=w-40,h=hh),dict(fontSize=30,bold=True,color=color,lineHeight=1.2)))
        if b['body']:objects.append(_text(f'hub.{index}.body',b['body'],dict(x=x+20,y=y+hh+30,w=w-40,h=bh),dict(fontSize=24,color=color,lineHeight=1.3)))
    group(0,core,r['x'],r['y'],320,r['h'],True)
    trunk=r['x']+364
    objects.append({'id':'hub.root','type':'line','x':r['x']+320,'y':r['y']+r['h']/2,'w':44,'h':0,'stroke':c['accent'],'strokeWidth':2})
    first=r['y']+row_h/2;last=r['y']+(len(right)-1)*(row_h+gap)+row_h/2
    if last>first:objects.append({'id':'hub.trunk','type':'line','x':trunk,'y':first,'w':0,'h':last-first,'stroke':c['accent'],'strokeWidth':2})
    for i,b in enumerate(right):
        y=r['y']+i*(row_h+gap)
        objects.append({'id':f'hub.link.{i}','type':'line','x':trunk,'y':y+row_h/2,'w':44,'h':0,'stroke':c['accent'],'strokeWidth':2})
        group(i+1,b,r['x']+408,y,r['w']-408,row_h)
    return _scene(page,pack,mid,objects)


def _scene(page, pack, master_id, objects):
    from .rendering import validate_scene
    return validate_scene({'schema':'ppt-scene','schemaVersion':1,'slideId':'S001','width':1280,'height':720,
                           'background':pack['colors']['paper'],'templateId':pack['id']+':'+master_id,
                           'title':page['title'],'objects':objects})

def compile_page(page, pack_id=None, images=()):
    binding = split(page.get('template_id'))
    pack = get(pack_id or (binding[0] if binding else DEFAULT))
    role = page['role']; rel = (page.get('composition') or {}).get('relationship','parallel')
    if role in {'cover','chapter','ending'}:
        candidates = [role]
    elif images:
        candidates = ['body-photo']
    elif rel in {'layers','hub'}:
        candidates = ['body-'+rel]
    elif rel == 'process':
        candidates = ['body-process']
    elif rel in {'parallel','comparison'}:
        candidates = ['body-columns','body-rows']
    else:
        candidates = ['body-rows']
    if binding and binding[0] == pack['id'] and binding[1] in candidates:
        candidates.remove(binding[1]);candidates.insert(0,binding[1])
    failures=[]
    for mid in candidates:
        try:
            scene=_render(page,pack,mid,images)
            return scene, {'packId':pack['id'],'masterId':mid,'packSHA256':hashlib.sha256(_json(pack).encode()).hexdigest(),
                           'relationship':rel,'sources':pack['sources'],'adaptation':failures}
        except EngineError as exc:
            if exc.code!='TEMPLATE_CAPACITY':raise
            failures.append({'masterId':mid,'reason':exc.message})
    _capacity(page, failures[-1]['reason'])

def bind_plan(studio, plan):
    """Freeze one family once. Old/unstructured/reference-style decks keep their path."""
    binding = next((split(p.get('template_id')) for p in plan['pages'] if split(p.get('template_id'))), None)
    pid = selected(studio) or (binding[0] if binding else None)
    if not pid:
        return False
    image_map = studio.wb.project_dir(studio.project_id) / 'template-source-images.json'
    frozen_images = json.loads(image_map.read_text()) if image_map.exists() else None
    for index, page in enumerate(plan['pages']):
        if frozen_images is not None:
            page['template_images'] = frozen_images[index]

        if not page.get('composition'):
            raise EngineError('INVALID_COMPOSITION','整套模板需要逐页 composition，完整保留内容分组。')
        images = ['asset:'+aid for aid in page.get('template_images',[])]
        for aid in page.get('template_images',[]):
            if studio.asset(aid)['mime'] not in {'image/png','image/jpeg'}:
                raise EngineError('INVALID_COMPOSITION','模板图片必须是本项目的 PNG 或 JPEG。')
        scene, _ = compile_page(page,pid,images)
        page['template_id'] = scene['templateId']
    colors=get(pid)['colors']
    plan['design']={'background':colors['paper'],'ink':colors['ink'],'accent':colors['accent'],
                    'surface':colors['surface'],'fontFamily':'Microsoft YaHei'}
    if studio.palette():
        plan['design'].update(accent=studio.palette()['primary'], secondary=studio.palette()['secondary'][0])
    return True

def is_local_job(studio,payload):
    if payload.get('kind')!='deck_page':return False
    with studio.wb._connection() as db:
        _,row=studio._deck_page(db,payload)
    return bool(split(json.loads(row['plan']).get('template_id')))

def scene_for_page(studio,page,page_index):
    from .core import _hash
    pid = split(page.get('template_id'))[0]
    with studio.wb._connection() as db:
        frozen = db.execute('SELECT sha256 FROM studio_pack_bindings WHERE project_id=?', (studio.project_id,)).fetchone()
    if frozen and frozen['sha256'] != _hash(get(pid)):
        raise EngineError('TEMPLATE_PACK_CHANGED','生成期间模板版本发生变化，未用新母版覆盖原计划。')
    scene,evidence=compile_page(page,images=['asset:'+a for a in page.get('template_images',[])])
    from .derived import _restyle_source
    source = _restyle_source(studio)
    if source is not None:
        scene['notes'] = source[page_index].get('notes','')
    scene=studio._resolve_images(scene)
    chosen = studio.palette()
    if chosen:
        from .palette import recolor_scene
        c = get(evidence['packId'])['colors']
        # Secondary colour is a tint on large panels, never a saturated slab.
        def tint(fg,bg):
            return '#'+''.join(f'{round(int(fg[i:i+2],16)*.12+int(bg[i:i+2],16)*.88):02X}' for i in (1,3,5))
        scene = recolor_scene(scene, {c['accent']: chosen['primary'], c['surface']: tint(chosen['secondary'][0],c['paper'])})
    return scene,evidence

def page_job(studio,payload):
    with studio.wb._connection() as db:
        _,row=studio._deck_page(db,payload)
    page=json.loads(row['plan'])
    scene,evidence=scene_for_page(studio,page,payload['pageIndex'])
    from .design_review import render_candidate
    folder=studio.wb.project_dir(studio.project_id)/'template-layouts'/str(payload['pageIndex']+1)
    folder.mkdir(parents=True,exist_ok=True)
    _,measure=render_candidate(scene,folder/'render')
    evidence['measurement']=measure
    (folder/'selection.json').write_text(_json(evidence),encoding='utf-8')
    if measure.get('overflow') or measure.get('imageFailures') or not measure.get('fontsReady'):
        raise EngineError('TEMPLATE_CAPACITY','浏览器测量发现文字溢出，未保存不完整页面。',measure)
    action={k:v for k,v in page.items() if k not in {'designBrief','template_images','diagram'}}
    action.update(type='slide_add',scene=scene)
    return {'reply':f'已使用「{get(evidence["packId"])["name"]}」适配第 {payload["pageIndex"]+1} 页。','actions':[action],'questions':[]}

def preview(pack_id,role):
    if role not in {'cover','chapter','content'}:
        raise EngineError('INVALID_REQUEST','预览类型无效。')
    page={'title':{'cover':'把内容融入好设计','chapter':'从内容到版式','content':'同一套设计，适配不同内容'}[role], 'role':role,
          'composition':{'purpose':'模板预览','relationship':'hero' if role!='content' else 'parallel',
                         'blocks':([{'id':'a','heading':'封面 · 章节 · 正文','body':'一次选定，整套保持一致'}] if role!='content' else
                                   [{'id':str(i),'heading':h,'body':b} for i,(h,b) in enumerate([
                                       ('理解内容','识别重点、关系和限定条件'),('匹配版式','按内容数量与容量选择变体'),('保留编辑','文字、形状和原图均可调整')])])}}
    return compile_page(page,pack_id)[0]


def default_plan(proposal, context):
    """New connected-model generation defaults to packs, without migrating old jobs."""
    if not context.get('templateContract') or not context.get('creationContract'):
        return proposal
    proposal = copy.deepcopy(proposal)
    for action in proposal.get('actions', []):
        if action['type'] == 'deck_start':
            binding = next((split(p.get('template_id')) for p in action['pages'] if split(p.get('template_id'))), None)
            pid = context['templateContract'].get('selectedPack') or (binding[0] if binding else DEFAULT)
            for p in action['pages']:
                if not split(p.get('template_id')):
                    rel=(p.get('composition') or {}).get('relationship')
                    master=p['role'] if p['role'] in {'cover','chapter','ending'} else ('body-columns' if rel in {'parallel','comparison'} else 'body-'+rel if rel in {'process','layers','hub'} else 'body-rows')
                    p['template_id'] = pid + ':' + master
    return proposal
