import copy
import unittest

from ppt_workbench import design_map, local_renderer, opening_templates, templates
from ppt_workbench.rendering import MAX_OBJECTS, validate_scene
from ppt_workbench.template_content import is_template_decoration, strip_template_decoration

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ZkAAAAASUVORK5CYII='


def content_scene():
    return validate_scene(dict(schema='ppt-scene', schemaVersion=1, slideId='S001',
        width=1280, height=720, notes='User notes', bindingSeparator='\n\n', objects=[
            dict(id='heading', type='text', binding='title', text='用户标题', x=20, y=20, w=900, h=100),
            dict(id='body', type='text', binding='keyPoints:0', text='用户正文完整保留', x=20, y=140, w=900, h=100),
            dict(id='photo', type='image', src=PNG, alt='真实用户图片', x=900, y=300, w=150, h=150)]))


class TemplateTransitionTests(unittest.TestCase):
    def test_cross_class_transitions_and_reapplication_preserve_content(self):
        targets = ['clean', 'editorial', 'portfolio-grid', 'vs-cards', 'cover',
                   'opening-02-01-cover', 'opening-04-02-toc', 'opening-05-02-chapter']
        original = content_scene()
        untouched = copy.deepcopy(original)
        for first in targets:
            initial = templates.apply_template(original, first)
            for second in targets:
                with self.subTest(first=first, second=second):
                    result = templates.apply_template(initial, second)
                    reapplied = templates.apply_template(result, second)
                    self.assertEqual(result, reapplied)
                    by_id = {o['id']: o for o in result['objects']}
                    for before in original['objects']:
                        for key in ('type', 'text', 'binding', 'src', 'alt', 'fit'):
                            self.assertEqual(before.get(key), by_id[before['id']].get(key))
                    self.assertEqual(result['notes'], original['notes'])
                    self.assertEqual(result['bindingSeparator'], '\n\n')
                    if not opening_templates.has_template(second):
                        self.assertFalse(any(o['id'].startswith('opening.fixed.') for o in result['objects']))
        self.assertEqual(original, untouched)

    def test_reserved_prefix_and_alt_are_not_image_ownership(self):
        for prefix in ('opening.fixed.', 'design-map.decoration.'):
            scene = content_scene()
            photo = scene['objects'][-1]
            photo.update(id=prefix + '0', alt='Source diagram decoration')
            for target in ('clean', 'portfolio-grid', 'cover', 'opening-02-01-cover'):
                with self.subTest(prefix=prefix, target=target):
                    result = templates.apply_template(scene, target)
                    saved = next(o for o in result['objects'] if o['id'] == photo['id'])
                    self.assertEqual(saved['src'], PNG)
                    self.assertEqual(saved['alt'], photo['alt'])

    def test_bundled_background_removed_despite_edited_alt_and_geometry(self):
        result = opening_templates.apply_template(content_scene(), 'opening-02-01-cover')
        backgrounds = [o for o in result['objects'] if is_template_decoration(o) and o['type'] == 'image']
        self.assertTrue(backgrounds)
        for obj in backgrounds:
            obj.update(alt='Edited description', x=0, y=0, w=100, h=100)
        cleaned = templates.apply_template(result, 'clean')
        self.assertEqual([o['id'] for o in cleaned['objects'] if o['type'] == 'image'], ['photo'])

    def test_bound_prefix_text_and_unbound_slot_ids_keep_bindings(self):
        scene = content_scene()
        scene['objects'][0]['id'] = 'opening.fixed.user-title'
        scene['objects'].append(dict(id='title', type='text', text='Unbound title ID', x=30, y=30, w=300, h=80))
        result = opening_templates.apply_template(scene, 'opening-02-01-cover')
        self.assertEqual({o['id']: o.get('binding') for o in result['objects'] if o['type'] == 'text' and not is_template_decoration(o)},
                         {o['id']: o.get('binding') for o in scene['objects'] if o['type'] == 'text'})

    def test_local_duplicate_display_removed_and_bound_ledger_becomes_visible(self):
        scene = local_renderer.scene_from_slide(dict(id='S001', title='标题', templateId='pillar-cards',
            keyPoints='第一组\n完整细节\n总结：甲\n\n第二组\n其他细节\n总结：乙'), {})
        bound = {o['id']: (o['text'], o['binding']) for o in scene['objects'] if o.get('binding')}
        scene['objects'].append(dict(id='pillar.1.bg', type='image', src=PNG, x=20, y=20, w=100, h=100))
        # Replace a shape with a real user image, retaining its original slot ID.
        scene['objects'] = [o for o in scene['objects'] if o['id'] != 'pillar.1.bg' or o['type'] == 'image']
        scene['objects'].append(dict(id='pillar.user-caption', type='text', text='用户独立添加的说明',
                                     x=20, y=20, w=300, h=50))
        # An edited derived text is now supplied content as well.
        edited = next(o for o in scene['objects'] if o['id'] == 'pillar.1.title')
        edited['text'] = '用户修改后的独立标题'
        for target in ('clean', 'portfolio-grid', 'cover', 'opening-02-01-cover'):
            with self.subTest(target=target):
                result = templates.apply_template(scene, target)
                self.assertEqual({o['id']: (o['text'], o['binding']) for o in result['objects'] if o.get('binding')}, bound)
                self.assertTrue(all(o['opacity'] == 1 for o in result['objects'] if o.get('binding')))
                self.assertTrue(any(o['id'] == 'pillar.1.bg' and o['src'] == PNG for o in result['objects']))
                self.assertEqual({o['id']: o['text'] for o in result['objects']
                                  if o['id'].startswith('pillar.') and o['type'] == 'text'},
                                 {'pillar.user-caption': '用户独立添加的说明', 'pillar.1.title': '用户修改后的独立标题'})

    def test_opening_decorations_respect_object_budget_and_scale(self):
        scene = content_scene()
        for i in range(MAX_OBJECTS - len(scene['objects'])):
            scene['objects'].append(dict(id=f'user.{i}', type='rect', x=0, y=0, w=10, h=10))
        result = opening_templates.apply_template(scene, 'opening-02-01-cover')
        self.assertEqual(len(result['objects']), MAX_OBJECTS)
        self.assertEqual({o['id'] for o in result['objects']}, {o['id'] for o in scene['objects']})
        small = content_scene()
        small.update(width=640, height=360)
        for obj in small['objects']:
            for key in ('x', 'y', 'w', 'h'):
                obj[key] /= 2
        for card in opening_templates.catalog():
            validate_scene(opening_templates.apply_template(small, card['id']))

    def test_generic_and_legacy_fit_supplied_text_without_rewriting(self):
        scene = content_scene()
        scene['objects'][0]['text'] = '需要完整保留的较长中文标题' * 5
        scene['objects'][1]['text'] = '正文需要保留完整表达与所有细节。' * 25
        for tid in ('editorial', 'clean', 'portfolio-grid'):
            result = templates.apply_template(scene, tid)
            by_id = {o['id']: o for o in result['objects']}
            self.assertEqual(by_id['heading']['text'], scene['objects'][0]['text'])
            self.assertLess(by_id['heading']['fontSize'], 40)

    def test_raw_design_map_preview_sources_are_retired_without_dropping_user_image(self):
        scene = design_map.sample_scene('cover')
        scene['objects'].append(dict(id='user-photo', type='image', src=PNG, x=0, y=0, w=100, h=100))
        source_nontext = {o['id'] for o in scene['objects'] if o['type'] != 'text' and o['id'] != 'user-photo'}
        result = strip_template_decoration(copy.deepcopy(scene))
        self.assertFalse(source_nontext & {o['id'] for o in result['objects']})
        self.assertTrue(any(o['id'] == 'user-photo' for o in result['objects']))

    def test_sample_opening_fixed_objects_are_not_reinterpreted_as_content(self):
        for card in opening_templates.catalog():
            sample = opening_templates.sample_scene(card['id'])
            cleaned = strip_template_decoration(copy.deepcopy(sample))
            self.assertTrue(all(o.get('binding') for o in cleaned['objects']))
