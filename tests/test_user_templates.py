"""User page templates: upload validation, endpoints, adaptation hooks."""
import base64
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench import user_templates as ut
from ppt_workbench import template_adaptation as adaptation

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"fakepngdata").decode()
JPG = base64.b64encode(b"\xff\xd8\xff" + b"fakejpeg").decode()


def file(name="页.png", mime="image/png", data=PNG):
    return {"filename": name, "mime": mime, "base64": data}


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.s = Studio(self.temp.name, "p1")

    def error(self, code, func, *a, **kw):
        with self.assertRaises(EngineError) as e:
            func(*a, **kw)
        self.assertEqual(e.exception.code, code)

    def test_pptx_pages_become_editable_layout_templates(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        self.s.demo()
        try:
            exported = Path(self.s.export("pptx")["path"])
        except EngineError as exc:
            if exc.code == "PPTX_DEPENDENCY_MISSING":
                self.skipTest("pptxgenjs not installed")
            raise
        pptx = {"filename": "我的模板.pptx", "mime": ut.PPTX_MIME, "base64": base64.b64encode(exported.read_bytes()).decode()}
        self.error("INVALID_UPLOAD", ut.upload, self.s, "page", [pptx, file()])
        self.error("INVALID_UPLOAD", ut.upload, self.s, "page", [dict(pptx, base64=PNG)])
        png = Path(self.temp.name) / "r.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n")
        with patch("ppt_workbench.design_review.render_candidate", return_value=(png, {"overflow": []})):
            result = ut.upload(self.s, "page", [pptx])
        self.assertEqual(result["slideCount"], 3)
        self.assertEqual([t["name"] for t in result["templates"]], [f"我的模板 · 第{n}页" for n in (1, 2, 3)])
        tid = result["templates"][0]["id"]
        layout = ut.template_layout(self.s, tid)
        self.assertIn("让想法成为看得见的页面", [o.get("text") for o in layout["objects"]])
        # Non-vision models adapt from the editable layout; the template's own text is example-only.
        before = self.s.get_scene("S002")
        self.s.set_agent_mode("api")
        moved = json.loads(json.dumps(before["scene"]))
        moved["objects"] = [dict(o, x=20 + (i * 137) % 600, y=20 + (i * 89) % 400, w=max(40, o["w"] // 2), h=max(20, o["h"] // 2))
                            for i, o in enumerate(moved["objects"])]
        calls = []
        def run(*a, **kw):
            calls.append((a, kw))
            if a[2].get("generationTask", {}).get("kind") == "design_loop_review":
                return {"reply": "PASS\nok", "actions": []}
            return {"reply": "done", "actions": [{"type": "scene_replace", "slide_id": "S002",
                    "base_revision": before["contentRevision"], "scene": moved}]}
        binding = {"id": "x", "label": "L", "mode": "api", "model": "m"}
        with patch("ppt_workbench.model_profiles.selected", return_value=binding), \
             patch("ppt_workbench.model_profiles.resolve", return_value={**binding, "vision": False}), \
             patch("ppt_workbench.agent_bridge.run_turn", side_effect=run), \
             patch("ppt_workbench.design_review.render_candidate", return_value=(png, {"fontsReady": True, "overflow": []})):
            proposal = adaptation.propose(self.s, "user-" + tid, "S002", before["sceneRevision"])
        context = calls[0][0][2]
        self.assertTrue(context["referenceLayout"]["exampleOnly"])
        self.assertEqual(context["referenceReadMode"], "layout-only")
        self.assertNotIn("preview_png", calls[0][1])
        self.assertEqual(proposal["scene"]["templateId"], "custom")

    def test_templates_are_private_to_their_personal_space(self):
        from ppt_workbench import owners
        legacy = None
        with patch("ppt_workbench.design_review.render_candidate", side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
            legacy = ut.upload(self.s, "page", [file("旧.png")])["templates"][0]["id"]
            marker = owners.set_current("a" * 43)
            try:
                mine = ut.upload(self.s, "page", [file("甲.png")])["templates"][0]["id"]
            finally:
                owners.reset(marker)
        def visible(token):
            marker = owners.set_current(token)
            try:
                return {t["id"] for t in ut.list_templates(self.s)}
            finally:
                owners.reset(marker)
        self.assertEqual(visible("a" * 43), {legacy, mine})
        self.assertEqual(visible("b" * 43), {legacy})
        marker = owners.set_current("b" * 43)
        try:
            self.error("TEMPLATE_NOT_FOUND", ut.rename, self.s, mine, "改名")
        finally:
            owners.reset(marker)

    def test_upload_validation(self):
        self.error("INVALID_UPLOAD", ut.upload, self.s, "page", [])
        self.error("INVALID_UPLOAD", ut.upload, self.s, "page", [file()] * 6)
        self.error("UNSUPPORTED_UPLOAD", ut.upload, self.s, "page", [file(mime="text/plain")])
        self.error("INVALID_UPLOAD", ut.upload, self.s, "page",
                   [file(data=base64.b64encode(b"GIF89a").decode())])
        self.error("UPLOAD_TOO_LARGE", ut.upload, self.s, "page",
                   [file(data="A" * 12_000_001)])

    def test_upload_png_fallback_when_no_renderer(self):
        with patch("ppt_workbench.design_review.render_candidate",
                   side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
            result = ut.upload(self.s, "page", [file(), file("b.png")])
        self.assertEqual(len(result["templates"]), 2)
        self.assertEqual(result["templates"][0]["name"], "页")
        path, sha = ut.image(self.s, result["templates"][0]["id"])
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
        self.assertIn("sha=" + sha, result["templates"][0]["previewUrl"])

    def test_jpeg_rejected_without_renderer(self):
        with patch("ppt_workbench.design_review.render_candidate",
                   side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
            self.error("RENDER_UNAVAILABLE", ut.upload, self.s, "page", [file("a.jpg", "image/jpeg", JPG)])

    def test_rename_and_delete(self):
        with patch("ppt_workbench.design_review.render_candidate",
                   side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
            tid = ut.upload(self.s, "page", [file()])["templates"][0]["id"]
        self.assertEqual(ut.rename(self.s, tid, "新名字")["templates"][0]["name"], "新名字")
        self.error("INVALID_REQUEST", ut.rename, self.s, tid, "")
        ut.delete(self.s, tid)
        self.assertEqual(ut.list_templates(self.s), [])

    def test_propose_user_template_needs_vision_and_apply_skips_preference(self):
        with patch("ppt_workbench.design_review.render_candidate",
                   side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
            tid = ut.upload(self.s, "page", [file()])["templates"][0]["id"]
        self.s.demo()
        before = self.s.get_scene("S001")
        self.s.set_agent_mode("manual")
        self.error("AGENT_REQUIRED", adaptation.propose, self.s, "user-" + tid, "S001", before["sceneRevision"])
        self.s.set_agent_mode("api")
        with patch("ppt_workbench.model_profiles.selected", return_value={"id": "x", "label": "L", "mode": "api", "model": "m"}), \
             patch("ppt_workbench.model_profiles.resolve", return_value={"id": "x", "mode": "api", "model": "m", "vision": False}):
            self.error("TEMPLATE_NEEDS_VISION", adaptation.propose, self.s, "user-" + tid, "S001", before["sceneRevision"])
        candidate = dict(before["scene"])
        candidate["objects"] = [dict(o, x=20 + (i * 137) % 600, y=20 + (i * 89) % 400,
                                     w=max(40, o["w"] // 2), h=max(20, o["h"] // 2))
                                for i, o in enumerate(candidate["objects"])]
        calls = []
        def run(*a, **kw):
            calls.append((a, kw))
            if a[2].get("generationTask", {}).get("kind") == "design_loop_review":
                return {"reply": "PASS\nok", "actions": []}
            return {"reply": "done", "actions": [{"type": "scene_replace", "slide_id": "S001",
                    "base_revision": before["contentRevision"], "scene": candidate}]}
        png = Path(self.temp.name) / "r.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n")
        with patch("ppt_workbench.model_profiles.selected", return_value={"id": "x", "label": "L", "mode": "api", "model": "m"}), \
             patch("ppt_workbench.model_profiles.resolve", return_value={"id": "x", "mode": "api", "model": "m", "vision": True}), \
             patch("ppt_workbench.agent_bridge.run_turn", side_effect=run), \
             patch("ppt_workbench.design_review.render_candidate", return_value=(png, {"fontsReady": True, "overflow": []})):
            proposal = adaptation.propose(self.s, "user-" + tid, "S001", before["sceneRevision"])
        self.assertEqual(proposal["scene"]["templateId"], "custom")
        self.assertEqual(calls[0][0][2]["referenceLayout"], None)
        self.assertEqual(calls[0][0][2]["referenceReadMode"], "image-only")
        self.assertTrue(calls[0][1]["preview_png"].name == "reference.png")
        self.assertEqual(calls[0][1]["preview_png"].read_bytes(), (ut._directory(self.s, tid) / "page.png").read_bytes())
        adaptation.apply(self.s, proposal["proposalId"])
        self.assertIsNone(self.s.selected_template())

    def test_layout_unchanged_retries_then_fails(self):
        self.s.demo()
        before = self.s.get_scene("S001")
        self.s.set_agent_mode("codex")
        same = before["scene"]
        moved = dict(before["scene"])
        moved["objects"] = [dict(o, x=20 + (i * 137) % 600, y=20 + (i * 89) % 400,
                                   w=max(40, o["w"] // 2), h=max(20, o["h"] // 2))
                            for i, o in enumerate(moved["objects"])]
        answers = iter([same, same, moved])
        def run(*a, **kw):
            if a[2].get("generationTask", {}).get("kind") == "design_loop_review":
                return {"reply": "PASS\nok", "actions": []}
            return {"reply": "done", "actions": [{"type": "scene_replace", "slide_id": "S001",
                    "base_revision": before["contentRevision"], "scene": next(answers)}]}
        png = Path(self.temp.name) / "r.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n")
        with patch("ppt_workbench.agent_bridge.run_turn", side_effect=run), \
             patch("ppt_workbench.design_review.render_candidate", return_value=(png, {"fontsReady": True, "overflow": []})):
            proposal = adaptation.propose(self.s, "claim-proof", "S001", before["sceneRevision"])
        self.assertEqual(proposal["scene"]["objects"], moved["objects"])
        def run2(*a, **kw):
            if a[2].get("generationTask", {}).get("kind") == "design_loop_review":
                return {"reply": "PASS\nok", "actions": []}
            return {"reply": "done", "actions": [{"type": "scene_replace", "slide_id": "S001",
                    "base_revision": before["contentRevision"], "scene": same}]}
        with patch("ppt_workbench.agent_bridge.run_turn", side_effect=run2), \
             patch("ppt_workbench.design_review.render_candidate", return_value=(png, {"fontsReady": True, "overflow": []})):
            with self.assertRaises(EngineError) as e:
                adaptation.propose(self.s, "claim-proof", "S001", before["sceneRevision"])
        self.assertEqual(e.exception.code, "TEMPLATE_LAYOUT_UNCHANGED")
        self.assertIn("构图", e.exception.message)


if __name__ == "__main__":
    unittest.main()
