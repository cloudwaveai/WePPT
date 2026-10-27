import copy
import unittest

from ppt_workbench import opening_templates
from ppt_workbench.rendering import validate_scene


class OpeningTemplateTests(unittest.TestCase):
    def test_reviewed_roles_sources_and_editable_content(self):
        cards = opening_templates.catalog()
        self.assertEqual(len(cards), 7)
        self.assertEqual([card['role'] for card in cards].count('cover'), 5)
        self.assertEqual([card['role'] for card in cards].count('toc'), 1)
        self.assertEqual([card['role'] for card in cards].count('chapter'), 1)
        original = {'schema': 'ppt-scene', 'schemaVersion': 1, 'slideId': 'S003',
                    'width': 1280, 'height': 720, 'objects': [
                        {'id': 'title', 'type': 'text', 'binding': 'title', 'text': '新演示主题',
                         'x': 10, 'y': 10, 'w': 500, 'h': 90},
                        {'id': 'takeaway', 'type': 'text', 'binding': 'takeaway', 'text': '新的副标题',
                         'x': 10, 'y': 110, 'w': 500, 'h': 70},
                        {'id': 'body', 'type': 'text', 'binding': 'keyPoints:0', 'text': '用户内容必须保留',
                         'x': 10, 'y': 210, 'w': 500, 'h': 100}]}
        untouched = copy.deepcopy(original)
        for card in cards:
            sample = opening_templates.sample_scene(card['id'])
            texts = '\n'.join(obj['text'] for obj in sample['objects'] if obj['type'] == 'text')
            for case_text in ('FDE', 'FESCO', '林伊默', '云涌世纪', 'cloudwaveai.com', '生产力'):
                self.assertNotIn(case_text, texts)
            self.assertEqual(sum(not item['legacy'] for item in cards), 3)
            scene = opening_templates.apply_template(original, card['id'])
            self.assertEqual(scene['slideId'], 'S003')
            self.assertEqual({obj.get('binding'): obj['text'] for obj in scene['objects'] if obj.get('binding')},
                             {obj['binding']: obj['text'] for obj in original['objects']})
            self.assertEqual(len(opening_templates.apply_template(scene, card['id'])['objects']), len(scene['objects']))
            validate_scene(scene)
        self.assertEqual(original, untouched)

    def test_deck_role_mapping_reuses_available_source_set(self):
        self.assertEqual(opening_templates.template_for_role('opening-04-01-cover', 'toc'), 'opening-04-02-toc')
        self.assertEqual(opening_templates.template_for_role('opening-05-01-cover', 'chapter'), 'opening-05-02-chapter')
        self.assertIsNone(opening_templates.template_for_role('opening-01-01-cover', 'content'))
