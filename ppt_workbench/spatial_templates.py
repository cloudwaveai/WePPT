"""Source-derived spatial compositions for executable template packs.

Words, groups and images remain independent native objects. Geometry is adapted
inside each method; no reference screenshot/brand/sample text is used as content.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from .core import EngineError


def fingerprint():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class Layout:
    def __init__(self, page, pack):
        self.page, self.pack, self.objects = page, pack, []
        self.c = pack['colors']
        self.method = pack['spatialMethod']['id']

    def fail(self, reason):
        raise EngineError('TEMPLATE_CAPACITY', f'《{self.page["title"]}》超出本套模板的可读容量：{reason}。原文已保留，请选择更大容量版式或确认拆页。')

    def add(self, kind, oid, x, y, w, h, **props):
        obj = dict(id=oid, type=kind, x=x, y=y, w=w, h=h, **props)
        self.objects.append(obj)
        return obj

    def shape(self, oid, x, y, w, h, fill=None, kind='rect', **props):
        return self.add(kind, oid, x, y, w, h, fill=fill or self.c['accent'], **props)

    def text(self, oid, text, x, y, w, size=24, color=None, bold=False, h=None, **props):
        from .template_packs import _height
        measured = _height(text, w, size, 1.3)
        if h is not None and measured > h:
            self.fail('完整文字超过阅读区')
        return self.add('text', oid, x, y, w, h if h is not None else max(measured, 1),
                        text=text, fontSize=size, color=color or self.c['ink'], bold=bold,
                        fontFamily='Microsoft YaHei', lineHeight=1.3, **props)

    def line(self, oid, x, y, w, h=0, **props):
        return self.add('line', oid, x, y, w, h, stroke=self.c['accent'], strokeWidth=2, **props)

    def rings(self, oid, cx, cy, diameter):
        for i, (ratio, color) in enumerate([(1, self.c['surface']), (.90, self.c['inverse']),
                (.82, self.c['surface']), (.76, self.c['inverse']), (.64, self.c['accent']), (.57, self.c['inverse'])]):
            d = diameter * ratio
            self.shape(f'{oid}.{i}', cx-d/2, cy-d/2, d, d, color, kind='ellipse',
                       **({'shadow':'soft'} if i in (1,3,5) else {}))

    def head(self, side=False):
        from .template_packs import _height
        title = self.page['title']
        if side:
            h = _height(title, 304, 50, 1.3)
            if h > 500: self.fail('侧栏标题过长')
            self.text('title', title, 64, max(80, (720-h)/2), 304, 50, bold=True, h=h, binding='title')
            return 170
        size = 48 if len(title) <= 22 else 40
        h = _height(title, 1152, size, 1.3)
        if h > 160: self.fail('标题超过标题区')
        self.text('title', title, 64, 42, 1152, size, bold=True, h=h, binding='title')
        return max(156, 42+h+26)

    def heading(self, block):
        return '\n'.join(block[k] for k in ('kicker', 'metric', 'heading') if block.get(k))

    def block(self, i, block, x, y, w, h, size=24):
        from .template_packs import _height
        heading = self.heading(block)
        hh = _height(heading, w, 28, 1.3)
        bh = _height(block.get('body',''), w, size, 1.3)
        gap = 12 if heading and block.get('body') else 0
        if hh + gap + bh > h: self.fail('完整内容组超过阅读区')
        if heading: self.text(f'group.{i}.heading', heading, x, y, w, 28, bold=True, h=hh)
        if block.get('body'): self.text(f'group.{i}.body', block['body'], x, y+hh+gap, w, size, h=bh)

    def lane(self, i, block, x, y, w, h, numbered=False):
        from .template_packs import _height
        heading = self.heading(block)
        start = 104 if numbered else 0
        hw = min(180, w*.24)
        channel = start + hw + 28
        if numbered:
            self.text(f'group.{i}.sequence', f'{i+1:02}', x, y, 78, 42, color=self.c['accent'], bold=True, h=70)
        hh = _height(heading, hw, 26, 1.3)
        bw = w - channel
        bh = _height(block.get('body',''), bw, 24, 1.3)
        if max(hh, bh) > h: self.fail('完整正文超过宽行阅读区')
        if heading: self.text(f'group.{i}.heading', heading, x+start, y, hw, 26, bold=True, h=hh)
        if block.get('body'): self.text(f'group.{i}.body', block['body'], x+w-bw, y, bw, 24, h=bh)


def _hero(q, blocks, images):
    from .template_packs import _height
    role = q.page['role']
    title = q.page['title']
    c, method = q.c, q.method
    # Large short titles retain their weight; long titles get a wider text-only composition.
    if not images:
        if method == 'type-weave':
            q.shape('spatial.edge', 0, 0, 28, 720)
            tx,ty,tw,size = 64,150,1152,88 if len(title)<=12 else 60
        elif method == 'offset-crossing':
            q.shape('spatial.backdrop', 844,0,436,720,c['ink'])
            q.shape('spatial.offset',132,170,1084,410,c['accent'])
            q.shape('spatial.paper',64,120,1084,410,c['inverse'])
            tx,ty,tw,size = 100,158,1000,76 if len(title)<=16 else 56
        elif method == 'translucent-planes':
            q.shape('spatial.rear-disc',810,84,340,340,c['secondary'],kind='ellipse')
            q.shape('spatial.backdrop',188,180,972,392,c['accent'],opacity=.38)
            q.shape('spatial.reading-plane',64,104,1040,404,c['inverse'],opacity=.86)
            tx,ty,tw,size = 108,156,944,76 if len(title)<=16 else 56
        else:
            q.rings('spatial.rings',958,360,492)
            tx,ty,tw,size = 64,190,650,70 if len(title)<=12 else 54
    else:
        if method == 'type-weave':
            q.shape('spatial.photo-ground',594,176,622,470,c['surface'])
            tx,ty,tw,size = 64,82,510,80 if len(title)<=9 else 50
        elif method == 'offset-crossing':
            q.shape('spatial.backdrop',844,0,436,720,c['ink'])
            q.shape('spatial.offset',658,128,558,510,c['accent'])
            tx,ty,tw,size = 64,132,510,76 if len(title)<=9 else 50
        elif method == 'translucent-planes':
            q.shape('spatial.rear-disc',830,72,336,336,c['secondary'],kind='ellipse')
            q.shape('spatial.rear-plane',672,144,506,514,c['accent'],opacity=.42)
            q.shape('spatial.reading-plane',64,104,536,480,c['inverse'],opacity=.9)
            tx,ty,tw,size = 98,154,470,70 if len(title)<=10 else 48
        else:
            q.rings('spatial.rings',940,354,516)
            tx,ty,tw,size = 64,154,510,76 if len(title)<=10 else 50
        for i, image in enumerate(images):
            h = (444-16*(len(images)-1))/len(images)
            q.add('image',f'image.{i}',638,190+i*(h+16),558,h,src=image,fit='contain',alt='用户原始图片')
    if role != 'cover': size = min(size,70)
    th = _height(title,tw,size,1.3)
    if th > 256: q.fail('完整标题超过封面阅读区')
    q.text('title',title,tx,ty,tw,size,bold=True,h=th,binding='title')
    by = max(ty+th+30, 385 if images else 350)
    if not blocks: return
    # Keep every group and every optional status/metric; no made-up subtitle.
    width = tw
    available = min(650, 530 if method in ('offset-crossing','translucent-planes') and not images else 654) - by
    gap = 18
    sizes = []
    for b in blocks:
        hh = _height(q.heading(b),width,28,1.3)
        bh = _height(b.get('body',''),width,24,1.3)
        sizes.append(hh+bh+(12 if hh and bh else 0))
    if sum(sizes)+gap*(len(blocks)-1)>available: q.fail('封面或章节的原文超过阅读区')
    for i,(b,h) in enumerate(zip(blocks,sizes)):
        q.block(i,b,tx,by,width,h);by+=h+gap


def _columns(q, blocks):
    top=q.head();n=len(blocks);bottom=660
    if q.method=='type-weave':
        q.shape('spatial.rule',64,top-16,1152,4)
        gap=42;w=(1152-gap*(n-1))/n
        for i,b in enumerate(blocks):
            x=64+i*(w+gap)
            q.block(i,b,x,top+28,w,bottom-top-28)
    elif q.method=='offset-crossing':
        # The shared axis is visual, not an invented process or hierarchy.
        if n not in (2,3,4):q.fail('错位并列页需要2–4组')
        axis=622
        q.shape('spatial.axis',axis,top,36,bottom-top,q.c['accent'])
        positions=[(64,top+20),(732,top+20)] if n==2 else [(64,top+20),(732,top+20),(64,top+260),(732,top+260)]
        if n==3:positions=[(64,top+20),(732,top+20),(732,top+260)]
        for i,(b,(x,y)) in enumerate(zip(blocks,positions)):
            q.shape(f'group.{i}.bridge',578 if x==64 else 646,y+10,56,28,q.c['secondary'])
            q.block(i,b,x,y,484,(bottom-y) if n==2 or (n==3 and i==0) else 212)
    elif q.method=='translucent-planes':
        gap=32;w=(1152-gap*(n-1))/n
        q.shape('spatial.rear-plane',98,top+30,1110,bottom-top-30,q.c['accent'],opacity=.32)
        q.shape('spatial.reading-plane',64,top,1110,bottom-top,q.c['inverse'],opacity=.92)
        w=(1054-gap*(n-1))/n
        for i,b in enumerate(blocks):q.block(i,b,92+i*(w+gap),top+26,w,bottom-top-52)
    else:
        # A parallel list has no shared semantic centre: keep the ring at an edge.
        q.rings('spatial.rings',1110,top+42,164)
        gap=40;w=(1152-gap*(n-1))/n
        for i,b in enumerate(blocks):q.block(i,b,64+i*(w+gap),top+142,w,bottom-top-142)


def _rows(q, blocks, form):
    from .template_packs import _height
    # Preflight the final reading boxes, including decorative offsets and padding.
    side=q.method=='type-weave' and form=='rows' and len(blocks)<=4
    gap=8
    def geometry(side):
        w=792 if side else 1152
        pad=16 if q.method in ('offset-crossing','translucent-planes') or form=='layers' else 0
        heights=[]
        for i,b in enumerate(blocks):
            dx=12*(i%2) if q.method in ('offset-crossing','translucent-planes') else 0
            rw=w-dx-(44 if q.method=='offset-crossing' else 0)-2*pad
            hw=min(180,rw*.24);bw=rw-hw-28-(104 if form=='process' else 0)
            heights.append(max(_height(q.heading(b),hw,26,1.3),_height(b.get('body',''),bw,24,1.3),70 if form=='process' else 44)+14)
        return heights
    heights=geometry(side)
    if side and sum(heights)+gap*(len(blocks)-1)>588:side=False;heights=geometry(False)
    top=q.head(side);x=420 if side else 64;w=792 if side else 1152
    if side:q.shape('spatial.edge',0,0,28,720);q.shape('spatial.divider',380,64,3,592,q.c['surface']);top=72
    available=(660 if side else 684)-top
    if sum(heights)+gap*(len(blocks)-1)>available:q.fail('完整内容超过宽行版容量')
    extra=(available-sum(heights)-gap*(len(blocks)-1))/len(blocks)
    if q.method=='offset-crossing':q.shape('spatial.spine',1182,top,34,available,q.c['ink'])
    elif q.method=='translucent-planes':q.shape('spatial.rear-plane',852,top,334,available,q.c['accent'],opacity=.4)
    elif q.method=='concentric-relief' and len(q.page['title'])<=18:q.rings('spatial.rings',1150,90,110)
    y=top
    for i,(b,base) in enumerate(zip(blocks,heights)):
        h=base+extra
        # Foreground may cross decorative planes, never another group's content.
        dx=12*(i%2) if q.method in ('offset-crossing','translucent-planes') else 0
        lane_x=x+dx;lane_w=w-dx-(44 if q.method=='offset-crossing' else 0)
        if form=='layers':
            q.shape(f'group.{i}.layer',lane_x,y-2,lane_w,h-2,q.c['surface'],opacity=.9)
        elif q.method=='offset-crossing':
            q.shape(f'group.{i}.back',lane_x+12,y+8,lane_w,h-12,q.c['surface'])
            q.shape(f'group.{i}.front',lane_x,y,lane_w,h-12,q.c['inverse'])
        elif q.method=='translucent-planes':q.shape(f'group.{i}.front',lane_x,y,lane_w,h-10,q.c['inverse'],opacity=.9)
        pad=16 if q.method in ('offset-crossing','translucent-planes') or form=='layers' else 0
        q.lane(i,b,lane_x+pad,y+6,lane_w-2*pad,h-14,numbered=form=='process')
        if form=='process' and i<len(blocks)-1:
            q.line(f'group.{i}.next',lane_x+pad+32,y+64,0,max(8,h+gap-64),endArrow=True)
        y+=h+gap


def _photo(q, blocks, images):
    top=q.head();bottom=660;n=len(blocks);gap=20
    if q.method=='offset-crossing':
        q.shape('spatial.backdrop',870,top,346,bottom-top,q.c['ink']);q.shape('spatial.offset',692,top,500,bottom-top-20,q.c['accent'])
    elif q.method=='type-weave':q.shape('spatial.photo-ground',684,top,532,bottom-top,q.c['surface'])
    elif q.method=='translucent-planes':
        q.shape('spatial.rear-plane',706,top,490,bottom-top,q.c['accent'],opacity=.4);q.shape('spatial.reading-plane',64,top,630,bottom-top,q.c['inverse'],opacity=.86)
    else:q.rings('spatial.rings',945,top+(bottom-top)/2,min(490,bottom-top))
    h=(bottom-top-gap*(n-1))/n
    for i,b in enumerate(blocks):q.block(i,b,84,top+i*(h+gap),530,h)
    ih=(bottom-top-gap*(len(images)-1))/len(images)
    for i,src in enumerate(images):q.add('image',f'image.{i}',692,top+i*(ih+gap),500,ih,src=src,fit='contain',alt='用户原始图片')


def _hub(q, blocks):
    top=q.head();height=660-top;core=blocks[0];related=blocks[1:];rh=(height-20*(len(related)-1))/len(related)
    if q.method=='concentric-relief':
        q.rings('spatial.rings',258,top+height/2,386)
        q.shape('spatial.hub-reading',92,top+54,292,height-84,q.c['inverse'])
    else:
        q.shape('spatial.hub-back',88,top+24,320,height-24,q.c['accent'],opacity=.3 if q.method=='translucent-planes' else 1)
        q.shape('spatial.hub-front',64,top,320,height-24,q.c['inverse'],opacity=.92)
    q.block(0,core,100,top+62,274,height-100)
    q.line('hub.root',410,top+height/2,38)
    first=top+rh/2;last=top+(len(related)-1)*(rh+20)+rh/2
    if last>first:q.line('hub.trunk',448,first,0,last-first)
    for i,b in enumerate(related):
        y=top+i*(rh+20)
        q.line(f'hub.link.{i}',448,y+rh/2,42)
        q.lane(i+1,b,506,y+8,706,rh-16)


def render(page, pack, master_id, images=()):
    from .template_packs import _scene
    if pack.get('rendererSHA256') != fingerprint():
        raise EngineError('TEMPLATE_PACK_CHANGED','空间模板与布局版本不一致，请重新构建模板库后再生成。')
    q=Layout(page,pack);blocks=(page.get('composition') or {}).get('blocks',[])
    m=pack['masters'][master_id]
    if not m['capacity'][0]<=len(blocks)<=m['capacity'][1]:q.fail('内容组数超出该版式范围')
    if len(images)>3:q.fail('当前图文版式每页最多保留3张原图')
    form=m['form']
    if form=='hero':_hero(q,blocks,images)
    elif images:_photo(q,blocks,images)
    elif form=='photo':q.fail('图文版式需要本项目原图')
    elif form=='hub':_hub(q,blocks)
    elif form=='columns':_columns(q,blocks)
    else:_rows(q,blocks,form)
    return _scene(page,pack,master_id,q.objects)
