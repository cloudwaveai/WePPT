"""Mechanical quality contracts against real SQLite/Scene files.

Reports in this module are explicit synthetic fixtures. They test server
validation and repair behavior, not actual browser layout or visual acceptance.
"""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from ppt_workbench.core import EngineError
from ppt_workbench.quality import audit_scene, propose_safe_repairs, validate_browser_report
from ppt_workbench.rendering import validate_scene, render_html
from ppt_workbench.studio import Studio


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII="


def basic_scene(sid="S001", body_height=180, body_text="这是专门用于程序测试的真实输入。"):
    return validate_scene({"schema": "ppt-scene", "schemaVersion": 1, "slideId": sid,
        "width": 1280, "height": 720, "background": "#FFFFFF", "templateId": "claim-proof", "objects": [
        {"id": "title", "type": "text", "text": "质量检查专用测试页", "binding": "title", "x": 64, "y": 64, "w": 1000, "h": 80,
         "fontSize": 40, "lineHeight": 1.2, "color": "#12243C"},
        {"id": "body-1", "type": "text", "text": body_text, "binding": "keyPoints:0", "x": 64, "y": 200, "w": 900, "h": body_height,
         "fontSize": 28, "lineHeight": 1.4, "color": "#12243C"},
        {"id": "image", "type": "image", "x": 1070, "y": 220, "w": 120, "h": 120, "src": "data:image/png;base64," + PNG},
    ]})


def fixture_report(scene, *, overflow=None, extra_height=30, fonts_ready=True, images_loaded=True):
    rows = []
    for obj in scene["objects"]:
        border = 2 * obj.get("strokeWidth", 0) if obj["type"] == "rect" else 0
        w, h = max(0, obj["w"] - border), max(0, obj["h"] - border)
        row = {"objectId": obj["id"], "type": obj["type"], "clientWidth": w, "clientHeight": h,
               "scrollWidth": w, "scrollHeight": h + (extra_height if obj["id"] == overflow else 0)}
        if obj["type"] == "image":
            row["imageLoaded"] = images_loaded
        rows.append(row)
    return {"schema": "ppt-browser-measurement", "schemaVersion": 1, "slideId": scene["slideId"], "width": scene["width"], "height": scene["height"],
            "fontsReady": fonts_ready, "imagesLoaded": images_loaded, "objects": rows,
            "overflowIds": [overflow] if overflow else []}


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ppt-quality-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(self.root, "quality")

    def add(self, scene=None):
        page = self.studio.wb.add_slide("quality", "质量检查专用测试页", "用户专门提供的测试内容。")
        source = scene or basic_scene()
        source = copy.deepcopy(source)
        source["slideId"] = page["slideId"]
        return self.studio.put_scene(page["slideId"], page["revision"], source, "生成测试页面")

    def assert_code(self, expected, function, *args, **kwargs):
        with self.assertRaises(EngineError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)

    def start_deck_scope_round(self):
        current = self.add()
        request = self.studio.enqueue("请按我给定的测试布局调整本稿。", scope="deck")
        scene = copy.deepcopy(current["scene"])
        scene["objects"][1]["h"] = 80
        self.studio.apply_plan(request["jobId"], {"reply": "已采用提供的测试布局。", "actions": [
            {"type": "scene_replace", "slide_id": current["slideId"], "base_revision": current["contentRevision"], "scene": scene}]})
        self.assertTrue(self.studio.quality_state()["repairPolicy"]["autoFix"])
        return request, self.studio.get_scene(current["slideId"])

    def finish_precise_title(self, request, current):
        self.studio.apply_plan(request["jobId"], {"reply": "只调整了标题。", "actions": [
            {"type": "scene_patch", "slide_id": current["slideId"], "base_scene_revision": current["sceneRevision"],
             "changes": [{"objectId": "title", "properties": {"fontSize": 44}}]}]})
        return self.studio.get_scene(current["slideId"])

    def test_estimate_never_counts_as_browser_measurement(self):
        self.add()
        quality = self.studio.run_quality(auto_fix=False)
        self.assertEqual(quality["status"], "awaiting_browser")
        self.assertFalse(quality["readyToReview"])
        self.assertFalse(quality["humanAccepted"])
        self.assertEqual(quality["browser"]["measured"], 0)
        self.assertEqual(quality["semanticStatus"], "operator_review_required")

    def test_measured_fit_replaces_capacity_estimate_without_claiming_human_review(self):
        scene = basic_scene(body_height=30, body_text="容量估算需要两行\n实际测量在测试中明确给出")
        self.assertIn("ESTIMATED_OVERFLOW", {i["code"] for i in audit_scene(scene)})
        report = validate_browser_report(scene, fixture_report(scene))
        self.assertNotIn("ESTIMATED_OVERFLOW", {i["code"] for i in audit_scene(scene, report)})
        current = self.add(scene)
        self.studio.run_quality(auto_fix=False)
        result = self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], report)
        self.assertEqual(result["quality"]["status"], "ready_to_review")
        self.assertFalse(result["quality"]["humanAccepted"])

    def test_readability_placeholders_overlap_and_contrast_are_reported(self):
        scene = basic_scene(body_height=200, body_text="[待补真实业务数据]")
        scene["objects"][1].update({"fontSize": 12, "color": "#EEEEEE", "y": 90})
        codes = {i["code"] for i in audit_scene(scene)}
        self.assertTrue({"TEXT_TOO_SMALL", "TEXT_CONTRAST", "CONTENT_PLACEHOLDER", "TEXT_BOX_OVERLAP"} <= codes)
        original = copy.deepcopy(scene)
        audit_scene(scene)
        self.assertEqual(scene, original)

    def test_intentional_background_container_is_not_a_text_overlap(self):
        scene = basic_scene()
        scene["objects"].insert(1, {"id": "card", "type": "rect", "x": 48, "y": 180, "w": 960, "h": 240,
            "fill": "#102544", "opacity": 1, "stroke": "none", "strokeWidth": 1, "radius": 12})
        scene["objects"][2]["color"] = "#FFFFFF"
        self.assertFalse(any(i["code"] in {"TEXT_BOX_OVERLAP", "TEXT_OCCLUDED", "TEXT_CONTRAST"} for i in audit_scene(scene)))
        validate_browser_report(scene, fixture_report(scene))

    def test_safe_repair_only_expands_height_and_preserves_words_images_other_page(self):
        first = self.add(basic_scene(body_height=25, body_text="第一行输入\n第二行输入"))
        other = self.add()
        other_bytes = Path(other["paths"]["source"]).read_bytes()
        original = first["scene"]
        quality = self.studio.run_quality(auto_fix=True, scope_slide_ids=[first["slideId"]])
        after = self.studio.get_scene(first["slideId"])
        self.assertGreater(after["sceneRevision"], first["sceneRevision"])
        self.assertEqual(len(quality["fixes"]), 1)
        for before_obj, after_obj in zip(original["objects"], after["scene"]["objects"]):
            if before_obj["id"] == "body-1":
                self.assertGreater(after_obj["h"], before_obj["h"])
                self.assertEqual({k: v for k, v in before_obj.items() if k != "h"}, {k: v for k, v in after_obj.items() if k != "h"})
            else:
                self.assertEqual(before_obj, after_obj)
        self.assertEqual(Path(other["paths"]["source"]).read_bytes(), other_bytes)
        self.assertEqual(self.studio.get_scene(other["slideId"])["sceneRevision"], other["sceneRevision"])
        self.assertEqual(quality["status"], "awaiting_browser")

    def test_precise_user_object_and_explicit_protection_are_not_changed_back(self):
        current = self.add(basic_scene(body_height=25, body_text="两行输入\n保留这个字号和文字框"))
        self.studio.run_quality(auto_fix=True, protected_objects={current["slideId"]: ["body-1"]})
        self.assertEqual(self.studio.get_scene(current["slideId"])["sceneRevision"], current["sceneRevision"])
        edited = self.studio.change_scene(current["slideId"], current["sceneRevision"], [{"objectId": "body-1", "properties": {"fontSize": 30}}], "body-1")
        self.studio.run_quality(auto_fix=True)
        self.assertEqual(self.studio.get_scene(current["slideId"])["sceneRevision"], edited["sceneRevision"])

    def test_safe_repair_does_not_move_into_another_object_or_shrink_words(self):
        scene = basic_scene(body_height=30, body_text="这段内容\n第二行\n第三行\n第四行")
        scene["objects"].append({"id": "boundary", "type": "line", "x": 64, "y": 240, "w": 900, "h": 0, "stroke": "#333333", "strokeWidth": 1})
        self.assertEqual(propose_safe_repairs(scene), [])
        current = self.add(scene)
        self.studio.run_quality(auto_fix=False)
        result = self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], fixture_report(current["scene"], overflow="body-1", extra_height=160))
        self.assertEqual(result["quality"]["status"], "needs_attention")
        self.assertFalse(result["quality"]["readyToReview"])
        self.assertIn("TEXT_OVERFLOW", {i["code"] for i in result["quality"]["issues"]})
        self.assertEqual(self.studio.get_scene(current["slideId"])["scene"], current["scene"])

    def test_stale_report_is_rejected_and_changed_scene_invalidates_quality(self):
        old = self.add()
        report = fixture_report(old["scene"])
        self.studio.record_browser_measurements(old["slideId"], old["sceneRevision"], report)
        self.assertTrue(self.studio.quality_state()["readyToReview"])
        new = self.studio.change_scene(old["slideId"], old["sceneRevision"], [{"objectId": "title", "properties": {"text": "当前新版标题"}}])
        self.assertEqual(self.studio.quality_state()["status"], "stale")
        self.assert_code("QUALITY_STALE_REPORT", self.studio.record_browser_measurements, old["slideId"], old["sceneRevision"], report)
        quality = self.studio.run_quality(auto_fix=False)
        self.assertEqual(quality["browser"]["measured"], 0)
        self.assertEqual(quality["status"], "awaiting_browser")
        self.assertEqual(new["scene"]["title"], "当前新版标题")

    def test_reports_must_be_complete_consistent_finite_and_have_no_approval_fields(self):
        current = self.add()
        base = fixture_report(current["scene"])
        invalid = []
        p = copy.deepcopy(base); p["objects"].pop(); invalid.append(p)
        p = copy.deepcopy(base); p["objects"][1]["objectId"] = p["objects"][0]["objectId"]; invalid.append(p)
        p = copy.deepcopy(base); p["passed"] = True; invalid.append(p)
        p = copy.deepcopy(base); p["objects"][0]["scrollHeight"] = float("nan"); invalid.append(p)
        p = copy.deepcopy(base); p["objects"][0]["clientHeight"] += 40; invalid.append(p)
        p = copy.deepcopy(base); p["overflowIds"] = ["body-1"]; invalid.append(p)
        p = copy.deepcopy(base); p["imagesLoaded"] = False; invalid.append(p)
        for report in invalid:
            with self.subTest(report=report):
                self.assert_code("INVALID_QUALITY_REPORT", self.studio.record_browser_measurements, current["slideId"], current["sceneRevision"], report)
        with self.studio.wb._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM studio_quality_measurements").fetchone()[0], 0)

    def test_incomplete_fonts_or_images_do_not_count_as_measured(self):
        current = self.add()
        for kwargs in ({"fonts_ready": False}, {"images_loaded": False}):
            reply = self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], fixture_report(current["scene"], **kwargs))
            self.assertEqual(reply["quality"]["status"], "awaiting_browser")
            self.assertEqual(reply["quality"]["browser"]["measured"], 0)
        reply = self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], fixture_report(current["scene"]))
        self.assertEqual(reply["quality"]["browser"]["measured"], 1)

    def test_all_pages_need_current_measurements_and_identical_reports_are_idempotent(self):
        first, second = self.add(), self.add()
        self.studio.record_browser_measurements(first["slideId"], first["sceneRevision"], fixture_report(first["scene"]))
        self.assertEqual(self.studio.quality_state()["status"], "awaiting_browser")
        self.studio.record_browser_measurements(second["slideId"], second["sceneRevision"], fixture_report(second["scene"]))
        self.assertEqual(self.studio.quality_state()["status"], "ready_to_review")
        with self.studio.wb._connection() as db:
            count = db.execute("SELECT COUNT(*) FROM studio_quality_runs").fetchone()[0]
        result = self.studio.record_browser_measurements(second["slideId"], second["sceneRevision"], fixture_report(second["scene"]))
        self.assertTrue(result["deduplicated"])
        with self.studio.wb._connection() as db:
            self.assertEqual(count, db.execute("SELECT COUNT(*) FROM studio_quality_runs").fetchone()[0])

    def test_browser_driven_repairs_have_a_persistent_budget(self):
        current = self.add(basic_scene(body_height=80))
        self.studio.run_quality(auto_fix=True)
        for _ in range(5):
            current = self.studio.get_scene(current["slideId"])
            self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], fixture_report(current["scene"], overflow="body-1", extra_height=20))
        state = self.studio.quality_state()
        self.assertEqual(len(state["fixes"]), 3)
        self.assertEqual(state["status"], "needs_attention")
        restored = Studio(self.root, "quality", create=False)
        self.assertEqual(len(restored.quality_state()["fixes"]), 3)
        after = restored.get_scene(current["slideId"])
        restored.record_browser_measurements(after["slideId"], after["sceneRevision"], fixture_report(after["scene"], overflow="body-1", extra_height=20))
        self.assertEqual(restored.get_scene(after["slideId"])["sceneRevision"], after["sceneRevision"])

    def test_browser_reports_do_not_widen_a_no_fix_or_single_page_scope(self):
        first, second = self.add(), self.add()
        self.studio.run_quality(auto_fix=False)
        self.studio.record_browser_measurements(first["slideId"], first["sceneRevision"], fixture_report(first["scene"], overflow="body-1"))
        self.assertEqual(self.studio.get_scene(first["slideId"])["sceneRevision"], first["sceneRevision"])
        self.studio.run_quality(auto_fix=True, scope_slide_ids=[second["slideId"]])
        self.studio.record_browser_measurements(first["slideId"], first["sceneRevision"], fixture_report(first["scene"], overflow="body-1", extra_height=40))
        self.assertEqual(self.studio.get_scene(first["slideId"])["sceneRevision"], first["sceneRevision"])
        self.assertEqual(self.studio.quality_state()["repairPolicy"]["slideIds"], [second["slideId"]])
        changed = self.studio.change_scene(second["slideId"], second["sceneRevision"], [{"objectId": "title", "properties": {"fontSize": 44}}], "title")
        self.studio.record_browser_measurements(changed["slideId"], changed["sceneRevision"], fixture_report(changed["scene"], overflow="body-1"))
        self.assertEqual(self.studio.get_scene(changed["slideId"])["sceneRevision"], changed["sceneRevision"])
        self.assertFalse(self.studio.quality_state()["repairPolicy"]["autoFix"])

    def test_protected_objects_survive_repairs_to_other_objects_and_later_measurement(self):
        scene = basic_scene(body_height=20)
        scene["objects"][0]["h"] = 20
        initial = self.add(scene)
        self.studio.run_quality(auto_fix=True, protected_objects={initial["slideId"]: ["title"]})
        after = self.studio.get_scene(initial["slideId"])
        self.assertGreater(after["sceneRevision"], initial["sceneRevision"])
        self.studio.record_browser_measurements(after["slideId"], after["sceneRevision"], fixture_report(after["scene"], overflow="title", extra_height=40))
        latest = self.studio.get_scene(after["slideId"])
        self.assertEqual(latest["sceneRevision"], after["sceneRevision"])
        self.assertEqual(self.studio.quality_state()["repairPolicy"]["protectedObjects"][after["slideId"]], ["title"])

    def test_delayed_round_check_and_report_cannot_repair_a_new_precise_round(self):
        first, current = self.start_deck_scope_round()
        delayed_policy = self.studio.quality_state()["repairPolicy"]
        second = self.studio.enqueue("只把标题字号改为44。", current["slideId"], "title")
        current = self.finish_precise_title(second, current)
        report = fixture_report(current["scene"], overflow="body-1", extra_height=40)
        self.assertTrue(propose_safe_repairs(current["scene"], report))
        self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], report)
        # The old caller resumes only after the precise edit and its measured
        # overflow. Its formerly valid scope must be rechecked under the lock.
        checked = self.studio.run_quality(auto_fix=True, round_id=first["roundId"], scope_slide_ids=delayed_policy["slideIds"])
        self.assertFalse(checked["repairPolicy"]["autoFix"])
        self.assertEqual(checked["repairPolicy"]["slideIds"], [])
        self.assertEqual(self.studio.get_scene(current["slideId"])["scene"], current["scene"])
        measured = self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"],
            fixture_report(current["scene"], overflow="body-1", extra_height=50))
        self.assertEqual(measured["quality"]["roundId"], second["roundId"])
        self.assertFalse(measured["quality"]["repairPolicy"]["autoFix"])
        self.assertEqual(self.studio.get_scene(current["slideId"])["sceneRevision"], current["sceneRevision"])

    def test_new_submission_disables_old_report_repairs_before_geometry_changes(self):
        _, current = self.start_deck_scope_round()
        second = self.studio.enqueue("只把标题字号改为44。", current["slideId"], "title")
        self.assertEqual(self.studio.job(second["jobId"])["status"], "queued")
        report = fixture_report(current["scene"], overflow="body-1", extra_height=40)
        measured = self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], report)
        self.assertEqual(measured["quality"]["roundId"], second["roundId"])
        self.assertFalse(measured["quality"]["repairPolicy"]["autoFix"])
        self.assertEqual(self.studio.get_scene(current["slideId"])["sceneRevision"], current["sceneRevision"])
        # The queued user's baseline remains usable, with every other object
        # retained after the selected title is changed.
        edited = self.finish_precise_title(second, current)
        self.assertEqual(edited["scene"]["objects"][1:], current["scene"]["objects"][1:])

    def test_current_check_holds_one_transaction_through_policy_and_execution(self):
        first, current = self.start_deck_scope_round()
        competitor = Studio(self.root, "quality", create=False)
        policy_read, resume_check = threading.Event(), threading.Event()
        submission_started, submission_done = threading.Event(), threading.Event()
        results, errors = {}, []
        original = self.studio.run_quality

        def delayed_check(*args, **kwargs):
            policy_read.set()
            if not resume_check.wait(5):
                raise AssertionError("The controlled check was not released")
            return original(*args, **kwargs)

        def check():
            try:
                results["check"] = self.studio.check_current_quality(auto_fix=True)
            except BaseException as exc:
                errors.append(exc)

        def submit():
            submission_started.set()
            try:
                results["submit"] = competitor.enqueue("只把标题字号改为44。", current["slideId"], "title")
            except BaseException as exc:
                errors.append(exc)
            finally:
                submission_done.set()

        checking, submitting = threading.Thread(target=check), threading.Thread(target=submit)
        with patch.object(self.studio, "run_quality", side_effect=delayed_check):
            try:
                checking.start()
                self.assertTrue(policy_read.wait(5))
                submitting.start()
                self.assertTrue(submission_started.wait(5))
                self.assertFalse(submission_done.wait(.05), "A new round committed between policy lookup and checking")
            finally:
                resume_check.set()
                checking.join(5)
                if submitting.ident is not None:
                    submitting.join(5)
        self.assertFalse(checking.is_alive())
        self.assertFalse(submitting.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results["check"]["roundId"], first["roundId"])
        self.assertNotEqual(results["submit"]["roundId"], first["roundId"])
        latest = self.studio.get_scene(current["slideId"])
        self.assertEqual(competitor.job(results["submit"]["jobId"])["payload"]["baseSceneRevision"], latest["sceneRevision"])

    def test_human_acceptance_is_separate_and_never_created_by_checks(self):
        current = self.add()
        self.studio.record_browser_measurements(current["slideId"], current["sceneRevision"], fixture_report(current["scene"]))
        quality = self.studio.quality_state()
        self.assertTrue(quality["readyToReview"])
        self.assertFalse(quality["humanAccepted"])
        page = self.studio.wb.get_slide("quality", current["slideId"])
        self.assertIsNone(page["reviews"]["content"])
        self.assertIsNone(page["reviews"]["visual"])
        self.studio.review(current["slideId"], current["sceneRevision"], "操作者明确查看测试页面后认可这一版。")
        self.assertTrue(self.studio.quality_state()["humanAccepted"])

    @unittest.skipUnless(shutil.which("node"), "Node is required for the generated JavaScript contract check")
    def test_generated_report_script_matches_server_contract_without_a_browser(self):
        scene = basic_scene()
        script = re.search(r"<script>(.*?)</script>", render_html(scene), re.S).group(1)
        fixture = fixture_report(scene)
        program = r"""
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),messages=[];
const elements=input.objects.map(o=>({...o,style:{left:'0px',top:'0px',width:'100px',height:'100px'},dataset:{objectId:o.objectId,type:o.type},complete:true,naturalWidth:1,addEventListener(){},classList:{add(){},remove(){}}}));
const slide={style:{},append(){}};
const document={fonts:{ready:Promise.resolve(),status:'loaded'},createElement(){return {style:{},dataset:{},append(){}};},getElementById(){return slide;},addEventListener(){},querySelectorAll(selector){
  if(selector==='[data-object-id]')return elements;
  if(selector==='.text')return elements.filter(o=>o.type==='text');
  if(selector==='img')return elements.filter(o=>o.type==='image');
  return [];
}};
vm.runInNewContext(input.script,{document,MutationObserver:class{observe(){}},parent:{postMessage(m){messages.push(m);}},innerWidth:1280,innerHeight:720,
  addEventListener(){},requestAnimationFrame(cb){cb();return 1;},cancelAnimationFrame(){},setTimeout(cb){cb();},clearTimeout(){},Promise});
setImmediate(()=>{const result=messages.filter(m=>m.type==='ppt-quality').at(-1);if(!result)throw Error('No quality report');process.stdout.write(JSON.stringify(result.report));});
"""
        result = subprocess.run([shutil.which("node"), "-e", program], input=json.dumps({"script": script, "objects": fixture["objects"]}),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        normalized = validate_browser_report(scene, json.loads(result.stdout))
        self.assertEqual(normalized, fixture)


if __name__ == "__main__":
    unittest.main()
