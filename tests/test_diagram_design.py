import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench.diagram_design import build_scene,validate_spec,submit_fallback
from ppt_workbench.agent_bridge import validate_plan
from ppt_workbench.image_generation import ImageJobs,GeneratedImage
from ppt_workbench import editor
from ppt_workbench.rendering import export_pptx

SPEC={'kind':'process','purpose':'说明完整流程','nodes':[
 {'id':'a','label':'输入材料','detail':'保留原稿与表达意图'},
 {'id':'b','label':'选择表达','detail':'先判断关系，再匹配版式','focus':True},
 {'id':'c','label':'继续编辑','detail':'文字和图形均可修改'}],
 'edges':[{'from':'a','to':'b'},{'from':'b','to':'c'}]}
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII=')
class Provider:
 def generate(self,prompt):return GeneratedImage(PNG,'image/png')

class DiagramTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.studio=Studio(self.tmp.name,'test');self.studio.set_agent_mode('manual')
 def add(self):
  j=self.studio.enqueue('做一页图解',client_message_id='initial')
  a={'type':'slide_add','title':'从材料到可编辑页面','user_intent':'展示流程','role':'content','diagram':SPEC}
  validate_plan({'reply':'完成','actions':[a]})
  result=self.studio.apply_plan(j['jobId'],{'reply':'完成','actions':[a]})
  return result['slideId']
 def test_deck_plan_preserves_diagram_for_page_generation(self):
  action={'type':'deck_start','title':'完整产品介绍','execution':'agent','pages':[
   {'title':'产品','user_intent':'介绍','role':'cover'},
   {'title':'产品流程','user_intent':'展示流程','role':'content','diagram':SPEC}]}
  validate_plan({'reply':'开始','actions':[action]})
  job=self.studio.enqueue('生成整套',scope='deck')
  self.studio.apply_plan(job['jobId'],{'reply':'开始','actions':[action]})
  with self.studio.wb._connection() as db:
   page=db.execute('SELECT plan FROM studio_deck_pages WHERE page_index=1').fetchone()
   self.assertEqual(json.loads(page['plan'])['diagram'],SPEC)
  broken=copy.deepcopy(action);broken['pages'][1]['diagram']['kind']='unknown'
  with self.assertRaises(EngineError):validate_plan({'reply':'开始','actions':[broken]})
 def test_empty_wire_reply_never_bypasses_action_validation(self):
  from ppt_workbench.agent_bridge import _decode_wire
  wire={'reply':'','questions':[], 'actions':[{'type':'slide_add','arguments_json':json.dumps(
    {'title':'产品','role':'cover','user_intent':'介绍产品'})}]}
  self.assertTrue(_decode_wire(wire)['reply'])
  wire['actions'][0]['arguments_json']='{}'
  with self.assertRaises(EngineError):_decode_wire(wire)
  wire['actions']=[]
  with self.assertRaises(EngineError):_decode_wire(wire)
 def test_native_scene_and_edit_and_pptx(self):
  sid=self.add();before=self.studio.get_scene(sid)
  self.assertTrue(self.studio.state()['slides'][0]['hasDiagram'])
  self.assertFalse(any(o['type']=='image' for o in before['scene']['objects']))
  updated=self.studio.change_scene(sid,before['sceneRevision'],[{'objectId':'dg-title-a','properties':{'text':'用户手改'}}])
  self.assertEqual(next(o['text'] for o in updated['scene']['objects'] if o['id']=='dg-title-a'),'用户手改')
  import zipfile
  p=Path(self.tmp.name)/'native.pptx';export_pptx([updated['scene']],p)
  with zipfile.ZipFile(p) as z:
   xml=z.read('ppt/slides/slide1.xml').decode();self.assertIn('用户手改',xml);self.assertNotIn('<p:pic>',xml)
 def test_fallback_keeps_heading_original_bytes_and_undo(self):
  sid=self.add();before=self.studio.get_scene(sid)
  response=submit_fallback(self.studio,sid,before['sceneRevision'],'click1')
  self.assertEqual(self.studio.get_scene(sid),before)
  self.assertTrue(submit_fallback(self.studio,sid,before['sceneRevision'],'click1')['deduplicated'])
  ImageJobs(self.studio).run_batch(response['jobId'],Provider())
  after=self.studio.get_scene(sid);self.assertNotIn('diagram',after['scene'])
  img=next(o for o in after['scene']['objects'] if o['type']=='image')
  self.assertEqual(base64.b64decode(img['src'].split(',')[1]),PNG)
  self.assertEqual(next(o for o in before['scene']['objects'] if o['id']=='title'),next(o for o in after['scene']['objects'] if o['id']=='title'))
  editor.travel(self.studio,sid,after['sceneRevision'],'undo')
  self.assertEqual(self.studio.get_scene(sid)['scene'],before['scene'])
 def test_stale_result_does_not_overwrite_and_current_text_in_prompt(self):
  sid=self.add();before=self.studio.get_scene(sid)
  current=self.studio.change_scene(sid,before['sceneRevision'],[{'objectId':'dg-title-a','properties':{'text':'手改不可覆盖'}}])
  with self.assertRaises(EngineError):submit_fallback(self.studio,sid,before['sceneRevision'],'stale')
  job=submit_fallback(self.studio,sid,current['sceneRevision'],'accepted')
  class EditingProvider:
   def generate(_,prompt):
    self.assertIn('手改不可覆盖',prompt)
    self.studio.change_scene(sid,current['sceneRevision'],[{'objectId':'dg-title-a','properties':{'text':'再次修改'}}])
    return GeneratedImage(PNG,'image/png')
  ImageJobs(self.studio).run_batch(job['jobId'],EditingProvider())
  self.assertEqual(self.studio.state()['imageBatches'][0]['status'],'conflict')
  self.assertIn('diagram',self.studio.get_scene(sid)['scene'])
 def test_provider_failure_preserves_original(self):
  sid=self.add();before=self.studio.get_scene(sid);job=submit_fallback(self.studio,sid,before['sceneRevision'],'fail')
  class BadProvider:
   def generate(_,prompt):raise RuntimeError('provider error')
  ImageJobs(self.studio).run_batch(job['jobId'],BadProvider())
  self.assertEqual(self.studio.get_scene(sid)['scene'],before['scene'])
 def test_scope_cannot_replace_selected_object_or_other_page(self):
  sid=self.add();current=self.studio.get_scene(sid)
  job=self.studio.enqueue('改一个字',sid,'dg-title-a')
  with self.assertRaises(EngineError):self.studio.apply_plan(job['jobId'],{'reply':'x','actions':[{'type':'diagram_image','slide_id':sid,'base_scene_revision':current['sceneRevision']}]})
 def test_validation_rejects_lossy_or_unknown_relationships(self):
  for spec in [{**SPEC,'nodes':SPEC['nodes']*3},{**SPEC,'edges':[{'from':[],'to':'b'}]},
   {**SPEC,'edges':[{'from':'a','to':'c'}]},{**SPEC,'nodes':[dict(n,detail='文'*101) for n in SPEC['nodes']]}]:
   with self.assertRaises(EngineError):validate_spec(spec)
 def test_all_native_layouts_fit_canvas(self):
  for kind,count in [('process',6),('layers',6),('hub',5),('comparison',6)]:
   spec={'kind':kind,'nodes':[{'id':f'n{i}','label':f'节点{i}','detail':'真实内容保留'} for i in range(count)],'edges':[]}
   build_scene({'id':'S001','title':'完整图解'},spec)
 def test_diagram_remains_editable_after_template_preview(self):
  from ppt_workbench.templates import apply_template
  sid=self.add();scene=self.studio.get_scene(sid)['scene'];result=apply_template(scene,'clean')
  self.assertEqual(sorted(o['text'] for o in scene['objects'] if o['type']=='text'),sorted(o['text'] for o in result['objects'] if o['type']=='text'))
