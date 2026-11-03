import base64
import tempfile
import unittest
import copy

from ppt_workbench.core import EngineError

from ppt_workbench.image_generation import GeneratedImage, ImageJobs
from ppt_workbench.studio import Studio

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII=')


class Provider:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return GeneratedImage(PNG, 'image/png')


class ImageJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.studio = Studio(self.tmp.name, 'demo')
        self.slide = self.studio.demo()['slides'][0]['id']
        scene = self.studio.get_scene(self.slide)
        self.studio.change_scene_objects(self.slide, scene['sceneRevision'], [{'op': 'add', 'object': {
            'id': 'generated-target', 'type': 'image', 'x': 10, 'y': 10, 'w': 20, 'h': 20,
            'src': 'data:image/png;base64,' + base64.b64encode(PNG).decode()}}])
        self.jobs = ImageJobs(self.studio)

    def enqueue(self):
        return self.jobs.enqueue('request-1', self.slide, 'generated-target', 'A landscape')

    def test_persist_apply_and_idempotency(self):
        job = self.enqueue()
        self.assertEqual(self.enqueue()['id'], job['id'])
        with self.assertRaises(ValueError):
            self.jobs.enqueue('request-1', self.slide, 'generated-target', 'Different')
        provider = Provider()
        done = self.jobs.run(job['id'], provider)
        self.assertEqual(done['status'], 'complete')
        self.assertEqual(self.jobs.run(job['id'], provider)['status'], 'complete')
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.studio.asset(done['asset_id'])['mime'], 'image/png')
        result = self.jobs.apply(job['id'])
        target = next(o for o in result['scene']['objects'] if o['id'] == 'generated-target')
        self.assertTrue(target['src'].startswith('data:image/png;base64,'))
        self.assertEqual(self.jobs.get(job['id'])['status'], 'applied')

    def test_changed_scene_retains_asset_without_applying(self):
        job = self.enqueue()
        done = self.jobs.run(job['id'], Provider())
        current = self.studio.get_scene(self.slide)
        self.studio.change_scene(self.slide, current['sceneRevision'], [{'objectId': 'generated-target', 'properties': {'x': 30}}])
        with self.assertRaises(ValueError):
            self.jobs.apply(job['id'])
        self.assertEqual(self.jobs.get(job['id'])['status'], 'complete')
        self.assertEqual(self.studio.asset(done['asset_id'])['mime'], 'image/png')

    def test_chat_plan_enqueues_batch(self):
        scene = self.studio.get_scene(self.slide)
        job = self.studio.enqueue('生成一张图片', self.slide, None, 'chat-image')
        action = {'type': 'image_generate', 'slide_id': self.slide, 'base_scene_revision': scene['sceneRevision'], 'images': [{'object_id': 'new-image', 'prompt': 'landscape', 'x': 10, 'y': 10, 'w': 20, 'h': 20}]}
        self.studio.apply_plan(job['jobId'], {'reply': '正在生成图片', 'actions': [action]})
        self.assertEqual(self.studio.state()['imageBatches'][0]['id'], job['jobId'])
        self.jobs.run_batch(job['jobId'], Provider())
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'applied')

    def test_batch_applies_three_images_atomically(self):
        images = [{'object_id': 'new-' + str(i), 'prompt': 'image ' + str(i), 'x': i * 20, 'y': 10, 'w': 20, 'h': 20} for i in range(3)]
        self.jobs.enqueue_batch('batch', self.slide, images)
        provider = Provider()
        self.jobs.run_batch('batch', provider)
        self.jobs.run_batch('batch', provider)
        self.assertEqual(provider.calls, 3)
        scene = self.studio.get_scene(self.slide)
        self.assertTrue(all(any(o['id'] == image['object_id'] for o in scene['scene']['objects']) for image in images))
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'applied')

    def test_batch_replaces_existing_image_preserving_user_properties(self):
        before = self.studio.get_scene(self.slide)
        original = next(o for o in before['scene']['objects'] if o['id'] == 'generated-target')
        images = [{'object_id': 'generated-target', 'replace_object_id': 'generated-target',
                   'prompt': 'new style', 'x': 99, 'y': 99, 'w': 99, 'h': 99}]
        self.jobs.enqueue_batch('replace', self.slide, images)
        self.jobs.run_batch('replace', Provider())
        after = self.studio.get_scene(self.slide)
        updated = next(o for o in after['scene']['objects'] if o['id'] == 'generated-target')
        self.assertEqual({k: v for k, v in updated.items() if k != 'src'},
                         {k: v for k, v in original.items() if k != 'src'})
        self.assertEqual([o['id'] for o in before['scene']['objects']],
                         [o['id'] for o in after['scene']['objects']])
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'applied')

    def test_batch_rejects_duplicate_targets_and_bound_text(self):
        image = {'object_id': 'generated-target', 'replace_object_id': 'generated-target',
                 'prompt': 'new style', 'x': 1, 'y': 1, 'w': 20, 'h': 20}
        with self.assertRaises(EngineError):
            self.jobs.enqueue_batch('duplicate', self.slide, [image, dict(image)])
        scene = self.studio.get_scene(self.slide)
        bound = next(o for o in scene['scene']['objects'] if o.get('binding'))
        with self.assertRaises(EngineError):
            self.jobs.enqueue_batch('bound', self.slide, [{**image, 'object_id': 'new', 'replace_object_id': bound['id']}])

    def install_cover(self):
        current = self.studio.get_scene(self.slide)
        scene = copy.deepcopy(current['scene'])
        scene['objects'].insert(0, {'id': 'cover-bg', 'type': 'rect', 'x': 0, 'y': 0,
                                   'w': 1280, 'h': 720, 'fill': '#17324D', 'opacity': .9})
        return self.studio.put_scene(self.slide, current['contentRevision'], scene, preserve_layout=True)

    def test_replace_rectangle_background_keeps_layer_geometry_words_and_original_bytes(self):
        before = self.install_cover()
        request = {'object_id': 'cover-bg', 'replace_object_id': 'cover-bg',
                   'prompt': 'abstract background', 'x': 50, 'y': 50, 'w': 100, 'h': 100}
        self.jobs.enqueue_batch('cover-background', self.slide, [request])
        provider = Provider()
        self.jobs.run_batch('cover-background', provider)
        self.jobs.run_batch('cover-background', provider)
        after = self.studio.get_scene(self.slide)['scene']
        self.assertEqual(provider.calls, 1)
        self.assertEqual(after['objects'][1:], before['scene']['objects'][1:])
        image = after['objects'][0]
        self.assertEqual(image['type'], 'image')
        self.assertEqual({k: image[k] for k in ('id','x','y','w','h','opacity')},
                         {k: before['scene']['objects'][0][k] for k in ('id','x','y','w','h','opacity')})
        self.assertEqual(base64.b64decode(image['src'].split(',')[1]), PNG)
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'applied')
        restored = self.studio.undo(self.slide, self.studio.get_scene(self.slide)['sceneRevision'])
        self.assertEqual(restored['scene']['objects'], before['scene']['objects'])

    def test_new_background_sits_above_canvas_fill_and_below_content(self):
        before = self.install_cover()
        self.jobs.enqueue_batch('add-background', self.slide, [{'object_id': 'new-background',
            'placement': 'background', 'prompt': 'background without text', 'x': 0, 'y': 0, 'w': 1280, 'h': 720}])
        self.jobs.run_batch('add-background', Provider())
        objects = self.studio.get_scene(self.slide)['scene']['objects']
        self.assertEqual(objects[0], before['scene']['objects'][0])
        self.assertEqual(objects[1]['id'], 'new-background')
        self.assertEqual(objects[2:], before['scene']['objects'][1:])

    def test_target_error_is_specific_and_creates_no_image_jobs(self):
        with self.assertRaises(EngineError) as caught:
            self.jobs.enqueue_batch('bad-target', self.slide, [{'object_id':'new', 'replace_object_id':'missing',
                'prompt':'background', 'x':0, 'y':0, 'w':1280, 'h':720}])
        self.assertEqual(caught.exception.code, 'IMAGE_INVALID_TARGET')
        self.assertEqual(caught.exception.details['objectId'], 'missing')
        with self.studio.wb._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM image_generation_jobs').fetchone()[0], 0)

    def test_bad_geometry_is_rejected_before_generation(self):
        for bad in [dict(x=-1),dict(w=1500),dict(h=float('nan')),dict(placement='behind-everything')]:
            with self.assertRaises(EngineError):
                self.jobs.enqueue_batch('bad-geometry', self.slide, [{'object_id':'new', 'prompt':'background',
                    'x':0,'y':0,'w':1280,'h':720,**bad}])

    def test_batch_retains_images_on_revision_change(self):
        images = [{'object_id': 'new', 'prompt': 'image', 'x': 10, 'y': 10, 'w': 20, 'h': 20}]
        self.jobs.enqueue_batch('batch', self.slide, images)
        studio, slide = self.studio, self.slide
        class ChangingProvider(Provider):
            def generate(self, prompt):
                scene = studio.get_scene(slide)
                studio.change_scene(slide, scene['sceneRevision'], [{'objectId': 'generated-target', 'properties': {'x': 30}}])
                return super().generate(prompt)
        self.jobs.run_batch('batch', ChangingProvider())
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'conflict')
        self.assertFalse(any(o['id'] == 'new' for o in self.studio.get_scene(slide)['scene']['objects']))
        self.assertEqual(len(self.studio.state()['assets']), 1)

    def test_batch_stops_after_failure(self):
        images = [{'object_id': 'new-' + str(i), 'prompt': 'image', 'x': i * 20, 'y': 10, 'w': 20, 'h': 20} for i in range(3)]
        self.jobs.enqueue_batch('batch', self.slide, images)
        class FailSecond(Provider):
            def generate(self, prompt):
                if self.calls == 1:
                    self.calls += 1
                    raise RuntimeError('secret')
                return super().generate(prompt)
        provider = FailSecond()
        self.jobs.run_batch('batch', provider)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(self.studio.state()['imageBatches'][0]['status'], 'failed')
        self.assertEqual(self.studio.state()['imageBatches'][0]['generatedCount'], 1)
        self.assertEqual(self.studio.state()['imageBatches'][0]['totalCount'], 3)
        self.assertEqual(self.studio.state()['imageBatches'][0]['errorCode'], 'IMAGE_PROVIDER_FAILED')
        self.assertEqual(len(self.studio.state()['assets']), 1)

    def test_no_result_records_safe_reason_without_claiming_saved_images(self):
        from ppt_workbench.codex_image_provider import CodexImageError
        class NoResult:
            def generate(self, prompt):
                raise CodexImageError('private provider detail', 'IMAGE_NO_RESULT')
        before = self.studio.get_scene(self.slide)
        self.jobs.enqueue_batch('empty', self.slide, [{'object_id': 'new', 'prompt': 'image', 'x': 10, 'y': 10, 'w': 20, 'h': 20}])
        self.jobs.run_batch('empty', NoResult())
        state = self.studio.state()
        self.assertEqual(state['imageBatches'][0]['generatedCount'], 0)
        self.assertEqual(state['imageBatches'][0]['errorCode'], 'IMAGE_NO_RESULT')
        self.assertEqual(state['assets'], [])
        self.assertEqual(self.studio.get_scene(self.slide), before)
        self.assertNotIn('private provider detail', str(state))

    def test_bad_provider_output_fails_without_exposing_error(self):
        class Bad:
            def generate(self, prompt):
                raise RuntimeError('secret')
        result = self.jobs.run(self.enqueue()['id'], Bad())
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('secret', str(result))


if __name__ == '__main__':
    unittest.main()
