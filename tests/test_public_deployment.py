"""Public HTTPS origin, private bootstrap cookie and persistent-token boundaries."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ppt_workbench.core import EngineError
from ppt_workbench.server import create_http_server


class PublicDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token = 'test-public-access-' + 'a' * 40
        self.token_file = Path(self.tmp.name) / 'access-token'
        self.token_file.write_text(self.token)
        self.token_file.chmod(0o600)
        self.config = {'WEPPT_PUBLIC_ORIGIN': 'https://ppt.bbstack.date',
                       'WEPPT_TOKEN_FILE': str(self.token_file), 'WEPPT_BIND_HOST': '127.0.0.1'}

    def start(self):
        with patch.dict(os.environ, self.config):
            server = create_http_server(Path(self.tmp.name) / 'data', 'dev', 0, 'outline')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join(3)
        self.addCleanup(stop)
        return server

    def request(self, server, method, path, body=None, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        values = {'Host': 'ppt.bbstack.date', **headers}
        if body is not None:
            values['Content-Type'] = 'application/json'
        connection.request(method, path, json.dumps(body) if body is not None else None, values)
        result = connection.getresponse(); data = result.read()
        answer = result.status, dict(result.getheaders()), data
        connection.close(); return answer

    def test_bootstrap_cookie_is_secure_and_anonymous_api_is_rejected(self):
        server = self.start()
        self.assertEqual(server.token, self.token)
        self.assertEqual(self.request(server, 'GET', '/api/state')[0], 401)
        code, headers, _ = self.request(server, 'GET', '/?token=' + self.token)
        self.assertEqual(code, 303)
        for flag in ('Secure', 'HttpOnly', 'SameSite=Strict'):
            self.assertIn(flag, headers['Set-Cookie'])
        self.assertEqual(headers['Location'], '/')
        self.assertEqual(self.request(server, 'GET', '/api/state', Cookie='ppt_studio=' + self.token)[0], 200)

    def test_post_accepts_only_configured_origins_and_hosts(self):
        server = self.start()
        auth = {'X-Studio-Token': self.token}
        self.assertEqual(self.request(server, 'POST', '/api/demo', {}, Origin='https://ppt.bbstack.date', **auth)[0], 200)
        self.assertEqual(self.request(server, 'POST', '/api/demo', {}, Origin='https://evil.example', **auth)[0], 403)
        self.assertEqual(self.request(server, 'POST', '/api/demo', {}, Origin='http://ppt.bbstack.date', **auth)[0], 403)
        self.assertEqual(self.request(server, 'GET', '/api/state', Host='evil.example', **auth)[0], 403)
        self.assertEqual(self.request(server, 'POST', '/api/demo', {}, Origin='https://ppt.bbstack.date')[0], 403)

    def test_invalid_origin_and_missing_persistent_auth_fail_closed(self):
        for value in ('http://ppt.bbstack.date', 'https://ppt.bbstack.date/path', 'https://user@ppt.bbstack.date'):
            with self.subTest(origin=value), patch.dict(os.environ, {**self.config, 'WEPPT_PUBLIC_ORIGIN': value}), self.assertRaises(EngineError):
                create_http_server(Path(self.tmp.name) / 'invalid', 'dev', 0)
        with patch.dict(os.environ, {**self.config, 'WEPPT_TOKEN_FILE': ''}), self.assertRaises(EngineError):
            create_http_server(Path(self.tmp.name) / 'invalid', 'dev', 0)

    def test_token_permissions_and_symlinks_are_rejected(self):
        self.token_file.chmod(0o644)
        with patch.dict(os.environ, self.config), self.assertRaises(EngineError):
            create_http_server(Path(self.tmp.name) / 'bad', 'dev', 0)
        self.token_file.chmod(0o600)
        link = Path(self.tmp.name) / 'link'; link.symlink_to(self.token_file)
        with patch.dict(os.environ, {**self.config, 'WEPPT_TOKEN_FILE': str(link)}), self.assertRaises(EngineError):
            create_http_server(Path(self.tmp.name) / 'bad', 'dev', 0)

    def test_container_bind_requires_explicit_public_configuration(self):
        with patch.dict(os.environ, {'WEPPT_BIND_HOST': '0.0.0.0', 'WEPPT_PUBLIC_ORIGIN': ''}), self.assertRaises(EngineError):
            create_http_server(Path(self.tmp.name) / 'bad', 'dev', 0)

    def test_explicit_open_access_needs_no_cookie_and_keeps_origin_checks(self):
        self.config.update(WEPPT_PUBLIC_ACCESS='open', WEPPT_TOKEN_FILE='')
        server = self.start()
        self.assertEqual(self.request(server, 'GET', '/')[0], 200)
        self.assertEqual(self.request(server, 'GET', '/api/state')[0], 200)
        self.assertEqual(self.request(server, 'POST', '/api/demo', {}, Origin='https://ppt.bbstack.date')[0], 200)
        self.assertEqual(self.request(server, 'POST', '/api/demo', {}, Origin='https://evil.example')[0], 403)
        self.assertEqual(self.request(server, 'GET', '/api/state', Host='evil.example')[0], 403)

    def test_open_access_requires_explicit_origin(self):
        with patch.dict(os.environ, {**self.config, 'WEPPT_PUBLIC_ACCESS': 'open', 'WEPPT_PUBLIC_ORIGIN': ''}), self.assertRaises(EngineError):
            create_http_server(Path(self.tmp.name) / 'bad', 'dev', 0)
