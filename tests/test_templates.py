import copy
import json
from pathlib import Path
import tempfile
import unittest

from ppt_workbench.core import EngineError
from ppt_workbench import design_map
from ppt_workbench.rendering import render_html, validate_scene
from ppt_workbench.studio import Studio
from ppt_workbench.templates import apply_template, catalog, recommend_templates, sample_scene, template_for_role
from test_studio import PNG


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.studio = Studio(self.temp.name, "visual", agent="manual")

    def assert_code(self, code, func, *args):
        with self.assertRaises(EngineError) as raised:
            func(*args)
        self.assertEqual(raised.exception.code, code)

    def test_recommendations_respect_page_role_and_content(self):
        cover = recommend_templates("cover", "产品介绍")
        self.assertTrue(cover)
        self.assertTrue(all("cover" in item["roles"] and not item.get("legacy") for item in cover))
        comparison = recommend_templates("content", "竞品对比和差异")
        self.assertTrue(comparison)
        self.assertTrue(all("content" in item["roles"] for item in comparison))
        self.assertTrue(any(item["family"] == "compare" for item in comparison[:3]))

    def test_browsing_purposes_follow_original_content_not_adaptation(self):
        from collections import Counter
        from ppt_workbench.template_categories import CATEGORIES
        cards = {t['id']: t for t in catalog() if not t.get('legacy')}
        counts = Counter(t['browseCategory'] for t in cards.values())
        self.assertEqual(sum(counts.values()), 138)
        self.assertEqual(set(counts), set(CATEGORIES))
        self.assertLess(max(counts.values()), 30)
        expected = {'reference-01-06': 'people', 'reference-03-08': 'case',
                    'reference-04-04': 'data', 'reference-04-05': 'data',
                    'reference-03-11': 'gallery', 'reference-04-08': 'compare',
                    'reference-01-04': 'process', 'reference-04-11': 'structure'}
        for tid, category in expected.items():
            self.assertEqual(cards[tid]['browseCategory'], category, tid)
        self.assertEqual(cards['reference-01-06']['family'], 'product')
        self.assertEqual(cards['reference-01-06']['role'], 'content')

    def test_quick_recommendations_work_without_model_service(self):
        self.studio.demo()
        result = self.studio.template_recommendations(self.studio.state()['selectedSlideId'])
        self.assertTrue(result['recommendations'])
        self.assertLessEqual(len(result['recommendations']), 6)
        layouts = [t.get('baseTemplateId', t['id']) for t in result['recommendations']]
        self.assertEqual(len(layouts), len(set(layouts)))

    def test_catalog_and_all_layouts_preserve_content_and_images(self):
        original = sample_scene("clean")
        original["objects"].append({"id": "photo", "type": "image", "src": "data:image/png;base64," + PNG,
                                    "alt": "原图", "x": 800, "y": 300, "w": 180, "h": 180})
        original = validate_scene(original)
        untouched = copy.deepcopy(original)
        variants = []
        for card in catalog():
            self.assertTrue({"id", "name", "description", "tags", "previewUrl", "roles", "family", "familyName", "use", "inputs", "checks"} <= set(card))
            scene = apply_template(original, card["id"])
            variants.append(json.dumps(scene))
            by_id = {obj["id"]: obj for obj in scene["objects"]}
            self.assertTrue({obj["id"] for obj in original["objects"]} <= set(by_id))
            for before in original["objects"]:
                after = by_id[before["id"]]
                for field in ("text", "binding", "src", "alt", "fit", "type", "id"):
                    self.assertEqual(before.get(field), after.get(field))
            preview = sample_scene(card["id"])
            self.assertIn(preview["title"], render_html(preview))
        self.assertEqual(len(set(variants)), len(catalog()))
        self.assertEqual(original, untouched)
        self.assert_code("UNKNOWN_TEMPLATE", sample_scene, "missing")

    def test_reference_counts_roles_and_source_metadata_are_exact(self):
        data = Path(__file__).resolve().parents[1] / "ppt_workbench" / "data"
        source = json.loads((data / "bbstack-templates.json").read_text())
        structure = json.loads((data / "bbstack-structure.json").read_text())
        cards = {entry["id"]: entry for entry in catalog()}
        self.assertEqual(len(source["templates"]), 54)
        self.assertEqual(len(cards), 147)
        self.assertEqual(sum(bool(c.get("variantOf")) for c in cards.values()), 7)
        self.assertEqual(sum(c["legacy"] for c in cards.values()), 9)
        self.assertEqual(sum(bool(c.get("local")) for c in cards.values()), 14)
        self.assertEqual({r["id"] for r in structure["roles"]}, {"cover", "toc", "chapter", "content", "ending", "appendix"})
        appendix = {tid for section in structure["appendixSections"] for tid in section["templateIds"]}
        self.assertEqual(appendix, {"table", "bar", "line", "case", "case-compare"})
        for authored in source["templates"]:
            card = cards[authored["id"]]
            for key, value in authored.items():
                self.assertEqual(card[key], value)
            primary = next((r["id"] for r in structure["roles"] if card["id"] in r["templateIds"]), "content")
            self.assertEqual(card["role"], primary)
            self.assertEqual(card["roles"], [primary] + (["appendix"] if card["id"] in appendix else []))
        for card in cards.values():
            self.assertEqual(card["previewUrl"], "/api/templates/preview?template=" + card["id"])
        cards["cover"]["example"]["title"] = "mutated"
        self.assertNotEqual(next(card for card in catalog() if card['id'] == 'cover')["example"]["title"], "mutated")

    def test_authored_examples_and_legacy_ids(self):
        for card in catalog():
            scene = sample_scene(card["id"])
            if design_map.has_template(card['id']):
                self.assertEqual(scene, design_map.sample_scene(card['id']))
                continue
            if "example" in card:
                self.assertEqual(scene["title"], card["example"]["title"])
                if not card.get("local") or card["visual"] in {"kpi-hero", "case-scorecard", "landscape-path"}:
                    self.assertEqual([o["text"] for o in scene["objects"] if o.get("binding", "").startswith("keyPoints:")],
                                     [s["label"] + "\n" + s["text"] for s in card["example"]["slots"]])
        for tid in ("clean", "editorial", "parallel", "comparison", "steps", "dark"):
            self.assertEqual(apply_template(sample_scene("clean"), tid)["templateId"], tid)

    def test_role_preference_and_spatial_layouts(self):
        self.assertEqual(template_for_role("cover-photo", "content"), "claim-proof")
        self.assertEqual(template_for_role("cover-photo", "chapter"), "chapter")
        self.assertEqual(template_for_role("bar", "appendix"), "bar")
        self.assertEqual(template_for_role("cover", "appendix"), "table")
        self.assertEqual(template_for_role("dark", "toc"), "dark")
        source = sample_scene("clean")
        def geometry(tid):
            return [(o["x"], o["y"], o["w"], o["h"]) for o in apply_template(source, tid)["objects"] if o["type"] == "text"]
        self.assertEqual(len({tuple(geometry(t)) for t in ("cover", "toc", "chapter", "ending")}), 4)
        self.assertNotEqual(geometry("parallel-two"), geometry("parallel-three"))
        self.assertNotEqual(geometry("parallel-three"), geometry("parallel-four"))
        self.assertNotEqual(geometry("hub"), geometry("hierarchy"))
        self.assertNotEqual(geometry("guide-split"), geometry("process"))
        for card in catalog():
            if card.get("family") == "data":
                applied = apply_template(source, card["id"])
                self.assertEqual([o["text"] for o in applied["objects"] if o['type'] == 'text'],
                                 [o["text"] for o in source["objects"] if o['type'] == 'text'])
                self.assertTrue({o['id'] for o in source['objects']} <= {o['id'] for o in applied['objects']})
        for size in ((640, 360), (3840, 2160)):
            scaled = copy.deepcopy(source)
            sx, sy = size[0] / scaled["width"], size[1] / scaled["height"]
            scaled.update(width=size[0], height=size[1])
            for obj in scaled["objects"]:
                for field in ("x", "w"):
                    obj[field] *= sx
                for field in ("y", "h"):
                    obj[field] *= sy
            for card in catalog():
                validate_scene(apply_template(scaled, card["id"]))

    def test_empty_project_preference_persists_and_applies_to_first_save(self):
        self.assertIsNone(self.studio.state()["selectedTemplateId"])
        self.studio.select_template("dark")
        reopened = Studio(self.temp.name, "visual", agent="manual")
        self.assertEqual(reopened.state()["selectedTemplateId"], "dark")
        reopened.demo()
        for slide in reopened.state()["slides"]:
            self.assertEqual(reopened.get_scene(slide["id"])["scene"]["templateId"], "dark")
        self.assertIsNone(Studio(self.temp.name, "other").selected_template())

    def test_application_persists_metadata_and_rejects_stale_without_mutation(self):
        self.studio.demo()
        sid = self.studio.state()["selectedSlideId"]
        current = self.studio.get_scene(sid)
        old_text = [(o["id"], o["text"], o.get("binding")) for o in current["scene"]["objects"] if o["type"] == "text"]
        applied = self.studio.select_template("editorial", sid, current["sceneRevision"])
        self.assertEqual(applied["sceneRevision"], current["sceneRevision"] + 1)
        self.assertEqual(old_text, [(o["id"], o["text"], o.get("binding")) for o in applied["scene"]["objects"] if o["type"] == "text"])
        self.assertEqual(json.loads(Path(applied["paths"]["source"]).read_text())["templateId"], "editorial")
        reopened = Studio(self.temp.name, "visual")
        self.assertEqual(reopened.get_scene(sid), {k: v for k, v in applied.items() if k != "selectedTemplateId"})
        self.assertEqual(reopened.state()["selectedTemplateId"], "editorial")
        self.assertEqual(reopened.context({"slideId": sid})["currentSceneTemplateId"], "editorial")
        self.assert_code("STALE_REVISION", reopened.select_template, "clean", sid, current["sceneRevision"])
        self.assert_code("STALE_REVISION", reopened.select_template, "clean", sid, None)
        self.assertEqual(reopened.state()["selectedTemplateId"], "editorial")
        self.assertEqual(reopened.get_scene(sid), {k: v for k, v in applied.items() if k != "selectedTemplateId"})
        regenerated = reopened.generate_scene(sid)
        self.assertEqual(regenerated["scene"]["templateId"], "editorial")

    def test_template_application_preserves_selection_and_page_specific_context(self):
        self.studio.demo()
        slides = self.studio.state()["slides"]
        self.assertGreaterEqual(len(slides), 2)
        first, second = slides[0]["id"], slides[1]["id"]
        self.studio.select(second)
        current = self.studio.get_scene(first)
        self.studio.select_template("editorial", first, current["sceneRevision"])
        state = self.studio.state()
        self.assertEqual(state["selectedSlideId"], second)
        self.assertEqual(next(s for s in state["slides"] if s["id"] == first)["sceneTemplateId"], "editorial")
        second_scene = self.studio.get_scene(second)["scene"]["templateId"]
        context = self.studio.context({"slideId": second})
        self.assertEqual(context["currentSceneTemplateId"], second_scene)
        self.assertEqual(context["selectedTemplateId"], "editorial")

    def test_manual_edit_updates_binding_invalidates_review_without_ai_round(self):
        self.studio.demo()
        sid = self.studio.state()["selectedSlideId"]
        current = self.studio.get_scene(sid)
        self.studio.review(sid, current["sceneRevision"])
        before = self.studio.state()
        result = self.studio.edit_scene(sid, current["sceneRevision"], [
            {"objectId": "title", "properties": {"text": "用户手工更新的标题"}}])
        page = self.studio.wb.get_slide("visual", sid)
        self.assertEqual(page["slide"]["title"], "用户手工更新的标题")
        self.assertFalse(page["reviews"]["visual"])
        after = self.studio.state()
        self.assertEqual(len(before["messages"]), len(after["messages"]))
        self.assertEqual(len(before["delivery"]["rounds"]), len(after["delivery"]["rounds"]))
        self.assert_code("STALE_REVISION", self.studio.edit_scene, sid, current["sceneRevision"], [
            {"objectId": "title", "properties": {"text": "旧版本"}}])
        self.assert_code("INVALID_SCENE_PATCH", self.studio.edit_scene, sid, result["sceneRevision"], [
            {"objectId": "title", "properties": {"binding": "takeaway"}}])
        self.assertEqual(result, self.studio.get_scene(sid))

    def test_missing_declared_logo_allows_edits_but_blocks_release(self):
        self.studio.demo()
        sid = self.studio.state()["selectedSlideId"]
        project = self.studio.wb.get_project("visual")
        self.studio.wb.update_project("visual", project["revision"],
                                      {"logoPolicy": "company", "logoReference": "missing-logo.svg"})
        current = self.studio.generate_scene(sid)
        state = next(s for s in self.studio.state()["slides"] if s["id"] == sid)
        self.assertFalse(current["stale"])
        self.assertTrue(state["previewMaterialUnavailable"])
        applied = self.studio.select_template("editorial", sid, current["sceneRevision"])
        edited = self.studio.edit_scene(sid, applied["sceneRevision"], [
            {"objectId": "title", "properties": {"text": "更新标题"}}])
        self.assertFalse(edited["stale"])
        self.assertEqual(self.studio.context({"slideId": sid})["selectedTemplateId"], "editorial")
        self.assertIn("MATERIAL_UNAVAILABLE", {i["code"] for i in self.studio.wb.get_slide("visual", sid)["integrityIssues"]})
        self.assertFalse(self.studio.wb.gate("visual")["ready"])
        self.assert_code("RELEASE_GATE_FAILED", self.studio.wb.release_manifest, "visual")

    def test_missing_slide_asset_still_blocks_edits(self):
        self.studio.demo()
        sid = self.studio.state()["selectedSlideId"]
        page = self.studio.wb.get_slide("visual", sid)
        self.studio.wb.patch_slide("visual", sid, page["revision"], [{"path": "/assets", "value": [
            {"id": "A1", "kind": "photo", "owner": "user", "status": "provided",
             "required": True, "reference": "missing.png", "description": "photo"}]}])
        current = self.studio.generate_scene(sid)
        self.assertTrue(current["stale"])
        self.assert_code("SCENE_STALE", self.studio.select_template, "editorial", sid, current["sceneRevision"])

    def test_content_and_artifact_integrity_block_both_manual_mutations(self):
        self.studio.demo()
        sid = self.studio.state()["selectedSlideId"]
        current = self.studio.get_scene(sid)
        Path(current["paths"]["preview"]).write_text("tampered")
        self.assertTrue(self.studio.get_scene(sid)["stale"])
        self.assert_code("SCENE_STALE", self.studio.select_template, "clean", sid, current["sceneRevision"])
        self.assert_code("SCENE_STALE", self.studio.edit_scene, sid, current["sceneRevision"], [
            {"objectId": "title", "properties": {"text": "不应保存"}}])
        self.assertEqual(self.studio.get_scene(sid)["sceneRevision"], current["sceneRevision"])
        repaired = self.studio.generate_scene(sid)
        self.studio.wb.patch_slide("visual", sid, repaired["contentRevision"], [{"path": "/takeaway", "value": "更新的内容"}])
        self.assert_code("SCENE_STALE", self.studio.select_template, "dark", sid, repaired["sceneRevision"])
        self.assert_code("SCENE_STALE", self.studio.edit_scene, sid, repaired["sceneRevision"], [
            {"objectId": "title", "properties": {"text": "不应保存"}}])
