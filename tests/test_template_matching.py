import copy
import tempfile
import unittest
from unittest.mock import patch
from ppt_workbench.studio import Studio
from ppt_workbench.core import EngineError
from ppt_workbench.template_matching import match, content_plan

class TemplateMatchingTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.s=Studio(tmp.name,'matching');self.s.demo()
        self.before=self.s.get_scene('S003');self.rev=self.before['sceneRevision']

    def test_search_is_readonly_uses_original_previews_and_no_model(self):
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=AssertionError('No model before selection')),patch('ppt_workbench.jev_recommendations._request',side_effect=AssertionError('No classifier call')):
            result=match(self.s,'S003',self.rev,'展示问题与解决方案的对照')
        self.assertEqual(result['modelCalls'],0)
        self.assertEqual(result['expressionPlan']['relationship'],'compare')
        self.assertEqual(len(result['recommendations']),3)
        self.assertTrue(all(t['reference'] and t['referencePreviewUrl'] for t in result['recommendations']))
        self.assertEqual(result['recommendations'][0]['browseCategory'],'compare')
        self.assertIn('reference-04-09',[t['id'] for t in result['recommendations']])
        self.assertEqual(self.s.get_scene('S003'),self.before)
        with self.s.wb._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM studio_template_proposals').fetchone()[0],0)

    def test_explicit_intent_changes_ranking(self):
        result=match(self.s,'S003',self.rev,'按阶段表达流程')
        self.assertEqual(result['recommendations'][0]['browseCategory'],'process')
        self.assertEqual(result['recommendations'][0]['capacity'],4)
        self.assertTrue(all(t['browseCategory']=='process' for t in result['recommendations']))

    def test_current_scene_text_overrides_saved_page_copy(self):
        scene=copy.deepcopy(self.before['scene'])
        scene['objects']=[{'type':'text','text':'组织架构与层级','binding':'title'}, {'type':'text','text':'研发部、运营部'}]
        plan=content_plan(scene,{'title':'历史销售趋势','keyPoints':['旧收入数据']},'')
        self.assertEqual(plan['relationship'],'structure')

    def test_stale_and_cross_project_requests_fail(self):
        with self.assertRaises(EngineError):match(self.s,'S003',self.rev+1)
        other=Studio(self.s.wb.root,'empty')
        with self.assertRaises(EngineError):match(other,'S003',self.rev)
        with self.assertRaises(EngineError):match(self.s,'S003',self.rev,{'invalid':True})

    def test_cover_role_never_receives_content_templates(self):
        before=self.s.get_scene('S001')
        result=match(self.s,'S001',before['sceneRevision'],'流程与计划')
        self.assertTrue(all(t['role']=='cover' for t in result['recommendations']))

if __name__=='__main__':unittest.main()
