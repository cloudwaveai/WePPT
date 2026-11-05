import hashlib
import http.client
import json
import tempfile
import threading
import unittest

from ppt_workbench.server import create_http_server, REFERENCE_ASSETS


class ReferenceLibraryTests(unittest.TestCase):
    def test_retired_original_library_redirects_and_assets_are_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            server = create_http_server(root, "references", 0, "manual", "reference-test-token")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def get(path, authorized=True):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                connection.request("GET", path, headers={"Cookie": "ppt_studio=reference-test-token"} if authorized else {})
                response = connection.getresponse()
                result = response.status, dict(response.getheaders()), response.read()
                connection.close()
                return result
            try:
                before = server.studio.state()
                for path in ["/reference-library.html", "/reference-library.js", "/reference-library.css", *REFERENCE_ASSETS]:
                    self.assertEqual(get(path, False)[0], 401, path)
                for path in ['/reference-library.html', '/guide.html']:
                    status, headers, _ = get(path)
                    self.assertEqual(status, 303)
                    self.assertEqual(headers['Location'], '/curated-designs.html')
                for path in ['/reference-library.js', '/reference-library.css', *REFERENCE_ASSETS]:
                    status, _, raw = get(path)
                    self.assertEqual(status, 410)
                    self.assertEqual(json.loads(raw)['error']['code'], 'TEMPLATE_RETIRED')
                for path in ["/reference-library/previews/04-19.png", "/reference-library/previews/PDF-29.png",
                             "/reference-library/../app.js", "/reference-library/%2e%2e/server.py",
                             "/reference-library/previews/01-01.png/extra", "/reference-library/templates/01.potx"]:
                    self.assertEqual(get(path)[0], 404, path)
                after = server.studio.state()
                self.assertEqual(after["messages"], before["messages"])
                self.assertEqual(after["slides"], before["slides"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
