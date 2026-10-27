"""Run with: python3 -m unittest discover -s tests -v"""
from pathlib import Path
import concurrent.futures
import copy
import json
import tempfile
import unittest

from ppt_workbench.core import Workbench, EngineError


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ppt-core-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.w = Workbench(self.root)
        self.w.create_project("demo", {"title": "测试项目", "purpose": "report", "audience": "测试审阅者",
                                       "outcome": "确认本页计划", "delivery": "read", "dataPolicy": "none", "logoPolicy": "none"})
        self.w.add_slide("demo", "测试第一页", "用户明确给出的测试原话")

    def assert_code(self, code, fn, *args, **kwargs):
        with self.assertRaises(EngineError) as raised:
            fn(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def ready_content(self):
        return self.w.patch_slide("demo", "S001", 1, [
            {"path": "/takeaway", "value": "用户明确的测试计划"},
            {"path": "/templateId", "value": "custom"},
            {"path": "/evidenceRequired", "value": "no"}], "填写测试当前页")

    def artifact_files(self):
        p = self.w.project_dir("demo")
        (p / "page.html").write_text('<!doctype html><h1 id="title">测试页面</h1>')
        (p / "preview.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><text y="20">TEST</text></svg>')
        (p / "objects.json").write_text(json.dumps({"slideId": "S001", "objects": [{"id": "S001.title", "locator": "#title", "type": "text"}]}))
        return p

    def make_record_ready(self):
        self.ready_content()
        self.w.record_review("demo", "S001", 2, "content", "测试操作者认可这一页的计划表达")
        self.artifact_files()
        self.w.register_artifact("demo", "S001", 2, "page.html", "preview.svg", "objects.json")
        self.w.record_review("demo", "S001", 2, "visual", "测试操作者查看了指定测试文件")

    def test_single_slide_patch_and_original_intent(self):
        other = self.w.add_slide("demo", "测试第二页", "另一个原话")
        before = self.w.get_slide("demo", other["slideId"])
        changed = self.ready_content()
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["slide"]["userIntent"], "用户明确给出的测试原话")
        self.assertEqual(self.w.get_slide("demo", other["slideId"]), before)
        self.assert_code("PROTECTED_FIELD", self.w.patch_slide, "demo", "S001", 2,
                         [{"path": "/userIntent", "value": "重写用户原话"}])
        self.assert_code("PROTECTED_FIELD", self.w.patch_slide, "demo", "S001", 2,
                         [{"path": "/render/status", "value": "approved"}])

    def test_stale_revision_and_concurrent_writers(self):
        def work(text):
            try:
                return Workbench(self.root).patch_slide("demo", "S001", 1, [{"path": "/title", "value": text}])["revision"]
            except EngineError as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, ["改动 A", "改动 B"]))
        self.assertEqual(results.count(2), 1)
        self.assertEqual(results.count("STALE_REVISION"), 1)
        self.assertEqual(len(self.w.history("demo", "S001")["revisions"]), 2)

    def test_import_does_not_trust_confirmed_or_verified_flags(self):
        exported = self.w.export_workspace("demo")
        s = exported["slides"][0]
        s["contentStatus"] = "confirmed"
        s["render"] = {"status": "approved", "artifactPath": "/untrusted/file", "previewPath": "/untrusted/image"}
        s["evidence"] = [{"id": "E1", "claim": "测试主张", "source": "测试资料", "locator": "测试页", "scope": "测试口径", "status": "verified", "verifiedBy": "user"}]
        self.w.import_workspace("imported", exported)
        view = self.w.get_slide("imported", "S001")
        self.assertEqual(view["slide"]["contentStatus"], "draft")
        self.assertEqual(view["slide"]["evidence"][0]["status"], "unverified")
        self.assertIsNone(view["artifact"])
        self.assertFalse(self.w.gate("imported")["ready"])
        self.assert_code("PROJECT_EXISTS", self.w.import_workspace, "imported", exported)

    def test_content_confirmation_is_not_evidence_or_render(self):
        self.ready_content()
        self.w.record_review("demo", "S001", 2, "content", "操作者确认本页内容")
        view = self.w.get_slide("demo", "S001")
        self.assertEqual(view["slide"]["contentStatus"], "confirmed")
        self.assertEqual(view["slide"]["render"]["status"], "not-rendered")
        self.assert_code("RELEASE_GATE_FAILED", self.w.release_manifest, "demo")

    def test_fake_evidence_state_cannot_be_patched(self):
        item = {"id": "E1", "claim": "测试主张", "source": "测试来源", "locator": "测试定位", "scope": "测试口径", "status": "verified", "verifiedBy": "user"}
        self.assert_code("REVIEW_REQUIRED", self.w.patch_slide, "demo", "S001", 1,
                         [{"path": "/evidence", "value": [item]}])

    def test_file_registration_requires_real_files_inside_project(self):
        self.ready_content()
        self.assert_code("FILE_NOT_FOUND", self.w.register_artifact, "demo", "S001", 2, "missing.html", "missing.png")
        outside = self.root / "outside.html"
        outside.write_text("outside")
        self.assert_code("PATH_OUTSIDE_WORKSPACE", self.w.register_artifact, "demo", "S001", 2, str(outside), str(outside))
        linked = self.w.project_dir("demo") / "escape.html"
        linked.symlink_to(outside)
        self.assert_code("PATH_OUTSIDE_WORKSPACE", self.w.register_artifact, "demo", "S001", 2, "escape.html", "escape.html")

    def test_changed_artifact_invalidates_release(self):
        self.make_record_ready()
        self.assertTrue(self.w.gate("demo")["ready"])
        result = self.w.release_manifest("demo")
        self.assertTrue(Path(result["manifestPath"]).is_file())
        self.assertEqual(result["manifest"]["type"], "ppt-workbench-release-manifest")
        self.assertIn("不认证人类身份", "".join(result["manifest"]["limitations"]))
        (self.w.project_dir("demo") / "preview.svg").write_text("changed after review")
        gate = self.w.gate("demo")
        self.assertFalse(gate["ready"])
        self.assertIn("ARTIFACT_CHANGED", {i["code"] for i in gate["slides"][0]["issues"]})
        view = self.w.get_slide("demo", "S001")
        self.assertIsNone(view["reviews"]["visual"])
        self.assertEqual(view["slide"]["render"]["status"], "draft")
        self.assertIsNone(view["slide"]["render"]["renderedRevision"])
        self.assertEqual(self.w.export_workspace("demo")["slides"][0]["render"]["status"], "draft")
        self.assert_code("RELEASE_GATE_FAILED", self.w.release_manifest, "demo")

    def test_material_bytes_bound_to_registration_and_visual_review(self):
        self.ready_content()
        folder = self.artifact_files()
        (folder / "logo.svg").write_text("logo-original")
        (folder / "shot.png").write_text("screenshot-original")
        project = self.w.get_project("demo")
        self.w.update_project("demo", project["revision"], {"logoPolicy": "company", "logoReference": "logo.svg"})
        self.w.patch_slide("demo", "S001", 2, [{"path": "/assets", "value": [{"id": "A1", "kind": "screenshot", "owner": "user",
            "status": "provided", "required": True, "reference": "shot.png", "description": "测试截图"}]}])
        self.w.record_review("demo", "S001", 3, "content", "审阅测试页")
        for material in ("logo.svg", "shot.png"):
            with self.subTest(material=material):
                self.w.register_artifact("demo", "S001", 3, "page.html", "preview.svg", "objects.json")
                self.w.record_review("demo", "S001", 3, "visual", "审阅指定文件")
                self.assertTrue(self.w.gate("demo")["ready"])
                (folder / material).write_text("replaced-same-filename")
                view = self.w.get_slide("demo", "S001")
                self.assertIsNone(view["reviews"]["visual"])
                self.assertIn("MATERIAL_CHANGED", {i["code"] for i in view["integrityIssues"]})
                self.assertFalse(self.w.gate("demo")["ready"])

    def test_append_input_preserves_transcript_and_unblocks_empty_intent(self):
        slide = self.w.add_slide("demo", "待补页", "")
        sid = slide["slideId"]
        self.assertFalse(self.w.next_action("demo", sid)["draftAllowed"])
        updated = self.w.append_user_input("demo", sid, 1, "这是用户后补原话", "对话中的补充回答")
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["slide"]["userIntent"], "")
        self.assertEqual(updated["slide"]["userInputs"][0]["text"], "这是用户后补原话")
        self.assertEqual(updated["slide"]["userInputs"][0]["provenance"], "client-transcribed-unverified")
        self.assertTrue(self.w.next_action("demo", sid)["draftAllowed"])
        self.assert_code("STALE_REVISION", self.w.append_user_input, "demo", sid, 1, "陈旧更新")
        restored = self.w.restore_slide("demo", sid, 2, 1)
        self.assertEqual(restored["slide"]["userInputs"], updated["slide"]["userInputs"])
        self.assert_code("PROTECTED_FIELD", self.w.patch_slide, "demo", sid, 3,
                         [{"path": "/userInputs", "value": []}])

    def test_missing_required_material_precedes_render_action(self):
        self.ready_content()
        self.w.patch_slide("demo", "S001", 2, [{"path": "/assets", "value": [{"id": "A1", "kind": "photo", "owner": "user",
            "status": "missing", "required": True, "reference": "", "description": "需要真实照片"}]}])
        self.w.record_review("demo", "S001", 3, "content", "确认结构")
        action = self.w.next_action("demo", "S001")
        self.assertEqual(action["action"], "collect_required_materials")
        self.assertTrue(action["draftAllowed"])

    def test_malformed_enum_is_structured_error_and_evidence_defaults_exist(self):
        for path in ("/role", "/candidateState", "/evidenceRequired"):
            with self.subTest(path=path):
                self.assert_code("INVALID_INPUT", self.w.patch_slide, "demo", "S001", 1, [{"path": path, "value": []}])
        self.w.patch_slide("demo", "S001", 1, [{"path": "/evidence", "value": [{"id": "E1", "claim": "测试待补主张"}]}])
        self.assertEqual(self.w.get_slide("demo", "S001")["slide"]["evidence"][0]["status"], "missing")
        self.assertFalse(self.w.gate("demo")["ready"])

    def test_restore_creates_new_revision_without_reviving_reviews(self):
        self.make_record_ready()
        self.w.patch_slide("demo", "S001", 2, [{"path": "/title", "value": "第三版标题"}])
        restored = self.w.restore_slide("demo", "S001", 3, 2)
        self.assertEqual(restored["revision"], 4)
        self.assertEqual(restored["slide"]["title"], "测试第一页")
        self.assertIsNone(restored["reviews"]["content"])
        self.assertIsNone(restored["artifact"])
        self.assertEqual([r["revision"] for r in self.w.history("demo", "S001")["revisions"]], [1, 2, 3, 4])

    def test_global_brief_change_invalidates_bound_content_review(self):
        self.make_record_ready()
        project = self.w.get_project("demo")
        self.w.update_project("demo", project["revision"], {"audience": "新的听众"})
        self.assertIsNone(self.w.get_slide("demo", "S001")["reviews"]["content"])
        self.assertFalse(self.w.gate("demo")["ready"])

    def test_next_action_limits_questions_and_template_catalog(self):
        self.w.create_project("empty")
        self.w.add_slide("empty", "", "")
        action = self.w.next_action("empty", "S001")
        self.assertLessEqual(len(action["questions"]), 3)
        self.assertFalse(action["draftAllowed"])
        self.assertEqual(len(self.w.list_templates()["templates"]), 54)
        self.assertEqual(self.w.get_template("chapter")["template"]["id"], "chapter")

    def test_html_export_preserves_appended_intent_without_roundtrip_duplication(self):
        self.w.append_user_input("demo", "S001", 1, "后补原话：请突出关键差异", "会议录音 03:12")
        full = self.w.export_workspace("demo")
        exported = self.w.export_workspace("demo", for_html=True)
        merged = exported["slides"][0]["userIntent"]
        self.assertIn("用户明确给出的测试原话", merged)
        self.assertIn("后补原话：请突出关键差异", merged)
        self.assertIn("会议录音 03:12", merged)
        self.assertIn(full["slides"][0]["userInputs"][0]["id"], merged)
        self.assertNotIn("userInputs", exported["slides"][0])
        self.assertIn("结构化来源记录被简化为文字", exported["htmlExportNotice"])
        self.assertEqual(self.w.export_workspace("demo"), full)
        self.assertEqual(full["slides"][0]["userIntent"], "用户明确给出的测试原话")
        self.w.import_workspace("roundtrip", exported)
        again = self.w.export_workspace("roundtrip", for_html=True)
        self.assertEqual(again["slides"][0]["userIntent"], merged)
        self.assertEqual(again["slides"][0]["userIntent"].count("后补原话：请突出关键差异"), 1)
        # JavaScript's limit counts UTF-16 units, not Python Unicode code points.
        self.w.add_slide("demo", "超长原话", "😀" * 8001)
        self.assert_code("HTML_EXPORT_TOO_LARGE", self.w.export_workspace, "demo", for_html=True)
        self.assertEqual(self.w.export_workspace("demo")["slides"][1]["userIntent"], "😀" * 8001)


if __name__ == "__main__":
    unittest.main()
