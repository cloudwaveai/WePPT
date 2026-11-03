"""Derived projects: audience variants and style restyle copies."""
import base64
import json
import tempfile
import unittest
from unittest.mock import patch

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio
from ppt_workbench import derived as mod
from ppt_workbench import user_templates as ut

PROFILE = {"summary": "深色商务风", "ui": {"grid": "12 栏", "whitespace": "留白", "hierarchy": "大标题", "containers": "卡片"},
           "elements": {"shapes": "圆", "lines": "细线", "imagery": "照片", "dataViz": "大数字"},
           "typography": {"title": "粗体", "body": "常规", "accent": "加粗"},
           "color": {"background": "#FFFFFF", "ink": "#111111", "primary": "#AA0000",
                     "secondary": ["#00AA00"], "usage": "主色强调"},
           "designStyle": {"keywords": ["商务", "深色", "大字"], "mood": "沉稳", "pageRhythm": "封面重"},
           "avoid": ["不要渐变", "不要阴影"]}
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"data").decode()


class DeriveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.s = Studio(self.temp.name, "source")
        self.s.demo()
        self.s.set_agent_mode("codex")

    def error(self, code, func, *a, **kw):
        with self.assertRaises(EngineError) as e:
            func(*a, **kw)
        self.assertEqual(e.exception.code, code)

    def test_source_extraction_and_message(self):
        sid = self.s.state()["slides"][0]["id"]
        current = self.s.get_scene(sid)
        scene = current["scene"]
        scene["objects"].insert(0, {"id": "brand-logo", "type": "text", "x": 0, "y": 0,
                                    "w": 10, "h": 10, "text": "LOGO"})
        scene["objects"].append({"id": "arrow", "type": "text", "x": 0, "y": 0,
                                 "w": 10, "h": 10, "text": "→"})
        self.s.put_scene(sid, current["contentRevision"], scene, "测试")
        pages = mod._source_pages(self.s)
        self.assertTrue(len(pages) >= 1)
        self.assertFalse(any("LOGO" in t for t in pages[0]["texts"]))
        self.assertNotIn("→", pages[0]["texts"])
        self.assertEqual(len(pages[0]["texts"]), len(set(pages[0]["texts"])))

    def test_audience_derive_creates_project_and_job(self):
        self.s.set_palette({"primary": "#1F4E9E", "secondary": ["#2BB3C0"]})
        result = mod.derive(self.s, "audience", audience="customer", note="突出移动端")
        target = Studio(self.temp.name, result["projectId"])
        self.assertTrue(result["projectId"].startswith("project-"))
        job = target.job(result["jobId"])
        self.assertEqual(job["status"], "queued")
        payload = job["payload"]
        message = payload["message"]
        self.assertIn("面向有付费意愿的客户", message)
        self.assertIn("报价待补充", message)
        self.assertIn("用户补充要求：突出移动端", message)
        self.assertIn("源稿内容（按页）", message)
        title = self.s.wb.get_project("source")["workspace"]["project"]["title"]
        self.assertIn(f"基于源稿《{title}》", message)
        self.assertEqual(target.state()["project"]["title"], f"{title} · 客户版"[:120])
        self.assertEqual(payload["scope"], "deck")
        self.assertEqual(target.palette()["primary"], "#1F4E9E")
        self.assertEqual(target.state()["derivedFrom"]["projectId"], "source")
        self.assertEqual(target.state()["derivedFrom"]["audienceLabel"], "客户版")
        self.assertIsNone(self.s.state()["derivedFrom"])

    def test_rules_verbatim_per_audience(self):
        for key, (label, rule) in mod.AUDIENCES.items():
            result = mod.derive(self.s, "audience", audience=key)
            target = Studio(self.temp.name, result["projectId"])
            message = target.job(result["jobId"])["payload"]["message"]
            self.assertIn(rule, message)
            self.assertIn(label[:-1], message.split("「")[1])

    def test_busy_and_agent_and_empty(self):
        self.s.enqueue("生成整稿", scope="deck", client_message_id="x1")
        self.error("DERIVE_BUSY", mod.derive, self.s, "audience", audience="customer")
        other = Studio(self.temp.name, "manualp")
        other.demo()
        other.set_agent_mode("manual")
        self.error("AGENT_REQUIRED", mod.derive, other, "audience", audience="customer")
        empty = Studio(self.temp.name, "empty")
        empty.set_agent_mode("codex")
        self.error("DERIVE_EMPTY", mod.derive, empty, "audience", audience="customer")

    def test_restyle_requires_profile_and_copies_style(self):
        with patch("ppt_workbench.design_review.render_candidate",
                   side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
            tid = ut.upload(self.s, "style", [{"filename": f"{i}.png", "mime": "image/png",
                                               "base64": PNG} for i in range(3)])["templates"][0]["id"]
        self.error("STYLE_NOT_ANALYZED", mod.derive, self.s, "restyle", style_id=tid)
        ut.update_style(self.s, tid, "我的风格", PROFILE)
        ut.select_style(self.s, tid)
        result = mod.derive(self.s, "restyle", style_id=tid)
        target = Studio(self.temp.name, result["projectId"])
        message = target.job(result["jobId"])["payload"]["message"]
        self.assertIn("按本项目选定的对标风格「我的风格」", message)
        self.assertIn("保持源稿的页数", message)
        self.assertEqual(ut.selected_style(target)["id"], tid)
        self.assertEqual(target.state()["derivedFrom"]["audienceLabel"], "对标风格")

    def test_too_long_guard(self):
        huge = "很长的内容" * 8000
        sid = self.s.state()["slides"][0]["id"]
        current = self.s.get_scene(sid)
        scene = current["scene"]
        with patch.object(mod, "_source_pages", return_value=[{"index": 1, "id": sid,
                "role": "content", "title": "长页", "texts": [huge], "scene": scene}]):
            self.error("DERIVE_TOO_LONG", mod.derive, self.s, "audience", audience="customer")


if __name__ == "__main__":
    unittest.main()
