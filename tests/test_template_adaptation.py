import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,MagicMock
from ppt_workbench.studio import Studio
from ppt_workbench.core import EngineError
from ppt_workbench import template_adaptation as adaptation
from ppt_workbench.model_profiles import select
from ppt_workbench.editor import travel

class TemplateAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Studio(self.tmp.name,'demo');self.s.demo();self.s.set_agent_mode('codex')
        self.before=self.s.get_scene('S001');self.rev=self.before['sceneRevision']
        self.candidate=copy.deepcopy(self.before['scene']);self.candidate['background']='#FDFDFD'
        self.candidate['objects']=[dict(o,x=20+(i*137)%600,y=20+(i*89)%400,w=max(40,o['w']//2),h=max(20,o['h']//2)) for i,o in enumerate(self.candidate['objects'])]
        self.png=Path(self.tmp.name)/'render.png';self.png.write_bytes(b'\x89PNG\r\n\x1a\n')
    def runner(self,*a,**kw):
        if a[2].get('generationTask',{}).get('kind')=='design_loop_review':
            return {'reply':'PASS\n层级与表达关系清楚。','actions':[]}
        return {'reply':'根据内容重建了模板的视觉分组。','questions':[],'actions':[{'type':'scene_replace','slide_id':'S001','base_revision':self.before['contentRevision'],'scene':self.candidate}]}
    def generate(self):
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=self.runner),patch('ppt_workbench.design_review.render_candidate',return_value=(Path(self.tmp.name)/'render.png',{'fontsReady':True,'overflow':[]})):
            return adaptation.propose(self.s,'reference-04-09','S001',self.rev)
    def test_original_reference_is_sent_and_apply_matches_preview_with_undo(self):
        calls=[]
        def run(*a,**kw):
            calls.append((a,kw));return self.runner(*a,**kw)
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=run),patch('ppt_workbench.design_review.render_candidate',return_value=(Path(self.tmp.name)/'render.png',{'fontsReady':True,'overflow':[]})):
            proposal=adaptation.propose(self.s,'reference-04-09','S001',self.rev)
        self.assertEqual(self.s.get_scene('S001'),self.before)
        expected=Path('ppt_workbench/web/reference-library/previews/04-09.png').read_bytes()
        self.assertEqual(Path(calls[0][1]['preview_png']).read_bytes(),expected)
        self.assertEqual(calls[0][0][2]['referenceLayout']['sourcePage'],adaptation.source_layout('reference-04-09')['sourcePage'])
        result=adaptation.apply(self.s,proposal['proposalId']);actual=self.s.get_scene('S001')
        self.assertEqual(actual['scene'],proposal['scene'])
        self.assertEqual(self.s.selected_template(),'reference-04-09')
        self.assertTrue(adaptation.apply(self.s,proposal['proposalId'])['alreadyApplied'])
        self.assertEqual(self.s.get_scene('S001')['sceneRevision'],actual['sceneRevision'])
        restored=travel(self.s,'S001',actual['sceneRevision'],'undo');self.assertEqual(restored['scene'],self.before['scene'])
    def test_changed_page_and_cross_project_cannot_apply(self):
        proposal=self.generate()
        other=Studio(self.tmp.name,'other')
        with self.assertRaises(EngineError) as e:adaptation.apply(other,proposal['proposalId'])
        self.assertEqual(e.exception.code,'PROPOSAL_NOT_FOUND')
        self.s.edit_scene('S001',self.rev,[{'objectId':'title','properties':{'color':'#654321'}}])
        newer=self.s.get_scene('S001')
        with self.assertRaises(EngineError):adaptation.apply(self.s,proposal['proposalId'])
        self.assertEqual(self.s.get_scene('S001'),newer)
    def test_missing_text_retries_three_times_and_never_changes_original(self):
        self.candidate['objects']=[o for o in self.candidate['objects'] if o['id']!='title']
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=self.runner) as run:
            with self.assertRaises(EngineError) as e:adaptation.propose(self.s,'reference-04-09','S001',self.rev)
        self.assertEqual(run.call_count,3);self.assertEqual(e.exception.code,'TEMPLATE_CONTENT_MISMATCH')
        self.assertEqual(self.s.get_scene('S001'),self.before)
    def test_overflow_never_publishes_proposal(self):
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=self.runner),patch('ppt_workbench.design_review.render_candidate',return_value=(Path('p.png'),{'fontsReady':True,'overflow':['title']})) as render:
            with self.assertRaises(EngineError) as e:adaptation.propose(self.s,'reference-04-09','S001',self.rev)
        self.assertEqual(render.call_count,3);self.assertEqual(e.exception.code,'TEMPLATE_OVERFLOW')
        with self.s.wb._connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM studio_template_proposals').fetchone()[0],0)
    def test_existing_images_keep_original_bytes_and_cannot_be_replaced(self):
        from test_studio import PNG
        source=copy.deepcopy(self.before['scene']);source['objects'].append({'id':'evidence','type':'image','x':100,'y':300,'w':100,'h':100,'src':'data:image/png;base64,'+PNG,'fit':'contain'})
        candidate=copy.deepcopy(source);candidate['objects'][-1]['src']='scene-image:S001/evidence'
        result=adaptation._validate_candidate(self.s,source,candidate,'reference-04-09')
        self.assertEqual(result['objects'][-1]['src'],source['objects'][-1]['src'])
        candidate['objects'][-1]['src']='https://example.com/picture.png'
        with self.assertRaises(EngineError):adaptation._validate_candidate(self.s,source,candidate,'reference-04-09')
    def test_direction_glyph_is_visual_but_new_body_text_is_rejected(self):
        candidate=copy.deepcopy(self.before['scene'])
        candidate['objects'].append({'id':'connector-arrow','type':'text','text':'→','x':300,'y':300,'w':32,'h':40,'fontSize':24})
        adaptation._validate_candidate(self.s,self.before['scene'],candidate,'reference-04-09')
        candidate['objects'][-1]['text']='虚构新业务结论'
        with self.assertRaises(EngineError):adaptation._validate_candidate(self.s,self.before['scene'],candidate,'reference-04-09')

    def test_source_geometry_exists_for_every_reference(self):
        from ppt_workbench.reference_templates import LAYOUTS
        for key in LAYOUTS:self.assertTrue(adaptation.source_layout('reference-'+key)['objects'])

class VisionApiTests(unittest.TestCase):
    def test_original_image_bytes_and_explicit_capability(self):
        from ppt_workbench.api_model_provider import run_api_turn
        from test_studio import PNG
        raw=base64.b64decode(PNG);profile={'model':'deepseek-flash','key_env':'TEST_KEY','base_url':'https://api.deepseek.com','vision':True}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'reply':'ok','questions':[],'actions':[]})}}]}).encode()
        with patch.dict('os.environ',{'TEST_KEY':'sentinel'}),patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            run_api_turn('reference',{'generationTask':{'kind':'template_adaptation'}},profile,30,image_bytes=raw)
            content=json.loads(opener.return_value.open.call_args.args[0].data)['messages'][1]['content']
            sent=json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertEqual(sent['reasoning_effort'],'low');self.assertEqual(sent['max_tokens'],8192)
            self.assertEqual(content[1]['image_url']['detail'],'original')
            self.assertEqual(base64.b64decode(content[1]['image_url']['url'].split(',')[1]),raw)
            with self.assertRaises(EngineError):run_api_turn('reference',{},dict(profile,vision=False),30,image_bytes=raw)

if __name__=='__main__':unittest.main()
