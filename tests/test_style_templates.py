"""3-page style benchmarks: upload, contact sheet, analysis, selection, precedence."""
import base64
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench import user_templates as ut

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"pngdata").decode()


def file(name="p.png"):
    return {"filename": name, "mime": "image/png", "base64": PNG}

PROFILE = {"summary": "深色商务风", "ui": {"grid": "12 栏", "whitespace": "大量留白", "hierarchy": "大标题", "containers": "圆角卡片"},
           "elements": {"shapes": "圆", "lines": "细线", "imagery": "照片", "dataViz": "大数字"},
           "typography": {"title": "粗体 40", "body": "常规 16", "accent": "主色加粗"},
           "color": {"background": "#FFFFFF", "ink": "#111111", "primary": "#AA0000",
                     "secondary": ["#00AA00"], "usage": "主色强调"},
           "designStyle": {"keywords": ["商务", "深色", "大字"], "mood": "沉稳", "pageRhythm": "封面重"},
           "avoid": ["不要渐变", "不要阴影"]}


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.s = Studio(self.temp.name, "st")

    def error(self, code, func, *a, **kw):
        with self.assertRaises(EngineError) as e:
            func(*a, **kw)
        self.assertEqual(e.exception.code, code)

    def upload3(self):
        with patch("ppt_workbench.design_review.render_candidate",
                   side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
            return ut.upload(self.s, "style", [file("a.png"), file("b.png"), file("c.png")])["templates"][0]

    def test_exactly_three(self):
        for files in ([file()], [file()] * 2, [file()] * 4):
            self.error("INVALID_UPLOAD", ut.upload, self.s, "style", files)

    def test_upload_pages_and_contact(self):
        t = self.upload3()
        self.assertEqual(len(t["previews"]), 3)
        path, sha = ut.image(self.s, t["id"], 2)
        self.assertTrue(path.name.endswith("page-3.png"))
        self.error("NOT_FOUND", ut.image, self.s, t["id"], 3)

    def test_analyze_parses_fenced_json_and_retries(self):
        t = self.upload3()
        self.s.set_agent_mode("codex")
        replies = iter([
            {"reply": "not json", "actions": []},
            {"reply": "前言```json\n" + json.dumps(PROFILE, ensure_ascii=False) + "\n```后记", "actions": []}])
        calls = []
        def run(*a, **kw):
            calls.append((a, kw))
            return next(replies)
        with patch("ppt_workbench.agent_bridge.run_turn", side_effect=run):
            result = ut.analyze_style(self.s, t["id"])
        self.assertEqual(len(calls), 2)
        self.assertIn("revisionCorrection", calls[1][0][2])
        self.assertEqual(calls[0][0][2]["generationTask"]["kind"], "style_analysis")
        self.assertEqual(result["template"]["profile"], PROFILE)
        self.assertEqual(result["template"]["analyzedBy"], "codex")

    def test_analyze_failure_after_retry(self):
        t = self.upload3()
        self.s.set_agent_mode("codex")
        with patch("ppt_workbench.agent_bridge.run_turn", return_value={"reply": "{}", "actions": []}):
            self.error("STYLE_ANALYSIS_FAILED", ut.analyze_style, self.s, t["id"])

    def test_analyze_requires_vision(self):
        t = self.upload3()
        self.s.set_agent_mode("api")
        with patch("ppt_workbench.model_profiles.selected", return_value={"id": "x", "mode": "api", "model": "m"}), \
             patch("ppt_workbench.model_profiles.resolve", return_value={"id": "x", "mode": "api", "model": "m", "vision": False}):
            self.error("TEMPLATE_NEEDS_VISION", ut.analyze_style, self.s, t["id"])

    def test_update_select_and_context(self):
        t = self.upload3()
        self.error("INVALID_STYLE_PROFILE", ut.update_style, self.s, t["id"], None, {"bad": 1})
        result = ut.update_style(self.s, t["id"], "我的风格", PROFILE)
        self.assertEqual(result["template"]["name"], "我的风格")
        state = ut.select_style(self.s, t["id"])
        self.assertEqual(state["styleReference"], {"id": t["id"], "name": "我的风格", "summary": "深色商务风"})
        ctx = self.s.context({"scope": "deck"})
        self.assertEqual(ctx["styleReference"]["name"], "我的风格")
        self.assertEqual(ctx["styleReference"]["profile"], PROFILE)
        self.assertIsNone(ut.select_style(self.s, None)["styleReference"])

    def test_create_deck_colour_precedence(self):
        t = self.upload3()
        ut.update_style(self.s, t["id"], None, PROFILE)
        ut.select_style(self.s, t["id"])
        plan = {"title": "整稿", "execution": "agent",
                "design": {"background": "#EEEEEE", "ink": "#222222", "accent": "#FF0000",
                           "fontFamily": "Microsoft YaHei"},
                "pages": [{"title": f"第{i}页", "user_intent": "原话", "role": r,
                           "takeaway": "点", "key_points": "测试文字"}
                          for i, r in enumerate(["cover", "ending"])]}
        self.s.create_deck(plan, "用户要求", "agent")
        with self.s.wb._connection() as db:
            design = json.loads(self.s._deck_row(db)["plan"])["design"]
        self.assertEqual(design["accent"], "#AA0000")
        self.assertEqual(design["secondary"], "#00AA00")
        self.assertEqual(design["background"], "#FFFFFF")
        self.s.set_palette({"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        other = Studio(self.temp.name, "st2")
        other.set_palette({"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        other.create_deck(plan, "用户要求", "agent")
        with other.wb._connection() as db:
            design = json.loads(other._deck_row(db)["plan"])["design"]
        self.assertEqual(design["accent"], "#1F4E9E")


if __name__ == "__main__":
    unittest.main()
