"""Fake-process contract tests, NOT real Claude/Codex model end-to-end tests."""
from pathlib import Path
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ppt_workbench.agent_bridge import diagnose, run_turn, validate_plan
from ppt_workbench.core import EngineError


class PlanValidationTests(unittest.TestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(EngineError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def test_open_questions_and_optional_choices_match_wire_schema(self):
        from ppt_workbench.agent_bridge import WIRE_SCHEMA
        choices_schema=WIRE_SCHEMA['properties']['questions']['items']['properties']['choices']
        self.assertEqual(choices_schema['minItems'],0)
        self.assertEqual(choices_schema['maxItems'],6)
        for count in (0,1,6):
            choices=[str(i) for i in range(count)]
            plan={'reply':'请提供公司 Logo 原图。','questions':[{'question':'请上传公司 Logo。','choices':choices}],'actions':[]}
            self.assertEqual(validate_plan(plan)['questions'],plan['questions'])

    def test_invalid_questions_have_specific_correctable_error(self):
        for choices in (None,'上传',[str(i) for i in range(7)],['']):
            with self.subTest(choices=choices):
                self.assert_code('INVALID_AGENT_QUESTION',validate_plan,{'reply':'需要 Logo','actions':[],
                    'questions':[{'question':'请提供 Logo','choices':choices}]})

    def test_scene_objects_protocol(self):
        action = {"type": "scene_objects", "slide_id": "S001", "base_scene_revision": 1,
                  "operations": [{"op": "add", "object": {"id": "new"}},
                                 {"op": "reorder", "objectId": "new", "index": 0},
                                 {"op": "delete", "objectId": "new"}]}
        self.assertEqual(validate_plan({"reply": "ok", "actions": [action]})["actions"], [action])
        for operations in ([], [{"op": "reorder", "objectId": "x", "index": True}],
                           [{"op": "delete", "objectId": "x", "index": 0}], [{"op": "unknown"}]):
            self.assert_code("INVALID_AGENT_OUTPUT", validate_plan,
                             {"reply": "x", "actions": [action | {"operations": operations}]})

    def test_human_review_is_not_a_generation_action(self):
        self.assert_code("INVALID_AGENT_OUTPUT", validate_plan, {
            "reply": "声称用户认可", "actions": [{"type": "review", "kind": "visual"}]})
        self.assert_code("INVALID_AGENT_OUTPUT", validate_plan, {
            "reply": "修改受保护字段", "actions": [{"type": "slide_patch", "slide_id": "S001", "base_revision": 1,
            "changes": [{"path": "/contentStatus", "value": "confirmed"}]}]})

    def test_one_slide_limit_is_checked_before_engine_application(self):
        action = {"type": "slide_patch", "slide_id": "S001", "base_revision": 1,
                  "changes": [{"path": "/title", "value": "标题"}]}
        self.assert_code("INVALID_AGENT_OUTPUT", validate_plan, {
            "reply": "修改两页", "actions": [action, {**action, "slide_id": "S002"}]})
        self.assert_code("INVALID_AGENT_OUTPUT", validate_plan, {
            "reply": "新建后再修改旧页", "actions": [action, {
                "type": "slide_add", "title": "新页", "user_intent": "用户的内容", "role": "content"}]})

    def test_project_update_and_one_page_are_allowed(self):
        plan = {"reply": "根据你的内容补齐项目用途并新建一页。", "actions": [
            {"type": "project_update", "changes": {"purpose": "report", "logoPolicy": "none"}},
            {"type": "slide_add", "title": "工作进度", "user_intent": "用户给出的进度材料", "role": "content"}],
            "questions": [{"question": "这一页主要面向谁？", "choices": ["管理层", "项目成员"]}]}
        result = validate_plan(plan)
        self.assertEqual(result, plan)
        self.assertIsNot(result["actions"], plan["actions"])

    def test_project_enum_values_are_normalized(self):
        # Model wording is mapped into the allowed enums instead of failing
        # the whole plan at project update time.
        result = validate_plan({"reply": "x", "actions": [
            {"type": "project_update", "changes": {"purpose": "产品介绍"}}]})
        self.assertEqual(result["actions"][0]["changes"]["purpose"], "proposal")
        result = validate_plan({"reply": "x", "actions": [
            {"type": "project_update", "changes": {"purpose": "公司战略宣讲材料", "logoPolicy": "企业标识", "dataPolicy": "内部"}}]})
        changes = result["actions"][0]["changes"]
        self.assertEqual(changes["purpose"], "other")
        self.assertEqual(changes["purposeOther"], "公司战略宣讲材料")
        self.assertEqual(changes["logoPolicy"], "undecided")
        self.assertEqual(changes["dataPolicy"], "undecided")
        # Explicit purposeOther is not overwritten by a recognisable purpose.
        result = validate_plan({"reply": "x", "actions": [
            {"type": "project_update", "changes": {"purpose": "季度汇报", "purposeOther": "自定义说明"}}]})
        self.assertEqual(result["actions"][0]["changes"]["purpose"], "report")
        self.assertEqual(result["actions"][0]["changes"]["purposeOther"], "自定义说明")

    def test_bad_types_unknown_fields_and_nonfinite_values_fail_cleanly(self):
        invalid = [
            {"reply": "x", "actions": [{"type": []}]},
            {"reply": "x", "actions": [], "approved": True},
            {"reply": "x", "actions": [{"type": "project_update", "changes": {"password": "x"}}]},
            {"reply": "x", "actions": [{"type": "scene_patch", "slide_id": "S001", "base_scene_revision": True,
                "changes": [{"objectId": "title", "properties": {"x": 2}}]}]},
            {"reply": "x", "actions": [{"type": "slide_patch", "slide_id": "S001", "base_revision": 1,
                "changes": [{"path": [], "value": "x"}]}]},
            {"reply": "x", "actions": [{"type": "scene_replace", "slide_id": "S001", "base_revision": 1,
                "scene": {"x": float("nan")}}]},
        ]
        for plan in invalid:
            with self.subTest(plan=plan):
                self.assert_code("INVALID_AGENT_OUTPUT", validate_plan, plan)

    def test_manual_mode_never_launches_cli(self):
        with patch("ppt_workbench.agent_bridge.subprocess.Popen") as launch:
            self.assertTrue(diagnose("manual")["available"])
            self.assert_code("MANUAL_MODE", run_turn, "manual", "标题缩短", {})
        launch.assert_not_called()

    def test_missing_binary_is_reported_truthfully(self):
        with patch("ppt_workbench.agent_bridge.shutil.which", return_value=None):
            status = diagnose("claude")
            self.assertFalse(status["available"])
            self.assertEqual(status["status"], "not_installed")
            self.assert_code("AGENT_NOT_INSTALLED", run_turn, "claude", "开始", {})

    def test_outline_mode_is_local_and_never_launches_a_cli(self):
        with patch("ppt_workbench.agent_bridge.subprocess.Popen") as launch:
            status = diagnose("outline")
            self.assertTrue(status["available"])
            self.assertIsNone(status["executable"])
            self.assertEqual(status["status"], "outline")
            self.assertIn("不调用模型", status["message"])
            self.assert_code("OUTLINE_MODE", run_turn, "outline", "开始", {})
        launch.assert_not_called()

    def test_whole_deck_plan_saves_only_one_plan_and_may_update_brief(self):
        deck = {"type": "deck_start", "title": "真实项目介绍", "execution": "agent", "pages": [
            {"title": "封面", "user_intent": "介绍这个项目", "role": "cover"},
            {"title": "能力", "user_intent": "用户提供的能力说明", "role": "content", "key_points": "实际材料"}]}
        result = validate_plan({"reply": "计划已提出，将按页生成。", "actions": [
            {"type": "project_update", "changes": {"title": "真实项目介绍"}}, deck]})
        self.assertEqual(len(result["actions"]), 2)
        invalid_actions = [
            [deck, deck],
            [deck, {"type": "slide_add", "title": "额外页", "user_intent": "不能同时生成", "role": "content"}],
            [deck, {"type": "scene_patch", "slide_id": "S001", "base_scene_revision": 1,
                    "changes": [{"objectId": "title", "properties": {"text": "其他页"}}]}],
            [{**deck, "source_message": "模型编造的原话"}],
            [{**deck, "pages": [{**deck["pages"][0], "approved": True}, deck["pages"][1]]}],
        ]
        for actions in invalid_actions:
            with self.subTest(actions=actions):
                self.assert_code("INVALID_AGENT_OUTPUT", validate_plan, {"reply": "测试", "actions": actions})

    def test_deck_feedback_is_dispatch_only_and_cannot_mix_mutations(self):
        batch = {"type": "deck_feedback", "edits": [
            {"slide_id": "S001", "instruction": "标题改为：用户给出的标题", "object_id": "title"},
            {"slide_id": "S004", "instruction": "背景换成白色"}]}
        self.assertEqual(validate_plan({"reply": "将按你的反馈逐页执行。", "actions": [batch]})["actions"], [batch])
        for actions in ([batch, batch], [batch, {"type": "project_update", "changes": {"title": "不应顺手改"}}],
                        [{**batch, "approved": True}],
                        [{**batch, "edits": [batch["edits"][0], batch["edits"][0]]}]):
            with self.subTest(actions=actions):
                self.assert_code("INVALID_AGENT_OUTPUT", validate_plan, {"reply": "测试拒绝", "actions": actions})


@unittest.skipUnless(os.name == "posix", "Fake executables use POSIX shebang scripts")
class AgentBridgeProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ppt-agent-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.capture = self.root / "captured.json"
        self.fake = self.root / "fake-agent"
        self.normal_wire = {"reply": "已缩短当前页标题。", "questions": [], "actions": [
            {"type": "scene_patch", "arguments_json": json.dumps({"slide_id": "S001", "base_scene_revision": 2,
                "changes": [{"objectId": "title", "properties": {"text": "更短标题"}}]}, ensure_ascii=False)}]}

    def program(self, response=None, *, mode="claude", exit_code=0, delay=0, raw=None):
        wire = self.normal_wire if response is None else response
        wrapped = {"type": "result", "is_error": False, "structured_output": wire} if mode == "claude" else wire
        result = json.dumps(wrapped, ensure_ascii=False) if raw is None else raw
        script = f'''#!{sys.executable}
import json, os, pathlib, sys, time
args = sys.argv[1:]
stdin = sys.stdin.read()
record = {{"args": args, "stdin": stdin, "cwd": os.getcwd(),
          "images": [pathlib.Path(args[i + 1]).read_bytes().hex() for i, arg in enumerate(args) if arg == "--image"]}}
if "--output-schema" in args:
    record["schema"] = json.loads(pathlib.Path(args[args.index("--output-schema")+1]).read_text())
pathlib.Path({str(self.capture)!r}).write_text(json.dumps(record), encoding="utf-8")
time.sleep({delay!r})
sys.stderr.write("SECRET_SHOULD_NOT_REACH_UI=confidential\\n")
if "--output-last-message" in args:
    pathlib.Path(args[args.index("--output-last-message")+1]).write_text({result!r}, encoding="utf-8")
else:
    sys.stdout.write({result!r})
sys.exit({exit_code!r})
'''
        self.fake.write_text(script, encoding="utf-8")
        self.fake.chmod(0o700)

    def invoke(self, mode="claude", prompt="将选中的标题改短", timeout=4, context=None):
        with patch("ppt_workbench.agent_bridge.shutil.which", return_value=str(self.fake)):
            return run_turn(mode, prompt, context if context is not None else {"selectedSlideId": "S001", "selectedObjectId": "title"},
                            timeout=timeout, workdir=self.project)

    def assert_clean(self):
        self.assertEqual(list(self.project.iterdir()), [])

    def test_claude_structured_envelope_and_no_shell_interpolation(self):
        self.program()
        marker = self.root / "injected"
        prompt = f'把标题缩短。$(touch {marker}) `touch {marker}`; "ignored"'
        plan = self.invoke(prompt=prompt)
        self.assertEqual(plan["actions"][0]["type"], "scene_patch")
        self.assertEqual(plan["actions"][0]["changes"][0]["properties"]["text"], "更短标题")
        capture = json.loads(self.capture.read_text())
        self.assertFalse(marker.exists())
        self.assertNotIn(prompt, capture["args"])
        self.assertEqual(json.loads(capture["stdin"].split("TASK_DATA_JSON:\n", 1)[1])["user_message"], prompt)
        self.assertEqual(capture["cwd"], str(self.project.resolve()))
        args = capture["args"]
        self.assertIn("--restricted", args)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--permission-prompts") + 1], "none")
        self.assertIn("mcp__*", args)
        self.assertFalse(any("dangerously" in arg or "skip-permissions" in arg for arg in args))
        self.assert_clean()

    def test_open_logo_request_survives_both_cli_protocols(self):
        wire={'reply':'请提供公司 Logo 原图。','questions':[{'question':'请上传 Logo 文件。','choices':[]}],'actions':[]}
        for mode in ('claude','codex'):
            with self.subTest(mode=mode):
                self.program(response=wire,mode=mode)
                self.assertEqual(self.invoke(mode=mode),wire)
                self.assert_clean()

    def test_outline_drafting_guidance_reaches_both_agents(self):
        for mode in ("claude", "codex"):
            with self.subTest(mode=mode):
                self.program(mode=mode)
                outline = "项目计划\n1. 背景\n2. 方案"
                self.invoke(mode=mode, prompt=outline, context={"projectId": "new", "outline": []})
                prompt = json.loads(self.capture.read_text())["stdin"]
                self.assertIn("a pasted outline alone is a request for a complete first draft", prompt)
                self.assertIn("Do not ask for optional content guidance before drafting", prompt)
                self.assertIn("use visible placeholders", prompt)
                self.assertIn("instead of pausing for optional information", prompt)
                self.assertEqual(json.loads(prompt.split("TASK_DATA_JSON:\n", 1)[1])["user_message"], outline)

    def test_codex_schema_file_and_restricted_configuration(self):
        self.program(mode="codex")
        plan = self.invoke(mode="codex")
        self.assertEqual(plan["actions"][0]["slide_id"], "S001")
        capture = json.loads(self.capture.read_text())
        args = capture["args"]
        self.assertEqual(args[0], "exec")
        self.assertEqual(args[-1], "-")
        self.assertIn("--ignore-user-config", args)
        self.assertIn("--ephemeral", args)
        self.assertIn('default_permissions="ppt_plan"', args)
        self.assertIn('project_doc_max_bytes=0', args)
        self.assertIn('features.shell_tool=false', args)
        self.assertIn('features.apps=false', args)
        self.assertIn('web_search="disabled"', args)
        self.assertIn('permissions.ppt_plan.network.enabled=false', args)
        self.assertNotIn("--sandbox", args)
        self.assertNotIn("--ignore-rules", args)
        self.assertFalse(any("dangerously" in arg for arg in args))
        self.assertFalse(capture["schema"]["additionalProperties"])
        self.assertEqual(capture["cwd"], str(self.project.resolve()))
        self.assert_clean()

    def test_codex_stages_selected_images_and_reports_supplied_context(self):
        import hashlib
        self.program(mode="codex")
        aid = "A-" + "a" * 32
        data = b"\x89PNG\r\n\x1a\nimage"
        uploads = self.project / "uploads"
        uploads.mkdir()
        (uploads / (aid + ".png")).write_bytes(data)
        record = {"id": aid, "mime": "image/png", "path": "uploads/" + aid + ".png",
                  "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        context = {"attachments": [{"assetId": aid, "readStatus": "not-inspected"}]}
        with patch("ppt_workbench.agent_bridge.shutil.which", return_value=str(self.fake)):
            run_turn("codex", "参考图片", context, timeout=4, workdir=self.project,
                     selected_ids=[aid], asset_records=[record])
        capture = json.loads(self.capture.read_text())
        self.assertEqual(capture["images"], [data.hex()])
        sent = json.loads(capture["stdin"].split("TASK_DATA_JSON:\n", 1)[1])
        self.assertEqual(sent["context"]["attachments"][0]["readStatus"], "image-supplied")
        self.assertEqual(context["attachments"][0]["readStatus"], "not-inspected")
        self.assertEqual(list(self.project.iterdir()), [uploads])
        (uploads / (aid + ".png")).write_bytes(b"changed")
        with patch("ppt_workbench.agent_bridge.shutil.which", return_value=str(self.fake)):
            with self.assertRaises(EngineError) as raised:
                run_turn("codex", "参考图片", context, timeout=4, workdir=self.project,
                         selected_ids=[aid], asset_records=[record])
        self.assertEqual(raised.exception.code, "INVALID_ATTACHMENTS")
        self.assertEqual(list(self.project.iterdir()), [uploads])

    def test_codex_keeps_model_selection_without_loading_tools(self):
        from ppt_workbench.agent_bridge import _command
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "config.toml").write_text('model="local-model"\nmodel_provider="custom"\n[model_providers.custom]\nname="Local"\nbase_url="http://127.0.0.1:9999/v1"\nwire_api="responses"\n[ mcp_servers.unwanted ]\ncommand="unwanted"\n')
            with patch.dict(os.environ, {"CODEX_HOME": directory}):
                args = _command("codex", "codex", Path(directory), Path("schema.json"), Path("result.json"))
            self.assertIn('model="local-model"', args)
            self.assertIn('model_provider="custom"', args)
            self.assertIn('model_providers.custom.base_url="http://127.0.0.1:9999/v1"', args)
            self.assertIn("--ignore-user-config", args)
            self.assertNotIn("unwanted", " ".join(args))

    def test_weppt_model_override_preserves_global_config(self):
        from ppt_workbench.agent_bridge import _command
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory, "config.toml")
            original = 'model="original-model"\n'
            config.write_text(original)
            with patch.dict(os.environ, {"CODEX_HOME": directory, "WEPPT_CODEX_MODEL": "commandcode-plan/gpt-6.1-terra"}):
                args = _command("codex", "codex", Path(directory), Path("schema.json"), Path("result.json"))
            self.assertIn('model="commandcode-plan/gpt-6.1-terra"', args)
            self.assertEqual(config.read_text(), original)

    def test_nonzero_error_does_not_expose_stderr_or_retry(self):
        self.program(exit_code=17)
        with self.assertRaises(EngineError) as raised:
            self.invoke()
        self.assertEqual(raised.exception.code, "AGENT_FAILED")
        self.assertEqual(raised.exception.details["exitCode"], 17)
        self.assertNotIn("confidential", json.dumps(raised.exception.to_dict()))
        self.assert_clean()

    def test_timeout_returns_without_applying_actions_and_removes_temp_files(self):
        self.program(delay=10)
        start = time.monotonic()
        with self.assertRaises(EngineError) as raised:
            self.invoke(timeout=0.2)
        self.assertEqual(raised.exception.code, "AGENT_TIMEOUT")
        self.assertLess(time.monotonic() - start, 3)
        self.assert_clean()

    def test_claude_missing_structured_output_is_not_treated_as_success(self):
        self.program(raw=json.dumps({"type": "result", "result": "普通自然语言"}))
        with self.assertRaises(EngineError) as raised:
            self.invoke()
        self.assertEqual(raised.exception.code, "INVALID_AGENT_OUTPUT")
        self.assert_clean()

    def test_duplicate_keys_and_markdown_are_not_silently_repaired(self):
        for raw in ['{"reply":"x","reply":"y","actions":[],"questions":[]}',
                    '```json\n{"reply":"x","actions":[],"questions":[]}\n```']:
            self.program(mode="codex", raw=raw)
            with self.subTest(raw=raw), self.assertRaises(EngineError) as raised:
                self.invoke(mode="codex")
            self.assertEqual(raised.exception.code, "INVALID_AGENT_OUTPUT")
            self.assert_clean()

    def test_wire_arguments_cannot_override_action_type(self):
        wire = {"reply": "x", "questions": [], "actions": [{
            "type": "project_update", "arguments_json": '{"type":"review","changes":{"title":"x"}}'}]}
        self.program(response=wire)
        with self.assertRaises(EngineError) as raised:
            self.invoke()
        self.assertEqual(raised.exception.code, "INVALID_AGENT_OUTPUT")
        self.assert_clean()

    def test_real_process_contract_accepts_deck_plan_without_direct_page_writes(self):
        body = {"title": "项目介绍", "execution": "agent", "pages": [
            {"title": "封面", "user_intent": "项目主题", "role": "cover"},
            {"title": "功能", "user_intent": "用户提供功能资料", "role": "content"}]}
        wire = {"reply": "已提出逐页计划。", "questions": [], "actions": [
            {"type": "deck_start", "arguments_json": json.dumps(body, ensure_ascii=False)}]}
        self.program(response=wire, mode="codex")
        plan = self.invoke(mode="codex", context={"projectId": "intro", "outline": []})
        self.assertEqual(plan["actions"], [{"type": "deck_start", **body}])
        captured = json.loads(self.capture.read_text())
        self.assertIn("deck_start", captured["schema"]["properties"]["actions"]["items"]["properties"]["type"]["enum"])
        self.assert_clean()

    def test_deck_page_context_rejects_different_page_and_keeps_questions(self):
        context = {"generationTask": {"kind": "deck_page", "deckId": "D-test", "pageIndex": 0},
                   "currentDeckPage": {"title": "已确定的标题", "role": "cover"}}
        body = {"title": "另一个标题", "role": "cover", "user_intent": "用户提供的主题"}
        wire = {"reply": "本页", "questions": [], "actions": [
            {"type": "slide_add", "arguments_json": json.dumps(body)}]}
        self.program(response=wire)
        with self.assertRaises(EngineError) as caught:
            self.invoke(context=context)
        self.assertEqual(caught.exception.code, "DECK_PAGE_SCOPE_MISMATCH")
        body["title"] = context["currentDeckPage"]["title"]
        wire["actions"][0]["arguments_json"] = json.dumps(body)
        self.program(response=wire)
        self.assertEqual(self.invoke(context=context)["actions"][0]["title"], "已确定的标题")
        self.program()
        with self.assertRaises(EngineError) as caught:
            self.invoke(context=context)
        self.assertEqual(caught.exception.code, "DECK_PAGE_PLAN_REQUIRED")
        question_wire = {"reply": "这页缺少项目名称，请补充。", "actions": [], "questions": [
            {"question": "使用哪个名称？", "choices": ["正式项目名", "内部暂定名"]}]}
        self.program(response=question_wire)
        self.assertEqual(self.invoke(context=context), question_wire)
        self.assert_clean()

    def test_feedback_image_generation_requires_bound_page_and_no_object_scope(self):
        body = {"slide_id": "S003", "base_scene_revision": 4, "images": [
            {"object_id": "new-image", "prompt": "test image", "x": 10, "y": 10, "w": 20, "h": 20}]}
        wire = {"reply": "生成中", "questions": [], "actions": [
            {"type": "image_generate", "arguments_json": json.dumps(body)}]}
        self.program(response=wire, mode="codex")
        child = {"generationTask": {"kind": "feedback_page"}, "currentFeedback": {"slideId": "S003"}}
        self.assertEqual(self.invoke(mode="codex", context=child)["actions"][0]["slide_id"], "S003")
        child["currentFeedback"]["slideId"] = "S002"
        with self.assertRaises(EngineError) as caught:
            self.invoke(mode="codex", context=child)
        self.assertEqual(caught.exception.code, "FEEDBACK_SCOPE_MISMATCH")
        child["currentFeedback"] = {"slideId": "S003", "objectId": "title"}
        with self.assertRaises(EngineError) as caught:
            self.invoke(mode="codex", context=child)
        self.assertEqual(caught.exception.code, "FEEDBACK_SCOPE_MISMATCH")

    def test_feedback_plan_roundtrip_and_child_scope_use_real_process_contract(self):
        body = {"edits": [{"slide_id": "S001", "instruction": "修改测试标题", "object_id": "title"},
                          {"slide_id": "S002", "instruction": "修改测试正文"}]}
        wire = {"reply": "将分派这两页。", "questions": [], "actions": [
            {"type": "deck_feedback", "arguments_json": json.dumps(body)}]}
        self.program(response=wire, mode="codex")
        self.assertEqual(self.invoke(mode="codex", context={"deliveryTask": {"scope": "deck"}})["actions"],
                         [{"type": "deck_feedback", **body}])
        child = {"generationTask": {"kind": "feedback_page"}, "currentFeedback": {"slideId": "S001", "objectId": "title"}}
        with self.assertRaises(EngineError) as caught:
            self.invoke(mode="codex", context=child)
        self.assertEqual(caught.exception.code, "FEEDBACK_SCOPE_MISMATCH")
        self.program()
        self.assertEqual(self.invoke(context=child)["actions"][0]["slide_id"], "S001")
        child["currentFeedback"]["objectId"] = "body-1"
        with self.assertRaises(EngineError) as caught:
            self.invoke(context=child)
        self.assertEqual(caught.exception.code, "FEEDBACK_SCOPE_MISMATCH")
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
