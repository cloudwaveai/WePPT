"""Reference selection is advisory; previews must never write a user's deck."""
import copy
import tempfile
import unittest

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench.templates import catalog, apply_template, recommend_templates
from ppt_workbench.reference_templates import LAYOUTS, visual_guidance


class ReferenceAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = Studio(self.tmp.name, 'demo')
        self.state = self.studio.demo()
        self.sid = self.state['selectedSlideId']

    def test_reference_provenance_and_adaptation_are_explicit(self):
        cards = [t for t in catalog() if t.get('reference')]
        self.assertEqual(len(cards), 44)
        self.assertEqual(len(LAYOUTS), 44)
        for card in cards:
            self.assertIn(card['baseTemplateId'], {t['id'] for t in catalog()})
            self.assertGreater(card['sourcePage'], 0)
            self.assertGreater(card['capacity'], 0)
            self.assertTrue(card['fitRule'])
        self.assertEqual(sum(t['adaptation'] == 'source-layout' for t in cards), 2)

    def test_preview_apply_and_transition_preserve_content(self):
        current = self.studio.get_scene(self.sid)
        before = copy.deepcopy(current)
        preview = self.studio.preview_template('reference-01-01', self.sid, current['sceneRevision'])
        self.assertEqual(self.studio.get_scene(self.sid), before)
        self.assertIsNone(self.studio.selected_template())
        self.studio.select_template('reference-01-01', self.sid, current['sceneRevision'])
        actual = self.studio.get_scene(self.sid)
        self.assertEqual(actual['scene'], preview['scene'])
        self.assertIsNone(self.studio.context()['visualGuidance']['selectedReference'])
        self.assertEqual(self.studio.context()['currentSceneTemplateId'], 'reference-01-01')
        original_text = {o['id']: o['text'] for o in before['scene']['objects'] if o['type'] == 'text'}
        for tid in ('reference-04-09', 'reference-03-05', 'reference-01-01', 'compare'):
            scene = apply_template(actual['scene'], tid)
            self.assertEqual({o['id']: o['text'] for o in scene['objects'] if o['id'] in original_text}, original_text)
            actual['scene'] = scene
        with self.assertRaises(EngineError):
            self.studio.preview_template('reference-04-09', self.sid, current['sceneRevision'])

    def test_cover_keeps_its_visual_and_template_changes_support_undo_redo(self):
        from ppt_workbench import editor
        current = self.studio.get_scene(self.sid)
        result = self.studio.preview_template('reference-01-01', self.sid, current['sceneRevision'])['scene']
        backgrounds = [o for o in result['objects'] if o['type'] == 'image' and o['id'].startswith('opening.fixed.')]
        self.assertTrue(backgrounds)
        self.assertTrue(all(o.get('opacity', 1) > 0 for o in backgrounds))
        self.assertFalse(any(o.get('text') == 'LOGO' for o in result['objects']))
        saved = self.studio.select_template('reference-01-01', self.sid, current['sceneRevision'])
        self.assertTrue(editor.history_status(self.studio, self.sid)['canUndo'])
        restored = editor.travel(self.studio, self.sid, saved['sceneRevision'], 'undo')
        self.assertEqual(restored['scene'], current['scene'])
        redone = editor.travel(self.studio, self.sid, restored['sceneRevision'], 'redo')
        self.assertEqual(redone['scene'], result)

    def test_recommendations_are_diverse_and_empty_project_is_supported(self):
        cards = recommend_templates('content', page={'title': '四阶段流程', 'keyPoints': '采集\n整理\n审核\n发布'})
        self.assertEqual(len({t.get('baseTemplateId', t['id']) for t in cards}), len(cards))
        self.assertTrue(all('content' in t['roles'] for t in cards))
        self.assertTrue(self.studio.template_recommendations(None)['recommendations'])
        guidance = visual_guidance('reference-04-09', catalog())
        self.assertEqual(guidance['selectedReference']['adaptation'], 'related-layout')
        self.assertIn('原图字节', ''.join(guidance['principles']))
