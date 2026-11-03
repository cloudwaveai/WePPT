"""Model routing contracts. API/CLI mocks are not live-model acceptance."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch, MagicMock
from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench import model_profiles as models
from ppt_workbench.agent_bridge import run_turn, _command


class ModelProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.config=self.root/'models.json'
        self.entries=[{'id':'ds','label':'DeepSeek · API','mode':'api','model':'deepseek-flash','base_url':'https://api.deepseek.com','key_env':'TEST_MODEL_KEY'}]
        self.save()
        self.env=patch.dict(os.environ,{'WEPPT_MODEL_PROFILES_FILE':str(self.config),'TEST_MODEL_KEY':'secret-sentinel'})
        self.env.start();self.addCleanup(self.env.stop)
        self.s=Studio(self.root/'data','a')
    def save(self):self.config.write_text(json.dumps(self.entries))
    def error(self,code,fn,*a,**kw):
        with self.assertRaises(EngineError) as e:fn(*a,**kw)
        self.assertEqual(e.exception.code,code)
    def test_public_state_selection_and_project_isolation(self):
        state=models.select(self.s,'ds')
        self.assertEqual(state['agent']['mode'],'api')
        serialized=json.dumps(state)
        for private in ('base_url','key_env','secret-sentinel','api.deepseek.com'):self.assertNotIn(private,serialized)
        self.assertEqual(models.selected(Studio(self.root/'data','a'))['id'],'ds')
        self.assertIsNone(models.selected(Studio(self.root/'data','b')))
        self.s.set_agent_mode('manual');self.assertIsNone(models.selected(self.s))
    def test_config_validation_and_removed_profile_can_be_reselected(self):
        models.select(self.s,'ds')
        saved=models.selected(self.s)
        self.entries=[];self.save()
        self.assertEqual(self.s.state()['selectedModelProfile']['model'],'unavailable')
        self.error('MODEL_PROFILE_CHANGED',models.resolve,saved)
        self.error('MODEL_PROFILE_CHANGED',self.s.enqueue,'do something')
        self.entries=[{'id':'replacement','label':'New API','mode':'api','model':'other','base_url':'https://api.deepseek.com','key_env':'TEST_MODEL_KEY'}];self.save()
        models.select(self.s,'replacement')
        self.entries[0]['base_url']='https://credential@example.com';self.save()
        self.error('MODEL_CONFIG_INVALID',models.profiles)
    def test_bound_jobs_ignore_later_legacy_mode_changes_and_record_provenance(self):
        models.select(self.s,'ds');job=self.s.enqueue('Explain only, no edits')
        self.error('MODEL_BUSY',models.select,self.s,'ds')
        self.s.set_agent_mode('manual')
        with patch('ppt_workbench.agent_bridge.run_turn',return_value={'reply':'测试回复','questions':[],'actions':[]}) as call:
            self.assertTrue(self.s.run_pending())
        self.assertEqual(call.call_args.args[0],'api')
        self.assertEqual(call.call_args.kwargs['model_binding']['model'],'deepseek-flash')
        result=self.s.job(job['jobId'])['result'];self.assertEqual(result['modelBinding']['id'],'ds')
        messages=self.s.state()['messages'];self.assertTrue(any(m.get('modelBinding',{}).get('id')=='ds' and m.get('isRoundOutput') for m in messages))
    def test_changed_profile_fails_without_calling_another_model(self):
        models.select(self.s,'ds');j=self.s.enqueue('hello')
        self.entries[0]['model']='another-model';self.save()
        with patch('ppt_workbench.agent_bridge.run_turn') as call:self.s.run_pending()
        call.assert_not_called();self.assertEqual(self.s.job(j['jobId'])['status'],'failed')
    def test_deck_and_feedback_children_inherit_binding(self):
        from test_deck_flow import fixture_plan
        models.select(self.s,'ds');j=self.s.enqueue('用户给定的两页计划',scope='deck')
        self.s.apply_plan(j['jobId'],{'reply':'计划','actions':[{'type':'deck_start',**fixture_plan(2,'agent')}]})
        with self.s.wb._connection() as db:
            children=[json.loads(r[0]) for r in db.execute('SELECT payload FROM studio_jobs WHERE project_id=?',('a',))]
        self.assertTrue(any(p.get('kind')=='deck_page' and p['modelBinding']['id']=='ds' for p in children))
        other=Studio(self.root/'data','feedback');other.demo();models.select(other,'ds')
        j=other.enqueue('修改这两页',scope='deck')
        other.apply_plan(j['jobId'],{'reply':'分派','actions':[{'type':'deck_feedback','edits':[{'slide_id':'S001','instruction':'修改标题'}]}]})
        with other.wb._connection() as db:
            children=[json.loads(r[0]) for r in db.execute('SELECT payload FROM studio_jobs WHERE project_id=?',('feedback',))]
        self.assertTrue(any(p.get('kind')=='feedback_page' and p['modelBinding']['id']=='ds' for p in children))
    def test_cli_model_override_keeps_restrictions(self):
        profile={'model':'gpt-6-sol'}
        args=_command('codex','codex',self.root,self.root/'schema',self.root/'result',profile)
        self.assertIn('model="gpt-6-sol"',args);self.assertIn('features.shell_tool=false',args)
        args=_command('claude','claude',self.root,self.root/'schema',self.root/'result',profile)
        self.assertEqual(args[-2:],['--model','gpt-6-sol']);self.assertIn('--restricted',args);self.assertIn('--strict-mcp-config',args)
    def response(self,content,finish='stop'):
        result=MagicMock();result.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':finish,'message':{'content':content}}]}).encode();return result
    def test_api_wire_validation_and_scope_are_shared(self):
        chosen=models.binding(self.entries[0]);wire=json.dumps({'reply':'已收到','questions':[],'actions':[]})
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=self.response(wire)
            plan=run_turn('api','hello',{},model_binding=chosen)
            self.assertEqual(plan['reply'],'已收到')
            req=opener.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url,'https://api.deepseek.com/chat/completions')
            self.assertEqual(json.loads(req.data)['model'],'deepseek-flash')
            self.assertIn('schema',json.loads(req.data)['messages'][0]['content'])
            opener.return_value.open.return_value=self.response(wire,'length')
            self.error('MODEL_OUTPUT_TRUNCATED',run_turn,'api','hello',{},model_binding=chosen)
            bad=json.dumps({'reply':'bad','questions':[],'actions':[{'type':'slide_patch','arguments_json':json.dumps({'slide_id':'other','base_revision':1,'changes':[{'path':'/title','value':'x'}]})}]})
            opener.return_value.open.return_value=self.response(bad)
            self.error('FEEDBACK_SCOPE_MISMATCH',run_turn,'api','hello',{'generationTask':{'kind':'feedback_page'},'currentFeedback':{'slideId':'S001'}},model_binding=chosen)
    def test_api_auth_failure_redacted_and_redirect_denied(self):
        from ppt_workbench.api_model_provider import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None,None,302,'',{},'https://wrong.example'))
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=urllib.error.HTTPError('https://api.deepseek.com',401,'secret-sentinel',{},io.BytesIO(b'secret-sentinel'))
            with self.assertRaises(EngineError) as e:run_turn('api','hello',{},model_binding=models.binding(self.entries[0]))
            self.assertEqual(e.exception.code,'MODEL_AUTH_FAILED');self.assertNotIn('secret-sentinel',str(e.exception.to_dict()))

if __name__=='__main__':unittest.main()
