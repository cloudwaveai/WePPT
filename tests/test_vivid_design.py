"""Visual-upgrade contracts (collab board T2-T8): richer primitives, rhythm evidence, anchors, exemplars, auto images."""
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench.rendering import validate_scene, render_html, patch_scene, export_pptx, emphasis_segments
from ppt_workbench.quality import audit_scene, visual_stats, visual_findings, deck_rhythm
from ppt_workbench.page_design import prepare_scene, validate_composition, validate_design, drop_unsupported_metrics
from ppt_workbench.deck_design import (validate_brief, validate_strategy, plan_rhythm, apply_plan_patch,
                                       review_plan, LAYOUT_ARCHETYPES, MAX_AUTO_IMAGES)
from ppt_workbench.design_exemplars import library, resolved_scene, for_page
from ppt_workbench.design_loop import patch_candidate
from ppt_workbench.content_capacity import page_capacity
from ppt_workbench.image_generation import GeneratedImage, ImageJobs
from ppt_workbench.deck_review import run_review
from test_deck_design import STRATEGY, BRIEF, deck_plan
from test_page_design import action, COMPOSITION

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII=')
NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}


def scene(objects, background='#FFFFFF'):
    return {'schema': 'ppt-scene', 'schemaVersion': 1, 'slideId': 'S001', 'width': 1280, 'height': 720,
            'background': background, 'objects': objects}


def text(oid, value, x=80, y=80, w=600, h=80, size=24, **extra):
    return {'id': oid, 'type': 'text', 'text': value, 'x': x, 'y': y, 'w': w, 'h': h, 'fontSize': size, **extra}


def codes(findings, code):
    return [f for f in findings if f['code'] == code]


class ScenePrimitiveTests(unittest.TestCase):
    def test_ellipse_rotation_shadow_and_text_styles_validate_and_render(self):
        s = validate_scene(scene([
            {'id': 'disc', 'type': 'ellipse', 'x': 900, 'y': 300, 'w': 300, 'h': 300, 'fill': '#C8553D', 'shadow': 'soft', 'rotation': -15},
            {'id': 'band', 'type': 'rect', 'x': 0, 'y': 0, 'w': 400, 'h': 720, 'fill': '#14202B', 'rotation': 10, 'shadow': 'lift'},
            text('title', '把控制权留在可编辑页面', size=48, letterSpacing=-1, binding='title',
                 emphasis=['可编辑页面', '不存在的词', '可编辑页面'], emphasisColor='#C8553D')]))
        self.assertEqual(s['objects'][2]['emphasis'], ['可编辑页面'])
        markup = render_html(s, interactive=False)
        for fragment in ('border-radius:50%', 'class="text-em"', 'letter-spacing:-1px', 'rotate(-15deg)', 'box-shadow:'):
            self.assertIn(fragment, markup)
        with self.assertRaises(EngineError):  # Unknown properties still fail.
            validate_scene(scene([{'id': 'd', 'type': 'ellipse', 'x': 0, 'y': 0, 'w': 10, 'h': 10, 'radius': 4}]))
        # Malformed optional decoration is normalized, never allowed to block a page.
        shape = lambda **extra: validate_scene(scene([{'id': 'd', 'type': 'ellipse', 'x': 0, 'y': 0, 'w': 10, 'h': 10, **extra}]))['objects'][0]
        self.assertNotIn('shadow', shape(shadow='huge'))
        self.assertEqual(shape(rotation=200)['rotation'], -160)
        self.assertNotIn('rotation', shape(rotation='15deg'))
        styled = lambda **extra: validate_scene(scene([text('t', 'abc', **extra)]))['objects'][0]
        self.assertEqual(styled(letterSpacing=99)['letterSpacing'], 40)
        self.assertEqual(styled(emphasis='abc')['emphasis'], ['abc'])
        self.assertEqual(styled(emphasis=['a'] * 9)['emphasis'], ['a'])
        self.assertEqual(styled(emphasis=[{'text': 'abc'}, 'b', ''])['emphasis'], ['b'])
        self.assertNotIn('emphasis', styled(emphasis={'phrase': 'abc'}))
        self.assertNotIn('emphasisColor', styled(emphasisColor='red'))
        self.assertEqual(styled(emphasis=['abc'])['text'], 'abc')
        plain = validate_scene(scene([text('t', 'abc'), {'id': 'r', 'type': 'rect', 'x': 0, 'y': 0, 'w': 9, 'h': 9}]))
        for key in ('emphasis', 'letterSpacing', 'emphasisColor'):
            self.assertNotIn(key, plain['objects'][0])
        self.assertNotIn('rotation', plain['objects'][1])

    def test_emphasis_segments_and_text_edits_drop_stale_highlights(self):
        self.assertEqual(emphasis_segments('先整稿再逐页，整稿优先', ['整稿', '整稿优先']),
                         [('先', False), ('整稿', True), ('再逐页，', False), ('整稿优先', True)])
        s = validate_scene(scene([text('t', '先整稿再逐页', emphasis=['整稿'])]))
        edited = patch_scene(s, [{'objectId': 't', 'properties': {'text': '先逐页'}}])
        self.assertNotIn('emphasis', edited['objects'][0])
        markup = render_html(validate_scene(scene([text('t', 'a<script>b', emphasis=['<script>'])])))
        self.assertIn('a<span class="text-em" style="color:#12243C;font-weight:700">&lt;script&gt;</span>b', markup)

    def test_new_shapes_inform_contrast_and_occlusion_checks(self):
        disc = {'id': 'disc', 'type': 'ellipse', 'x': 100, 'y': 100, 'w': 600, 'h': 600, 'fill': '#14202B'}
        light = text('body-1', '深色圆内的浅色文字', x=250, y=350, w=300, h=40, color='#F6F3EE')
        self.assertFalse(codes(audit_scene(scene([disc, light])), 'TEXT_CONTRAST'))
        self.assertTrue(codes(audit_scene(scene([disc, dict(light, color='#1D2A35')])), 'TEXT_CONTRAST'))
        corner = text('body-1', '角落文字', x=110, y=110, w=200, h=40, color='#1D2A35')
        self.assertFalse(codes(audit_scene(scene([disc, corner])), 'TEXT_CONTRAST'))
        rotated = {'id': 'band', 'type': 'rect', 'x': 0, 'y': 0, 'w': 1280, 'h': 720, 'fill': '#14202B', 'rotation': 5}
        self.assertFalse(codes(audit_scene(scene([rotated, dict(light, color='#1D2A35')])), 'TEXT_CONTRAST'))
        pale = text('title', '重点词', size=40, binding='title', emphasis=['重点'], emphasisColor='#F0F0F0')
        self.assertTrue(codes(audit_scene(scene([pale])), 'TEXT_CONTRAST'))
        covered = scene([text('body-1', '被遮挡', x=200, y=200, w=100, h=40),
                         {'id': 'disc', 'type': 'ellipse', 'x': 150, 'y': 150, 'w': 300, 'h': 300, 'fill': '#C8553D'}])
        self.assertTrue(codes(audit_scene(covered), 'TEXT_OCCLUDED'))

    def test_review_repairs_may_add_ellipses_but_not_words(self):
        base = validate_scene(scene([text('title', '标题', binding='title')]))
        add = lambda obj: {'type': 'scene_objects', 'slide_id': 'S001', 'base_scene_revision': 1, 'operations': [{'op': 'add', 'object': obj}]}
        revised = patch_candidate(base, add({'id': 'disc', 'type': 'ellipse', 'x': 0, 'y': 0, 'w': 50, 'h': 50, 'fill': '#C8553D'}), 1)
        self.assertEqual(revised['objects'][-1]['type'], 'ellipse')
        with self.assertRaises(EngineError):
            patch_candidate(base, add(text('extra', '新增正文')), 1)

    def test_review_may_combine_one_patch_and_one_object_edit(self):
        from ppt_workbench.design_loop import review_candidate
        page = validate_scene(scene([text('title', '标题', binding='title', size=30), text('body-1', '正文内容', y=200, size=20)]))
        def render(s, folder):
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'p.png').write_bytes(b'png')
            return folder / 'p.png', dict(fontsReady=True, overflow=[])
        stages = []
        def runner(mode, prompt, context, **kwargs):
            stages.append(context['reviewStage'])
            if context['reviewStage'] == 'critique-and-repair':
                return dict(reply='REVISE\n太平', actions=[
                    {'type': 'scene_patch', 'slide_id': 'S001', 'base_scene_revision': 1,
                     'changes': [{'objectId': 'title', 'properties': {'fontSize': 80, 'h': 110}}]},
                    {'type': 'scene_objects', 'slide_id': 'S001', 'base_scene_revision': 1, 'operations': [
                        {'op': 'add', 'index': 0, 'object': {'id': 'panel', 'type': 'rect', 'x': 0, 'y': 0, 'w': 400, 'h': 720, 'fill': '#EAE3D8'}}]}])
            return dict(reply='PASS', actions=[])
        validate = lambda action, base=None: patch_candidate(page if base is None else base, action, 1)
        with tempfile.TemporaryDirectory() as folder, patch('ppt_workbench.design_review.render_candidate', side_effect=render):
            final, _, report = review_candidate(page, folder, {'scene': {'sceneRevision': 1}}, 'claude', runner, validate, '')
        self.assertEqual((final['objects'][0]['id'], final['objects'][1]['fontSize']), ('panel', 80))
        self.assertEqual(report['status'], 'revised_and_reviewed')
        self.assertEqual(stages, ['critique-and-repair', 'verify-repair'])

    def test_overflow_with_a_rejected_repair_is_fitted_instead_of_failing_the_page(self):
        from ppt_workbench.design_loop import review_candidate
        page = validate_scene(scene([text('title', '标题', binding='title', size=40), text('body-1', '很长的正文内容', y=200, size=40)]))
        def render(s, folder):
            folder = Path(folder); folder.mkdir(parents=True, exist_ok=True); (folder / 'p.png').write_bytes(b'png')
            body = next(o for o in s['objects'] if o['id'] == 'body-1')
            return folder / 'p.png', dict(fontsReady=True, overflow=['body-1'] if body['fontSize'] > 30 else [])
        def runner(mode, prompt, context, **kwargs):  # Proposes a repair that changes the words.
            return dict(reply='REVISE\n溢出', actions=[{'type': 'scene_patch', 'slide_id': 'S001', 'base_scene_revision': 1,
                        'changes': [{'objectId': 'body-1', 'properties': {'text': '改写'}}]}])
        def validate(action, base=None):
            raise EngineError('DESIGN_REVIEW_SCOPE', '设计修正改变了文字或原始图片。')
        with tempfile.TemporaryDirectory() as folder, patch('ppt_workbench.design_review.render_candidate', side_effect=render):
            final, measurement, report = review_candidate(page, folder, {'scene': {'sceneRevision': 1}}, 'claude', runner, validate, '')
        body = next(o for o in final['objects'] if o['id'] == 'body-1')
        self.assertEqual(body['text'], '很长的正文内容')
        self.assertLessEqual(body['fontSize'], 30)
        self.assertEqual(measurement['overflow'], [])
        self.assertTrue(report['overflowFitted'])

    def test_pptx_exports_new_primitives_and_keeps_short_labels_on_one_line(self):
        if not shutil.which('node'):
            self.skipTest('Node.js not installed')
        s = scene([
            {'id': 'disc', 'type': 'ellipse', 'x': 900, 'y': 300, 'w': 300, 'h': 300, 'fill': '#C8553D', 'shadow': 'soft'},
            {'id': 'band', 'type': 'rect', 'x': 0, 'y': 0, 'w': 300, 'h': 200, 'fill': '#14202B', 'rotation': -10},
            text('title', '把控制权留在可编辑页面', size=48, h=70, binding='title', letterSpacing=2,
                 emphasis=['可编辑页面'], emphasisColor='#C8553D'),
            text('num', '01', x=80, y=300, w=60, h=60, size=50, bold=True, lineHeight=1),
            text('body-1', '第一行\n第二行很长的说明文字', y=400, h=120, size=20)])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'vivid.pptx'
            try:
                export_pptx([s], target)
            except EngineError as exc:
                if exc.code == 'PPTX_DEPENDENCY_MISSING':
                    self.skipTest('Install npm dependency pptxgenjs to run PPTX test')
                raise
            with zipfile.ZipFile(target) as deck:
                root = ET.fromstring(deck.read('ppt/slides/slide1.xml'))
        shapes = {sp.find('p:nvSpPr/p:cNvPr', NS).attrib['name']: sp for sp in root.findall('.//p:sp', NS)}
        self.assertEqual(shapes['disc'].find('.//a:prstGeom', NS).attrib['prst'], 'ellipse')
        self.assertIsNotNone(shapes['disc'].find('.//a:outerShdw', NS))
        self.assertEqual(shapes['band'].find('.//a:xfrm', NS).attrib.get('rot'), str(350 * 60000))
        runs = shapes['title'].findall('.//a:r', NS)
        self.assertEqual(''.join(r.find('a:t', NS).text for r in runs), '把控制权留在可编辑页面')
        accented = [r.find('a:t', NS).text for r in runs if r.find('a:rPr/a:solidFill/a:srgbClr', NS).attrib['val'] == 'C8553D']
        self.assertEqual(accented, ['可编辑页面'])
        self.assertTrue(all(r.find('a:rPr', NS).attrib.get('spc') == '150' for r in runs))
        for paragraph in root.findall('.//a:p', NS):  # Valid DrawingML: at most one pPr, before the runs.
            self.assertLessEqual(len(paragraph.findall('a:pPr', NS)), 1)
            self.assertTrue(paragraph.find('a:pPr', NS) is None or list(paragraph)[0].tag.endswith('}pPr'))
        self.assertEqual(shapes['num'].find('.//a:bodyPr', NS).attrib['wrap'], 'none')
        # CSS line pitch (fontSize × lineHeight) exported as exact points, not a font-relative percentage.
        self.assertEqual(shapes['num'].find('.//a:lnSpc/a:spcPts', NS).attrib['val'], '3750')
        self.assertIsNone(shapes['num'].find('.//a:lnSpc/a:spcPct', NS))
        self.assertEqual(shapes['body-1'].find('.//a:bodyPr', NS).attrib['wrap'], 'square')
        self.assertEqual([p.findall('a:r', NS)[0].find('a:t', NS).text for p in shapes['body-1'].findall('.//a:p', NS)],
                         ['第一行', '第二行很长的说明文字'])


class VisualRhythmTests(unittest.TestCase):
    def dull(self, sid):
        return dict(scene([text('title', '使用流程', size=42, binding='title'),
                           {'id': 'rule', 'type': 'line', 'x': 80, 'y': 170, 'w': 1100, 'h': 0},
                           text('body-1', '用自然语言说明主题、目的与需要覆盖的内容，作为整稿生成的第一步输入。', y=200, w=1100, h=420, size=22)],
                          background='#F7F5F1'), slideId=sid)

    def test_flat_text_pages_raise_warning_only_findings(self):
        rhythm = deck_rhythm([self.dull('S%03d' % i) for i in range(1, 5)])
        found = {f['code'] for f in rhythm['findings']}
        self.assertTrue({'LOW_SCALE_CONTRAST', 'FLAT_PAGE', 'LAYOUT_MONOTONY', 'NO_TONAL_RHYTHM'} <= found)
        self.assertTrue(all(f['severity'] == 'warning' for f in rhythm['findings']))
        stats = rhythm['pages'][0]
        self.assertEqual((stats['maxFontSize'], stats['bodyFontSize'], stats['tone']), (42, 22, 'light'))
        self.assertFalse(any(f['severity'] == 'error' for f in audit_scene(self.dull('S001'))))

    def test_exemplars_cover_every_archetype_without_errors_or_rhythm_findings(self):
        exemplars = library()['exemplars']
        self.assertEqual(sorted(e['archetype'] for e in exemplars), sorted(LAYOUT_ARCHETYPES))
        scenes = []
        for index, exemplar in enumerate(exemplars):
            resolved = resolved_scene(exemplar)
            resolved['slideId'] = 'S%03d' % (index + 1)
            self.assertLessEqual(len(resolved['objects']), 25, exemplar['archetype'])
            self.assertFalse([f for f in audit_scene(resolved) if f['severity'] == 'error'], exemplar['archetype'])
            self.assertFalse(visual_findings(visual_stats(resolved)), exemplar['archetype'])
            scenes.append(resolved)
        self.assertFalse(codes(deck_rhythm(scenes)['findings'], 'LAYOUT_MONOTONY'))

    def test_few_anchors_and_repeated_previous_skeleton_are_reported(self):
        from ppt_workbench.quality import previous_page_findings
        dull = [self.dull('S%03d' % i) for i in range(1, 5)]
        self.assertTrue(codes(deck_rhythm(dull)['findings'], 'FEW_ANCHORS'))
        first, second = visual_stats(dull[0]), visual_stats(dull[1])
        self.assertEqual(previous_page_findings(first, second)[0]['code'], 'SIMILAR_TO_PREVIOUS')
        hero = resolved_scene(next(e for e in library()['exemplars'] if e['archetype'] == 'hero-statement'))
        self.assertEqual(previous_page_findings(first, visual_stats(hero)), [])

    def test_dark_split_and_inverse_tones_are_measured(self):
        split = visual_stats(scene([{'id': 'p', 'type': 'rect', 'x': 0, 'y': 0, 'w': 500, 'h': 720, 'fill': '#14202B'},
                                    text('title', '标题', size=60, binding='title'), text('body-1', '正文' * 10, y=300, size=20)]))
        self.assertEqual(split['tone'], 'split')
        self.assertEqual(split['scaleRatio'], 3.0)
        inverse = visual_stats(scene([text('title', '标题', size=60, color='#FFFFFF', binding='title')], background='#14202B'))
        self.assertEqual(inverse['tone'], 'inverse')
        self.assertIsNone(inverse['scaleRatio'])


class PlanContractTests(unittest.TestCase):
    def test_optional_design_strategy_brief_fields_validate_and_old_plans_still_pass(self):
        validate_design({'background': '#FFFFFF', 'ink': '#111111', 'accent': '#C8553D', 'fontFamily': 'Noto Sans SC'})
        validate_design({'background': '#FFFFFF', 'ink': '#111111', 'accent': '#C8553D', 'fontFamily': 'Noto Sans SC',
                         'secondary': '#2F6F73', 'surface': '#EAE3D8', 'inverse': '#14202B'})
        with self.assertRaises(EngineError):
            validate_design({'background': '#FFFFFF', 'ink': '#111111', 'accent': '#C8553D', 'fontFamily': 'X', 'surface': 'beige'})
        with self.assertRaises(EngineError):
            validate_design({'background': '#FFFFFF', 'ink': '#111111', 'accent': '#C8553D', 'fontFamily': 'X', 'glow': '#FFFFFF'})
        validate_strategy(STRATEGY)
        validate_strategy(dict(STRATEGY, signatureMotif='左侧出血色带与大号淡色序号', scaleContrast='锚点96/标题44/正文20'))
        with self.assertRaises(EngineError):
            validate_strategy(dict(STRATEGY, palette='暖色'))
        validate_brief(BRIEF)
        rich = dict(BRIEF, layoutArchetype='big-number', focalElement='原文数字 3', backgroundTreatment='split', imagePrompt='晨雾中的远山')
        self.assertEqual(validate_brief(rich), rich)
        for bad in ({'imagePrompt': '图' * 601}, {'focalElement': ''}, {'density': 'medium'}):
            with self.assertRaises(EngineError):
                validate_brief(dict(BRIEF, **bad))
        # Optional layout hints never fail a plan: synonyms (even a relationship name in the
        # wrong field) are mapped, unknown values are dropped.
        hinted = dict(BRIEF, layoutArchetype='Process', backgroundTreatment='dark', density='sparse')
        validate_brief(hinted)
        self.assertEqual((hinted['layoutArchetype'], hinted['backgroundTreatment'], hinted['density']),
                         ('timeline', 'inverse', 'breathing'))
        unknown = dict(BRIEF, layoutArchetype='bento', backgroundTreatment='gradient')
        validate_brief(unknown)
        self.assertNotIn('layoutArchetype', unknown)
        self.assertNotIn('backgroundTreatment', unknown)

    def test_missing_or_misnamed_design_notes_are_filled_from_page_content(self):
        from ppt_workbench.deck_design import normalize_brief
        brief = normalize_brief({'claim': '自有主张', 'notes': '多余字段', 'density': ''}, COMPOSITION, '能力边界')
        validate_brief(brief)
        self.assertEqual(brief['claim'], '自有主张')
        self.assertNotIn('notes', brief)
        self.assertEqual(brief['density'], 'breathing')
        self.assertEqual(normalize_brief(None, COMPOSITION)['claim'], COMPOSITION['purpose'])

    def test_plan_rhythm_reports_missing_repeated_flat_and_excess_images(self):
        plan = {'strategy': STRATEGY, 'pages': [{'designBrief': dict(BRIEF)} for _ in range(5)]}
        self.assertEqual({f['code'] for f in plan_rhythm(plan)}, {'ARCHETYPE_MISSING', 'TONE_FLAT'})
        archetypes = ['hero-statement', 'grid-cards', 'grid-cards', 'timeline', 'quote']
        for page, archetype, treatment in zip(plan['pages'], archetypes, ['inverse', 'paper', 'paper', 'paper', 'paper']):
            page['designBrief'].update(layoutArchetype=archetype, backgroundTreatment=treatment, imagePrompt='无文字配图')
        found = {f['code']: f for f in plan_rhythm(plan, 'auto')}
        self.assertEqual(found['ARCHETYPE_REPEAT']['pages'], [[2, 3]])
        self.assertIn('IMAGE_PAGES_EXCEED', found)
        self.assertNotIn('TONE_FLAT', found)
        self.assertNotIn('IMAGE_PAGES_EXCEED', {f['code'] for f in plan_rhythm(plan, 'off')})
        self.assertEqual(plan_rhythm({'pages': plan['pages']}), [])

    def test_sparse_plan_review_may_add_only_whitelisted_optional_fields(self):
        draft = dict(deck_plan(), type='deck_start')
        draft['design'] = {'background': '#FFFFFF', 'ink': '#111111', 'accent': '#C8553D', 'fontFamily': 'Noto Sans SC'}
        patch_action = {'type': 'deck_plan_patch', 'changes': [
            {'path': ['pages', 0, 'designBrief', 'layoutArchetype'], 'value': 'comparison'},
            {'path': ['pages', 1, 'composition', 'blocks', 0, 'kicker'], 'value': '现在'},
            {'path': ['design', 'inverse'], 'value': '#14202B'},
            {'path': ['strategy', 'signatureMotif'], 'value': '明暗两半'}]}
        revised = apply_plan_patch(draft, patch_action)
        self.assertEqual(revised['pages'][0]['designBrief']['layoutArchetype'], 'comparison')
        self.assertEqual(revised['pages'][1]['composition']['blocks'][0]['kicker'], '现在')
        self.assertEqual(revised['design']['inverse'], '#14202B')
        self.assertNotIn('layoutArchetype', draft['pages'][0]['designBrief'])
        for path in (['pages', 0, 'designBrief', 'mood'], ['pages', 0, 'notes'], ['design', 'glow'], ['strategy', 'palette']):
            with self.assertRaises(EngineError):
                apply_plan_patch(draft, {'type': 'deck_plan_patch', 'changes': [{'path': path, 'value': 'x'}]})

    def test_plan_reviewer_receives_rhythm_findings(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        studio = Studio(tmp.name, 'test', agent='manual')
        proposal = dict(reply='草稿', actions=[dict(type='deck_start', **deck_plan())])
        seen = []
        def runner(mode, prompt, context, **kwargs):
            seen.append(context['rhythmFindings'])
            self.assertIn('rhythmFindings', prompt)
            return dict(reply='PASS', actions=[])
        review_plan(studio, {'id': 'J-rhythm', 'payload': {}}, proposal, {'imageMode': 'auto'}, 'claude', runner)
        self.assertEqual({f['code'] for f in seen[0]}, {'ARCHETYPE_MISSING'})
        report = json.loads((studio.wb.project_dir('test') / 'plan-reviews' / 'J-rhythm' / 'report.json').read_text())
        self.assertEqual(report['finalRhythmFindings'], seen[0])


class AnchorTests(unittest.TestCase):
    def test_kicker_and_metric_are_short_optional_anchors_resolved_by_text_ref(self):
        composition = copy.deepcopy(COMPOSITION)
        composition['blocks'][0].update(kicker='现在', metric='2')
        validate_composition(composition)
        for bad in ({'kicker': '很长很长很长很长很长很长很长很长的标签'}, {'metric': ''}, {'note': '额外'}):
            broken = copy.deepcopy(COMPOSITION)
            broken['blocks'][0].update(bad)
            with self.assertRaises(EngineError):
                validate_composition(broken)
        a = action()
        a['composition'] = composition
        a['scene']['objects'].append({'id': 'kicker', 'type': 'text', 'textRef': 'block.now.kicker', 'x': 64, 'y': 400, 'w': 200, 'h': 40, 'fontSize': 16})
        a['scene']['objects'].append({'id': 'metric', 'type': 'text', 'textRef': 'block.now.metric', 'x': 64, 'y': 450, 'w': 200, 'h': 140, 'fontSize': 110})
        resolved = prepare_scene(a)
        self.assertEqual([o['text'] for o in resolved['objects'][-2:]], ['现在', '2'])
        ranged = copy.deepcopy(a)
        ranged['scene']['objects'][-1]['textRange'] = [0, 1]
        with self.assertRaises(EngineError):
            prepare_scene(ranged)
        missing = copy.deepcopy(a)
        missing['scene']['objects'][-1]['textRef'] = 'block.later.metric'
        # The plan has no such optional anchor: only that decoration is dropped, never planned words.
        self.assertNotIn('metric', [o['id'] for o in prepare_scene(missing)['objects']])

    def test_unsourced_metrics_are_dropped_before_the_plan_is_saved(self):
        plan = deck_plan()
        plan['pages'][0]['composition']['blocks'][0]['metric'] = '80%'
        plan['pages'][1]['composition']['blocks'][0]['metric'] = '3 个'
        plan['pages'][1]['composition']['blocks'][1]['metric'] = '三步'
        dropped = drop_unsupported_metrics(copy.deepcopy(plan), ['我们有 3 个控制点'])
        self.assertEqual([d['metric'] for d in dropped], ['80%', '三步'])
        from ppt_workbench.page_design import metric_supported
        for metric, source, expected in (('80', '已有180个用户', False), ('3亿元', '系统有3个模块', False),
                                         ('八成', '多数用户愿意复用', False), ('180', '已有180个用户', True),
                                         ('3个', '系统有3个模块', True), ('80 %', '满意度80％', True),
                                         ('1.5', '版本 1.52 发布', False), ('三步', '只需三步完成', True),
                                         ('八亿元', '营收十八亿元', False), ('十万元', '成本三十万元', False),
                                         ('十八亿元', '营收十八亿元', True), ('三十万元', '成本三十万元', True),
                                         ('第三', '第三十名', False)):
            self.assertEqual(metric_supported(metric, source), expected, (metric, source))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        studio = Studio(tmp.name, 'test', agent='manual')
        studio.create_deck(plan, '介绍工作台：三个控制点，3 个页面角色')
        saved = studio.next_job()['context']['currentDeckPage']['composition']['blocks'][0]
        self.assertNotIn('metric', saved)

    def test_relationship_synonyms_are_mapped_and_unknown_values_name_the_allowed_set(self):
        for given, expected in (('timeline', 'process'), ('Hub_Spoke', 'hub'), ('对比', 'comparison'),
                                (' Summary ', 'summary'), ('流程', 'process'), ('evidence', 'evidence'),
                                ('ordered-rows', 'process'), ('grid-cards', 'parallel')):
            composition = copy.deepcopy(COMPOSITION)
            composition['relationship'] = given
            self.assertEqual(validate_composition(composition)['relationship'], expected, given)
        for unknown in ('mosaic', None, ['process']):
            composition = copy.deepcopy(COMPOSITION)
            composition['relationship'] = unknown
            with self.assertRaises(EngineError) as caught:
                validate_composition(composition)
            self.assertIn('hero、parallel、comparison、process', caught.exception.message)

    def test_text_ref_variants_resolve_to_planned_words_and_unknown_refs_name_the_valid_ones(self):
        def page(*objects):
            a = action()
            a['scene']['objects'] = [o for o in a['scene']['objects'] if o['id'] == 'title'] + list(objects)
            return a
        ref = lambda oid, value, **extra: {'id': oid, 'type': 'text', 'textRef': value, 'x': 64, 'y': 200, 'w': 500, 'h': 80, 'fontSize': 26, **extra}
        resolved = prepare_scene(page(ref('h', 'blocks.now.Title', text='模型重打的字'), ref('b', 'now.content'),
                                      ref('k', 'block.now.kicker'), ref('h2', 'block.later.heading'), ref('b2', 'block.later.body')))
        texts = {o['id']: o['text'] for o in resolved['objects']}
        self.assertEqual((texts['h'], texts['b']), ('已实现', '直接修改文字与布局'))
        self.assertNotIn('k', texts)  # Optional kicker absent from the plan: the decoration is dropped.
        with self.assertRaises(EngineError) as caught:
            prepare_scene(page(ref('x', 'block.zzz.body')))
        self.assertIn("'block.zzz.body'", caught.exception.message)
        self.assertIn('block.now.heading', caught.exception.message)

    def test_table_cells_cover_a_pipe_separated_block_but_missing_cells_fail(self):
        a = action()
        a['composition']['blocks'][1]['body'] = '精华版｜1天｜6万元\n标准版｜3天｜15万元'
        cells = ['精华版', '1天', '6万元', '标准版', '3天', '15万元']
        a['scene']['objects'] = [o for o in a['scene']['objects'] if o['id'] != 'later-body'] + [
            text(f'c{i}', c, x=680 + (i % 3) * 120, y=300 + (i // 3) * 60, w=110, h=50, size=20) for i, c in enumerate(cells)]
        prepare_scene(a)
        a['scene']['objects'] = [o for o in a['scene']['objects'] if o.get('text') != '15万元']
        with self.assertRaises(EngineError):
            prepare_scene(a)

    def test_unbound_or_missing_planned_title_is_bound_or_added(self):
        a = action()
        a['scene']['objects'][0].pop('binding'); a['scene']['objects'][0]['text'] = '能力\n边界'
        bound = prepare_scene(a)
        self.assertEqual([o['text'] for o in bound['objects'] if o.get('binding') == 'title'], ['能力边界'])
        b = action()
        b['scene']['objects'] = b['scene']['objects'][1:]
        added = prepare_scene(b)
        self.assertEqual([o['text'] for o in added['objects'] if o.get('binding') == 'title'], ['能力边界'])

    def test_style_numbers_are_clamped_but_non_numbers_still_fail(self):
        page = validate_scene(scene([text('n', '3', size=200, lineHeight=0.6, opacity=1.4),
                                     {'id': 'r', 'type': 'rect', 'x': 0, 'y': 0, 'w': 5, 'h': 30, 'radius': 20, 'strokeWidth': 40}]))
        number, bar = page['objects']
        self.assertEqual((number['fontSize'], number['lineHeight'], number['opacity']), (160, 1, 1))
        self.assertEqual((bar['radius'], bar['strokeWidth']), (2.5, 24))
        for bad in ({'fontSize': 'huge'}, {'fontSize': float('nan')}, {'opacity': None}):
            with self.assertRaises(EngineError):
                validate_scene(scene([dict(text('n', '3'), **bad)]))
        self.assertIn('setTimeout(reportQuality', render_html(page))

    def test_capacity_estimate_uses_the_new_body_size(self):
        result = page_capacity({'composition': {'blocks': [dict(id='a', heading='步骤', body='说明' * 30)]}})
        self.assertEqual(result['equalColumnScenario']['bodyFontPx'], 20)
        self.assertEqual(result['groups'][0]['estimatedBodyLinesIfEqualColumns'], 2)


class ExemplarContextTests(unittest.TestCase):
    def test_generation_context_carries_one_matching_exemplar(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        studio = Studio(tmp.name, 'test', agent='manual')
        plan = deck_plan()
        plan['pages'][0]['designBrief']['layoutArchetype'] = 'big-number'
        studio.create_deck(plan, '完整用户需求')
        context = studio.next_job()['context']
        self.assertEqual(context['designExemplar']['archetype'], 'big-number')
        self.assertTrue(any(o.get('textRef') == 'block.A.metric' for o in context['designExemplar']['scene']['objects']))
        self.assertEqual(context['imageMode'], 'auto')
        self.assertEqual(context['autoImageLimit'], MAX_AUTO_IMAGES)
        self.assertIn('ellipse', context['sceneSpec']['types'])

    def test_fallback_archetype_follows_role_relationship_and_avoids_repeating_previous(self):
        self.assertEqual(for_page({'role': 'cover', 'composition': {'relationship': 'parallel'}})['archetype'], 'hero-statement')
        self.assertEqual(for_page({'role': 'content', 'composition': {'relationship': 'process'}})['archetype'], 'timeline')
        self.assertEqual(for_page({'role': 'content', 'composition': {'relationship': 'process'}}, previous='timeline')['archetype'], 'split-asymmetric')
        metric = {'role': 'content', 'composition': {'relationship': 'evidence', 'blocks': [{'id': 'a', 'metric': '3'}]}}
        self.assertEqual(for_page(metric)['archetype'], 'big-number')


class Provider:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return GeneratedImage(PNG, 'image/png')


class AutoImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = Studio(self.tmp.name, 'test', agent='manual')

    def finish_deck(self, prompts=(True, False), slot=True):
        plan = deck_plan()
        plan['design'] = {'background': '#F6F3EE', 'ink': '#1D2A35', 'accent': '#C8553D', 'fontFamily': 'Noto Sans SC', 'surface': '#EAE3D8'}
        for page, prompt in zip(plan['pages'], prompts):
            if prompt:
                page['designBrief']['imagePrompt'] = '晨雾中的远山，右侧留白'
        self.studio.create_deck(plan, '完整用户需求')
        for _ in range(2):
            job = self.studio.next_job()['job']
            a = action()
            if slot:
                a['scene']['objects'].insert(0, {'id': 'image-slot', 'type': 'rect', 'x': 760, 'y': 0, 'w': 520, 'h': 720, 'fill': '#EAE3D8'})
            self.studio.apply_plan(job['id'], dict(reply='页', actions=[a]))
        with self.studio.wb.atomic() as db:
            deck = self.studio._deck_row(db)
            row = db.execute('SELECT id FROM studio_jobs WHERE client_message_id=?', ('deck-review:' + deck['id'],)).fetchone()
            db.execute("UPDATE studio_jobs SET status='running' WHERE id=?", (row['id'],))
        def sheets(scenes, folder):
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            png = folder / 'sheet.png'
            png.write_bytes(b'png')
            return [(0, len(scenes), png)], [dict(fontsReady=True, overflow=[]) for _ in scenes]
        with patch('ppt_workbench.deck_review.contact_sheets', side_effect=sheets):
            run_review(self.studio, self.studio.job(row['id']), 'claude', lambda *a, **k: dict(reply='PASS', actions=[]))
        return [b for b in self.studio.state()['imageBatches']]

    def test_mode_defaults_on_and_can_be_switched_off(self):
        self.assertEqual(self.studio.image_mode(), 'auto')
        with patch.dict(os.environ, {'WEPPT_AUTO_IMAGES': 'off'}):
            self.assertEqual(self.studio.image_mode(), 'off')
        self.assertEqual(self.studio.set_image_mode('off')['imageMode'], 'off')
        with self.assertRaises(EngineError):
            self.studio.set_image_mode('always')

    def test_finished_deck_queues_marked_slot_and_applies_it_automatically(self):
        batches = self.finish_deck()
        self.assertEqual(len(batches), 1)
        slide = batches[0]['slide_id']
        before = self.studio.get_scene(slide)
        provider = Provider()
        ImageJobs(self.studio).run_batch(batches[0]['id'], provider)
        self.assertIn('不出现任何文字', provider.prompts[0])
        self.assertIn('晨雾中的远山', provider.prompts[0])
        after = self.studio.get_scene(slide)
        image = after['scene']['objects'][0]
        self.assertEqual((image['id'], image['type'], image['x'], image['w']), ('image-slot', 'image', 760, 520))
        self.assertEqual([o['text'] for o in after['scene']['objects'] if o['type'] == 'text'],
                         [o['text'] for o in before['scene']['objects'] if o['type'] == 'text'])
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'applied')
        self.assertEqual(self.studio.deck_state()['revisionCount'], 0)

    def test_auto_image_lands_on_newer_revision_only_when_slot_is_untouched(self):
        batch = self.finish_deck()[0]
        current = self.studio.get_scene(batch['slide_id'])
        self.studio.change_scene(batch['slide_id'], current['sceneRevision'], [{'objectId': 'title', 'properties': {'x': 70}}])
        ImageJobs(self.studio).run_batch(batch['id'], Provider())
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'applied')
        scene = self.studio.get_scene(batch['slide_id'])['scene']
        self.assertEqual(next(o for o in scene['objects'] if o['id'] == 'title')['x'], 70)

    def test_moved_slot_is_a_conflict_and_keeps_the_colour_field(self):
        batch = self.finish_deck()[0]
        current = self.studio.get_scene(batch['slide_id'])
        self.studio.change_scene(batch['slide_id'], current['sceneRevision'], [{'objectId': 'image-slot', 'properties': {'x': 700}}])
        ImageJobs(self.studio).run_batch(batch['id'], Provider())
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'conflict')
        slot = next(o for o in self.studio.get_scene(batch['slide_id'])['scene']['objects'] if o['id'] == 'image-slot')
        self.assertEqual(slot['type'], 'rect')

    def test_any_user_edit_to_the_reserved_slot_wins_over_the_image(self):
        batch = self.finish_deck()[0]
        current = self.studio.get_scene(batch['slide_id'])
        self.studio.change_scene(batch['slide_id'], current['sceneRevision'], [{'objectId': 'image-slot', 'properties': {'rotation': 15}}])
        ImageJobs(self.studio).run_batch(batch['id'], Provider())
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'conflict')
        slot = next(o for o in self.studio.get_scene(batch['slide_id'])['scene']['objects'] if o['id'] == 'image-slot')
        self.assertEqual((slot['type'], slot['rotation']), ('rect', 15))
        for props in ({'fill': '#C8553D'}, {'shadow': 'soft'}):
            entry = {'auto': True, 'slot': dict(slot), 'replace_object_id': 'image-slot'}
            from ppt_workbench.auto_images import slots_unchanged
            edited = dict(self.studio.get_scene(batch['slide_id'])['scene'])
            edited['objects'] = [dict(o, **props) if o['id'] == 'image-slot' else o for o in edited['objects']]
            self.assertFalse(slots_unchanged(edited, [entry]), props)

    def test_landed_image_keeps_the_deck_review_current(self):
        batch = self.finish_deck()[0]
        before = self.studio.deck_state()['designReview']['status']
        ImageJobs(self.studio).run_batch(batch['id'], Provider())
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'applied')
        self.assertEqual(self.studio.deck_state()['designReview']['status'], before)
        self.assertNotEqual(before, 'stale')

    def test_server_switch_overrides_saved_project_setting(self):
        self.studio.set_image_mode('auto')
        with patch.dict(os.environ, {'WEPPT_AUTO_IMAGES': 'off'}):
            self.assertEqual(self.studio.image_mode(), 'off')
            self.assertTrue(self.studio.state()['imageModeLocked'])
            with self.assertRaises(EngineError) as caught:
                self.studio.set_image_mode('auto')
            self.assertEqual(caught.exception.code, 'IMAGE_MODE_LOCKED')
            self.assertEqual(self.studio.set_image_mode('off')['imageMode'], 'off')

    def test_no_batches_without_slot_prompt_or_when_mode_is_off(self):
        self.assertEqual(self.finish_deck(slot=False), [])
        self.studio = Studio(tempfile.mkdtemp(dir=self.tmp.name), 'test', agent='manual')
        self.assertEqual(self.finish_deck(prompts=(False, False)), [])
        self.studio = Studio(tempfile.mkdtemp(dir=self.tmp.name), 'test', agent='manual')
        self.studio.set_image_mode('off')
        self.assertEqual(self.finish_deck(), [])


if __name__ == '__main__':
    unittest.main()
