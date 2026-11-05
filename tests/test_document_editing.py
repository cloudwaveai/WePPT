import copy
import tempfile
import unittest
from ppt_workbench.studio import Studio
from ppt_workbench.document_editing import operate
from ppt_workbench.core import EngineError

class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Studio(self.tmp.name,'document',agent='manual');self.s.demo()
    def op(self,action,**kw):
        return operate(self.s,action,self.s.state()['projectRevision'],**kw)['state']
    def test_insert_at_current_copy_remove_restore_without_model(self):
        original=self.s.state();ids=[p['id'] for p in original['slides']]
        state=self.op('insert',after_id=ids[0]);new=state['selectedSlideId']
        self.assertEqual([p['id'] for p in state['slides']],[ids[0],new,*ids[1:]])
        self.assertTrue(next(p for p in state['slides'] if p['id']==new)['hasPreview'])
        restored=self.op('undo');self.assertEqual([p['id'] for p in restored['slides']],ids)
        source=copy.deepcopy(self.s.get_scene(ids[0])['scene'])
        state=self.op('duplicate',slide_id=ids[0],after_id=ids[1]);sid=state['selectedSlideId']
        duplicate=self.s.get_scene(sid)['scene'];self.assertEqual(duplicate['objects'],source['objects'])
        self.assertEqual(self.s.get_scene(ids[0])['scene'],source)
        removed=self.op('remove',slide_id=sid);self.assertNotIn(sid,[p['id'] for p in removed['slides']])
        restored=self.op('undo');self.assertIn(sid,[p['id'] for p in restored['slides']])
        self.assertEqual(self.s.get_scene(sid)['scene'],duplicate)
        self.assertEqual(self.s.state()['jobs'],[])
    def test_move_front_and_stale_protection(self):
        state=self.s.state();ids=[p['id'] for p in state['slides']]
        moved=self.op('move',slide_id=ids[-1],after_id=None)
        self.assertEqual(moved['slides'][0]['id'],ids[-1])
        with self.assertRaises(EngineError) as e:operate(self.s,'remove',state['projectRevision'],ids[0])
        self.assertEqual(e.exception.code,'STALE_REVISION')
        restored=self.op('undo');self.assertEqual([p['id'] for p in restored['slides']],ids)
    def test_invalid_position_is_atomic(self):
        before=self.s.wb.get_project(self.s.project_id)
        with self.assertRaises(EngineError):self.op('insert',after_id='missing')
        self.assertEqual(self.s.wb.get_project(self.s.project_id),before)
    def test_busy_deck_rejects_structure_edit(self):
        self.s.enqueue('生成整稿',scope='deck')
        with self.assertRaises(EngineError) as e:self.op('insert')
        self.assertEqual(e.exception.code,'DOCUMENT_BUSY')
