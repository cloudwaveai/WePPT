import copy
import json
import unittest
from pathlib import Path

from ppt_workbench.design_map import apply_template, has_template, sample_scene
from ppt_workbench.rendering import validate_scene


class DesignMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Path(__file__).resolve().parents[1] / 'ppt_workbench' / 'data'
        catalog = json.loads((cls.data / 'bbstack-templates.json').read_text())
        structure = json.loads((cls.data / 'bbstack-structure.json').read_text())
        cls.ids = [x['id'] for x in catalog['templates']] + [x['id'] for x in structure['variants']['parallel']]

    def content(self):
        return validate_scene(dict(schema='ppt-scene', schemaVersion=1, slideId='S002', width=1280, height=720,
            background='#FFFFFF', objects=[
                dict(id='user.title', type='text', text='我的独立标题', binding='title', x=30, y=20, w=800, h=80),
                dict(id='user.point', type='text', text='用户原文：不得替换 312', binding='keyPoints:0', x=30, y=130, w=800, h=100),
                dict(id='user.takeaway', type='text', text='仅有的判断', binding='takeaway', x=30, y=240, w=800, h=100),
                dict(id='design-map.decoration.user-image', type='image', x=900, y=250, w=40, h=40,
                     src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==', alt='真实用户图片', fit='contain'),
            ]))

    def test_switch_from_extracted_cover_retires_its_images_and_fits_long_text(self):
        from ppt_workbench.templates import apply_template as apply
        original = self.content()
        original['objects'][2]['text'] = '选一个喜欢的样子，把内容做进去，再按自己的想法修改。'
        extracted = apply(original, 'opening-02-01-cover')
        self.assertTrue(any(o['id'].startswith('opening.fixed.') for o in extracted['objects']))
        switched = apply(extracted, 'cover-photo')
        self.assertFalse(any(o['id'].startswith('opening.fixed.') for o in switched['objects']))
        self.assertEqual([o['src'] for o in switched['objects'] if o['type'] == 'image'],
                         [o['src'] for o in original['objects'] if o['type'] == 'image'])
        takeaway = next(o for o in switched['objects'] if o.get('binding') == 'takeaway')
        from ppt_workbench.quality import _estimated_height
        self.assertLessEqual(_estimated_height(takeaway), takeaway['h'])

    def test_exact_coverage_and_independent_validated_previews(self):
        self.assertEqual(len(self.ids), 61)
        for tid in self.ids:
            with self.subTest(tid=tid):
                self.assertTrue(has_template(tid))
                scene = sample_scene(tid)
                self.assertEqual(scene['templateId'], tid)
                self.assertTrue(scene['title'])
                scene['objects'][0]['x'] = -1
                validate_scene(sample_scene(tid))
        for invalid in ('../cover', 'manifest', 'missing', None):
            self.assertFalse(has_template(invalid))

    def test_all_applications_preserve_bindings_images_and_only_user_text(self):
        original = self.content()
        before = copy.deepcopy(original)
        for tid in self.ids:
            with self.subTest(tid=tid):
                scene = apply_template(original, tid)
                by_id = {o['id']: o for o in scene['objects']}
                self.assertEqual([o['text'] for o in original['objects'] if o['type'] == 'text'],
                                 [o['text'] for o in scene['objects'] if o['type'] == 'text'])
                for obj in original['objects']:
                    for field in ('id', 'type', 'text', 'binding', 'src', 'alt', 'fit'):
                        self.assertEqual(obj.get(field), by_id[obj['id']].get(field))
                reapplied = apply_template(scene, tid)
                self.assertEqual(scene, reapplied)
        self.assertEqual(original, before)

    def test_primary_source_geometry_and_cjk_text_widths(self):
        expected = {'cover': (60, 197.44), 'cover-photo': (60, 190.8), 'toc': (64, 162.08),
                    'chapter': (388, 218.8), 'chapter-image': (646, 247.84)}
        for tid, (x, y) in expected.items():
            title = next(o for o in sample_scene(tid)['objects'] if o.get('binding') == 'title')
            self.assertAlmostEqual(title['x'], x)
            self.assertAlmostEqual(title['y'], y)
            self.assertGreaterEqual(title['w'], len(title['text']) * title['fontSize'])
        chapter = sample_scene('chapter')
        self.assertTrue(any(o['type'] == 'rect' and (o['x'], o['y'], o['w'], o['h']) == (0, 0, 308, 720)
                            for o in chapter['objects']))

    def test_chart_examples_never_become_applied_user_data(self):
        for tid in ('bar', 'line', 'composition', 'kpi', 'waterfall', 'funnel', 'scatter'):
            entry = json.loads((self.data / 'design-map-scenes' / (tid + '.json')).read_text())
            self.assertTrue(entry['unsafeDecorations'])
            applied = apply_template(self.content(), tid)
            self.assertEqual(len([o for o in applied['objects'] if o['type'] == 'text']), 3)
            # All illustrative numeric marks below the heading are omitted.
            self.assertFalse(any(o['id'].startswith('design-map.decoration.') and o.get('alt') == 'Source diagram decoration'
                                 for o in applied['objects']))


if __name__ == '__main__':
    unittest.main()
