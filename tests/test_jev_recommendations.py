import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ppt_workbench import jev_recommendations as jev
from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio


def response(payload, *, winner=-1, confidence=.95):
    ids = list(payload['questions']['template']['criteria'])
    return {'answers': {'template': {'type': 'choice', 'choice': ids[winner],
            'confidence': confidence, 'probabilities': {k: 1 if k == ids[winner] else 0 for k in ids}}}}


class JevTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.studio = Studio(self.temp.name, 'jev', agent='manual')
        self.studio.demo()
        self.sid = self.studio.state()['selectedSlideId']
        self.before = self.studio.get_scene(self.sid)
        self.rev = self.before['sceneRevision']
        self.env = patch.dict(os.environ, {'WEPPT_JEV_API_KEY': 'test-secret-only', 'WEPPT_JEV_MODEL': jev.DEFAULT_MODEL})
        self.env.start()
        self.addCleanup(self.env.stop)
        jev._cache.clear()
        jev._last_attempt = 0

    def recommend(self):
        return jev.recommend(self.studio, self.sid, self.rev)

    def test_reads_do_not_call_model_and_missing_key_falls_back(self):
        with patch.object(jev, '_request') as request:
            self.assertTrue(self.studio.template_recommendations(self.sid)['smartAvailable'])
            with patch.dict(os.environ, {'WEPPT_JEV_API_KEY': ''}):
                self.assertEqual(self.recommend()['recommendationEngine'], 'rules')
            request.assert_not_called()

    def test_rank_cache_and_no_page_mutation(self):
        calls = []
        def call(payload, key):
            calls.append(copy.deepcopy(payload))
            return response(payload)
        with patch.object(jev, '_request', side_effect=call) as request:
            first, second = self.recommend(), self.recommend()
            self.assertEqual(request.call_count, 1)
        ids = list(calls[0]['questions']['template']['criteria'])
        self.assertEqual(first['recommendationEngine'], 'jev')
        self.assertEqual(first['recommendations'][0]['id'], ids[-1])
        self.assertTrue(second['cached'])
        self.assertLessEqual(len(ids), 12)
        self.assertEqual(self.studio.get_scene(self.sid), self.before)
        self.assertNotIn('test-secret-only', json.dumps(first))

    def test_current_edited_text_used_without_image_payloads(self):
        text = next(o for o in self.before['scene']['objects'] if o['type'] == 'text')
        self.studio.edit_scene(self.sid, self.rev, [{'objectId': text['id'], 'properties': {'text': '用户刚编辑的新文字'}}])
        self.rev = self.studio.get_scene(self.sid)['sceneRevision']
        def check(payload, key):
            self.assertIn('用户刚编辑的新文字', payload['state'])
            self.assertNotIn('data:image', json.dumps(payload))
            return response(payload)
        with patch.object(jev, '_request', side_effect=check):
            self.assertEqual(self.recommend()['recommendationEngine'], 'jev')

    def test_invalid_or_failed_provider_is_safe_fallback(self):
        for bad in ({}, {'answers': {'template': {'choice': 'invented'}}},
                    TimeoutError('test-secret-only: provider body')):
            jev._cache.clear(); jev._last_attempt = 0
            with patch.object(jev, '_request', side_effect=bad if isinstance(bad, Exception) else None, return_value=bad) as request:
                result = self.recommend()
                self.assertEqual(result['recommendationEngine'], 'rules')
                self.assertEqual(result['recommendationStatus'], 'unavailable')
                self.assertNotIn('test-secret-only', json.dumps(result))
                self.assertTrue(self.recommend()['cached'])
                self.assertEqual(request.call_count, 1)
        self.assertEqual(self.studio.get_scene(self.sid), self.before)

    def test_invalid_probabilities_and_uncertainty(self):
        for confidence, expected in ((float('nan'), 'unavailable'), (.1, 'uncertain')):
            jev._cache.clear(); jev._last_attempt = 0
            with patch.object(jev, '_request', side_effect=lambda p, k: response(p, confidence=confidence)):
                result = self.recommend()
                self.assertEqual(result['recommendationStatus'], expected)
                self.assertEqual(result['recommendationEngine'], 'rules')

    def test_page_changed_during_decision_rejects_result(self):
        def change(payload, key):
            text = next(o for o in self.before['scene']['objects'] if o['type'] == 'text')
            self.studio.edit_scene(self.sid, self.rev, [{'objectId': text['id'], 'properties': {'text': '并发编辑'}}])
            return response(payload)
        with patch.object(jev, '_request', side_effect=change), self.assertRaises(EngineError) as error:
            self.recommend()
        self.assertEqual(error.exception.code, 'STALE_REVISION')

    def test_stale_input_never_calls_model(self):
        with patch.object(jev, '_request') as request, self.assertRaises(EngineError):
            jev.recommend(self.studio, self.sid, self.rev - 1)
        request.assert_not_called()

    def test_single_layout_is_not_misreported_as_missing_configuration(self):
        from ppt_workbench.templates import recommend_templates
        only = recommend_templates('cover', limit=1)
        with patch.object(jev, 'recommend_templates', return_value=only), patch.object(jev, '_request') as request:
            result = self.recommend()
            self.assertEqual(result['recommendationStatus'], 'single_candidate')
            self.assertEqual(result['recommendationEngine'], 'rules')
            request.assert_not_called()

    def test_concurrent_request_does_not_duplicate_external_call(self):
        with patch.object(jev, '_request') as request:
            jev._lock.acquire()
            try:
                result = self.recommend()
            finally:
                jev._lock.release()
            self.assertEqual(result['recommendationStatus'], 'busy')
            request.assert_not_called()

    def test_transport_uses_fixed_endpoint_timeout_and_no_redirect(self):
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
            jev._request({'model': jev.DEFAULT_MODEL}, 'test-secret-only')
            args, kwargs = opener.return_value.open.call_args
            self.assertEqual(args[0].full_url, jev.ENDPOINT)
            self.assertEqual(args[0].get_header('User-agent'), 'WePPT/1.0')
            self.assertEqual(kwargs['timeout'], 15)
            self.assertIsInstance(opener.call_args.args[0], jev._NoRedirect)


if __name__ == '__main__':
    unittest.main()
