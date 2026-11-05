import json
import unittest
import test_http
from ppt_workbench import curated_designs, templates, template_packs


class RetiredTemplateTests(unittest.TestCase):
    setUp = test_http.HTTPTests.setUp
    tearDown = test_http.HTTPTests.tearDown
    request = test_http.HTTPTests.request

    def test_library_contains_only_curated_50_and_no_old_75(self):
        old_ids = set(templates._REFERENCE)
        self.assertEqual(len(old_ids), 75)
        cards = json.loads(self.request('GET', '/api/templates')[2])['templates']
        self.assertEqual({c['id'] for c in cards}, {r['id'] for r in curated_designs.catalog()})
        self.assertFalse(old_ids & {c['id'] for c in cards})
        self.assertEqual(json.loads(self.request('GET', '/api/template-packs')[2])['packs'], [])
        recommendations = json.loads(self.request('GET', '/api/templates/recommendations')[2])
        self.assertTrue(all(c['referenceOnly'] for c in recommendations['recommendations']))

    def test_retired_writes_leave_existing_document_unchanged(self):
        self.server.studio.demo()
        before = self.server.studio.get_scene('S001')
        for endpoint in ('/api/template', '/api/template-packs/select', '/api/template-packs/apply',
                         '/api/templates/adapt', '/api/templates/match', '/api/templates/recommendations'):
            status, _, raw = self.request('POST', endpoint, {'templateId': 'cover', 'packId': template_packs.DEFAULT})
            self.assertEqual(status, 410, endpoint)
            self.assertEqual(json.loads(raw)['error']['code'], 'TEMPLATE_RETIRED')
        self.assertEqual(self.server.studio.get_scene('S001'), before)
        self.assertEqual(self.request('GET', '/api/scene?slide=S001')[0], 200)

    def test_ai_new_project_has_no_legacy_candidates_even_with_old_preference(self):
        studio = self.server.studio
        template_packs.select(studio, template_packs.DEFAULT, studio.state()['projectRevision'])
        studio.select_template('editorial')  # Simulate a preference saved before retirement.
        ctx = studio.context()
        self.assertIsNone(ctx['templateContract'])
        self.assertIsNone(ctx['selectedTemplateId'])
        self.assertEqual(ctx['templates'], [])
        self.assertEqual(ctx['recommendedTemplates'], [])
        self.assertEqual(len(ctx['curatedDesignLibrary']['references']), 50)

    def test_curated_cover_validates_id_and_retains_authentication(self):
        url = '/api/curated-designs/cover?id=curated-129'
        self.assertEqual(self.request('GET', url, authorized=False)[0], 401)
        self.assertEqual(self.request('GET', url)[0], 200)
        for value in ('../../server.py', 'cover', 'curated-missing'):
            self.assertEqual(self.request('GET', '/api/curated-designs/cover?id=' + value)[0], 400)

    def test_user_upload_library_is_preserved(self):
        status, _, raw = self.request('GET', '/api/user-templates')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['templates'], [])
