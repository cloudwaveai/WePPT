"""Current page styles, backed by the spatial library and lossless scene adapters.

Historical IDs remain resolvable; only the browsing/recommendation defaults change.
"""
from __future__ import annotations
import copy,hashlib,json
from .core import EngineError
from .rendering import validate_scene
from .template_content import strip_template_decoration

# id, name, category, role, spatial family, preferred master
RECIPES = (
 ('poster','大字开场','cover','cover','type-weave','cover'),
 ('window','错位开场','cover','cover','offset-crossing','cover'),
 ('chapter','章节切换','chapter','chapter','offset-crossing','chapter'),
 ('contents','目录轴线','toc','toc','offset-crossing','body-rows'),
 ('editorial','编辑式正文','argument','content','type-weave','body-rows'),
 ('bridge','跨界并列','argument','content','offset-crossing','body-columns'),
 ('compare','左右对照','compare','content','offset-crossing','body-columns'),
 ('process','顺序路径','process','content','type-weave','body-process'),
 ('structure','中心与关联','structure','content','concentric-relief','body-hub'),
 ('layers','层面结构','structure','content','translucent-planes','body-layers'),
 ('data','数据与解读','data','content','type-weave','body-rows'),
 ('product','系统与说明','product','content','offset-crossing','body-photo'),
 ('case','证据侧讲','case','content','translucent-planes','body-photo'),
 ('people','人物与介绍','people','content','type-weave','body-photo'),
 ('gallery','原图展陈','gallery','content','offset-crossing','body-photo'),
 ('ending','结论收束','ending','ending','concentric-relief','ending'),
)

def recipe(tid):
    return next((r for r in RECIPES if tid=='pagekit-'+r[0]+'-v1'),None)

def catalog():
    result=[]
    for key,name,category,role,family,master in RECIPES:
        result.append(dict(id='pagekit-'+key+'-v1',name=name,title=name,description=name,
            role=role,roles=[role]+(['appendix'] if category in ('data','case','gallery') else []),family=category,familyName=name,sourceCategory=None,
            use=name,tags=[name,category],inputs=[],checks=['完整保留原文和原图','容量不足时明确提示'],
            legacy=False,current=True,spatialMethod=family,master=master,
            browseCategory=category,sourceLabel='空间关系样式 · '+family,capacityLabel='最多 6 组文字、3 张原图；以完整可读为准'))
    return result


def _signature(obj):
    return hashlib.sha256(json.dumps({k:v for k,v in obj.items() if k!='id'},sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:20]


def _owned(obj):
    return obj['id'].startswith('pagekit.fixed.') and obj['id'].split('.')[-1]==_signature(obj)


def _seal(obj,index):
    obj=copy.deepcopy(obj);obj['id']='fixed'
    obj=validate_scene(dict(schema='ppt-scene',schemaVersion=1,slideId='S001',width=1280,height=720,background='#FFFFFF',objects=[obj]))['objects'][0]
    obj['id']=f'pagekit.fixed.{index}.{_signature(obj)}'
    return obj


def _compile(page,r,images):
    from .template_packs import compile_page
    _,_,_,role,family,master=r
    pid='spatial-'+family+'-v1'
    page=copy.deepcopy(page);page['role']=role if role in ('cover','chapter','ending') else 'content'
    rel={'body-process':'process','body-hub':'hub','body-layers':'layers','body-columns':'parallel'}.get(master,'evidence' if images else 'summary')
    page['composition']['relationship']=rel
    # A page style carries an intended geometry, while the compiler may select a
    # larger variant from the same family when full text needs more room.
    page['template_id']=pid+':'+master
    return compile_page(page,pid,images=images)[0]


def apply(scene,tid):
    r=recipe(tid)
    if not r:raise EngineError('UNKNOWN_TEMPLATE','未找到页面样式。')
    original=validate_scene(scene)
    if original['width']!=1280:
        factor=1280/original['width'];normalized=copy.deepcopy(original)
        normalized['objects']=[o for o in normalized['objects'] if not _owned(o)]
        normalized.update(width=1280,height=720)
        for o in normalized['objects']:
            for key in ('x','y','w','h'):o[key]*=factor
        result=apply(normalized,tid);result.update(width=original['width'],height=original['height'])
        for i,o in enumerate(result['objects']):
            fixed=_owned(o)
            for key in ('x','y','w','h'):o[key]/=factor
            if o['type']=='text':o['fontSize']=max(10,o['fontSize']/factor)
            if fixed:o['id']=f'pagekit.fixed.{i}.{_signature(o)}'
        return validate_scene(result)
    source=strip_template_decoration(copy.deepcopy(original))
    source['objects']=[o for o in source['objects'] if not _owned(o)]
    titles=[o for o in source['objects'] if o['type']=='text' and o.get('binding')=='title']
    title=titles[0] if titles else next((o for o in source['objects'] if o['type']=='text'),None)
    if not title:raise EngineError('TEMPLATE_CAPACITY','本页没有可识别的标题，请保留原页并使用整稿改版。')
    content=[o for o in source['objects'] if o is not title]
    shapes=[o for o in content if o['type'] not in ('text','image')]
    if shapes:
        return _preserve_graphic(source,tid,r,title,content)
    texts=[o for o in content if o['type']=='text'];images=[o for o in content if o['type']=='image']
    if len(texts)>6 or len(images)>3:
        raise EngineError('TEMPLATE_CAPACITY','本页内容超过该样式容量，原稿已保留；请使用整稿改版或选择更大阅读区。')
    blocks=[dict(id=f'b{i}',heading='',body=o['text']) for i,o in enumerate(texts)]
    page=dict(title=title['text'],role=r[3],user_intent='保留本页所有内容',composition=dict(purpose='页面换版',relationship='summary',blocks=blocks))
    # The image styles are useful even before assets arrive: a text-only variant
    # keeps real content and does not invent a picture or empty frame.
    render_recipe=r
    if not images and r[5]=='body-photo':render_recipe=(*r[:5],'body-rows')
    if not texts and not images:render_recipe=(*r[:3],'cover',r[4],'cover')
    compiled=_compile(page,render_recipe,[o['src'] for o in images])
    compiled=_page_geometry(compiled,r,texts,images)
    objects=[]
    for obj in compiled['objects']:
        o=copy.deepcopy(obj);old=None
        if o['id']=='title':old=title
        elif o['id'].startswith('group.') and o['id'].endswith('.body'):old=texts[int(o['id'].split('.')[1])]
        elif o['id'].startswith('image.'):old=images[int(o['id'].split('.')[1])]
        if old:
            o['id']=old['id']
            if o['type']=='image':
                for k,v in old.items():
                    if k not in ('x','y','w','h'):o[k]=copy.deepcopy(v)
            for k in ('binding','textSource','alt','fit'):
                if k in old:o[k]=copy.deepcopy(old[k])
            if o['type']=='text':
                o['text']=old['text']
                if 'binding' not in old:o.pop('binding',None)
                first=old['text'].split('\n',1)[0]
                if '\n' in old['text'] and len(first)<=24:
                    o['emphasis']=[first]
                for key in ('emphasis','emphasisColor','textSource'):
                    if key in old:o[key]=copy.deepcopy(old[key])
        else:o=_seal(o,len(objects))
        objects.append(o)
    result=copy.deepcopy(original);result.update(templateId=tid,background=compiled['background'],objects=objects)
    result.pop('diagram',None)
    return validate_scene(result)


def _page_geometry(compiled,r,texts,images):
    """Purpose-specific reading areas beyond the family-level master."""
    from .template_packs import _height,get
    c=get('spatial-'+r[4]+'-v1')['colors']
    objects=compiled['objects']
    title=next(o for o in objects if o['id']=='title')
    if r[0]=='ending' and len(title['text'])<=16:
        title['fontSize']=min(title['fontSize'],48)
        title['h']=_height(title['text'],title['w'],title['fontSize'],1.3)
    if r[0]=='contents' and not images:
        title.update(x=64,y=48,w=1152,h=_height(title['text'],1152,60,1.3),fontSize=60)
        top=190;gap=24;heights=[max(54,_height(o['text'],980,32,1.3)) for o in texts]
        if sum(heights)+gap*max(0,len(texts)-1)>470:
            raise EngineError('TEMPLATE_CAPACITY','目录原文超过完整阅读区，原稿已保留。')
        objects=[title,dict(id='toc.axis',type='line',x=142,y=top,w=0,h=440,stroke=c['accent'],strokeWidth=3)]
        y=top
        for i,(old,h) in enumerate(zip(texts,heights)):
            objects.append(dict(id=f'toc.number.{i}',type='text',text=f'{i+1:02}',x=64,y=y,w=64,h=54,fontSize=32,color=c['accent'],bold=True))
            objects.append(dict(id=f'group.{i}.body',type='text',text=old['text'],x=184,y=y,w=1000,h=h,fontSize=32,color=c['ink'],lineHeight=1.3))
            y+=h+gap+(470-sum(heights)-gap*max(0,len(texts)-1))/max(1,len(texts))
    if r[0]=='gallery' and len(images)==1 and len(texts)<=3:
        title.update(x=64,y=42,w=1152,h=_height(title['text'],1152,48,1.3),fontSize=48)
        objects=[title,dict(id='gallery.ground',type='rect',x=48,y=154,w=760,h=518,fill=c['surface']),
                 dict(id='image.0',type='image',src=images[0]['src'],fit='contain',alt=images[0].get('alt',''),x=64,y=170,w=728,h=486)]
        y=176
        for i,old in enumerate(texts):
            h=_height(old['text'],344,26,1.3)
            if y+h>672:raise EngineError('TEMPLATE_CAPACITY','图片说明超过完整阅读区，原稿已保留。')
            objects.append(dict(id=f'group.{i}.body',type='text',text=old['text'],x=860,y=y,w=344,h=h,fontSize=26,color=c['ink'],lineHeight=1.3))
            y+=h+40
    return dict(compiled,objects=objects)


def _preserve_graphic(source,tid,r,title,content):
    """Keep an authored diagram/chart as one composition, including its text.

    Shapes are never hidden or replaced by invented bars/data. A protected panel
    keeps original colors readable. Only display geometry changes uniformly.
    """
    from .template_packs import get,_height
    colors=get('spatial-'+r[4]+'-v1')['colors']
    left=min(o['x'] for o in content);top=min(o['y'] for o in content)
    right=max(o['x']+o['w'] for o in content);bottom=max(o['y']+o['h'] for o in content)
    title_h=_height(title['text'],1152,48,1.3)
    if title_h>160:raise EngineError('TEMPLATE_CAPACITY','标题超出阅读区，原稿已保留。')
    area_top=max(170,48+title_h+24);height=676-area_top
    scale=min(1120/max(1,right-left),(height-32)/max(1,bottom-top),1.25)
    if any(o['type']=='text' and o['fontSize']*scale<18 for o in content):
        raise EngineError('TEMPLATE_CAPACITY','保留现有图形和完整文字后阅读区不足，原稿未改；请使用整稿改版。')
    objects=[_seal(dict(type='rect',x=1016,y=0,w=264,h=720,fill=colors['accent']),0),
        _seal(dict(type='rect',x=64,y=area_top,w=1152,h=height,fill=source['background']),1)]
    t=copy.deepcopy(title);t.update(x=64,y=42,w=1152,h=title_h,fontSize=48,lineHeight=1.3,color=colors['ink'],bold=True);objects.append(t)
    ox=80+(1120-(right-left)*scale)/2;oy=area_top+16+(height-32-(bottom-top)*scale)/2
    for obj in content:
        o=copy.deepcopy(obj);o.update(x=ox+(o['x']-left)*scale,y=oy+(o['y']-top)*scale,w=o['w']*scale,h=o['h']*scale)
        if o['type']=='text':o['fontSize']*=scale
        objects.append(o)
    result=copy.deepcopy(source);result.update(templateId=tid,background=colors['paper'],objects=objects)
    # The original chart/diagram and its topology remain the same.
    return validate_scene(result)


def sample(tid):
    r=recipe(tid)
    if not r:raise EngineError('UNKNOWN_TEMPLATE','未找到页面样式。')
    from .template_packs import _height
    title={'cover':'把内容融入好设计','toc':'汇报结构','chapter':'从内容到设计','ending':'保留重点，形成下一步'}.get(r[3],r[1])
    texts={
        'compare':['现状\n说明已有做法、适用范围与限制。','调整方向\n对应相同维度说明变化与依据。'],
        'process':['理解内容\n保留事实、顺序和限定条件。','匹配结构\n按真实步骤选择阅读路径。','检查结果\n核对全文、关系与原图。'],
        'structure':['共同对象\n只有明确关联时建立中心。','关联内容\n保留各项身份和解释。','适用边界\n说明条件与真实限制。'],
        'data':['数据原件\n保留真实图表与全部数值。','解读依据\n说明口径、时间与适用范围。'],
        'editorial':['核心观点\n先说结论，再给完整依据。','具体说明\n正文按篇幅分配阅读区，保留限定条件。','下一步\n明确行动、对象和适用边界。'],
        'contents':['问题与目标','方法与依据','结果与下一步'],
    }
    key=r[0];lines=texts.get(key,['完整原文\n保留事实、状态与适用范围。','内容与版式\n根据真实信息关系调整空间。'])
    if r[3] in ('cover','chapter','ending'):lines=['先理解内容，再形成合适的表达。']
    scene=dict(schema='ppt-scene',schemaVersion=1,slideId='S001',width=1280,height=720,background='#FFFFFF',title=title,objects=[dict(id='title',type='text',binding='title',text=title,x=64,y=48,w=1152,h=100,fontSize=48)])
    for i,text in enumerate(lines):scene['objects'].append(dict(id=f'body.{i}',type='text',binding=f'keyPoints:{i}',text=text,x=64,y=200+i*120,w=1100,h=100,fontSize=24))
    if key in ('product','case','gallery'):
        import base64
        from pathlib import Path
        raw=(Path(__file__).parent/'data/page-kits/editor-original.png').read_bytes()
        scene['objects'].append(dict(id='sample.original',type='image',
            src='data:image/png;base64,'+base64.b64encode(raw).decode(),
            alt='WePPT 本地演示界面原图，仅用于样式示例',fit='contain',x=64,y=200,w=720,h=440))
        scene['notes']='样式示例；图片为本地演示界面，不代表客户实测或人物照片。'
    return apply(validate_scene(scene),tid)
