"""Real subprocess stdio integration, not only direct Python function calls."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for MCP integration tests")
class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_scene_context_and_chat_round_trip_over_real_stdio(self):
        from mcp import Client, StdioServerParameters
        from ppt_workbench.studio import Studio

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "state"
            pid = "mcp-studio"
            params = StdioServerParameters(command=sys.executable, cwd=temp,
                args=["-m", "ppt_workbench.mcp_server", "--root", str(root)])

            async def call(client, name, arguments):
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result)
                self.assertTrue(result.structured_content["ok"])
                self.assertEqual(json.loads(result.content[0].text), result.structured_content)
                return result.structured_content["data"]

            async with Client(params, read_timeout_seconds=15) as client:
                listed = {tool.name for tool in (await client.list_tools()).tools}
                self.assertTrue({"ppt_scene_generate", "ppt_scene_patch", "ppt_studio_context",
                    "ppt_chat_next", "ppt_chat_respond", "ppt_export"} <= listed)
                await call(client, "ppt_project_create", {"project_id": pid, "brief": {"title": "MCP聊天集成测试"}})
                page = await call(client, "ppt_slide_add", {"project_id": pid, "title": "用户给出的页标题",
                    "user_intent": "我希望这一页说明项目目前的问题"})
                sid = page["slideId"]
                patched = await call(client, "ppt_slide_patch", {"project_id": pid, "slide_id": sid,
                    "base_revision": page["revision"], "changes": [{"path": "/keyPoints", "value": "用户的第一条内容\n用户的第二条内容"}]})
                generated = await call(client, "ppt_scene_generate", {"project_id": pid, "slide_id": sid,
                    "base_revision": patched["revision"]})
                self.assertTrue(Path(generated["paths"]["source"]).is_file())
                self.assertTrue(Path(generated["paths"]["preview"]).is_file())
                context = await call(client, "ppt_studio_context", {"project_id": pid, "slide_id": sid})
                self.assertEqual(context["scene"]["sceneRevision"], generated["sceneRevision"])
                self.assertEqual(context["currentPage"]["slide"]["userIntent"], "我希望这一页说明项目目前的问题")
                direct = await call(client, "ppt_scene_patch", {"project_id": pid, "slide_id": sid,
                    "base_scene_revision": generated["sceneRevision"],
                    "changes": [{"objectId": "title", "properties": {"text": "MCP精确修改后的标题"}}]})
                self.assertGreater(direct["sceneRevision"], generated["sceneRevision"])

                # This is the same durable producer used by the browser. Reading
                # and responding below cross the actual MCP subprocess boundary.
                local = Studio(root, pid, create=False)
                queued = local.enqueue("请只把选中的标题再改成：用户最终指定的标题", sid, "title", "stdio-chat-round")
                pending = await call(client, "ppt_chat_next", {"project_id": pid})
                self.assertTrue(pending["pending"])
                self.assertEqual(pending["job"]["id"], queued["jobId"])
                self.assertEqual(pending["context"]["selectedObjectId"], "title")
                responded = await call(client, "ppt_chat_respond", {"project_id": pid, "job_id": queued["jobId"],
                    "plan": {"reply": "已按你的原话修改选中的标题。", "actions": [{"type": "scene_patch", "slide_id": sid,
                        "base_scene_revision": pending["context"]["scene"]["sceneRevision"],
                        "changes": [{"objectId": "title", "properties": {"text": "用户最终指定的标题"}}]}]}})
                self.assertEqual(responded["slideId"], sid)
                self.assertEqual(local.job(queued["jobId"])["status"], "complete")
                refreshed = await call(client, "ppt_studio_context", {"project_id": pid, "slide_id": sid})
                self.assertEqual(refreshed["currentPage"]["slide"]["title"], "用户最终指定的标题")
                self.assertEqual(refreshed["scene"]["sceneRevision"], responded["sceneRevision"])
                self.assertIn("用户最终指定的标题", Path(refreshed["scene"]["paths"]["preview"]).read_text())
                self.assertFalse((await call(client, "ppt_chat_next", {"project_id": pid}))["pending"])
                exported = await call(client, "ppt_export", {"project_id": pid, "format_name": "html"})
                self.assertTrue(Path(exported["path"]).is_file())
                self.assertIn("用户最终指定的标题", Path(exported["path"]).read_text())

    async def test_state_errors_templates_and_restart_over_stdio(self):
        from mcp import Client, StdioServerParameters

        with tempfile.TemporaryDirectory() as temp:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "ppt_workbench.mcp_server", "--root", str(Path(temp) / "state")],
                cwd=temp,
            )
            async with Client(params, read_timeout_seconds=15) as client:
                listing = await client.list_tools()
                names = {t.name for t in listing.tools}
                self.assertIn("ppt_next_action", names)
                self.assertIn("ppt_release_manifest", names)
                self.assertFalse(any("review" in name or "approve" in name for name in names))
                result = await client.call_tool("ppt_project_create", {
                    "project_id": "mcp-test", "brief": {"title": "明确标记的测试项目"}})
                self.assertFalse(result.is_error, result)
                self.assertTrue(result.structured_content["ok"])
                added = await client.call_tool("ppt_slide_add", {
                    "project_id": "mcp-test", "title": "测试页", "user_intent": "测试专用原话"})
                page = added.structured_content["data"]
                sid, rev = page["slideId"], page["revision"]
                patched = await client.call_tool("ppt_slide_patch", {
                    "project_id": "mcp-test", "slide_id": sid, "base_revision": rev,
                    "changes": [{"path": "/takeaway", "value": "测试拟用表达"}]})
                self.assertFalse(patched.is_error, patched)
                stale = await client.call_tool("ppt_slide_patch", {
                    "project_id": "mcp-test", "slide_id": sid, "base_revision": rev,
                    "changes": [{"path": "/takeaway", "value": "不能覆盖新版本"}]})
                self.assertTrue(stale.is_error)
                self.assertEqual(stale.structured_content["error"]["code"], "STALE_REVISION")
                # The readable JSON and structured result must agree for all clients.
                self.assertEqual(json.loads(stale.content[0].text), stale.structured_content)
                protected = await client.call_tool("ppt_slide_patch", {
                    "project_id": "mcp-test", "slide_id": sid, "base_revision": rev + 1,
                    "changes": [{"path": "/contentStatus", "value": "confirmed"}]})
                self.assertTrue(protected.is_error)
                templates = await client.call_tool("ppt_template_get", {})
                self.assertEqual(len(templates.structured_content["data"]["templates"]), 50)
                self.assertTrue(all(t['id'].startswith('curated-') for t in templates.structured_content['data']['templates']))
                resources = await client.list_resources()
                self.assertTrue(any(str(r.uri) == "ppt://guide" for r in resources.resources))
                blocked = await client.call_tool("ppt_release_manifest", {"project_id": "mcp-test"})
                self.assertTrue(blocked.is_error)
                self.assertEqual(blocked.structured_content["error"]["code"], "RELEASE_GATE_FAILED")
            # A completely new server process must recover the same revision.
            async with Client(params, read_timeout_seconds=15) as client:
                current = await client.call_tool("ppt_slide_get", {"project_id": "mcp-test", "slide_id": sid})
                self.assertEqual(current.structured_content["data"]["revision"], rev + 1)
                self.assertEqual(current.structured_content["data"]["slide"]["userIntent"], "测试专用原话")
                next_step = await client.call_tool("ppt_next_action", {"project_id": "mcp-test", "slide_id": sid})
                self.assertFalse(next_step.is_error, next_step)
                self.assertEqual(next_step.structured_content["data"]["slideId"], sid)
                self.assertLessEqual(len(next_step.structured_content["data"]["questions"]), 3)
                appended = await client.call_tool("ppt_slide_append_input", {
                    "project_id": "mcp-test", "slide_id": sid, "base_revision": rev + 1,
                    "text": "测试专用后续原话", "source_note": "集成测试转录位置"})
                self.assertFalse(appended.is_error, appended)
                html = await client.call_tool("ppt_workspace_export", {
                    "project_id": "mcp-test", "for_html": True})
                html_page = html.structured_content["data"]["slides"][0]
                self.assertIn("测试专用后续原话", html_page["userIntent"])
                self.assertIn("集成测试转录位置", html_page["userIntent"])
                self.assertNotIn("userInputs", html_page)

    async def test_legacy_handshake_can_discover_and_call(self):
        from mcp import Client, StdioServerParameters

        with tempfile.TemporaryDirectory() as temp:
            params = StdioServerParameters(command=sys.executable, cwd=temp,
                args=["-m", "ppt_workbench.mcp_server", "--root", str(Path(temp) / "state")])
            async with Client(params, read_timeout_seconds=15, mode="legacy") as client:
                listing = await client.list_tools()
                self.assertEqual(len(listing.tools), 33)
                result = await client.call_tool("ppt_template_get", {"template_id": "curated-129"})
                self.assertFalse(result.is_error, result)
                self.assertEqual(result.structured_content["data"]["template"]["id"], "curated-129")
                retired = await client.call_tool('ppt_template_get', {'template_id': 'cover'})
                self.assertTrue(retired.is_error)

    async def test_whole_deck_plan_control_and_resume_over_stdio(self):
        from mcp import Client, StdioServerParameters
        with tempfile.TemporaryDirectory() as temp:
            params = StdioServerParameters(command=sys.executable, cwd=temp,
                args=["-m", "ppt_workbench.mcp_server", "--root", str(Path(temp) / "state")])
            async def call(client, name, arguments):
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result)
                return result.structured_content["data"]
            async with Client(params, read_timeout_seconds=15) as client:
                await call(client, "ppt_project_create", {"project_id": "whole", "brief": {"title": "测试稿"}})
                await call(client, "ppt_deck_start", {"project_id": "whole", "source_message": "用户提供两页：标题与正文，只用于测试。",
                    "execution": "outline", "plan": {"title": "测试稿", "pages": [
                        {"title": "封面标题", "user_intent": "第一张是封面", "role": "cover", "key_points": "用户提供的原文"},
                        {"title": "正文标题", "user_intent": "第二张是正文", "role": "content", "key_points": "保留正文内容"}]}})
                paused = await call(client, "ppt_deck_control", {"project_id": "whole", "action": "pause"})
                self.assertEqual(paused["status"], "paused")
                self.assertFalse((await call(client, "ppt_deck_step", {"project_id": "whole"}))["processed"])
            async with Client(params, read_timeout_seconds=15) as client:
                status = await call(client, "ppt_deck_status", {"project_id": "whole"})
                self.assertEqual(status["completedPages"], 0)
                self.assertEqual(status["status"], "paused")
                await call(client, "ppt_deck_control", {"project_id": "whole", "action": "resume"})
                first = await call(client, "ppt_deck_step", {"project_id": "whole"})
                self.assertEqual(first["deck"]["completedPages"], 1)
                last = await call(client, "ppt_deck_step", {"project_id": "whole"})
                self.assertEqual(last["deck"]["status"], "complete")
                self.assertEqual(last["deck"]["completedPages"], 2)
                exported = await call(client, "ppt_export", {"project_id": "whole", "format_name": "html"})
                self.assertIn("正文标题", Path(exported["path"]).read_text())

    async def test_deck_answer_tool_binds_user_words_to_pending_page(self):
        from mcp import Client, StdioServerParameters
        with tempfile.TemporaryDirectory() as temp:
            params = StdioServerParameters(command=sys.executable, cwd=temp,
                args=["-m", "ppt_workbench.mcp_server", "--root", str(Path(temp) / "state")])
            async def call(client, name, arguments):
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result)
                return result.structured_content["data"]
            async with Client(params, read_timeout_seconds=15) as client:
                pid = "answers"
                await call(client, "ppt_project_create", {"project_id": pid})
                pages = [{"title": "第一张测试页", "role": "cover", "user_intent": "用户已有标题"},
                         {"title": "第二张测试页", "role": "content", "user_intent": "需要确认用户观点"}]
                await call(client, "ppt_deck_start", {"project_id": pid, "plan": {"title": "测试稿", "pages": pages},
                    "source_message": "用户需要上述两页测试，第二页先问我。", "execution": "agent"})
                one = await call(client, "ppt_chat_next", {"project_id": pid})
                await call(client, "ppt_chat_respond", {"project_id": pid, "job_id": one["job"]["id"],
                    "plan": {"reply": "第一张测试页完成", "actions": [{"type": "slide_add", **pages[0]}]}})
                two = await call(client, "ppt_chat_next", {"project_id": pid})
                await call(client, "ppt_chat_respond", {"project_id": pid, "job_id": two["job"]["id"],
                    "plan": {"reply": "请选择一个重点。", "actions": [], "questions": [
                        {"question": "强调哪项？", "choices": ["观点", "步骤"]}]}})
                blocked = await call(client, "ppt_deck_status", {"project_id": pid})
                await call(client, "ppt_deck_answer", {"project_id": pid, "text": "用户原话：强调步骤。",
                    "question_message_id": blocked["pendingQuestionMessageId"], "client_message_id": "mcp-answer-once"})
                await call(client, "ppt_deck_control", {"project_id": pid, "action": "retry"})
                pending = await call(client, "ppt_chat_next", {"project_id": pid})
                self.assertIn("用户原话：强调步骤", json.dumps(pending["context"]["currentDeckPage"]["supplementalAnswers"], ensure_ascii=False))
                self.assertEqual((await call(client, "ppt_deck_status", {"project_id": pid}))["revisionCount"], 0)

    async def test_three_round_tools_route_batch_and_keep_measurement_pending(self):
        from mcp import Client, StdioServerParameters
        with tempfile.TemporaryDirectory() as temp:
            params = StdioServerParameters(command=sys.executable, cwd=temp,
                args=["-m", "ppt_workbench.mcp_server", "--root", str(Path(temp) / "state")])
            async def call(client, name, arguments):
                result = await client.call_tool(name, arguments)
                self.assertFalse(result.is_error, result)
                return result.structured_content["data"]
            async with Client(params, read_timeout_seconds=20) as client:
                pid = "round-tools"
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertTrue({"ppt_delivery_submit", "ppt_delivery_status", "ppt_delivery_control", "ppt_quality_check", "ppt_quality_status"} <= names)
                self.assertNotIn("ppt_quality_report", names)
                self.assertFalse(any("review" in name or "approve" in name for name in names))
                await call(client, "ppt_project_create", {"project_id": pid})
                source = "按大纲排版\n# MCP三轮接口测试\n## 封面｜测试封面\n结论：明确测试目的\n这是接口测试文字。\n## 内容｜测试正文\n结论：明确测试范围\n不属于真实UI验收。"
                args = {"project_id": pid, "text": source, "client_message_id": "round-one"}
                await call(client, "ppt_delivery_submit", args)
                duplicate = await call(client, "ppt_delivery_submit", args)
                self.assertTrue(duplicate["deduplicated"])
                for _ in range(2):
                    await call(client, "ppt_deck_step", {"project_id": pid})
                one = await call(client, "ppt_delivery_status", {"project_id": pid})
                self.assertEqual((one["inputCount"], one["outputCount"]), (1, 1))
                await call(client, "ppt_delivery_submit", {"project_id": pid, "text": "整稿修改\n第1页：标题改为：用户指定封面\n第2页：标题改为：用户指定正文", "client_message_id": "round-two"})
                for _ in range(2):
                    await call(client, "ppt_deck_step", {"project_id": pid})
                two = await call(client, "ppt_delivery_status", {"project_id": pid})
                self.assertEqual((two["inputCount"], two["outputCount"]), (2, 2))
                self.assertEqual(set(two["activeRound"]["changedSlideIds"]), {"S001", "S002"})
                quality = await call(client, "ppt_quality_check", {"project_id": pid, "auto_fix": True})
                self.assertFalse(quality["readyToReview"])
                self.assertEqual(len(quality["browser"]["pendingSlideIds"]), 2)
                self.assertFalse(two["targetSatisfied"])
                self.assertEqual((await call(client, "ppt_delivery_status", {"project_id": pid}))["inputCount"], 2)
                exported = await call(client, "ppt_export", {"project_id": pid, "format_name": "html"})
                self.assertIn("用户指定正文", Path(exported["path"]).read_text())


if __name__ == "__main__":
    unittest.main()
