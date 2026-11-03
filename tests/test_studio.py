"""Integration tests against real SQLite state and rendered local artifacts.

No model is mocked as if it had generated a deck. Studio.demo uses its explicitly
labelled deterministic sample data; CLI availability is mocked only when testing
the missing-client path.
"""
from pathlib import Path
import base64
import copy
import hashlib
import json
import random
import struct
import tempfile
import unittest
import zlib
from unittest.mock import patch

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII="


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ppt-studio-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.studio = Studio(self.root, "demo")
        self.initial = self.studio.demo()
        self.ids = [slide["id"] for slide in self.initial["slides"]]

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(EngineError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def snapshot_pages(self):
        snapshot = {}
        for sid in self.ids:
            current = self.studio.get_scene(sid)
            snapshot[sid] = {"scene": current, "page": self.studio.wb.get_slide("demo", sid),
                             "sourceBytes": Path(current["paths"]["source"]).read_bytes(),
                             "previewBytes": Path(current["paths"]["preview"]).read_bytes()}
        return snapshot

    def database_snapshot(self):
        with self.studio.wb._connection() as db:
            names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {name: [tuple(row) for row in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid')]
                    for name in names}

    def plan_patch(self, sid, scene_revision, object_id="title", **properties):
        return {"reply": "已按当前要求调整这一页。", "actions": [{"type": "scene_patch", "slide_id": sid,
            "base_scene_revision": scene_revision,
            "changes": [{"objectId": object_id, "properties": properties}]}]}

    def test_pending_codex_passes_project_scoped_selected_records(self):
        self.studio.set_agent_mode("codex")
        selected = self.studio.upload("selected.png", "image/png", PNG)
        self.studio.upload("other.png", "image/png", PNG)
        job = self.studio.enqueue("参考图片", self.ids[0], attachments=[selected["assetId"]])
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), \
             patch("ppt_workbench.agent_bridge.run_turn", return_value={"reply": "收到", "actions": []}) as run:
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(self.studio.job(job["jobId"])["status"], "complete")
        self.assertEqual(run.call_args.kwargs["selected_ids"], [selected["assetId"]])
        self.assertEqual([r["id"] for r in run.call_args.kwargs["asset_records"]], [selected["assetId"]])
        self.assertEqual(run.call_args.args[2]["attachments"][0]["readStatus"], "not-inspected")
        self.assertEqual(run.call_args.args[2]["pageExpression"]["assets"]["imageCount"], 1)

    def test_scene_objects_apply_reorder_and_enforce_scope_and_revision(self):
        sid = self.ids[0]
        current = self.studio.get_scene(sid)
        objects = current["scene"]["objects"]
        obj = copy.deepcopy(objects[0])
        obj["id"] = "extra-object"
        obj.pop("binding", None)
        action = {"type": "scene_objects", "slide_id": sid, "base_scene_revision": current["sceneRevision"],
                  "operations": [{"op": "add", "object": obj}]}
        selected = self.studio.enqueue("add", sid, "title", "object-scope")
        self.assert_code("SCOPE_VIOLATION", self.studio.apply_plan, selected["jobId"], {"reply": "x", "actions": [action]})
        stale = self.studio.enqueue("add", sid, None, "stale-object")
        self.assert_code("STALE_REVISION", self.studio.apply_plan, stale["jobId"],
                         {"reply": "x", "actions": [action | {"base_scene_revision": current["sceneRevision"] + 1}]})
        job = self.studio.enqueue("add", sid, None, "add-object")
        self.studio.apply_plan(job["jobId"], {"reply": "x", "actions": [action]})
        added = self.studio.get_scene(sid)
        self.assertEqual(added["scene"]["objects"][-1]["id"], "extra-object")
        job = self.studio.enqueue("reorder", sid, None, "reorder-object")
        self.studio.apply_plan(job["jobId"], {"reply": "x", "actions": [action | {
            "base_scene_revision": added["sceneRevision"],
            "operations": [{"op": "reorder", "objectId": "extra-object", "index": 0}]}]})
        reordered = self.studio.get_scene(sid)
        self.assertEqual(reordered["scene"]["objects"][0]["id"], "extra-object")
        self.assertGreater(reordered["sceneRevision"], added["sceneRevision"])
        job = self.studio.enqueue("delete", sid, None, "delete-object")
        self.studio.apply_plan(job["jobId"], {"reply": "x", "actions": [action | {
            "base_scene_revision": reordered["sceneRevision"],
            "operations": [{"op": "delete", "objectId": "extra-object"}]}]})
        self.assertNotIn("extra-object", [o["id"] for o in self.studio.get_scene(sid)["scene"]["objects"]])

    def test_demo_has_three_real_source_preview_and_object_manifests(self):
        self.assertEqual(len(self.ids), 3)
        self.assertTrue(self.initial["demo"])
        for sid in self.ids:
            view = self.studio.get_scene(sid)
            self.assertFalse(view["stale"])
            self.assertGreater(len(view["scene"]["objects"]), 1)
            for path in view["paths"].values():
                self.assertTrue(Path(path).is_file())
                self.assertTrue(Path(path).resolve().is_relative_to(self.root))
            self.assertEqual(json.loads(Path(view["paths"]["source"]).read_text()), view["scene"])
            self.assertIn('data-object-id="title"', Path(view["paths"]["preview"]).read_text())
            manifest = json.loads(Path(view["paths"]["objects"]).read_text())
            self.assertEqual(manifest["slideId"], sid)
            self.assertEqual({obj["id"] for obj in manifest["objects"]}, {obj["id"] for obj in view["scene"]["objects"]})
        self.assert_code("PROJECT_NOT_EMPTY", self.studio.demo)

    def test_selected_object_patch_preserves_other_objects_and_other_pages_bytes(self):
        before = self.snapshot_pages()
        sid = self.ids[1]
        current = before[sid]["scene"]
        title = next(obj for obj in current["scene"]["objects"] if obj["id"] == "title")
        job = self.studio.enqueue("请只把选中的对象字号增加三级", sid, "title", "precise-edit")
        result = self.studio.apply_plan(job["jobId"], self.plan_patch(sid, current["sceneRevision"], fontSize=title["fontSize"] + 3))
        self.assertEqual({item["objectId"] for item in result["changes"]}, {"title"})
        after = self.snapshot_pages()
        self.assertEqual(self.studio.job(job["jobId"])["status"], "complete")
        for other in self.ids:
            if other != sid:
                self.assertEqual(after[other], before[other])
        old_objects = {obj["id"]: obj for obj in current["scene"]["objects"]}
        new_objects = {obj["id"]: obj for obj in after[sid]["scene"]["scene"]["objects"]}
        self.assertEqual(old_objects.keys(), new_objects.keys())
        for oid in old_objects:
            if oid != "title":
                self.assertEqual(old_objects[oid], new_objects[oid])
        self.assertEqual(new_objects["title"], old_objects["title"] | {"fontSize": title["fontSize"] + 3})
        self.assertEqual(after[sid]["page"]["slide"]["userIntent"], before[sid]["page"]["slide"]["userIntent"])

    def test_stale_job_and_scene_revision_are_rejected_without_mutation(self):
        sid = self.ids[0]
        old = self.studio.get_scene(sid)
        job = self.studio.enqueue("等待代理处理的旧请求", sid, "title", "stale-request")
        title = next(obj for obj in old["scene"]["objects"] if obj["id"] == "title")
        self.studio.change_scene(sid, old["sceneRevision"], [{"objectId": "title", "properties": {"fontSize": title["fontSize"] + 2}}])
        after = self.database_snapshot()
        self.assert_code("STALE_REVISION", self.studio.apply_plan, job["jobId"], self.plan_patch(sid, old["sceneRevision"], text="过时修改"))
        self.assertEqual(after, self.database_snapshot())
        self.assert_code("STALE_REVISION", self.studio.change_scene, sid, old["sceneRevision"], [{"objectId": "title", "properties": {"text": "旧版本修改"}}])
        self.assertEqual(after, self.database_snapshot())

    def test_content_change_blocks_editing_stale_preview(self):
        sid = self.ids[0]
        old = self.studio.get_scene(sid)
        self.studio.wb.patch_slide("demo", sid, old["contentRevision"], [{"path": "/takeaway", "value": "用户提供的新主张"}])
        self.assertTrue(self.studio.get_scene(sid)["stale"])
        self.assert_code("SCENE_STALE", self.studio.change_scene, sid, old["sceneRevision"], [{"objectId": "title", "properties": {"text": "不能改旧图"}}])

    def test_body_object_binding_updates_content_and_survives_regeneration(self):
        sid = self.ids[2]
        original = self.studio.wb.get_slide("demo", sid)["slide"]
        current = self.studio.get_scene(sid)
        body = next(obj for obj in current["scene"]["objects"] if obj.get("binding") == "keyPoints:1")
        replacement = "用户补充：先核对真实材料，再确认本页表达"
        expected_points = original["keyPoints"].splitlines()
        expected_points[1] = replacement
        job = self.studio.enqueue("请把选中的正文改为：" + replacement, sid, body["id"])
        self.studio.apply_plan(job["jobId"], self.plan_patch(sid, current["sceneRevision"], body["id"], text=replacement))
        updated = self.studio.wb.get_slide("demo", sid)
        self.assertEqual(updated["slide"]["keyPoints"], "\n".join(expected_points))
        self.assertEqual(updated["slide"]["userIntent"], original["userIntent"])
        regenerated = self.studio.generate_scene(sid, updated["revision"])
        actual = next(obj for obj in regenerated["scene"]["objects"] if obj.get("binding") == "keyPoints:1")
        self.assertEqual(actual["text"], replacement)
        self.assertEqual(self.studio.wb.get_slide("demo", sid)["slide"]["keyPoints"], "\n".join(expected_points))
        self.assertIn(replacement, Path(regenerated["paths"]["preview"]).read_text())

    def test_large_image_context_uses_opaque_reference_and_patch_preserves_bytes(self):
        def chunk(kind, value):
            return struct.pack("!I", len(value)) + kind + value + struct.pack("!I", zlib.crc32(kind + value))
        width = height = 768
        pixels = random.Random(17).randbytes(width * height * 4)
        scanlines = b"".join(b"\x00" + pixels[start:start + width * 4] for start in range(0, len(pixels), width * 4))
        raw = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))
        self.assertGreater(len(raw), 2 * 1024 * 1024)
        encoded = base64.b64encode(raw).decode()
        uploaded = self.studio.upload("large-reference.png", "image/png", encoded)
        sid = self.ids[0]
        current = self.studio.get_scene(sid)
        scene = copy.deepcopy(current["scene"])
        scene["objects"].append({"id": "large-reference", "type": "image", "x": 1100, "y": 20,
            "w": 60, "h": 60, "src": "asset:" + uploaded["assetId"], "fit": "contain", "alt": "用户提供的大图"})
        current = self.studio.put_scene(sid, current["contentRevision"], scene)
        context = self.studio.context({"slideId": sid, "attachments": [uploaded["assetId"]]})
        image = next(obj for obj in context["scene"]["scene"]["objects"] if obj["id"] == "large-reference")
        self.assertEqual(image["src"], "scene-image:" + sid + "/large-reference")
        self.assertEqual(context["attachments"][0]["readStatus"], "not-inspected")
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("data:image", serialized)
        self.assertNotIn(encoded[:100], serialized)
        self.assertLess(len(serialized.encode()), 100_000)
        patched = self.studio.change_scene(sid, current["sceneRevision"], [{"objectId": image["id"],
            "properties": {"src": image["src"], "x": 1090}}], allowed_object_id=image["id"])
        result = next(obj for obj in patched["scene"]["objects"] if obj["id"] == image["id"])
        self.assertEqual(result["x"], 1090)
        self.assertEqual(base64.b64decode(result["src"].split(",", 1)[1]), raw)

    def test_client_message_id_and_completed_plan_are_idempotent(self):
        sid = self.ids[0]
        current = self.studio.get_scene(sid)
        one = self.studio.enqueue("将选中标题改成新的标题", sid, "title", "same-client-message")
        two = self.studio.enqueue("将选中标题改成新的标题", sid, "title", "same-client-message")
        self.assertEqual(one["jobId"], two["jobId"])
        self.assertTrue(two["deduplicated"])
        plan = self.plan_patch(sid, current["sceneRevision"], text="这是新的标题")
        first_result = self.studio.apply_plan(one["jobId"], plan)
        after = self.database_snapshot()
        second_result = self.studio.apply_plan(one["jobId"], plan)
        self.assertTrue(second_result["deduplicated"])
        self.assertEqual(second_result["sceneRevision"], first_result["sceneRevision"])
        self.assertEqual(after, self.database_snapshot())
        matches = [m for m in self.studio.state()["messages"] if m["role"] == "user" and m.get("jobId") == one["jobId"]]
        self.assertEqual(len(matches), 1)

    def test_selected_object_cannot_edit_another_object_or_replace_page(self):
        sid = self.ids[1]
        current = self.studio.get_scene(sid)
        job = self.studio.enqueue("只改标题", sid, "title", "scope-guard")
        other = next(obj for obj in current["scene"]["objects"] if obj["id"] != "title")
        before = self.database_snapshot()
        self.assert_code("SCOPE_VIOLATION", self.studio.apply_plan, job["jobId"], self.plan_patch(sid, current["sceneRevision"], other["id"], x=other["x"] + 1))
        replace = {"reply": "替换整页", "actions": [{"type": "scene_replace", "slide_id": sid,
            "base_revision": current["contentRevision"], "scene": current["scene"]}]}
        self.assert_code("SCOPE_VIOLATION", self.studio.apply_plan, job["jobId"], replace)
        self.assertEqual(before, self.database_snapshot())

    def test_later_action_failure_rolls_back_all_database_writes(self):
        sid = self.ids[0]
        current = self.studio.get_scene(sid)
        title = next(obj for obj in current["scene"]["objects"] if obj["id"] == "title")
        job = self.studio.enqueue("尝试两阶段局部修改", sid, "title", "atomic-plan")
        before = self.database_snapshot()
        original_pages = self.snapshot_pages()
        first = self.plan_patch(sid, current["sceneRevision"], fontSize=title["fontSize"] + 2)["actions"][0]
        second = self.plan_patch(sid, current["sceneRevision"], fontSize="huge")["actions"][0]
        self.assert_code("INVALID_SCENE", self.studio.apply_plan, job["jobId"], {"reply": "两项修改", "actions": [first, second]})
        self.assertEqual(before, self.database_snapshot())
        self.assertEqual(original_pages, self.snapshot_pages())
        self.assertEqual(self.studio.job(job["jobId"])["status"], "queued")

    def test_export_html_contains_three_pages_and_retains_original_sources(self):
        before = self.snapshot_pages()
        exported = self.studio.export("html")
        path = Path(exported["path"])
        self.assertTrue(path.is_file())
        self.assertTrue(path.resolve().is_relative_to(self.root))
        self.assertEqual(exported["slideCount"], 3)
        self.assertTrue(exported["draft"])
        html = path.read_text(encoding="utf-8")
        self.assertEqual(html.count('<section class="page'), 3)
        for page in before.values():
            self.assertIn(page["page"]["slide"]["title"], html)
        self.assertNotIn('src="https:', html)
        self.assertEqual(before, self.snapshot_pages())

    def test_text_upload_is_bound_to_chat_and_not_marked_verified(self):
        content = "# 用户的实际材料\n第一张只介绍目前存在的问题，不填虚构的收益数字。"
        uploaded = self.studio.upload("brief.md", "", base64.b64encode(content.encode()).decode())
        self.assertEqual(uploaded["mime"], "text/markdown")
        self.assertEqual(uploaded["readStatus"], "text-available")
        record = self.studio.asset(uploaded["assetId"])
        path = self.studio.wb.project_dir("demo") / record["path"]
        self.assertEqual(path.read_text(), content)
        self.assertEqual(record["sha256"], hashlib.sha256(content.encode()).hexdigest())
        job = self.studio.enqueue("请参考我的附件", self.ids[0], attachments=[uploaded["assetId"]])
        context = self.studio.context(self.studio.job(job["jobId"])["payload"])
        self.assertEqual(context["attachments"][0]["text"], content)
        self.assertNotIn("verified", context["attachments"][0])

    def test_image_upload_resolves_exact_bytes_into_editable_scene(self):
        raw = base64.b64decode(PNG)
        uploaded = self.studio.upload("reference.png", "image/png", PNG)
        record = self.studio.asset(uploaded["assetId"])
        self.assertEqual((self.studio.wb.project_dir("demo") / record["path"]).read_bytes(), raw)
        current = self.studio.get_scene(self.ids[0])
        scene = copy.deepcopy(current["scene"])
        scene["objects"].append({"id": "user-photo", "type": "image", "x": 1100, "y": 20,
            "w": 60, "h": 60, "src": "asset:" + uploaded["assetId"], "alt": "用户提供的图片", "fit": "contain"})
        changed = self.studio.put_scene(self.ids[0], current["contentRevision"], scene)
        actual = next(obj for obj in changed["scene"]["objects"] if obj["id"] == "user-photo")
        self.assertEqual(base64.b64decode(actual["src"].split(",", 1)[1]), raw)
        self.assertEqual(json.loads(Path(changed["paths"]["source"]).read_text())["objects"][-1], actual)
        self.assert_code("INVALID_UPLOAD", self.studio.upload, "fake.png", "image/png", base64.b64encode(b"not an image").decode())

    def test_uploaded_image_can_replace_selected_image_without_other_object_changes(self):
        uploaded = self.studio.upload("original.png", "image/png", PNG)
        sid = self.ids[0]
        current = self.studio.get_scene(sid)
        scene = copy.deepcopy(current["scene"])
        scene["objects"].append({"id": "selected-image", "type": "image", "x": 1100, "y": 20,
            "w": 60, "h": 60, "src": "asset:" + uploaded["assetId"], "fit": "contain"})
        current = self.studio.put_scene(sid, current["contentRevision"], scene)
        # A genuine one-pixel RGBA PNG with a different pixel value and valid CRCs.
        def chunk(kind, value):
            return struct.pack("!I", len(value)) + kind + value + struct.pack("!I", zlib.crc32(kind + value))
        replacement_bytes = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 6, 0, 0, 0))
                             + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")) + chunk(b"IEND", b""))
        second = self.studio.upload("replacement.png", "image/png", base64.b64encode(replacement_bytes).decode())
        before = self.snapshot_pages()
        job = self.studio.enqueue("只替换选中的图片，保持它的位置和尺寸", sid, "selected-image", attachments=[second["assetId"]])
        self.studio.apply_plan(job["jobId"], self.plan_patch(sid, current["sceneRevision"], "selected-image", src="asset:" + second["assetId"]))
        after = self.snapshot_pages()
        for other in self.ids:
            if other != sid:
                self.assertEqual(before[other], after[other])
        original_objects = {obj["id"]: obj for obj in current["scene"]["objects"]}
        new_objects = {obj["id"]: obj for obj in after[sid]["scene"]["scene"]["objects"]}
        for oid in original_objects:
            if oid != "selected-image":
                self.assertEqual(original_objects[oid], new_objects[oid])
        self.assertEqual(base64.b64decode(new_objects["selected-image"]["src"].split(",", 1)[1]), replacement_bytes)
        self.assertEqual({k: v for k, v in original_objects["selected-image"].items() if k != "src"},
                         {k: v for k, v in new_objects["selected-image"].items() if k != "src"})

    def test_project_binding_change_marks_page_list_and_scene_stale_consistently(self):
        project = self.studio.wb.get_project("demo")
        self.studio.wb.update_project("demo", project["revision"], {"title": "用户更正了项目主题"})
        state = self.studio.state()
        for page in state["slides"]:
            self.assertTrue(page["stale"])
            self.assertTrue(self.studio.get_scene(page["id"])["stale"])
            self.assertIsNone(self.studio.wb.get_slide("demo", page["id"])["artifact"])
        self.assert_code("SCENE_STALE", self.studio.export, "html")

    def test_missing_agent_keeps_new_job_queued_and_does_not_fake_a_reply(self):
        studio = Studio(self.root, "missing-cli", agent="codex")
        with patch("ppt_workbench.agent_bridge.shutil.which", return_value=None), patch("ppt_workbench.agent_bridge.subprocess.Popen") as launch:
            before = studio.state()
            queued = studio.enqueue("请按我的大纲生成第一页：为什么需要改变", client_message_id="without-cli")
            self.assertFalse(studio.run_pending())
            after = studio.state()
            pending = studio.next_job()
        self.assertFalse(after["agent"]["available"])
        self.assertEqual(queued["status"], "queued")
        self.assertTrue(pending["pending"])
        self.assertEqual(pending["job"]["id"], queued["jobId"])
        self.assertEqual(after["slides"], [])
        self.assertEqual([m for m in after["messages"] if m["role"] == "assistant"],
                         [m for m in before["messages"] if m["role"] == "assistant"])
        launch.assert_not_called()

    def test_new_page_intent_comes_from_user_message_not_model_claim(self):
        message = "请新增一页，解释我的方案还缺少什么证据。"
        job = self.studio.enqueue(message, self.ids[0])
        result = self.studio.apply_plan(job["jobId"], {"reply": "已建立这一页的草稿。", "actions": [{
            "type": "slide_add", "title": "证据待补齐", "role": "content", "user_intent": "模型试图编造的用户原话",
            "takeaway": "把未证实的主张留待验证", "key_points": "[待提供] 原始资料"}]})
        new_page = self.studio.wb.get_slide("demo", result["slideId"])
        self.assertEqual(new_page["slide"]["userIntent"], message)
        self.assertFalse(self.studio.get_scene(result["slideId"])["stale"])


if __name__ == "__main__":
    unittest.main()
