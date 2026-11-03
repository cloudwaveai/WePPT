import json
import os
import sys
from pathlib import Path
import tempfile
import unittest

from ppt_workbench.codex_image_provider import CodexImageError, CodexImageProvider, _read_image


class CodexImageProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.generated = self.home / 'generated_images'
        self.generated.mkdir(parents=True)
        self.image = self.generated / 'image.png'
        self.image.write_bytes(b'\x89PNG\r\n\x1a\nimage')
        self.command = self.root / 'codex'

    def script(self, body):
        self.command.write_text('#!' + sys.executable + '\n' + body)
        self.command.chmod(0o700)

    def provider(self, timeout=2):
        return CodexImageProvider(codex_home=self.home, executable=self.command, timeout=timeout)

    def test_session_returns_image(self):
        self.script('import sys\nsys.stdin.read()\nprint(' + repr(json.dumps({'path': str(self.image)})) + ')\n')
        result = self.provider().generate('a landscape')
        self.assertEqual(result.data, self.image.read_bytes())
        self.assertEqual(result.mime, 'image/png')

    def test_native_session_artifact_survives_incorrect_final_no_result(self):
        thread='01a18b42-87fa-7991-86e1-1c37f11bf6e5'
        target=self.generated/thread/'exec-test.png'
        self.script('import sys,json\nfrom pathlib import Path\nsys.stdin.read()\n'
                    'assert "--json" in sys.argv\n'
                    f'p=Path({str(target)!r});p.parent.mkdir();p.write_bytes({self.image.read_bytes()!r})\n'
                    f'print(json.dumps({{"type":"thread.started","thread_id":{thread!r}}}))\n'
                    'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"{\\"error\\":\\"IMAGE_NO_RESULT\\"}"}}))\n')
        result=self.provider().generate('one background')
        self.assertEqual(result.data,self.image.read_bytes())

    def test_other_session_file_cannot_mask_no_result(self):
        thread='01a18b42-87fa-7991-86e1-1c37f11bf6e5'
        self.script('import json\n'
                    f'print(json.dumps({{"type":"thread.started","thread_id":{thread!r}}}))\n'
                    'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"{\\"error\\":\\"IMAGE_NO_RESULT\\"}"}}))\n')
        with self.assertRaises(CodexImageError) as caught:self.provider().generate('one image')
        self.assertEqual(caught.exception.code,'IMAGE_NO_RESULT')

    def session_with_two_images(self, thread, report=None):
        folder=self.generated/thread
        message=('print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":json.dumps({"path":'
                 + repr(str(folder/report)) + '})}}))\n') if report else ''
        self.script('import json,os\nfrom pathlib import Path\n'
                    f'p=Path({str(folder)!r});p.mkdir(exist_ok=True)\n'
                    '(p/"one.png").write_bytes(b"\\x89PNG\\r\\n\\x1a\\none");(p/"two.png").write_bytes(b"\\x89PNG\\r\\n\\x1a\\ntwo")\n'
                    'os.utime(p/"one.png",(1,1));os.utime(p/"two.png",(2,2))\n'
                    f'print(json.dumps({{"type":"thread.started","thread_id":{thread!r}}}))\n' + message)
        return folder

    def test_several_images_from_the_new_session_use_reported_or_latest(self):
        self.session_with_two_images('01a18b42-87fa-7991-86e1-1c37f11bf6e5', report='one.png')
        self.assertTrue(self.provider().generate('one image').data.endswith(b'one'))
        self.session_with_two_images('01a18b42-87fa-7991-86e1-1c37f11bf6e6')
        self.assertTrue(self.provider().generate('one image').data.endswith(b'two'))

    def test_session_artifacts_must_be_new(self):
        folder=self.session_with_two_images('01a18b42-87fa-7991-86e1-1c37f11bf6e5')
        self.provider().generate('one image')
        (folder/'two.png').unlink()
        with self.assertRaises(CodexImageError):self.provider().generate('one image')

    def test_rejects_paths_and_symlinks(self):
        outside = self.root / 'secret'
        outside.write_bytes(self.image.read_bytes())
        link = self.generated / 'link'
        link.symlink_to(outside)
        for path in (outside, link, self.generated / '..' / 'secret'):
            with self.subTest(path=path), self.assertRaises(CodexImageError):
                _read_image(self.generated, str(path))

    def test_rejects_bad_content_and_size(self):
        self.image.write_bytes(b'not an image')
        with self.assertRaises(CodexImageError):
            _read_image(self.generated, str(self.image))
        with self.image.open('wb') as f:
            f.truncate(8 * 1024 * 1024 + 1)
        with self.assertRaises(CodexImageError):
            _read_image(self.generated, str(self.image))

    def test_failures_are_bounded_and_redacted(self):
        for body, expected in (
            ("import time\ntime.sleep(5)\n", 'timed out'),
            ("import sys\nsys.exit(1)\n", 'session failed'),
            ("print('not json')\n", 'invalid response'),
            ("print('x' * 100000)\n", 'exceeded the limit'),
        ):
            self.script(body)
            with self.subTest(expected=expected), self.assertRaisesRegex(CodexImageError, expected):
                self.provider(timeout=0.2).generate('test')

    def test_missing_executable(self):
        with self.assertRaisesRegex(CodexImageError, 'start'):
            self.provider().generate('test')

    def test_no_image_and_unavailable_tool_have_safe_failure_codes(self):
        for response, expected in (({'path': ''}, 'IMAGE_NO_RESULT'),
                                   ({'error': 'IMAGE_TOOL_UNAVAILABLE'}, 'IMAGE_TOOL_UNAVAILABLE'),
                                   ({'error': 'IMAGE_NO_RESULT'}, 'IMAGE_NO_RESULT')):
            self.script('import sys\nsys.stdin.read()\nprint(' + repr(json.dumps(response)) + ')\n')
            with self.subTest(response=response), self.assertRaises(CodexImageError) as caught:
                self.provider().generate('test')
            self.assertEqual(caught.exception.code, expected)


if __name__ == '__main__':
    unittest.main()
