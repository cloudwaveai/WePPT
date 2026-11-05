"""Build versioned editable masters once; runtime never redraws them with an LLM.
Geometry is a documented interpretation of reviewed screenshots, not an exact PPTX import.
No source photographs, brand marks, sample facts, or screenshot text are bundled as content.
"""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'ppt_workbench/data/template-packs';OUT.mkdir(parents=True,exist_ok=True)
refs=json.loads((OUT/'sources.json').read_text())['samples']
def reference(prefix):
 return [{k:r[k] for k in ('file','title','sourceUrl','sha256','role')} for r in refs if r['file'].startswith(prefix)]
def rect(id,x,y,w,h,fill,**kw):return dict(id=id,type='rect',x=x,y=y,w=w,h=h,fill=fill,**kw)
def line(id,x,y,w,h,color):return dict(id=id,type='line',x=x,y=y,w=w,h=h,stroke=color,strokeWidth=1)
colors={'crimson-grid-v1':{'paper':'#F7F5F1','ink':'#651F16','accent':'#651F16','surface':'#EEE8E2','muted':'#66564D','inverse':'#FFFFFF'},
        'blue-editorial-v1':{'paper':'#F4F7FB','ink':'#293F61','accent':'#5578A8','surface':'#E3EBF6','muted':'#475D79','inverse':'#FFFFFF'},
        'forest-editorial-v1':{'paper':'#111713','ink':'#F1F2E8','accent':'#A8BA83','surface':'#253328','muted':'#C8D0C0','inverse':'#111713'}}
packs=[]
for pid,name,prefix,principles in [
 ('crimson-grid-v1','绛红方格','02-', ['大面积纸白与绛红建立主次；封面网格提供秩序，正文采用红色标题带与完整说明区。','封面居中，章节复用标题区域，正文按内容在分栏与宽行之间匹配。']),
 ('blue-editorial-v1','蓝白图文','20-', ['从原页保留左文右图、上下层次和同一基线；真实图片充当主视觉。','没有用户图片时选文字变体，不生成空图框或装饰圆来代替图片。']),
 ('forest-editorial-v1','墨绿编辑','00-', ['保留深色底、醒目文字和横向分割；有图片时使用分区图文，不复制参考品牌与摄影。','内容之间用留白与细线分层，不把所有信息装进同样的卡片。'])]:
 c=colors[pid]
 fixed=[]
 if pid.startswith('crimson'):
  fixed=[rect('master.top',0,0,1280,12,c['accent']),rect('master.bottom',0,708,1280,12,c['accent'])]
 elif pid.startswith('forest'):
  fixed=[line('master.rule',72,130,1136,0,c['accent'])]
 else:
  fixed=[line('master.rule',72,130,1136,0,'#B8C8DF')]
 title={'x':72,'y':42,'w':1136,'h':74,'fontSize':44,'color':c['ink'],'bold':True,'fontFamily':'Microsoft YaHei','lineHeight':1.15}
 body={'x':72,'y':174,'w':1136,'h':470}
 masters={}
 for role in ['cover','chapter','ending']:
  decor=[]
  if pid.startswith('crimson'):
   decor=[rect('master.corner.1',0,0,72,40,c['accent']),rect('master.corner.2',1208,680,72,40,c['accent'])]
   for i,x in enumerate(range(0,1281,40)):decor.append(line('master.grid.x'+str(i),x,192,0,360,'#E1DDD7'))
   for i,y in enumerate(range(192,553,40)):decor.append(line('master.grid.y'+str(i),0,y,1280,0,'#E1DDD7'))
  else:decor=[line('master.cover.rule',72,146,1136,0,c['accent'])]
  masters[role]={'role':role,'roles':[role],'form':'hero','capacity':[0,3],
    'provenance':{'referenceRole':'cover','basis':'visible-screenshot-estimate' if role=='cover' else 'derived-from-cover','changes':'去除示例品牌、英文眉题、署名与口号；标题高度适应中文换行。'},
    'fixed':decor,'title':dict(title,x=88,y=208,w=1104,h=192,fontSize=82 if role=='cover' else 70,align='center' if pid.startswith('crimson') else 'left'),
    'contentRegion':{'x':120,'y':432,'w':1040,'h':214}}
 for form,capacity,relations in [('columns',[2,4],['parallel','compare','comparison']),('rows',[1,6],['parallel','summary','argument','evidence','general','cause','product','structure']),('process',[2,5],['process','timeline','cycle']),('photo',[1,3],['evidence','product','parallel']),('layers',[2,5],['layers']),('hub',[2,5],['hub'])]:
  masters['body-'+form]={'role':'content','roles':['content','toc','appendix'],'form':form,'capacity':capacity,'relationships':relations,
    'provenance':{'referenceRole':'body','basis':'visible-screenshot-estimate' if (pid.startswith('crimson') and form=='columns') or (pid.startswith('blue') and form=='photo') else 'derived-variant',
                  'changes':'按同套标题基线、色彩角色和分组方式形成变体；原页数量不是固定槽位，保留每组标题与正文的对应关系。'},
    'fixed':fixed,'title':title,'contentRegion':body,
    'headingStyle':{'fontSize':30,'bold':True,'color':c['ink'],'lineHeight':1.2},
    'bodyStyle':{'fontSize':24,'color':c['ink'],'lineHeight':1.4},
    'groupStyle':{'panel':pid.startswith('crimson'),'headingBand':pid.startswith('crimson'),'rule':not pid.startswith('crimson')}}
 packs.append({'id':pid,'version':1,'name':name,'description':principles[0],'principles':principles,'sources':reference(prefix),
   'extraction':{'observed':principles,'estimated':'1280×720 页面；从截图估算可见分区与对齐，不声称获得原生对象参数。',
      'fixed':['整套色彩角色','标题基线','正文阅读区','图文层级'],
      'adaptable':['按关系选择正文变体','按真实组数重复内容模块','长文改宽行','已有图片的位置与说明'],
      'notImported':['参考原文与品牌','参考摄影与截图','无法确认的透明度、渐变与内部图层']},
   'colors':c,'masters':masters})
# Four spatial methods are the visible library for new work. Historical packs
# remain byte-for-byte compatible with already-bound jobs and stored preferences.
import sys
sys.path.insert(0,str(ROOT))
from ppt_workbench.spatial_templates import fingerprint
spatial_refs=json.loads((OUT/'spatial-sources.json').read_text())['references']
spatial=[]
for method,name,source_ids,palette,relations in [
 ('type-weave','字图穿插',['R44-01'],['#E9B8C3','#164C39','#164C39','#FFF5DB','#FFF5DB'],
  ['以字体尺度和字图前后关系建立主次，保护标题和证据完整。','长文使用大标题侧栏与独立阅读轴，不退回等大卡片。']),
 ('offset-crossing','跨界错位',['S201-01','S201-04','R20-04'],['#F4F2E8','#263C2A','#849A3D','#CCD5B8','#A0B65F'],
  ['主体跨过深浅分界，底板错位露边；没有原图时使用完整文字构图，不生成空图框。','按真实关系选择错位并列、顺序宽行、层级或中心连接，不能只因数量相同就替换关系。']),
 ('translucent-planes','透叠层面',['R42-05'],['#E9ECF5','#172C61','#4763B5','#D7DEF1','#97B7D5'],
  ['后层在透明板下保持可见，文字保持实色，透明观感不冒充玻璃材质。','信息增加时把透叠集中到边缘，完整保留阅读区；流程不能强加为四层结构。']),
 ('concentric-relief','同心浮雕',['S350-01','S627-01'],['#F0F3F0','#243D31','#3F845A','#D6E1D3','#8CB59A'],
  ['共心层面与统一边缘明暗建立浅浮雕，不用圆弧假装完成率或指标。','只有明确的中心关系才把内容围绕中心；并列和流程采用独立阅读区，圆形母题退向边缘。'])]:
 pid='spatial-'+method+'-v1';paper,ink,accent,surface,secondary=palette
 masters={}
 for role in ('cover','chapter','ending'):
  masters[role]=dict(role=role,roles=[role],form='hero',capacity=[0,3],relationships=['hero'],
    provenance=dict(basis='source-derived-spatial-adaptation',sourcePages=source_ids))
 for form,capacity,relationships in [('columns',[2,4],['parallel','comparison']),('rows',[1,6],['parallel','comparison','evidence','summary','hero']),('process',[2,6],['process']),('photo',[1,3],['evidence','parallel','comparison','summary','hero']),('layers',[2,5],['layers']),('hub',[2,5],['hub'])]:
  masters['body-'+form]=dict(role='content',roles=['content','toc','appendix'],form=form,capacity=capacity,relationships=relationships,
    provenance=dict(basis='source-derived-spatial-adaptation',sourcePages=source_ids))
 spatial.append(dict(id=pid,version=1,name=name,spatialMethod=dict(id=method,invariants=relations,
    limitations='摄影、人物、复杂材质与精确原生图层未导入；只使用本项目真实原图和独立原生文字图形。'),
    description=relations[0],principles=relations,sources=[spatial_refs[k] for k in source_ids],
    rendererSHA256=fingerprint(),colors=dict(paper=paper,ink=ink,accent=accent,surface=surface,secondary=secondary,inverse='#FFFFFF',muted=ink),masters=masters))
manifest={'schema':'weppt-template-packs','version':1,'packs':spatial+packs}
(OUT/'catalog.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
inventory={'reviewSelected':json.loads((OUT/'sources.json').read_text())['reviewSelected'],
 'existingOriginalLibrary':{'path':'web/reference-library/catalog.json','templates':44,'status':'reference-only-unless-imported'},
 'readyPacks':[p['id'] for p in spatial], 'legacyPacks':[p['id'] for p in packs], 'note':'素材参考与可执行模板分开计数；新增四种空间关系用于新稿；旧三套只保留历史任务兼容。未将所有素材或分析记录算作可执行模板。'}
(OUT/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2))
print('Built',len(spatial),'spatial packs +',len(packs),'historical packs')
