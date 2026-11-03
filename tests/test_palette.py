"""Colour palette preferences, deterministic recolouring and HTTP endpoints."""
import http.client
import json
import tempfile
import threading
import unittest

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench.palette import (PALETTE_PRESETS, normalize_palette, recolor_scene,
                                   detect_scene_colors)
from ppt_workbench.server import create_http_server


PALETTE = {"primary": "#1F4E9E", "secondary": ["#2BB3C0", "#F2A541"]}


def scene_with(objects, background="#FFFFFF"):
    return {"schema": "ppt-scene", "schemaVersion": 1, "slideId": "S001",
            "width": 1280, "height": 720, "background": background, "objects": objects}


def text_obj(oid, color, **extra):
    return {"id": oid, "type": "text", "x": 60, "y": 60, "w": 400, "h": 80,
            "text": "测试文字", "fontSize": 24, "color": color, "opacity": 1, **extra}


def rect_obj(oid, fill, **extra):
    return {"id": oid, "type": "rect", "x": 0, "y": 0, "w": 1280, "h": 720,
            "fill": fill, "opacity": 1, **extra}


class ValidationTests(unittest.TestCase):
    def test_normalize_uppercases_and_checks_shape(self):
        self.assertEqual(normalize_palette({"primary": "#1f4e9e", "secondary": ["#2bb3c0"]}),
                         {"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        for bad in [{"primary": "blue", "secondary": ["#2BB3C0"]},
                    {"primary": "#1F4E9E", "secondary": []},
                    {"primary": "#1F4E9E", "secondary": ["#1", "#2", "#3"]},
                    {"primary": "#1F4E9E", "secondary": "#2BB3C0"},
                    {"primary": "#1F4E9E", "secondary": ["#1F4E9E"]},
                    {"primary": "#1F4E9E", "secondary": ["#2BB3C0", "#2BB3C0"]},
                    "not-a-dict"]:
            with self.assertRaises(EngineError) as raised:
                normalize_palette(bad)
            self.assertEqual(raised.exception.code, "INVALID_PALETTE")

    def test_presets_match_spec(self):
        self.assertEqual(len(PALETTE_PRESETS), 8)
        self.assertEqual(PALETTE_PRESETS[0], {"name": "商务蓝", "primary": "#1F4E9E",
                                              "secondary": ["#2BB3C0", "#F2A541"]})
        self.assertEqual(PALETTE_PRESETS[-1]["primary"], "#B08D57")


class RecolorTests(unittest.TestCase):
    def test_exact_case_insensitive_replacement(self):
        scene = scene_with([rect_obj("bg", "#ff0000"),
                            text_obj("t", "#00FF00", stroke="#123456", emphasisColor="#ABCDEF")],
                           background="#Ff0000")
        out = recolor_scene(scene, {"#FF0000": "#1F4E9E", "#00ff00": "#22C1C3",
                                    "#123456": "#F2A541", "#abcdef": "#FFD43B"})
        self.assertEqual(out["background"], "#1F4E9E")
        rect, text = out["objects"]
        self.assertEqual(rect["fill"], "#1F4E9E")
        self.assertEqual((text["color"], text["stroke"], text["emphasisColor"]),
                         ("#22C1C3", "#F2A541", "#FFD43B"))

    def test_contrast_guard_keeps_original_text_colour(self):
        scene = scene_with([rect_obj("panel", "#FF0000"),
                            text_obj("t", "#FF0000", emphasisColor="#FF0000")])
        out = recolor_scene(scene, {"#FF0000": "#1F4E9E"})
        rect, text = out["objects"]
        self.assertEqual(rect["fill"], "#1F4E9E")
        self.assertEqual(text["color"], "#FF0000")
        self.assertEqual(text["emphasisColor"], "#FF0000")

    def test_detect_ranks_saturated_colours_by_area(self):
        scene = scene_with([rect_obj("big", "#3366CC"),
                            text_obj("small", "#E8590C"),
                            rect_obj("plain", "#EEEEEE", x=10, y=10, w=50, h=50)],
                           background="#FF0000")
        self.assertEqual(detect_scene_colors(scene), ["#3366CC", "#E8590C"])


class StudioPaletteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ppt-palette-")
        self.addCleanup(self.temp.cleanup)
        self.studio = Studio(self.temp.name, "pal")

    def error(self, code, func, *args, **kwargs):
        with self.assertRaises(EngineError) as raised:
            func(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def slide(self, index=0):
        return self.studio.state()["slides"][index]

    def test_set_get_clear_palette_and_state(self):
        self.assertIsNone(self.studio.palette())
        state = self.studio.set_palette({"primary": "#1f4e9e", "secondary": ["#2bb3c0"]})
        self.assertEqual(state["palette"], {"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        self.assertEqual(state["palettePresets"], PALETTE_PRESETS)
        self.assertEqual(self.studio.state()["palette"]["primary"], "#1F4E9E")
        context = self.studio.context({"scope": "deck"})
        self.assertEqual(context["userPalette"]["primary"], "#1F4E9E")
        self.assertIn("用户指定的主色和辅色", context["userPalette"]["instruction"])
        self.error("INVALID_PALETTE", self.studio.set_palette, {"primary": "#1", "secondary": ["#2BB3C0"]})
        self.assertIsNone(self.studio.set_palette(None)["palette"])
        self.assertIsNone(self.studio.context({"scope": "deck"})["userPalette"])

    def test_create_deck_design_override(self):
        self.studio.set_palette(PALETTE)
        plan = {"title": "配色整稿", "execution": "agent",
                "design": {"background": "#FFFFFF", "ink": "#111111", "accent": "#FF0000",
                           "fontFamily": "Microsoft YaHei", "secondary": "#00FF00"},
                "pages": [{"title": f"第 {i} 页", "user_intent": "用户原话", "role": role,
                           "takeaway": "要点", "key_points": "用户提供的测试文字"}
                          for i, role in enumerate(["cover", "content", "ending"])]}
        self.studio.create_deck(plan, "用户要求生成整稿", "agent")
        with self.studio.wb._connection() as db:
            design = json.loads(self.studio._deck_row(db)["plan"])["design"]
        self.assertEqual((design["accent"], design["secondary"], design["tertiary"]),
                         ("#1F4E9E", "#2BB3C0", "#F2A541"))

    def test_create_deck_without_palette_keeps_design(self):
        plan = {"title": "普通整稿", "execution": "agent",
                "design": {"background": "#FFFFFF", "ink": "#111111", "accent": "#FF0000",
                           "fontFamily": "Microsoft YaHei"},
                "pages": [{"title": "封面", "user_intent": "用户原话", "role": "cover",
                           "takeaway": "要点", "key_points": "用户提供的测试文字"},
                          {"title": "结束", "user_intent": "用户原话", "role": "ending",
                           "takeaway": "要点", "key_points": "用户提供的测试文字"}]}
        self.studio.create_deck(plan, "用户要求生成整稿", "agent")
        with self.studio.wb._connection() as db:
            design = json.loads(self.studio._deck_row(db)["plan"])["design"]
        self.assertEqual(design["accent"], "#FF0000")
        self.assertNotIn("tertiary", design)

    def test_apply_requires_palette(self):
        self.studio.demo()
        self.error("PALETTE_MISSING", self.studio.apply_palette, "deck")

    def test_apply_page_detects_colours_and_undoes(self):
        self.studio.demo()
        self.studio.set_palette(PALETTE)
        sid = self.slide(0)["id"]
        current = self.studio.get_scene(sid)
        scene = current["scene"]
        for obj in scene["objects"]:
            if obj["type"] == "rect" and obj.get("fill") not in (None, "none"):
                obj["fill"] = "#3366CC"
                break
        else:
            scene["objects"].insert(0, rect_obj("wash", "#3366CC"))
        saved = self.studio.put_scene(sid, current["contentRevision"], scene, "测试配色")
        result = self.studio.apply_palette("page", sid, saved["sceneRevision"])
        self.assertEqual(result["changedSlides"], [sid])
        self.assertEqual(result["skipped"], [])
        recolored = self.studio.get_scene(sid)["scene"]
        self.assertIn("#1F4E9E", json.dumps(recolored))
        self.assertNotIn("#3366CC", json.dumps(recolored))
        from ppt_workbench.editor import history_status
        self.assertTrue(history_status(self.studio, sid)["canUndo"])

    def test_apply_deck_design_mapping_and_skips(self):
        plan = {"title": "带设计整稿", "execution": "agent",
                "design": {"background": "#FFFFFF", "ink": "#111111", "accent": "#AA0000",
                           "secondary": "#00AA00", "fontFamily": "Microsoft YaHei"},
                "pages": [{"title": "封面", "user_intent": "用户原话", "role": "cover",
                           "takeaway": "要点", "key_points": "用户提供的测试文字"},
                          {"title": "结束", "user_intent": "用户原话", "role": "ending",
                           "takeaway": "要点", "key_points": "用户提供的测试文字"}]}
        self.studio.create_deck(plan, "用户要求生成整稿", "agent")
        self.studio.demo()
        self.studio.set_palette(PALETTE)
        first, second = self.slide(0), self.slide(1)
        for slide, colour in [(first, "#AA0000"), (second, "#00AA00")]:
            current = self.studio.get_scene(slide["id"])
            scene = current["scene"]
            scene["objects"].insert(0, rect_obj("band-" + slide["id"], colour))
            self.studio.put_scene(slide["id"], current["contentRevision"], scene, "测试配色")
        stale = self.studio.wb.get_slide(self.studio.project_id, second["id"])
        self.studio.wb.patch_slide(self.studio.project_id, second["id"], stale["revision"],
                                   [{"path": "/title", "value": "改过的标题"}])
        self.studio.wb.add_slide(self.studio.project_id, "无预览页", "用户原话", "content")
        result = self.studio.apply_palette("deck")
        self.assertEqual(result["changedSlides"], [first["id"]])
        reasons = {skip["slideId"]: skip["reason"] for skip in result["skipped"]}
        self.assertEqual(reasons[second["id"]], "stale")
        self.assertIn("missing", reasons.values())
        recolored = json.dumps(self.studio.get_scene(first["id"])["scene"])
        self.assertIn("#1F4E9E", recolored)
        self.assertNotIn("#AA0000", recolored)
        again = self.studio.apply_palette("page", first["id"])
        self.assertEqual(again["changedSlides"], [])
        self.assertEqual(again["skipped"], [{"slideId": first["id"], "reason": "unchanged"}])


    def test_second_palette_remaps_via_last_applied(self):
        self.studio.demo()
        sid = self.slide(0)["id"]
        current = self.studio.get_scene(sid)
        scene = current["scene"]
        scene["objects"].insert(0, rect_obj("band-" + sid, "#AA0000"))
        self.studio.put_scene(sid, current["contentRevision"], scene, "测试配色")
        self.studio.set_palette({"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        self.studio.apply_palette("page", sid)
        self.assertIn("#1F4E9E", json.dumps(self.studio.get_scene(sid)["scene"]))
        self.studio.set_palette({"primary": "#E8590C", "secondary": ["#1C7ED6"]})
        result = self.studio.apply_palette("page", sid)
        self.assertEqual(result["changedSlides"], [sid])
        recolored = json.dumps(self.studio.get_scene(sid)["scene"])
        self.assertIn("#E8590C", recolored)
        self.assertNotIn("#1F4E9E", recolored)


class PaletteHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = create_http_server(self.temp.name, "web", 0, "manual", "test-browser-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, method, path, body=None, *, authorized=True, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"X-Studio-Token": "test-browser-token"} if authorized else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        result = conn.getresponse()
        data = result.read()
        answer = (result.status, dict(result.getheaders()), data)
        conn.close()
        return answer

    def test_palette_endpoints(self):
        body = {"primary": "#1f4e9e", "secondary": ["#2bb3c0", "#f2a541"]}
        self.assertEqual(self.request("POST", "/api/palette", body, authorized=False)[0], 403)
        status, _, raw = self.request("POST", "/api/palette", body)
        self.assertEqual(status, 200, raw)
        state = json.loads(raw)
        self.assertEqual(state["palette"]["primary"], "#1F4E9E")
        self.assertEqual(state["palettePresets"][0]["name"], "商务蓝")
        self.assertEqual(self.request("POST", "/api/palette", {"primary": "#1", "secondary": []})[0], 400)
        self.server.studio.demo()
        status, _, raw = self.request("POST", "/api/palette/apply", {"scope": "deck"})
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        self.assertIn("changedSlides", result)
        self.assertIn("state", result)
        status, _, raw = self.request("POST", "/api/palette", {"clear": True})
        self.assertEqual(status, 200, raw)
        self.assertIsNone(json.loads(raw)["palette"])
        self.assertEqual(self.request("POST", "/api/palette/apply", {"scope": "deck"})[0], 400)


if __name__ == "__main__":
    unittest.main()
