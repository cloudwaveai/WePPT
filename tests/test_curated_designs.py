import copy
import json
import tempfile
import unittest
from pathlib import Path

from ppt_workbench import curated_designs, template_packs
from ppt_workbench.core import EngineError
from ppt_workbench.deck_design import validate_strategy
from ppt_workbench.studio import Studio
from test_deck_design import deck_plan, STRATEGY
import test_http


class CuratedDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = Studio(self.tmp.name, 'curated', agent='manual')

    def test_reviewed_catalog_has_exact_identity_and_all_previews(self):
        records = curated_designs.catalog()
        self.assertEqual(len(records), 50)
        self.assertEqual(len({r['id'] for r in records}), 50)
        self.assertEqual(len({r['catalog_id'] for r in records}), 50)
        self.assertEqual(sum(r['use'] == '排版主库' for r in records), 30)
        self.assertEqual(sum(len(r['previews']) for r in records), 400)
        for r in records:
            self.assertTrue(r['caution'] and r['adaptation_proposal'])
            self.assertTrue(r['source_url'].startswith('https://'))
        records[0]['name'] = 'mutated'
        self.assertNotEqual(curated_designs.catalog()[0]['name'], 'mutated')

    def test_planner_sees_50_but_is_not_forced_into_default_pack(self):
        ctx = self.studio.context()
        self.assertEqual(len(ctx['curatedDesignLibrary']['references']), 50)
        self.assertIsNone(ctx['templateContract'])
        proposal = {'reply': 'ready', 'actions': [{'type': 'deck_start', **deck_plan()}]}
        routed = template_packs.default_plan(proposal, ctx)
        self.assertEqual(proposal, routed)

    def test_selected_reference_survives_real_deck_job_roundtrip(self):
        plan = deck_plan()
        plan['strategy']['curatedReferenceId'] = 'curated-129'
        original = copy.deepcopy(plan)
        self.studio.create_deck(plan, '文案已确认，参考紫绿金属，根据内容排版。')
        ctx = self.studio.next_job()['context']
        refs = ctx['curatedDesignReferences']
        self.assertEqual(refs['selectedReferenceId'], 'curated-129')
        self.assertEqual([r['id'] for r in refs['references']], ['curated-129'])
        self.assertEqual(ctx['currentDeckPage']['composition'], original['pages'][0]['composition'])
        self.assertIsNone(ctx['curatedDesignLibrary'])
        self.assertIsNone(ctx['templateContract'])
        self.assertFalse(template_packs.is_local_job(self.studio, self.studio.next_job()['job']['payload']))
        self.assertEqual(plan, original)

    def test_invalid_reference_is_rejected(self):
        with self.assertRaises(EngineError) as caught:
            validate_strategy({**STRATEGY, 'curatedReferenceId': 'curated-missing'})
        self.assertEqual(caught.exception.code, 'INVALID_DESIGN_REFERENCE')

    def test_reference_language_stays_consistent_on_content_page(self):
        page = deck_plan()['pages'][0]
        result = curated_designs.for_page(page, {**STRATEGY, 'curatedReferenceId': 'curated-228'})
        self.assertEqual(result['references'][0]['id'], 'curated-228')
        self.assertIn('正文', result['roleAdvice'])
        self.assertNotIn('scene', result)
        self.assertNotIn('previews', result['references'][0])

    def test_role_shortlist_does_not_mutate_or_inject_business_content(self):
        page = deck_plan()['pages'][0]
        original = copy.deepcopy(page)
        body = curated_designs.for_page(page)
        self.assertEqual(len(body['references']), 3)
        self.assertTrue(all(r['use'] == '排版主库' for r in body['references']))
        hero = curated_designs.for_page({**page, 'role': 'cover'})
        self.assertTrue(all(r['use'] == '视觉增强' for r in hero['references']))
        self.assertEqual(page, original)

    def test_retired_pack_preference_does_not_bind_new_deck(self):
        template_packs.select(self.studio, template_packs.DEFAULT, self.studio.state()['projectRevision'])
        ctx = self.studio.context()
        self.assertIsNone(ctx['templateContract'])
        plan = deck_plan()
        plan['strategy']['curatedReferenceId'] = 'curated-129'
        self.studio.create_deck(plan, '明确采用固定套系')
        job = self.studio.next_job()
        self.assertFalse(template_packs.is_local_job(self.studio, job['job']['payload']))

    def test_historical_bound_plan_without_preference_keeps_contract(self):
        plan = deck_plan()
        for p in plan['pages']:
            p['template_id'] = template_packs.DEFAULT + ':body-rows'
        self.studio.create_deck(plan, '历史模板任务')
        self.assertIsNotNone(self.studio.next_job()['context']['templateContract'])


class CuratedHTTPTests(unittest.TestCase):
    setUp = test_http.HTTPTests.setUp
    tearDown = test_http.HTTPTests.tearDown
    request = test_http.HTTPTests.request
    def test_curated_catalog_route_and_editor_entry(self):
        status, headers, raw = self.request('GET', '/curated-designs.html')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers['Content-Type'])
        text = raw.decode('utf-8')
        self.assertEqual(text.count('<article '), 50)
        self.assertEqual(text.count('<figcaption>代表图'), 400)
        self.assertIn('id="curated-129"', text)
        self.assertEqual(self.request('GET', '/curated-designs.html', authorized=False)[0], 401)
        status, _, raw = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('href="/curated-designs.html"', raw.decode('utf-8'))
