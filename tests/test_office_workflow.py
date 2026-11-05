"""Document/import/workflow regressions; no remote model calls."""
import base64
import copy
import io
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path
from ppt_workbench import background_tasks as bg, owners, user_templates as ut
from ppt_workbench.studio import Studio
from ppt_workbench.core import EngineError
from ppt_workbench.document_editing import operate
from ppt_workbench.presentation_import import import_presentation
from test_style_templates import PROFILE, file
from test_pptx_opening import NS


def presentation_fixture(pages=2, unsupported=False):
    a,p,r=NS['a'],NS['p'],NS['r']
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst>'+''.join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1,pages+1))+'</p:sldIdLst><p:sldSz cx="12800000" cy="7200000"/></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="{r}/slide" Target="slides/slide{i}.xml"/>' for i in range(1,pages+1))+'</Relationships>')
        for i in range(1,pages+1):
            shape=f'<p:sp><p:nvSpPr><p:cNvPr id="2"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="800000" y="700000"/><a:ext cx="11000000" cy="1000000"/></a:xfrm></p:spPr><p:txBody><a:bodyPr lIns="0" rIns="0" tIns="0" bIns="0"/><a:p><a:r><a:rPr sz="3600"><a:solidFill><a:srgbClr val="243247"/></a:solidFill></a:rPr><a:t>原稿第{i}页完整标题</a:t></a:r></a:p></p:txBody></p:sp>'
            if unsupported and i==pages:shape+='<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="9"/></p:nvGraphicFramePr></p:graphicFrame>'
            z.writestr(f'ppt/slides/slide{i}.xml',f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree>{shape}</p:spTree></p:cSld></p:sld>')
    return raw.getvalue()


class OfficeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Studio(self.tmp.name,'office',agent='manual');self.s.demo()
    def style(self):
        with patch('ppt_workbench.design_review.render_candidate',side_effect=EngineError('DESIGN_RENDER_UNAVAILABLE','no')):
            tid=ut.upload(self.s,'style',[file()])['templates'][0]['id']
        ut.update_style(self.s,tid,profile=PROFILE)
        return tid
    def test_deck_palette_undo_restores_all_scenes_and_mapping(self):
        originals={p['id']:copy.deepcopy(self.s.get_scene(p['id'])['scene']) for p in self.s.state()['slides']}
        self.s.set_palette({'primary':'#9C325A','secondary':['#527C55']})
        result=self.s.apply_palette('deck')
        self.assertTrue(result['changedSlides']);self.assertTrue(result['state']['documentHistory']['canUndo'])
        state=operate(self.s,'undo',result['state']['projectRevision'])['state']
        for sid,scene in originals.items():self.assertEqual(self.s.get_scene(sid)['scene'],scene)
        self.assertFalse(state['documentHistory']['canUndo'])
        from ppt_workbench.palette import applied_palette
        self.assertIsNone(applied_palette(self.s))
    def test_atomic_palette_restores_future_preference_and_rejects_stale(self):
        before=self.s.state()['projectRevision']
        chosen={'primary':'#9C325A','secondary':['#527C55']}
        result=self.s.apply_palette('deck',palette_value=chosen,project_revision=before)
        self.assertEqual(self.s.palette(),chosen)
        operate(self.s,'undo',result['state']['projectRevision'])
        self.assertIsNone(self.s.palette())
        with self.assertRaises(EngineError):self.s.apply_palette('deck',palette_value=chosen,project_revision=before)
        self.assertIsNone(self.s.palette())

    def test_palette_undo_cannot_overwrite_later_manual_edit(self):
        self.s.set_palette({'primary':'#9C325A','secondary':['#527C55']})
        result=self.s.apply_palette('deck');sid=result['changedSlides'][0]
        saved=self.s.get_scene(sid);scene=saved['scene'];scene['background']='#EEEEEE'
        self.s.put_scene(sid,saved['contentRevision'],scene)
        with self.assertRaises(EngineError):operate(self.s,'undo',result['state']['projectRevision'])
        self.assertEqual(self.s.get_scene(sid)['scene']['background'],'#EEEEEE')
    def test_background_restyle_creates_owned_copy_and_deduplicates(self):
        marker=owners.set_current(owners.new_token());self.addCleanup(owners.reset,marker)
        owners.claim_project(self.s.wb,self.s.project_id)
        tid=self.style();self.s.set_agent_mode('codex')
        before=self.s.wb.get_project(self.s.project_id)
        result=bg.submit_style(self.s,tid,before['revision'])
        self.assertEqual(bg.submit_style(self.s,tid,before['revision'])['taskId'],result['taskId'])
        result=bg.run_pending(self.s)
        self.assertIn('projectId',result,bg.state(self.s))
        target=Studio(self.tmp.name,result['projectId'])
        self.assertEqual(target.job(result['jobId'])['status'],'queued')
        self.assertEqual(ut.selected_style(target)['id'],tid)
        self.assertEqual(owners.project_owner(target.wb,target.project_id),owners.current())
        self.assertEqual(self.s.wb.get_project(self.s.project_id),before)
        self.assertEqual(bg.state(self.s)[0]['status'],'complete')
        self.assertIsNone(bg.run_pending(self.s))
        bg.submit_style(self.s,tid,self.s.state()['projectRevision'])
        again=bg.run_pending(self.s)
        self.assertIn('projectId',again,bg.state(self.s))
    def test_restart_reopens_pending_project_without_browser(self):
        from ppt_workbench.server import create_http_server
        other=Studio(self.tmp.name,'unopened',agent='manual')
        tid=self.style()
        bg.submit_style(other,tid,other.state()['projectRevision'])
        server=create_http_server(self.tmp.name,'office',port=0)
        try:
            server.start_worker()
            import time
            deadline=time.monotonic()+4
            while time.monotonic()<deadline and bg.state(other)[0]['status']!='complete':time.sleep(.02)
            self.assertIn('unopened',server.studios)
            self.assertEqual(bg.state(other)[0]['status'],'complete')
            self.assertEqual(ut.selected_style(other)['id'],tid)
        finally:
            server.server_close()
            if server.worker_thread:server.worker_thread.join(5)

    def test_background_model_selection_cannot_silently_change(self):
        tid=self.style();self.s.set_agent_mode('codex')
        bg.submit_style(self.s,tid,self.s.state()['projectRevision'])
        self.s.set_agent_mode('manual')
        bg.run_pending(self.s)
        self.assertEqual(bg.state(self.s)[0]['error']['code'],'MODEL_PROFILE_CHANGED')
        self.assertEqual(len(self.s.wb.list_projects()),1)

    def test_source_shows_derived_failure_instead_of_stale_queued_message(self):
        tid=self.style();self.s.set_agent_mode('codex')
        bg.submit_style(self.s,tid,self.s.state()['projectRevision'])
        result=bg.run_pending(self.s)
        target=Studio(self.tmp.name,result['projectId'])
        target.fail_job(result['jobId'],EngineError('INVALID_AGENT_OUTPUT','模型未返回有效结果'))
        self.assertIn('未完成',bg.state(self.s)[0]['stage'])
        # A hidden target must not leak its progress through the source task.
        marker=owners.set_current(owners.new_token())
        try:
            owners.claim_project(target.wb,target.project_id)
        finally:owners.reset(marker)
        marker=owners.set_current(owners.new_token())
        try:self.assertEqual(bg.state(self.s)[0]['stage'],'改版稿已进入后台生成')
        finally:owners.reset(marker)

    def test_stale_background_and_restart_failure_preserve_source(self):
        tid=self.style();self.s.set_agent_mode('codex')
        revision=self.s.state()['projectRevision'];bg.submit_style(self.s,tid,revision)
        operate(self.s,'insert',revision)
        bg.run_pending(self.s)
        self.assertEqual(bg.state(self.s)[0]['error']['code'],'STALE_REVISION')
        result=bg.submit_style(self.s,tid,self.s.state()['projectRevision'])
        with self.s.wb.atomic() as db:db.execute("UPDATE studio_background_tasks SET status='running' WHERE id=?",(result['taskId'],))
        bg.recover(self.s)
        self.assertEqual(bg.state(self.s)[0]['error']['code'],'WORKFLOW_INTERRUPTED')
    def test_import_all_pages_original_bytes_and_owner(self):
        marker=owners.set_current(owners.new_token());self.addCleanup(owners.reset,marker)
        raw=presentation_fixture(4)
        result=import_presentation(self.s,'原稿.pptx',base64.b64encode(raw).decode())
        target=Studio(self.tmp.name,result['projectId']);state=target.state()
        self.assertEqual(len(state['slides']),4)
        self.assertEqual((target.wb.project_dir(target.project_id)/'import/source.pptx').read_bytes(),raw)
        self.assertEqual(owners.project_owner(target.wb,target.project_id),owners.current())
        for i,p in enumerate(state['slides'],1):
            self.assertIn(f'原稿第{i}页完整标题',[o.get('text') for o in target.get_scene(p['id'])['scene']['objects']])
        self.assertEqual(state['importSource']['slideCount'],4)
    def test_unsupported_later_page_rejects_whole_import(self):
        before=self.s.wb.list_projects()
        with self.assertRaises(EngineError) as e:
            import_presentation(self.s,'bad.pptx',base64.b64encode(presentation_fixture(3,True)).decode())
        self.assertEqual(e.exception.code,'PPTX_IMPORT_UNSUPPORTED')
        self.assertEqual(e.exception.details['pages'],[3])
        self.assertEqual(self.s.wb.list_projects(),before)

if __name__=='__main__':unittest.main()
