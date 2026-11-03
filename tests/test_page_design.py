import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ppt_workbench.studio import Studio
from ppt_workbench.core import EngineError
from ppt_workbench.agent_bridge import validate_plan
from ppt_workbench.page_design import prepare_scene
from ppt_workbench.design_review import review_new_page
from ppt_workbench.rendering import scene_from_slide

COMPOSITION={'purpose':'解释能力边界','relationship':'comparison','blocks':[
 {'id':'now','heading':'已实现','body':'直接修改文字与布局'},
 {'id':'later','heading':'待验证','body':'复杂文件的兼容性'}]}

def action():
 texts=[('title','能力边界',64,48,48),('now','已实现',64,200,30),('now-body','直接修改文字与布局',64,280,26),
        ('later','待验证',680,200,30),('later-body','复杂文件的兼容性',680,280,26)]
 objects=[{'id':i,'type':'text','text':t,'x':x,'y':y,'w':500,'h':80,'fontSize':size,**({'binding':'title'} if i=='title' else {})} for i,t,x,y,size in texts]
 return {'type':'slide_add','title':'能力边界','role':'content','user_intent':'说明边界','composition':copy.deepcopy(COMPOSITION),
         'scene':{'schema':'ppt-scene','schemaVersion':1,'slideId':'S001','background':'#FFFFFF','objects':objects}}

class PageDesignTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.studio=Studio(self.tmp.name,'test');self.studio.set_agent_mode('manual')
 def test_authored_layout_retained_with_selected_template_and_real_id(self):
  self.studio.select_template('dark')
  for _ in range(2):
   a=action();j=self.studio.enqueue('新建页');result=self.studio.apply_plan(j['jobId'],{'reply':'完成','actions':[a]})
   saved=self.studio.get_scene(result['slideId'])['scene']
   self.assertEqual(saved['slideId'],result['slideId']);self.assertEqual(saved['background'],'#FFFFFF')
   self.assertEqual(saved['objects'],prepare_scene(a)['objects'])
  self.assertEqual(result['slideId'],'S002')
 def test_original_asset_reference_resolves_without_transcoding(self):
  import base64
  from test_diagram_design import PNG
  uploaded=self.studio.upload('original.png','image/png',base64.b64encode(PNG).decode())
  a=action();a['scene']['objects'].append({'id':'evidence','type':'image','src':'asset:'+uploaded['assetId'],'x':64,'y':400,'w':200,'h':100})
  validate_plan({'reply':'完成','actions':[a]})
  j=self.studio.enqueue('带原图的新页');out=self.studio.apply_plan(j['jobId'],{'reply':'完成','actions':[a]})
  scene=self.studio.get_scene(out['slideId'])['scene']
  self.assertEqual(base64.b64decode(next(o['src'] for o in scene['objects'] if o['type']=='image').split(',')[1]),PNG)
 def test_content_omission_rejected_atomically(self):
  a=action();a['scene']['objects'].pop();j=self.studio.enqueue('新建')
  with self.assertRaises(EngineError):self.studio.apply_plan(j['jobId'],{'reply':'完成','actions':[a]})
  self.assertEqual(self.studio.state()['slides'],[])
 def test_exact_unique_title_gets_binding_without_changing_content(self):
  a=action();a['scene']['objects'][0].pop('binding')
  scene=prepare_scene(a)
  self.assertEqual(scene['objects'][0]['binding'],'title')
  self.assertEqual(scene['objects'][0]['text'],a['title'])
  a['scene']['objects'][0]['text']='模型改写的标题'
  with self.assertRaises(EngineError):prepare_scene(a)
  a=action();a['scene']['objects'][0].pop('binding');extra=copy.deepcopy(a['scene']['objects'][0]);extra['id']='duplicate';a['scene']['objects'].append(extra)
  self.assertEqual(sum(o.get('binding')=='title' for o in prepare_scene(a)['objects']),1)  # Exactly one copy is bound.
 def test_text_references_preserve_original_words_and_reject_unknown_sources(self):
  a=action()
  refs=['title','block.now.heading','block.now.body','block.later.heading','block.later.body']
  for obj,ref in zip(a['scene']['objects'],refs):obj.pop('text');obj['textRef']=ref
  resolved=prepare_scene(a)
  self.assertEqual([o['text'] for o in resolved['objects']],[o['text'] for o in action()['scene']['objects']])
  self.assertTrue(all('textRef' not in o for o in resolved['objects']))
  a['scene']['objects'][2]['textRef']='block.missing.body'
  with self.assertRaises(EngineError):prepare_scene(a)
  a['scene']['objects'][2]['textRef']='block.now.body';a['scene']['objects'][2]['text']='缩写'
  # A retyped (possibly shortened) copy never reaches the page: the planned words win.
  self.assertEqual(prepare_scene(a)['objects'][2]['text'],'直接修改文字与布局')
 def test_minimal_deck_action_uses_saved_content_and_resolves_references(self):
  a=action();planned={k:v for k,v in a.items() if k not in {'type','scene'}}
  planned.update(takeaway='明确能力边界',key_points='已实现：直接修改文字与布局\n待验证：复杂文件的兼容性')
  self.studio.create_deck({'title':'方案原文测试','execution':'agent','pages':[planned,planned]},'用户原话','agent')
  pending=self.studio.next_job();a.pop('composition')
  for obj,ref in zip(a['scene']['objects'],['title','block.now.heading','block.now.body','block.later.heading','block.later.body']):
   obj.pop('text');obj['textRef']=ref
  out=self.studio.apply_plan(pending['job']['id'],{'reply':'生成当前页','actions':[a]})
  slide=self.studio.wb.get_slide('test',out['slideId'])['slide']
  self.assertEqual(slide['takeaway'],planned['takeaway']);self.assertEqual(slide['keyPoints'],planned['key_points'])
  self.assertEqual(self.studio.get_scene(out['slideId'])['scene']['objects'],prepare_scene(action())['objects'])
 def test_plan_accepts_structured_content_and_design(self):
  p={'title':'产品介绍','execution':'agent','design':{'background':'#FFFFFF','ink':'#142D50','accent':'#C49A2B','fontFamily':'Microsoft YaHei'},
     'pages':[{k:v for k,v in action().items() if k not in {'type','scene'}}]*2}
  validate_plan({'reply':'计划','actions':[{'type':'deck_start',**p}]})
 def test_footer_is_not_automatically_inserted(self):
  scene=scene_from_slide({'id':'S001','title':'当前页','role':'content','keyPoints':'文字'},{'title':'重复主题'})
  self.assertNotIn('重复主题',[o.get('text') for o in scene['objects']])
  a=action();a['scene']['objects'].append({'id':'footer.project','type':'text','text':'主题','x':64,'y':670,'w':400,'h':30})
  with self.assertRaises(EngineError):prepare_scene(a)
 def fake_render(self,scene,folder):
  folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);p=folder/'candidate.png';p.write_bytes(b'\x89PNG\r\n\x1a\n')
  return p,{'fontsReady':True,'overflow':[]}
 def test_review_repairs_only_draft_and_keeps_words(self):
  a=action();plan={'reply':'初稿','actions':[a]};revised=copy.deepcopy(a);revised['scene']['objects'][1]['x']=100
  with patch('ppt_workbench.design_review.render_candidate',side_effect=self.fake_render):
   out=review_new_page(self.studio,{'id':'J-test'},plan,{'currentDeckPage':a},'codex',lambda *args,**kwargs:{'reply':'REVISE\n改善间距','actions':[revised]})
  self.assertEqual(out['actions'][0]['scene']['objects'][1]['x'],100);self.assertEqual(self.studio.state()['slides'],[])
 def test_saved_plan_owns_metadata_while_visible_text_is_checked(self):
  a=action();planned=copy.deepcopy(a);a['composition']['purpose']='同一页的另一种方案说明'
  with patch('ppt_workbench.design_review.render_candidate',side_effect=self.fake_render):
   out=review_new_page(self.studio,{'id':'J-metadata'},{'reply':'初稿','actions':[a]},{'currentDeckPage':planned},'codex',lambda *args,**kwargs:{'reply':'PASS\n可读','actions':[]})
  self.assertEqual(out['actions'][0]['composition'],planned['composition'])
  a['scene']['objects'].pop()
  with self.assertRaises(EngineError):
   review_new_page(self.studio,{'id':'J-missing'},{'reply':'初稿','actions':[a]},{'currentDeckPage':planned},'codex',lambda *args,**kwargs:self.fail('must reject before review'))
 def test_review_cannot_drop_or_rewrite_content(self):
  a=action();plan={'reply':'初稿','actions':[a]};revised=copy.deepcopy(a);revised['scene']['objects'].append({'id':'extra','type':'text','text':'虚构增长','x':50,'y':500,'w':100,'h':40})
  with patch('ppt_workbench.design_review.render_candidate',side_effect=self.fake_render):
   out=review_new_page(self.studio,{'id':'J-bad'},plan,{'currentDeckPage':a},'codex',lambda *args,**kwargs:{'reply':'REVISE\n完成','actions':[revised]})
  self.assertEqual(out['actions'],plan['actions']);self.assertIn('未完成',out['reply'])
 def test_diagram_reviewer_receives_rendered_objects_and_metadata(self):
  a=action();a.pop('scene');a['diagram']={'kind':'comparison','purpose':'边界对照','nodes':[
   {'id':b['id'],'label':b['heading'],'detail':b['body']} for b in COMPOSITION['blocks']],'edges':[]}
  def reviewer(mode,prompt,context,**kwargs):
   scene=copy.deepcopy(context['candidateScene'])
   self.assertEqual(scene['diagram']['kind'],'comparison')
   scene['objects'][0]['x']+=2
   revised={k:v for k,v in a.items() if k!='diagram'};revised['scene']=scene
   return {'reply':'REVISE\n调整标题位置，保留图解信息','actions':[revised]}
  with patch('ppt_workbench.design_review.render_candidate',side_effect=self.fake_render):
   out=review_new_page(self.studio,{'id':'J-diagram'},{'reply':'初稿','actions':[a]},{'currentDeckPage':a},'codex',reviewer)
  self.assertIn('scene',out['actions'][0])
  self.assertEqual(out['actions'][0]['scene']['diagram'],prepare_scene(a)['diagram'])
 def test_unsupported_visual_review_never_claims_reviewed(self):
  a=action()
  with patch('ppt_workbench.design_review.render_candidate',side_effect=self.fake_render):
   def reviewer(*args,**kwargs):
    self.assertNotIn('preview_png',kwargs)
    return {'reply':'PASS\n结构合理，未看图','actions':[]}
   review_new_page(self.studio,{'id':'J-claude'},{'reply':'初稿','actions':[a]},{'currentDeckPage':a},'claude',reviewer)
  report=json.loads((self.studio.wb.project_dir('test')/'design-reviews/J-claude/pass-1/report.json').read_text())
  self.assertEqual(report['reviewMode'],'structure-only');self.assertEqual(report['status'],'reviewed');self.assertFalse(report['humanAccepted'])
