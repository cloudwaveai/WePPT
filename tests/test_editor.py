"""Versioned manual edits and preview/apply boundaries, with explicit model doubles."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ppt_workbench import editor
from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = Studio(Path(self.tmp.name), 'editor-test', agent='outline')
        state = self.studio.demo()
        self.sid = state['slides'][0]['id']
        self.before = self.studio.get_scene(self.sid)
        self.obj = next(o for o in self.before['scene']['objects'] if o['type'] == 'text')

    def change(self, **properties):
        current = self.studio.get_scene(self.sid)
        return self.studio.edit_scene(self.sid, current['sceneRevision'],
                                     [{'objectId': self.obj['id'], 'properties': properties}])

    def plan(self, properties, oid=None):
        return {'reply': '测试模型建议', 'questions': [], 'actions': [{
            'type': 'scene_patch', 'slide_id': self.sid,
            'base_scene_revision': self.before['sceneRevision'],
            'changes': [{'objectId': oid or self.obj['id'], 'properties': properties}]}]}

    def suggest(self, properties, action='polish', oid=None):
        self.studio.set_agent_mode('codex')
        with patch('ppt_workbench.agent_bridge.run_turn', return_value=self.plan(properties, oid)):
            return editor.suggest(self.studio, self.sid, self.before['sceneRevision'],
                                  action, self.obj['id'] if action != 'layout' else None)

    def test_formats_and_geometry_preserve_other_objects_and_round_count(self):
        count = self.studio.delivery_state()['inputCount']
        result = self.change(fontSize=42, color='#AA3300', bold=True, align='center', x=80)
        after = next(o for o in result['scene']['objects'] if o['id'] == self.obj['id'])
        self.assertEqual(after['fontSize'], 42)
        self.assertEqual(after['text'], self.obj['text'])
        for old, new in zip(self.before['scene']['objects'], result['scene']['objects']):
            if old['id'] != self.obj['id']:
                self.assertEqual(old, new)
        self.assertEqual(self.studio.delivery_state()['inputCount'], count)
        self.assertTrue(editor.history_status(self.studio, self.sid)['canUndo'])

    def test_multi_step_undo_redo_persists_after_restart(self):
        first = self.change(fontSize=42)
        second = self.change(color='#AA3300')
        studio = Studio(Path(self.tmp.name), 'editor-test')
        undo1 = editor.travel(studio, self.sid, second['sceneRevision'], 'undo')
        self.assertEqual(undo1['scene'], first['scene'])
        undo2 = editor.travel(studio, self.sid, undo1['sceneRevision'], 'undo')
        self.assertEqual(undo2['scene'], self.before['scene'])
        redo1 = editor.travel(studio, self.sid, undo2['sceneRevision'], 'redo')
        redo2 = editor.travel(studio, self.sid, redo1['sceneRevision'], 'redo')
        self.assertEqual(redo2['scene'], second['scene'])
        self.assertFalse(editor.history_status(studio, self.sid)['canRedo'])

    def test_new_edit_after_undo_discards_redo_branch(self):
        result = self.change(fontSize=42)
        editor.travel(self.studio, self.sid, result['sceneRevision'], 'undo')
        self.change(color='#BB2200')
        self.assertFalse(editor.history_status(self.studio, self.sid)['canRedo'])

    def test_external_page_change_does_not_get_overwritten_by_undo(self):
        self.change(fontSize=42)
        current = self.studio.get_scene(self.sid)
        self.studio.change_scene(self.sid, current['sceneRevision'],
                                [{'objectId': self.obj['id'], 'properties': {'color': '#BB2200'}}])
        status = editor.history_status(self.studio, self.sid)
        self.assertFalse(status['canUndo'])
        with self.assertRaises(EngineError):
            editor.travel(self.studio, self.sid, status['sceneRevision'], 'undo')

    def test_invalid_properties_and_stale_revision_leave_scene_unchanged(self):
        for props in [{'src': 'data:bad'}, {'fontSize': 'huge'}, {'x': 'invalid'}, {'id': 'other'}]:
            with self.assertRaises(EngineError):
                self.change(**props)
        self.assertEqual(self.studio.get_scene(self.sid)['scene'], self.before['scene'])
        self.change(fontSize=42)
        with self.assertRaises(EngineError):
            self.studio.edit_scene(self.sid, self.before['sceneRevision'],
                                  [{'objectId': self.obj['id'], 'properties': {'text': 'stale'}}])

    def test_suggestion_preview_does_not_mutate_then_apply_is_once_and_undoable(self):
        proposal = self.suggest({'text': '建议文字'})
        self.assertEqual(self.studio.get_scene(self.sid)['scene'], self.before['scene'])
        self.assertIn('建议文字', proposal['afterHtml'])
        self.assertNotIn('建议文字', proposal['beforeHtml'])
        result = editor.apply_suggestion(self.studio, proposal['proposalId'])
        self.assertTrue(any(o.get('text') == '建议文字' for o in result['scene']['objects']))
        with self.assertRaises(EngineError):
            editor.apply_suggestion(self.studio, proposal['proposalId'])
        restored = editor.travel(self.studio, self.sid, result['sceneRevision'], 'undo')
        self.assertEqual(restored['scene'], self.before['scene'])

    def test_stale_and_cross_project_proposals_cannot_apply(self):
        proposal = self.suggest({'text': '建议文字'})
        other = Studio(Path(self.tmp.name), 'other')
        with self.assertRaises(EngineError):
            editor.apply_suggestion(other, proposal['proposalId'])
        self.change(fontSize=42)
        with self.assertRaises(EngineError):
            editor.apply_suggestion(self.studio, proposal['proposalId'])
        self.assertFalse(any(o.get('text') == '建议文字' for o in self.studio.get_scene(self.sid)['scene']['objects']))

    def test_layout_cannot_delete_text_or_shrink_fonts_and_object_scope_is_enforced(self):
        for props in [{'text': ''}, {'fontSize': 10}]:
            with self.assertRaises(EngineError):
                self.suggest(props, 'layout')
        other = next(o for o in self.before['scene']['objects'] if o['id'] != self.obj['id'])
        with self.assertRaises(EngineError):
            self.suggest({'text': '越界修改'}, oid=other['id'])
        self.assertEqual(self.studio.get_scene(self.sid)['scene'], self.before['scene'])

    def test_missing_model_is_reported_without_fake_suggestion(self):
        with self.assertRaises(EngineError) as raised:
            editor.suggest(self.studio, self.sid, self.before['sceneRevision'], 'layout')
        self.assertEqual(raised.exception.code, 'AGENT_REQUIRED')

    def test_late_model_response_cannot_create_a_stale_proposal(self):
        self.studio.set_agent_mode('codex')
        def delayed(*args, **kwargs):
            self.change(fontSize=42)
            return self.plan({'text': '过期建议'})
        with patch('ppt_workbench.agent_bridge.run_turn', side_effect=delayed):
            with self.assertRaises(EngineError):
                editor.suggest(self.studio, self.sid, self.before['sceneRevision'], 'polish', self.obj['id'])


if __name__ == '__main__':
    unittest.main()
