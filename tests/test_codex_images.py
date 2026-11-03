import hashlib
from pathlib import Path
import tempfile
import unittest

from ppt_workbench.codex_images import ImageSelectionError, stage_codex_images


class CodexImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "uploads").mkdir()
        self.stage = self.root / "stage"
        self.stage.mkdir()
        self.asset_id = "A-" + "a" * 32
        self.data = b"\x89PNG\r\n\x1a\nimage-data"
        self.path = self.root / "uploads" / (self.asset_id + ".png")
        self.path.write_bytes(self.data)
        self.record = {"id": self.asset_id, "mime": "image/png", "path": "uploads/" + self.path.name,
                       "bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest()}

    def select(self, ids=None, records=None):
        return stage_codex_images(self.root, self.stage, [self.asset_id] if ids is None else ids,
                                  [self.record] if records is None else records)

    def test_stages_only_selected_images_as_private_copies(self):
        paths = self.select()
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].read_bytes(), self.data)
        self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
        self.path.write_bytes(b"changed")
        self.assertEqual(paths[0].read_bytes(), self.data)
        self.assertEqual(self.select([], [self.record]), [])

    def test_rejects_untrusted_paths_digest_and_changed_content(self):
        for patch in ({"path": "../../secret.png"}, {"path": "/tmp/secret.png"},
                      {"sha256": "0" * 64}, {"bytes": 8 * 1024 * 1024 + 1}):
            with self.subTest(patch=patch), self.assertRaises(ImageSelectionError):
                self.select(records=[self.record | patch])
        self.path.write_bytes(b"x" * len(self.data))
        with self.assertRaises(ImageSelectionError):
            self.select()

    def test_rejects_symlink_and_missing_or_duplicate_selection(self):
        self.path.unlink()
        self.path.symlink_to(Path(self.temp.name) / "secret")
        with self.assertRaises(ImageSelectionError):
            self.select()
        with self.assertRaises(ImageSelectionError):
            self.select(records=[])
        with self.assertRaises(ImageSelectionError):
            self.select(ids=[self.asset_id, self.asset_id])

    def test_ignores_selected_non_image_and_rejects_unknown_type(self):
        self.assertEqual(self.select(records=[self.record | {"mime": "application/pdf"}]), [])
        with self.assertRaises(ImageSelectionError):
            self.select(records=[self.record | {"mime": "image/svg+xml"}])

    def test_total_limit_cleans_previously_staged_images(self):
        from unittest.mock import patch
        with patch("ppt_workbench.codex_images.MAX_TOTAL_BYTES", len(self.data) - 1):
            with self.assertRaises(ImageSelectionError):
                self.select()
        self.assertEqual(list(self.stage.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
