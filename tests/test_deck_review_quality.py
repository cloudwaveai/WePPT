"""Deck review quality: deterministic anchor boost, wider scope, scaled budget."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ppt_workbench.studio import Studio
from ppt_workbench.core import EngineError
from ppt_workbench.quality import boost_anchors
from ppt_workbench.deck_review import run_review
from test_deck_design import deck_plan, STRATEGY, BRIEF
from test_page_design import action


def scene(objects, background="#FFFFFF"):
    return {"schema": "ppt-scene", "schemaVersion": 1, "slideId": "S001", "width": 1280,
            "height": 720, "background": background, "objects": objects}


def text(oid, t, x, y, w=200, h=60, size=24, **kw):
    return {"id": oid, "type": "text", "text": t, "x": x, "y": y, "w": w, "h": h,
            "fontSize": size, **kw}


class BoostAnchorTests(unittest.TestCase):
    def test_noop_when_enough_anchors_or_too_few_pages(self):
        self.assertEqual(boost_anchors([scene([text("a", "大标题", 60, 60, size=80)])], {}), [])
        self.assertEqual(boost_anchors([scene([text("a", "大标题", 60, 60, size=80)]),
                                        scene([text("b", "小", 60, 60, size=20)])], {}), [])

    def test_priority_metric_digit_kicker_other(self):
        s = scene([text("other", "短词", 60, 500), text("k1", "KPI", 60, 380),
                   text("num", "42", 60, 260), text("m", "98%", 60, 140)])
        plan = {"pages": [{"blocks": [{"metric": "98%"}, {"kicker": "KPI"}]}]}
        boosts = boost_anchors([s, scene([text("x", "也短", 900, 600, size=20)])], plan)
        self.assertEqual(len(boosts), 1)
        self.assertEqual(boosts[0]["objectId"], "m")

    def test_overlap_and_canvas_rejection(self):
        s = scene([text("free", "7", 60, 560, w=40, h=40), text("block", "很长的一段正文内容", 60, 60),
                   text("corner", "边", 1180, 600, w=80, h=40)])
        boosts = boost_anchors([s, scene([text("a", "也短", 900, 600, size=20)])], {})
        self.assertEqual(boosts[0]["objectId"], "free")
        # 'corner' boosted box (1 char, 72px) would exceed the right inset: rejected → 'free' wins.
        s2 = scene([text("mid", "关键词", 600, 300), text("crowd", "人群", 560, 240, w=160, h=50)])
        boosts2 = boost_anchors([s2, scene([text("a", "也短", 900, 600, size=20)])], {})
        # '人群' (2 chars) enlarged overlaps 'mid' region if they intersect; whichever survives
        # must not overlap any text object.
        if boosts2:
            obj = next(o for o in s2["objects"] if o["id"] == boosts2[0]["objectId"])
            others = [o for o in s2["objects"] if o["type"] == "text" and o is not obj]
            for o in others:
                self.assertFalse(obj["x"] < o["x"] + o["w"] and o["x"] < obj["x"] + obj["w"]
                                 and obj["y"] < o["y"] + o["h"] and o["y"] < obj["y"] + obj["h"])

    def test_alignment_anchors(self):
        s = scene([text("c", "中", 400, 300, w=120, h=40, align="center", valign="middle")])
        boost_anchors([s, scene([text("a", "也短", 900, 600, size=20)])], {})
        obj = s["objects"][0]
        self.assertAlmostEqual(obj["x"] + obj["w"] / 2, 460, places=1)
        self.assertAlmostEqual(obj["y"] + obj["h"] / 2, 320, places=1)
        s2 = scene([text("r", "右", 1000, 600, w=120, h=40, align="right", valign="bottom")])
        boost_anchors([s2, scene([text("a", "也短", 900, 600, size=20)])], {})
        obj2 = s2["objects"][0]
        self.assertAlmostEqual(obj2["x"] + obj2["w"], 1120, places=1)
        self.assertAlmostEqual(obj2["y"] + obj2["h"], 640, places=1)

    def test_need_count_and_box_size(self):
        scenes = [scene([text(f"t{i}", "短", 60, 60, w=60, h=40), text(f"b{i}", "正文占位文本",
                          60, 200, w=400, h=300)]) for i in range(4)]
        boosts = boost_anchors(scenes, {})
        self.assertEqual(len(boosts), 2)
        obj = scenes[0]["objects"][0]
        self.assertEqual(obj["fontSize"], 72)
        self.assertEqual(obj["lineHeight"], 1)
        self.assertEqual(obj["h"], 90)
        self.assertGreater(obj["w"], 70)


class RunReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.studio = Studio(self.temp.name, "test", agent="manual")

    def ready(self, pages=2, mutate=None):
        plan = deck_plan()
        base = plan["pages"][0]
        plan["pages"] = [copy.deepcopy(base) for _ in range(pages)]
        self.studio.create_deck(plan, "完整用户需求")
        for _ in range(pages):
            job = self.studio.next_job()["job"]
            self.studio.apply_plan(job["id"], dict(reply="页", actions=[action()]))
        if mutate:
            for slide in self.studio.state()["slides"]:
                cur = self.studio.get_scene(slide["id"])
                self.studio.put_scene(slide["id"], cur["contentRevision"],
                                      mutate(cur["scene"]), "测试布景")
        with self.studio.wb.atomic() as db:
            deck = self.studio._deck_row(db)
            row = db.execute("SELECT id FROM studio_jobs WHERE client_message_id=?",
                             ("deck-review:" + deck["id"],)).fetchone()
            db.execute("UPDATE studio_jobs SET status='running' WHERE id=?", (row["id"],))
            return self.studio.job(row["id"])

    def sheets(self, overflow_ids=None):
        def call(scenes, folder):
            folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
            png = folder / "sheet.png"; png.write_bytes(b"png")
            sheets = [(start, min(4, len(scenes) - start), png)
                      for start in range(0, len(scenes), 4)]
            return sheets, [dict(fontsReady=True,
                                 overflow=list(overflow_ids or []) if i == 0 else [])
                            for i in range(len(scenes))]
        return call

    def render(self, scene, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        png = folder / "page.png"; png.write_bytes(b"png")
        return png, dict(fontsReady=True, overflow=[])

    def with_num(self, scene):
        scene = copy.deepcopy(scene)
        scene["objects"].append(text("num", "7", 64, 560, w=40, h=40, size=30))
        return scene

    def test_boost_applied_and_saved(self):
        job = self.ready(mutate=self.with_num)
        with patch("ppt_workbench.deck_review.contact_sheets", side_effect=self.sheets()):
            run_review(self.studio, job, "claude", lambda *a, **k: dict(reply="PASS\n好", actions=[]))
        scene = self.studio.get_scene("S001")["scene"]
        num = next(o for o in scene["objects"] if o["id"] == "num")
        self.assertEqual(num["fontSize"], 72)
        self.assertEqual(num["lineHeight"], 1)
        review = self.studio.deck_state()["designReview"]
        self.assertIn("S001", review["repairedPages"])
        self.assertEqual(review["status"], "reviewed")

    def test_overflow_reverts_boost(self):
        job = self.ready(mutate=self.with_num)
        with patch("ppt_workbench.deck_review.contact_sheets",
                   side_effect=self.sheets(overflow_ids=["num"])):
            run_review(self.studio, job, "claude", lambda *a, **k: dict(reply="PASS\n好", actions=[]))
        scene = self.studio.get_scene("S001")["scene"]
        num = next(o for o in scene["objects"] if o["id"] == "num")
        self.assertEqual(num["fontSize"], 30)
        review = self.studio.deck_state()["designReview"]
        self.assertNotIn("S001", review["repairedPages"])
        with self.studio.wb._connection() as db:
            row = db.execute("SELECT result FROM studio_jobs WHERE client_message_id LIKE 'deck-review:%'").fetchone()
        report = json.loads(row["result"])["deckDesignReview"]
        self.assertEqual(report["anchorBoostReverted"], [{"slideId": "S001", "objectId": "num"}])

    def big_deck(self, pages, mutate=None):
        plan = deck_plan()
        base = plan["pages"][0]
        plan["pages"] = [copy.deepcopy(base) for _ in range(pages)]
        self.studio.create_deck(plan, "完整用户需求")
        for _ in range(pages):
            job = self.studio.next_job()["job"]
            self.studio.apply_plan(job["id"], dict(reply="页", actions=[action()]))
        if mutate:
            for slide in self.studio.state()["slides"]:
                cur = self.studio.get_scene(slide["id"])
                self.studio.put_scene(slide["id"], cur["contentRevision"], mutate(cur["scene"]), "布景")
        with self.studio.wb.atomic() as db:
            deck = self.studio._deck_row(db)
            row = db.execute("SELECT id FROM studio_jobs WHERE client_message_id=?",
                             ("deck-review:" + deck["id"],)).fetchone()
            db.execute("UPDATE studio_jobs SET status='running' WHERE id=?", (row["id"],))
            return self.studio.job(row["id"])

    def anchored(self, scene):
        scene = copy.deepcopy(scene)
        scene["objects"][0]["fontSize"] = 80
        return scene

    def test_edit_for_page_in_another_sheet_is_repaired(self):
        job = self.big_deck(6, mutate=self.anchored)
        def runner(mode, prompt, context, **kw):
            if context["generationTask"]["kind"] == "deck_review":
                if context["reviewStage"] == "initial":
                    return dict(reply="REVISE\n第五页焦点不清",
                                actions=[dict(type="deck_feedback",
                                              edits=[dict(slide_id="S005", instruction="放大焦点")])])
                return dict(reply="PASS\nok", actions=[])
            if context.get("reviewStage") == "critique-and-repair":
                return dict(reply="REVISE", actions=[dict(type="scene_patch", slide_id="S005",
                    base_scene_revision=self.studio.get_scene("S005")["sceneRevision"],
                    changes=[dict(objectId="now", properties={"x": 300})])])
            return dict(reply="PASS", actions=[])
        with patch("ppt_workbench.deck_review.contact_sheets", side_effect=self.sheets()), \
             patch("ppt_workbench.design_review.render_candidate", side_effect=self.render):
            run_review(self.studio, job, "claude", runner)
        self.assertEqual(self.studio.get_scene("S005")["scene"]["objects"][1]["x"], 300)
        self.assertIn("S005", self.studio.deck_state()["designReview"]["repairedPages"])

    def test_cap_scales_with_page_count(self):
        job = self.big_deck(12, mutate=self.anchored)
        edits = [dict(slide_id=f"S{i:03d}", instruction="调整") for i in (1, 2, 3, 4)]
        def runner(mode, prompt, context, **kw):
            if context["generationTask"]["kind"] == "deck_review":
                if context["reviewStage"] == "initial":
                    return dict(reply="REVISE\n四页需修", actions=[dict(type="deck_feedback", edits=edits)])
                return dict(reply="PASS\nok", actions=[])
            if context.get("reviewStage") == "critique-and-repair":
                sid = context["deckReviewInstruction"] and None
                target = next(s["slideId"] for s in (context.get("scene") and [] or []))
                return dict(reply="PASS", actions=[])
            return dict(reply="PASS", actions=[])
        # Simpler: repair runner that moves 'now' on whichever page is being repaired.
        sid_holder = []
        def runner2(mode, prompt, context, **kw):
            if context["generationTask"]["kind"] == "deck_review":
                if context["reviewStage"] == "initial":
                    return dict(reply="REVISE\n四页需修", actions=[dict(type="deck_feedback", edits=edits)])
                return dict(reply="PASS\nok", actions=[])
            if context.get("reviewStage") == "critique-and-repair":
                return dict(reply="PASS", actions=[])
            return dict(reply="PASS", actions=[])
        with patch("ppt_workbench.deck_review.contact_sheets", side_effect=self.sheets()), \
             patch("ppt_workbench.design_review.render_candidate", side_effect=self.render):
            run_review(self.studio, job, "claude", runner2)
        with self.studio.wb._connection() as db:
            row = db.execute("SELECT result FROM studio_jobs WHERE client_message_id LIKE 'deck-review:%'").fetchone()
        report = json.loads(row["result"])["deckDesignReview"]
        self.assertEqual(report["pageRepairCalls"], 4)
        self.assertNotIn("deferredEdits", report)

    def test_prompt_contains_gap_and_anchor_sentences(self):
        job = self.ready()
        prompts, contexts = [], []
        def runner(mode, prompt, context, **kw):
            if context["generationTask"]["kind"] == "deck_review":
                prompts.append(prompt); contexts.append(context)
            return dict(reply="PASS\nok", actions=[])
        with patch("ppt_workbench.deck_review.contact_sheets", side_effect=self.sheets()):
            run_review(self.studio, job, "claude", runner)
        self.assertIn("待补充", prompts[0])
        self.assertIn("anchorBoosts", contexts[0])
        self.assertIn("系统已先自动放大", prompts[0])


if __name__ == "__main__":
    unittest.main()
