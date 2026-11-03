import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from ppt_workbench.core import EngineError
from ppt_workbench.design_loop import review_candidate, experiences
from ppt_workbench.diagram_design import guidance_for_page
from ppt_workbench.studio import Studio
from ppt_workbench.template_adaptation import propose,apply
from ppt_workbench.editor import travel
from test_page_design import action
from ppt_workbench.page_design import prepare_scene

class DesignLoopTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.scene=prepare_scene(action());self.context={'sceneSpec':{},'diagramDesign':guidance_for_page({'title':'记忆闭环'})}
    def render(self,scene,folder):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);p=folder/'candidate.png';p.write_bytes(b'\x89PNG\r\n\x1a\n')
        return p,{'fontsReady':True,'overflow':[]}
    def loop(self,runner,**kwargs):
        with patch('ppt_workbench.design_review.render_candidate',side_effect=self.render):
            return review_candidate(self.scene,self.root/'review',self.context,'claude',runner,lambda a:a['scene'],'仅返回候选 scene',**kwargs)
    def test_one_repair_then_verify_bounded_and_no_fake_vision(self):
        calls=[];candidate=copy.deepcopy(self.scene);candidate['objects'][0]['x']=80
        def runner(mode,prompt,context,**kw):
            calls.append(context);self.assertNotIn('preview_png',kw)
            return {'reply':'REVISE\n调整标题','actions':[{'scene':candidate}]} if len(calls)==1 else {'reply':'PASS\n检查通过','actions':[]}
        final,_,report=self.loop(runner)
        self.assertEqual(final,candidate);self.assertEqual(report['status'],'revised_and_reviewed');self.assertEqual(len(calls),2)
        self.assertEqual(calls[1]['candidateScene'],candidate);self.assertEqual(report['reviewMode'],'structure-only');self.assertFalse(report['humanAccepted'])
        self.assertEqual(calls[0]['diagramDesign']['selectedType'],'cycle')
        self.assertEqual(calls[1]['previousReview']['reply'],'REVISE\n调整标题')
        self.assertTrue(calls[1]['previousReview']['repairAccepted'])
    def test_repeated_revision_cannot_start_unbounded_loop(self):
        final,_,report=self.loop(lambda *a,**k:{'reply':'REVISE\n继续改','actions':[{'scene':self.scene}]})
        self.assertEqual(report['modelCalls'],2);self.assertEqual(report['status'],'needs_attention')
    def test_error_and_missing_verdict_never_claim_success(self):
        def fail(*a,**k):raise EngineError('MODEL_ERROR','模型调用失败')
        for runner in (fail,lambda *a,**k:{'reply':'看起来还行','actions':[]}):
            final,_,report=self.loop(runner)
            self.assertEqual(final,self.scene);self.assertEqual(report['status'],'needs_attention')
    def test_budget_stops_before_extra_call(self):
        final,_,report=self.loop(lambda *a,**k:self.fail('No model call'),deadline=time.monotonic()-1)
        self.assertEqual(report['modelCalls'],0);self.assertEqual(report['status'],'budget_exhausted')
    def test_vision_capability_controls_actual_image_delivery(self):
        def runner(mode,prompt,context,**kw):
            self.assertIn('preview_png',kw);self.assertEqual(Path(kw['preview_png']).read_bytes(),b'\x89PNG\r\n\x1a\n')
            return {'reply':'PASS\n已看图','actions':[]}
        with patch('ppt_workbench.design_review.render_candidate',side_effect=self.render),patch('ppt_workbench.model_profiles.resolve',return_value={'vision':True}):
            _,_,report=review_candidate(self.scene,self.root/'vision',self.context,'api',runner,lambda a:a['scene'],'scene',model_binding={'id':'test'})
        self.assertEqual(report['reviewMode'],'image-and-structure')
    def test_candidate_patch_is_isolated_and_revision_bound(self):
        from ppt_workbench.design_loop import patch_candidate
        original=copy.deepcopy(self.scene)
        a={'type':'scene_patch','slide_id':'S001','base_scene_revision':1,'changes':[{'objectId':'title','properties':{'x':80}}]}
        revised=patch_candidate(self.scene,a,1)
        self.assertEqual(revised['objects'][0]['x'],80);self.assertEqual(self.scene,original)
        with self.assertRaises(EngineError):patch_candidate(self.scene,a,2)
        b={'type':'scene_objects','slide_id':'S001','base_scene_revision':1,'operations':[{'op':'add','object':{'id':'extra','type':'text','text':'额外文案','x':1,'y':1,'w':100,'h':30}}]}
        with self.assertRaises(EngineError):patch_candidate(self.scene,b,1)
        b['operations'][0]['object']['text']='→'
        arrow=patch_candidate(self.scene,b,1)
        self.assertEqual(arrow['objects'][-1]['text'],'→')
    def test_skill_selection_reads_visible_body_and_notes(self):
        self.assertEqual(guidance_for_page({'title':'Agent Memory','keyPoints':['结果会再次供后续任务取用']})['selectedType'],'cycle')
        guide=guidance_for_page({'title':'Agent Memory','notes':'反馈回路返回保存环节'})
        self.assertEqual(guide['selectedType'],'cycle')
        self.assertEqual(guide['runtimeReference'],'adaptations/feedback-flow.md')
        self.assertEqual(guidance_for_page({'notes':'新的反馈返回保存环节。'})['selectedType'],'cycle')
        self.assertNotIn('exactly one hub',guide['selectedTypeReference'])
        shared=guidance_for_page({'title':'共享记忆库的更新闭环'})
        self.assertEqual(shared['selectedType'],'loop')
        self.assertEqual(shared['runtimeReference'],'references/type-loop.md')

    def test_review_keeps_source_content_separate_from_wrong_candidate(self):
        from ppt_workbench.design_loop import semantic_source
        original=copy.deepcopy(self.scene)
        original['notes']='反馈返回保存环节，不返回输入。'
        self.context['semanticSource']=semantic_source(original)
        self.scene['notes']='候选错误地返回输入'
        def runner(mode,prompt,ctx,**kw):
            self.assertEqual(ctx['semanticSource']['notes'],original['notes'])
            self.assertEqual(ctx['candidateScene']['notes'],'候选错误地返回输入')
            self.assertNotIn('objects',ctx['semanticSource'])
            return {'reply':'NEEDS_ATTENTION\n反馈目标错误','actions':[]}
        _,_,report=self.loop(runner)
        self.assertEqual(report['status'],'needs_attention')

    def test_applied_experience_is_project_scoped_and_undo_excludes_it(self):
        s=Studio(self.root/'workspace','demo');s.demo();s.set_agent_mode('codex');before=s.get_scene('S003')
        def runner(mode,prompt,context,**kw):
            self.assertIn('diagramDesign',context)
            if context['generationTask']['kind']=='design_loop_review':return {'reply':'PASS\n清楚','actions':[]}
            self.assertEqual(context['adaptationApproach'],'creative')
            self.assertEqual(context['semanticSource']['notes'],before['scene'].get('notes',''))
            self.assertEqual(len(context['semanticSource']['text']),sum(o['type']=='text' for o in before['scene']['objects']))
            moved=copy.deepcopy(before['scene']);spots=[(o['x'],o['y']) for o in moved['objects'] if o['type'] in ('text','image')][::-1]
            moved['objects']=list(moved['objects'])
            moved['objects']=[dict(o,x=(o['x']+400)%max(1,1280-o['w']),y=(o['y']+300)%max(1,720-o['h'])) if o['type'] in ('text','image') else o for o in moved['objects']]
            return {'reply':'借鉴配色，自由组织','actions':[{'type':'scene_replace','slide_id':'S003','base_revision':before['contentRevision'],'scene':moved}]}
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=runner),patch('ppt_workbench.design_review.render_candidate',side_effect=self.render):
            proposal=propose(s,'reference-04-09','S003',before['sceneRevision'])
        relation=proposal['relationship'];self.assertEqual(experiences(s,relation)['items'],[])
        apply(s,proposal['proposalId']);self.assertEqual(len(experiences(s,relation)['items']),1)
        other=Studio(self.root/'workspace','other');self.assertEqual(experiences(other,relation)['items'],[])
        current=s.get_scene('S003');travel(s,'S003',current['sceneRevision'],'undo')
        self.assertEqual(experiences(s,relation)['items'],[])

if __name__=='__main__':unittest.main()
