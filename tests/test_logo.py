"""Brand logo: placement logic, apply/remove, deck hook, Chrome processing."""
import base64
import json
import shutil
import struct
import tempfile
import unittest
import zlib
from unittest.mock import patch
from pathlib import Path

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench import logo as mod

LOGO = {"width": 120, "height": 60, "hasAlpha": True, "removedBackground": True,
        "tone": "dark", "meanColor": "#1F2329", "preview": "data:image/png;base64,AAA=",
        "variants": {"original": "x", "white": "x", "dark": "x"},
        "dataUrls": {k: "data:image/png;base64," + k.encode().hex().upper().encode().decode()
                     for k in ("original", "white", "dark")}}


def scene(objects, background="#FFFFFF"):
    return {"schema": "ppt-scene", "schemaVersion": 1, "slideId": "S001", "width": 1280,
            "height": 720, "background": background, "objects": objects}


def text(oid, x, y, w, h, t="文字"):
    return {"id": oid, "type": "text", "x": x, "y": y, "w": w, "h": h, "text": t}


class PlaceTests(unittest.TestCase):
    def logo(self, **kw):
        return {**LOGO, **kw}

    def placed(self, result):
        return next((o for o in result["scene"]["objects"] if o["id"] == "brand-logo"), None)

    def test_free_corner_top_right(self):
        result = mod.place_logo(scene([text("t", 600, 300, 200, 40)]),
                                self.logo(), {"position": "auto", "size": "medium", "pages": "all"}, "content")
        obj = self.placed(result)
        self.assertEqual((obj["x"], obj["y"]), (1280 - obj["w"] - 40, 40))
        self.assertEqual(obj["h"], 44)

    def test_blocked_corners_and_shrink(self):
        cover = [text(f"t{i}", x, y, w, h)
                 for i, (x, y, w, h) in enumerate([(1100, 0, 180, 80), (0, 0, 180, 80),
                                                   (1100, 640, 180, 80)])]
        result = mod.place_logo(scene(cover + [text("body", 0, 640, 180, 80)]),
                                self.logo(), {"position": "auto", "size": "medium", "pages": "all"}, "content")
        self.assertEqual(result.get("skipped"), "no-space")
        result = mod.place_logo(scene(cover), self.logo(),
                                {"position": "auto", "size": "medium", "pages": "all"}, "content")
        obj = self.placed(result)
        self.assertEqual(obj["x"], 40)
        self.assertEqual(obj["y"], 720 - obj["h"] - 40)

    def test_explicit_position(self):
        result = mod.place_logo(scene([]), self.logo(),
                                {"position": "bottom-left", "size": "small", "pages": "all"}, "content")
        obj = self.placed(result)
        self.assertEqual(obj["x"], 40)
        self.assertEqual(obj["h"], 32)

    def test_pages_scope_excludes_and_strips(self):
        existing = scene([dict(id="brand-logo", type="image", x=0, y=0, w=10, h=10,
                               src="data:image/png;base64,AAA=", fit="contain", alt="Logo"),
                          text("t", 500, 300, 100, 30)])
        result = mod.place_logo(existing, self.logo(),
                                {"position": "auto", "size": "medium", "pages": "cover"}, "content")
        self.assertEqual(result["skipped"], "excluded")
        self.assertIsNone(self.placed(result))

    def test_variant_matrix(self):
        dark = self.logo(tone="dark")
        result = mod.place_logo(scene([], "#1F2329"), dark,
                                {"position": "auto", "size": "medium", "pages": "all"}, "content")
        self.assertEqual(self.placed(result)["src"], dark["dataUrls"]["white"])
        light = self.logo(tone="light", meanColor="#F5F5F5")
        result = mod.place_logo(scene([], "#F8F8F8"), light,
                                {"position": "auto", "size": "medium", "pages": "all"}, "content")
        self.assertEqual(self.placed(result)["src"], light["dataUrls"]["dark"])
        opaque = self.logo(hasAlpha=False, removedBackground=False)
        result = mod.place_logo(scene([], "#111111"), opaque,
                                {"position": "auto", "size": "medium", "pages": "all"}, "content")
        self.assertEqual(self.placed(result)["src"], opaque["dataUrls"]["original"])

    def test_cover_scale(self):
        result = mod.place_logo(scene([]), self.logo(),
                                {"position": "auto", "size": "medium", "pages": "all"}, "cover")
        self.assertGreater(self.placed(result)["h"], 44)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.s = Studio(self.temp.name, "logo")
        self.s.demo()
        for slide in self.s.state()["slides"]:
            self.s.wb.add_slide(self.s.project_id, slide["title"], "目的", slide["role"]) if False else None

    def record(self, settings=None):
        body = {"width": 120, "height": 60, "hasAlpha": True, "removedBackground": True,
                "tone": "dark", "meanColor": "#1F2329", "preview": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n123").decode(),
                "variants": {"original": "logo-original.png"}}
        folder = self.s.wb.project_dir(self.s.project_id) / "brand"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "logo-original.png").write_bytes(b"\x89PNG\r\n\x1a\n123")
        mod.save_logo_record(self.s, body, settings or {"position": "auto", "size": "medium", "pages": "all"})

    def test_apply_and_remove_with_undo(self):
        self.record()
        result = mod.apply_logo(self.s)
        self.assertEqual(result["changedSlides"], ["S001", "S003"])
        self.assertEqual(result["skipped"], [{"slideId": "S002", "reason": "no-space"}])
        scene = self.s.get_scene("S001")["scene"]
        logo_obj = next(o for o in scene["objects"] if o["id"] == "brand-logo")
        self.assertEqual(logo_obj["fit"], "contain")
        self.assertEqual(scene["objects"][-1]["id"], "brand-logo")
        from ppt_workbench.editor import travel
        rev = self.s.get_scene("S001")["sceneRevision"]
        undone = travel(self.s, "S001", rev, "undo")
        self.assertFalse(any(o["id"] == "brand-logo" for o in undone["scene"]["objects"]))
        result = mod.remove_logo(self.s)
        self.assertIsNone(mod.project_logo(self.s))
        self.assertFalse(any(o["id"] == "brand-logo" for o in self.s.get_scene("S003")["scene"]["objects"]))

    def test_pages_setting_excludes_cover(self):
        self.record({"position": "auto", "size": "medium", "pages": "except-cover"})
        mod.apply_logo(self.s)
        self.assertFalse(any(o["id"] == "brand-logo" for o in self.s.get_scene("S001")["scene"]["objects"]))
        self.assertTrue(any(o["id"] == "brand-logo" for o in self.s.get_scene("S003")["scene"]["objects"]))

    def test_apply_missing_logo(self):
        with self.assertRaises(EngineError) as e:
            mod.apply_logo(self.s)
        self.assertEqual(e.exception.code, "LOGO_MISSING")

    def test_deck_hook_places_and_keeps_review_fresh(self):
        self.record()
        plan = {"title": "整稿", "execution": "agent",
                "design": {"background": "#FFFFFF", "ink": "#111111", "accent": "#FF0000",
                           "fontFamily": "Microsoft YaHei"},
                "pages": [{"title": f"第{i}页", "user_intent": "原话", "role": r,
                           "takeaway": "点", "key_points": "字"}
                          for i, r in enumerate(["cover", "ending"])]}
        with self.s.wb.atomic() as db:
            db.execute("INSERT INTO studio_decks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("dk1", self.s.project_id, "整稿", "running", "agent", "m", "m1",
                        json.dumps(plan, ensure_ascii=False), "fp", None, None,
                        "2026-01-01", "2026-01-01"))
            for i, sid in enumerate(("S001", "S003")):
                db.execute("INSERT INTO studio_deck_pages VALUES (?,?,?,?,?,?,?,?)",
                           ("dk1", i, json.dumps(plan["pages"][i]), "complete", sid, None, 0, None))
        with self.s.wb.atomic() as db:
            deck = self.s._deck_row(db)
            placed = mod.apply_to_deck(self.s, db, deck)
        self.assertEqual(set(placed), {"S001", "S003"})
        self.assertTrue(any(o["id"] == "brand-logo" for o in self.s.get_scene("S001")["scene"]["objects"]))


@unittest.skipUnless(__import__("shutil").which("google-chrome") or __import__("os").environ.get("WEPPT_CHROMIUM") or __import__("shutil").which("chromium"),
                     "needs headless Chrome")
class ChromeProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.s = Studio(self.temp.name, "logochrome")

    def png(self, w, h, fill, shape=None):
        raw = b""
        for y in range(h):
            raw += b"\x00"
            for x in range(w):
                if shape and shape[0] <= x < shape[2] and shape[1] <= y < shape[3]:
                    raw += bytes(shape[4:])
                else:
                    raw += bytes(fill)
        def chunk(tag, data):
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw))
                + chunk(b"IEND", b""))

    def test_white_background_removed(self):
        data = self.png(200, 100, (255, 255, 255, 255), (60, 25, 140, 75, 20, 20, 80, 255))
        result = mod.process_logo(self.s, "l.png", "image/png", base64.b64encode(data).decode())
        logo = result["logo"]
        self.assertTrue(logo["removedBackground"])
        self.assertEqual(logo["tone"], "dark")
        self.assertLess(logo["width"], 200)
        self.assertGreater(logo["width"], 80)

    def test_transparent_png_kept(self):
        data = self.png(200, 100, (255, 255, 255, 0), (60, 25, 140, 75, 200, 30, 30, 255))
        result = mod.process_logo(self.s, "l.png", "image/png", base64.b64encode(data).decode())
        self.assertTrue(result["logo"]["hasAlpha"])


if __name__ == "__main__":
    unittest.main()


class ExportTests(unittest.TestCase):
    def test_logo_picture_survives_pptx_export(self):
        import zipfile
        w, h = 4, 4
        raw = b""
        for y in range(h):
            raw += b"\x00" + bytes((30, 60, 180, 255)) * w
        def chunk(tag, data):
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        s = scene([{"id": "brand-logo", "type": "image", "x": 40, "y": 40, "w": 60, "h": 30,
                    "src": "data:image/png;base64," + base64.b64encode(png).decode(),
                    "fit": "contain", "alt": "Logo"}])
        from ppt_workbench.rendering import export_pptx
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "logo.pptx"
            export_pptx([s], target)
            with zipfile.ZipFile(target) as z:
                media = [n for n in z.namelist() if n.startswith("ppt/media/") and not n.endswith("/")]
                self.assertTrue(media, "exported pptx must embed the logo picture")
                self.assertIn(z.read(media[0])[:8], (b"\x89PNG\r\n\x1a\n", png[:8]))
