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

    def test_restyle_one_page_with_style_reference(self):
        from ppt_workbench import template_adaptation as adaptation
        tid = self.upload3()["id"]
        self.s.demo()
        before = self.s.get_scene("S001")
        self.s.set_agent_mode("api")
        binding = {"id": "x", "label": "L", "mode": "api", "model": "m"}
        self.error("STYLE_NOT_ANALYZED", adaptation.propose, self.s, "style-" + tid, "S001", before["sceneRevision"])
        ut.update_style(self.s, tid, profile=PROFILE)
        same = json.loads(json.dumps(before["scene"]))
        same["background"] = "#FAFAFA"  # Same geometry: a style restyle may keep the structure.
        calls = []
        def run(*a, **kw):
            calls.append((a, kw))
            if a[2].get("generationTask", {}).get("kind") == "design_loop_review":
                return {"reply": "PASS\nok", "actions": []}
            return {"reply": "done", "actions": [{"type": "scene_replace", "slide_id": "S001",
                    "base_revision": before["contentRevision"], "scene": same}]}
        png = Path(self.temp.name) / "r.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n")
        with patch("ppt_workbench.model_profiles.selected", return_value=binding), \
             patch("ppt_workbench.model_profiles.resolve", return_value={**binding, "vision": False}), \
             patch("ppt_workbench.agent_bridge.run_turn", side_effect=run), \
             patch("ppt_workbench.design_review.render_candidate", return_value=(png, {"fontsReady": True, "overflow": []})):
            proposal = adaptation.propose(self.s, "style-" + tid, "S001", before["sceneRevision"])
        context, prompt = calls[0][0][2], calls[0][0][1]
        self.assertEqual(context["styleReference"]["profile"], PROFILE)
        self.assertEqual(context["referenceReadMode"], "profile-only")  # Non-vision models still restyle from the profile.
        self.assertNotIn("preview_png", calls[0][1])
        self.assertIn("对标风格重做本页", prompt)
        self.assertNotIn("构图基本未变的方案会被退回", prompt)
        self.assertEqual(proposal["scene"]["templateId"], "custom")
        adaptation.apply(self.s, proposal["proposalId"])
        self.assertIsNone(self.s.selected_template())
        self.assertEqual(self.s.get_scene("S001")["scene"]["background"], "#FAFAFA")

    def test_one_to_three_references_and_originals(self):
        for files in ([], [file()] * 4):
            self.error("INVALID_UPLOAD", ut.upload, self.s, "style", files)
        for count in (1, 2, 3):
            with patch("ppt_workbench.design_review.render_candidate", side_effect=EngineError("DESIGN_RENDER_UNAVAILABLE", "no")):
                template = ut.upload(self.s, "style", [file()] * count)["templates"][0]
            self.assertEqual(len(template['previews']), count)
            path, _ = ut.image(self.s, template['id'], 0)
            self.assertEqual((path.parent / 'original-1.png').read_bytes(), base64.b64decode(PNG))

    def test_spatial_observation_is_preserved_and_validated(self):
        profile = {**PROFILE, 'spatial': {'observation': '标题遮挡图片', 'estimates': '标题约占上方三分之一', 'reproduction': '前景主体与后景文字分层'}}
        self.assertEqual(ut.validate_profile(profile), profile)
        profile['spatial'] = {'observation': ['bad']}
        self.error('INVALID_STYLE_PROFILE', ut.validate_profile, profile)

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

    def test_invalid_field_is_named_without_dropping_extra_colours(self):
        profile = json.loads(json.dumps(PROFILE))
        profile['color']['secondary'] = ['#112233', '#223344', '#334455']
        self.assertIsNone(ut.parse_profile_reply(json.dumps(profile)))
        self.assertEqual(ut.profile_errors(json.dumps(profile)), ['color.secondary: hexlist'])

    def test_api_analysis_uses_read_only_profile_without_edit_envelope(self):
        from unittest.mock import MagicMock
        from ppt_workbench.api_model_provider import run_api_turn
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(PROFILE)}}]}).encode()
        profile={'model':'deepseek-flash','key_env':'TEST_KEY','base_url':'https://api.deepseek.com','vision':True}
        with patch.dict('os.environ',{'TEST_KEY':'sentinel'}),patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            result=run_api_turn(ut.ANALYZE_PROMPT,{'generationTask':{'kind':'style_analysis'}},profile,30)
            self.assertEqual(ut.parse_profile_reply(result['reply']),PROFILE)
            self.assertEqual(result['actions'],[])
            sent=json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertEqual(sent['reasoning_effort'],'low')
            self.assertNotIn('arguments_json',sent['messages'][0]['content'])
            response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(PROFILE),'tool_calls':[{}]}}]}).encode()
            with self.assertRaises(EngineError):run_api_turn('',{'generationTask':{'kind':'style_analysis'}},profile,30)

    def test_malformed_model_envelope_retries_once_and_records_failure(self):
        tid=self.upload3()['id'];self.s.set_agent_mode('codex')
        with patch('ppt_workbench.agent_bridge.run_turn',side_effect=[EngineError('INVALID_AGENT_OUTPUT','bad JSON'),{'reply':json.dumps(PROFILE),'actions':[]}]) as run:
            result=ut.analyze_style(self.s,tid)
        self.assertEqual(run.call_count,2)
        self.assertEqual(result['template']['profile'],PROFILE)
        files=list((self.s.wb.project_dir(self.s.project_id)/'style-analysis'/tid).glob('*attempt*.json'))
        self.assertEqual(len(files),2)
        self.assertTrue(any('error' in json.loads(p.read_text()) for p in files))

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
