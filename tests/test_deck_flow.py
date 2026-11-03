"""Whole-deck state-machine checks with real SQLite and real rendered scenes.

Outline fixtures are explicitly local supplied-text rendering. Patched model
plans test the adapter contract only and are never presented as live model/UI
acceptance.
"""
from pathlib import Path
import base64
import copy
import tempfile
import unittest
from unittest.mock import patch

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio


def fixture_plan(count=3, execution="outline"):
    roles = ["cover"] + ["content"] * (count - 2) + ["ending"]
    return {"title": "明确标注的整稿测试", "execution": execution,
        "pages": [{"title": f"测试第 {i + 1} 页", "user_intent": f"该页计划摘要 {i + 1}", "role": role,
                   "template_id": role if role in {"cover", "ending"} else "claim-proof",
                   "takeaway": f"测试核心表达 {i + 1}", "key_points": "用户提供的测试文字\n不代表真实业务事实"}
                  for i, role in enumerate(roles)]}


class DeckFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ppt-deck-flow-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(self.root, "deck")
        self.source = "用户的原始要求：这是测试整稿，请使用我已给出的逐页测试文字，保留原话。"

    def error(self, code, func, *args, **kwargs):
        with self.assertRaises(EngineError) as raised:
            func(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def start(self, count=3, execution="outline"):
        return self.studio.create_deck(fixture_plan(count, execution), self.source, execution)

    def finish(self):
        for _ in range(35):
            if not self.studio.run_pending():
                break
        else:
            self.fail("Scheduler did not reach a stable state.")
        return self.studio.deck_state()

    def mock_agent_plan(self, mode, prompt, context, **kwargs):
        page = {k: v for k, v in context["currentDeckPage"].items() if k in {"title", "role", "user_intent", "template_id", "takeaway", "key_points"}}
        page["user_intent"] = "模型声称的用户原话：此内容不能成为原话字段"
        return {"reply": "测试替身输出当前页动作，不是实际模型调用。", "actions": [{"type": "slide_add", **page}]}

    def test_agent_deck_recovers_unknown_and_incompatible_templates(self):
        plan = fixture_plan(3, "agent")
        plan["pages"][0]["template_id"] = "parallel-three"
        plan["pages"][1]["template_id"] = "invented-layout"
        plan["pages"][2]["template_id"] = "ending"
        self.studio.create_deck(plan, self.source, "agent")
        from ppt_workbench.templates import catalog
        entries = {entry["id"]: entry for entry in catalog()}
        with self.studio.wb._connection() as db:
            import json
            pages = [json.loads(row[0]) for row in db.execute(
                "SELECT plan FROM studio_deck_pages ORDER BY page_index")]
        for page in pages:
            self.assertIn(page["template_id"], entries)
            self.assertIn(page["role"], entries[page["template_id"]]["roles"])
        self.assertEqual(pages[2]["template_id"], "ending")

    def test_visual_variant_is_accepted_and_generated(self):
        plan = fixture_plan(3)
        plan["pages"][1]["template_id"] = "parallel-three"
        self.studio.create_deck(plan, self.source, "outline")
        state = self.finish()
        self.assertEqual(state["status"], "complete")
        slide = self.studio.wb.get_slide("deck", self.studio.state()["slides"][1]["id"])["slide"]
        self.assertEqual(slide["templateId"], "parallel-three")

    def test_ten_pages_continue_automatically_with_real_previews_and_original_source(self):
        initial = self.start(10)
        self.assertEqual(initial["totalPages"], 10)
        self.assertEqual(initial["completedPages"], 0)
        for completed in range(1, 11):
            self.assertTrue(self.studio.run_pending())
            state = self.studio.state()
            self.assertEqual(state["deck"]["completedPages"], completed)
            self.assertEqual(len(state["slides"]), completed)
            sid = state["slides"][-1]["id"]
            scene = self.studio.get_scene(sid)
            self.assertTrue(Path(scene["paths"]["preview"]).is_file())
            self.assertIn(f"测试第 {completed} 页", Path(scene["paths"]["preview"]).read_text())
            self.assertEqual(self.studio.wb.get_slide("deck", sid)["slide"]["userIntent"], self.source)
        final = self.studio.deck_state()
        self.assertEqual(final["status"], "complete")
        self.assertIsNotNone(final["initialCompletedAt"])
        self.assertEqual(final["revisionCount"], 0)
        self.assertFalse(final["qualityAccepted"])
        self.assertFalse(self.studio.run_pending())
        exported = self.studio.export("html")
        self.assertEqual(exported["slideCount"], 10)
        self.assertIn("测试第 10 页", Path(exported["path"]).read_text())

    def test_explicit_outline_chat_intake_deduplicates_and_marks_local_execution(self):
        text = "按大纲排版\n# 用户提供的标题\n## 封面｜逐页工作台\n副标题：用户给出的副标题\n## 结束｜从一页开始\n- 用户给出的结束文字"
        job = self.studio.enqueue(text, client_message_id="outline-once")
        self.assertEqual(job["status"], "complete")
        duplicate = self.studio.enqueue(text, client_message_id="outline-once")
        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(duplicate["jobId"], job["jobId"])
        state = self.finish()
        self.assertEqual(state["completedPages"], 2)
        self.assertEqual(state["execution"], "outline")
        messages = self.studio.state()["messages"]
        self.assertEqual(sum(m["role"] == "user" for m in messages), 1)
        self.assertTrue(any("不调用模型" in m["text"] for m in messages))

    def test_agent_modes_route_explicit_and_bare_outlines_to_agent(self):
        explicit = "按大纲排版\n# 计划\n## 封面｜标题\n介绍\n## 结束｜结尾\n谢谢"
        bare = "项目计划\n1. 背景\n2. 方案\n3. 下一步"
        for mode in ("claude", "codex"):
            for index, text in enumerate((explicit, bare)):
                with self.subTest(mode=mode, text=text):
                    studio = Studio(self.root, f"{mode}-{index}", agent=mode)
                    job = studio.enqueue(text, scope="deck")
                    self.assertEqual(job["status"], "queued")
                    self.assertIsNone(studio.deck_state())
                    self.assertEqual(studio.job(job["jobId"])["payload"]["message"], text)

    def test_agent_cannot_switch_to_deterministic_outline_execution(self):
        from ppt_workbench.outline import parse_outline
        text = "按大纲排版\n# 计划\n## 封面｜标题\n介绍\n## 结束｜结尾\n谢谢"
        studio = Studio(self.root, "agent-outline-guard", agent="codex")
        job = studio.enqueue(text, scope="deck")
        self.error("OUTLINE_MODE_REQUIRED", studio.apply_plan, job["jobId"],
                   {"reply": "计划", "actions": [{"type": "deck_start", **parse_outline(text)}]})
        self.assertIsNone(studio.deck_state())

    def test_pause_resume_prevents_extra_pages_and_reuses_queue(self):
        self.start()
        self.assertTrue(self.studio.run_pending())
        self.studio.control_deck("pause")
        queued_id = self.studio.deck_state()["pages"][1]
        self.assertFalse(self.studio.run_pending())
        self.assertEqual(self.studio.deck_state()["completedPages"], 1)
        self.studio.control_deck("resume")
        self.studio.control_deck("resume")
        final = self.finish()
        self.assertEqual(final["completedPages"], 3)
        self.assertTrue(all(p["attempts"] == 1 for p in final["pages"]))
        self.assertEqual(len(self.studio.state()["slides"]), 3)

    def test_cancel_keeps_completed_pages_and_blocks_partial_deck_export(self):
        self.start()
        self.studio.run_pending()
        sid = self.studio.state()["slides"][0]["id"]
        source = Path(self.studio.get_scene(sid)["paths"]["source"]).read_bytes()
        self.studio.control_deck("cancel")
        self.assertFalse(self.studio.run_pending())
        self.assertEqual(self.studio.deck_state()["status"], "cancelled")
        self.assertEqual(Path(self.studio.get_scene(sid)["paths"]["source"]).read_bytes(), source)
        self.error("DECK_INCOMPLETE", self.studio.export, "html")
        self.assertEqual(self.studio.export("html", sid)["slideCount"], 1)
        self.error("DECK_CANCELLED", self.studio.control_deck, "retry")

    def test_failed_page_rolls_back_and_retry_does_not_duplicate(self):
        self.start()
        with patch("ppt_workbench.studio.scene_from_slide", side_effect=EngineError("TEST_RENDER_FAIL", "测试渲染失败")):
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(self.studio.deck_state()["status"], "blocked")
        self.assertEqual(self.studio.state()["slides"], [])
        self.assertEqual(self.studio.deck_state()["lastError"]["code"], "TEST_RENDER_FAIL")
        self.studio.control_deck("retry")
        final = self.finish()
        self.assertEqual(final["completedPages"], 3)
        self.assertEqual(final["pages"][0]["attempts"], 2)
        self.assertEqual([p["slideId"] for p in final["pages"]], ["S001", "S002", "S003"])

    def test_restart_recovers_in_flight_page_without_recreating_completed_pages(self):
        self.start()
        self.studio.run_pending()
        next_job = self.studio.next_job()["job"]
        with self.studio.wb.atomic() as db:
            db.execute("UPDATE studio_jobs SET status='running' WHERE id=?", (next_job["id"],))
            db.execute("UPDATE studio_deck_pages SET status='running' WHERE job_id=?", (next_job["id"],))
        restarted = Studio(self.root, "deck")
        self.assertEqual(restarted.recover_interrupted_jobs(), 1)
        self.studio = restarted
        final = self.finish()
        self.assertEqual(final["completedPages"], 3)
        self.assertTrue(all(p["attempts"] == 1 for p in final["pages"]))
        self.assertEqual(len(self.studio.state()["slides"]), 3)

    def test_revisions_are_grouped_per_feedback_and_persist_beyond_target(self):
        self.start()
        self.finish()
        sid = self.studio.state()["slides"][0]["id"]
        others = {p["id"]: Path(self.studio.get_scene(p["id"])["paths"]["source"]).read_bytes() for p in self.studio.state()["slides"][1:]}
        for number in range(1, 5):
            job = self.studio.enqueue(f"标题改为：用户第 {number} 次修改", sid, "title", f"feedback-{number}")
            self.assertEqual(job["status"], "complete")
            self.assertEqual(self.studio.deck_state()["revisionCount"], number)
            self.studio.enqueue(f"标题改为：用户第 {number} 次修改", sid, "title", f"feedback-{number}")
            self.assertEqual(self.studio.deck_state()["revisionCount"], number)
        self.studio.set_agent_mode("outline")
        reloaded = Studio(self.root, "deck")
        self.assertEqual(reloaded.agent_mode, "outline")
        result = reloaded.deck_state()
        self.assertEqual(result["revisionCount"], 4)
        self.assertFalse(result["withinRevisionTarget"])
        self.assertFalse(result["qualityAccepted"])
        self.assertTrue(all(r["source"] == "chat" for r in result["revisions"]))
        for other, original in others.items():
            self.assertEqual(Path(self.studio.get_scene(other)["paths"]["source"]).read_bytes(), original)

    def test_feedback_during_initial_generation_is_recorded_and_undo_adds_one(self):
        self.start()
        self.studio.run_pending()
        sid = self.studio.state()["selectedSlideId"]
        self.studio.enqueue("标题改为：初稿期间的用户修改", sid)
        self.assertEqual(self.studio.deck_state()["revisionCount"], 1)
        self.assertEqual(self.studio.deck_state()["revisions"][0]["stage"], "during-initial-draft")
        self.studio.enqueue("撤销上一步", sid)
        self.assertEqual(self.studio.deck_state()["revisionCount"], 2)
        self.assertEqual(self.finish()["revisionCount"], 2)

    def test_outline_unknown_request_is_honest_and_never_stays_queued(self):
        self.studio.set_agent_mode("outline")
        request = self.studio.enqueue("请随机编一套商业数据和客户案例")
        self.assertEqual(request["status"], "complete")
        self.assertEqual(self.studio.state()["slides"], [])
        self.assertIn("不调用模型", self.studio.job(request["jobId"])["result"]["reply"])
        self.assertFalse(self.studio.next_job()["pending"])

    def test_selected_object_undo_cannot_revert_unrelated_objects(self):
        self.start()
        self.finish()
        sid = self.studio.state()["slides"][0]["id"]
        changed = self.studio.enqueue("背景换成白色", sid)
        self.assertEqual(changed["status"], "complete")
        before = self.studio.get_scene(sid)
        attempted = self.studio.enqueue("撤销上一步", sid, "title")
        self.assertEqual(attempted["status"], "failed")
        self.assertEqual(self.studio.job(attempted["jobId"])["result"]["error"]["code"], "SCOPE_VIOLATION")
        self.assertEqual(self.studio.get_scene(sid), before)
        self.assertEqual(self.studio.deck_state()["revisionCount"], 1)

    def test_missing_agent_blocks_deck_but_external_mcp_can_continue(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": False}):
            self.assertFalse(self.studio.run_pending())
        self.assertEqual(self.studio.deck_state()["status"], "blocked")
        self.assertEqual(self.studio.deck_state()["lastError"]["code"], "AGENT_NOT_INSTALLED")
        pending = self.studio.next_job()
        self.assertTrue(pending["pending"])
        self.studio.apply_plan(pending["job"]["id"], self.mock_agent_plan("codex", "", pending["context"]))
        self.assertEqual(self.studio.deck_state()["completedPages"], 1)
        sid = self.studio.state()["slides"][0]["id"]
        self.assertEqual(self.studio.wb.get_slide("deck", sid)["slide"]["userIntent"], self.source)

    def test_agent_plan_contract_runs_once_per_page_and_stops_after_complete(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=self.mock_agent_plan) as calls:
            self.assertEqual(self.finish()["completedPages"], 3)
            self.assertEqual(calls.call_count, 3)
        self.assertEqual(self.studio.deck_state()["revisionCount"], 0)

    def test_cancel_while_model_is_running_rejects_late_result(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        def finish_after_cancel(*args, **kwargs):
            self.studio.control_deck("cancel")
            return self.mock_agent_plan(*args, **kwargs)
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=finish_after_cancel):
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(self.studio.deck_state()["status"], "cancelled")
        self.assertEqual(self.studio.state()["slides"], [])

    def test_malformed_agent_output_retries_without_duplicate_page(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        contexts = []
        def generate(mode, prompt, context, **kwargs):
            contexts.append(context)
            if len(contexts) == 1:
                raise EngineError("INVALID_AGENT_OUTPUT", "Agent 没有返回可解析的完整 JSON。")
            return self.mock_agent_plan(mode, prompt, context, **kwargs)
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=generate):
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[1]["revisionCorrection"]["code"], "INVALID_AGENT_OUTPUT")
        self.assertEqual(len(self.studio.state()["slides"]), 1)
        self.assertEqual(self.studio.deck_state()["completedPages"], 1)

    def test_malformed_agent_output_stops_after_three_calls(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=EngineError("INVALID_AGENT_OUTPUT", "格式错误")) as calls:
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(calls.call_count, 3)
        self.assertEqual(self.studio.state()["slides"], [])
        self.assertEqual(self.studio.deck_state()["status"], "blocked")
        self.assertEqual(self.studio.deck_state()["lastError"]["code"], "INVALID_AGENT_OUTPUT")

    def test_truncated_page_output_gets_one_compact_retry(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        contexts = []
        def generate(mode, prompt, context, **kwargs):
            contexts.append(context)
            if len(contexts) == 1:
                raise EngineError("MODEL_OUTPUT_TRUNCATED", "模型输出被长度限制截断，未应用修改。")
            return self.mock_agent_plan(mode, prompt, context, **kwargs)
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=generate):
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[1]["revisionCorrection"]["code"], "MODEL_OUTPUT_TRUNCATED")
        self.assertIn("紧凑", contexts[1]["revisionCorrection"]["instruction"])
        self.assertEqual(self.studio.deck_state()["completedPages"], 1)

    def test_invalid_composition_in_a_plan_gets_a_correction_retry(self):
        self.studio.set_agent_mode("codex")
        contexts = []
        def plan(mode, prompt, context, **kwargs):
            contexts.append(context)
            if len(contexts) == 1:
                raise EngineError("INVALID_COMPOSITION", "页面关系类型无效：'mosaic'，只能是 hero、parallel 之一。")
            return {"reply": "已改正", "actions": []}
        self.studio.enqueue("把这份大纲做成整稿", scope="deck")
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=plan):
            self.studio.run_pending()
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[1]["revisionCorrection"]["code"], "INVALID_COMPOSITION")
        self.assertIn("mosaic", contexts[1]["revisionCorrection"]["message"])

    def test_repeated_truncation_blocks_after_a_single_retry(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=EngineError("MODEL_OUTPUT_TRUNCATED", "截断")) as calls:
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(self.studio.state()["slides"], [])
        self.assertEqual(self.studio.deck_state()["lastError"]["code"], "MODEL_OUTPUT_TRUNCATED")

    def test_empty_agent_actions_preserve_questions_and_block_for_input(self):
        self.studio.set_agent_mode("codex")
        self.start(execution="agent")
        plan = {"reply": "这一页需要你的真实材料。", "actions": [], "questions": [{"question": "这一页采用哪份材料？", "choices": ["我提供材料", "保留明确占位"]}]}
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", return_value=plan):
            self.assertTrue(self.studio.run_pending())
        self.assertEqual(self.studio.deck_state()["status"], "blocked")
        self.assertEqual(self.studio.deck_state()["lastError"]["code"], "PAGE_NEEDS_INPUT")
        messages = self.studio.state()["messages"]
        self.assertTrue(any("这一页采用哪份材料" in m["text"] for m in messages))
        self.assertEqual(self.studio.state()["slides"], [])

    def block_second_page_for_input(self):
        self.start(execution="agent")
        first = self.studio.next_job()
        self.studio.apply_plan(first["job"]["id"], self.mock_agent_plan("manual", "", first["context"]))
        second = self.studio.next_job()
        self.studio.apply_plan(second["job"]["id"], {"reply": "请补充第二页采用的真实材料。", "actions": [],
            "questions": [{"question": "第二页的结论如何表述？", "choices": ["保留用户给出的表述", "我补充真实材料"]}]})
        self.assertEqual(self.studio.deck_state()["currentPage"], 2)
        question = self.studio.deck_state()["pendingQuestionMessageId"]
        self.assertIsNotNone(question)
        return question

    def test_pending_page_answer_cannot_modify_last_completed_page_and_is_replayed(self):
        question = self.block_second_page_for_input()
        sid = self.studio.state()["slides"][0]["id"]
        old_page = self.studio.wb.get_slide("deck", sid)
        old_scene = self.studio.get_scene(sid)
        answer = "标题改为：这条文字是第二页补充材料，不能用作修改第一页的命令。"
        result = self.studio.enqueue(answer, client_message_id="answer-once", choice_message_id=question)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["deckAnswer"])
        for _ in range(3):
            repeated = self.studio.enqueue(answer, client_message_id="answer-once", choice_message_id=question)
            self.assertTrue(repeated["deduplicated"])
            self.assertEqual(repeated["jobId"], result["jobId"])
        self.assertEqual(self.studio.wb.get_slide("deck", sid), old_page)
        self.assertEqual(self.studio.get_scene(sid), old_scene)
        self.assertEqual(self.studio.deck_state()["pendingAnswerCount"], 1)
        self.assertEqual(self.studio.deck_state()["revisionCount"], 0)
        self.assertFalse(self.studio.next_job()["pending"])
        self.studio.control_deck("retry")
        retry = self.studio.next_job()
        supplement = retry["context"]["currentDeckPage"]["supplementalAnswers"]
        self.assertEqual(len(supplement), 1)
        self.assertEqual(supplement[0]["text"], answer)
        self.assertEqual(supplement[0]["questionMessageId"], question)
        self.assertIsNone(retry["context"]["currentPage"])
        self.studio.apply_plan(retry["job"]["id"], self.mock_agent_plan("manual", "", retry["context"]))
        final_second = self.studio.wb.get_slide("deck", "S002")["slide"]
        self.assertEqual(final_second["userIntent"], self.source)
        self.assertEqual([x["text"] for x in final_second["userInputs"]], [answer])
        self.assertEqual(self.studio.get_scene(sid), old_scene)
        self.assertEqual(self.studio.deck_state()["completedPages"], 2)

    def test_explicit_pending_answer_keeps_attachments_and_survives_restart(self):
        self.block_second_page_for_input()
        asset = self.studio.upload("用户材料.txt", "text/plain", base64.b64encode("用户补充的真实文字".encode()).decode())
        response = self.studio.enqueue("第二页使用我上传的材料。", attachments=[asset["assetId"]], reply_to_deck_page=True)
        self.assertTrue(response["deckAnswer"])
        self.studio = Studio(self.root, "deck")
        self.studio.control_deck("retry")
        next_page = self.studio.next_job()
        self.assertEqual(next_page["context"]["currentDeckPage"]["supplementalAnswers"][0]["attachmentIds"], [asset["assetId"]])
        self.assertEqual(next_page["context"]["attachments"][0]["text"], "用户补充的真实文字")
        self.assertEqual(next_page["job"]["payload"]["slideId"], None)

    def test_old_question_and_explicit_old_page_target_are_rejected(self):
        old_question = self.block_second_page_for_input()
        self.error("QUESTION_SCOPE_MISMATCH", self.studio.enqueue, "不应作为旧页修改", "S001", None, None, None, old_question)
        self.error("STALE_QUESTION", self.studio.enqueue, "不存在的题目", choice_message_id="M-wrong-project-or-message")
        self.studio.control_deck("retry")
        retry = self.studio.next_job()
        self.studio.apply_plan(retry["job"]["id"], {"reply": "第二页还有一个待明确问题。", "actions": [],
            "questions": [{"question": "请确认这一次的问题。", "choices": ["采用新口径", "提供资料"]}]})
        new_question = self.studio.deck_state()["pendingQuestionMessageId"]
        self.assertNotEqual(old_question, new_question)
        self.error("STALE_QUESTION", self.studio.enqueue, "旧题答案", choice_message_id=old_question)
        self.studio.enqueue("采用新口径", choice_message_id=new_question)
        self.studio.control_deck("retry")
        second = self.studio.next_job()
        self.studio.apply_plan(second["job"]["id"], self.mock_agent_plan("manual", "", second["context"]))
        self.error("STALE_QUESTION", self.studio.enqueue, "第二页已经完成的旧题答案", choice_message_id=new_question)
        self.assertEqual(len(self.studio.state()["slides"]), 2)

    def test_plan_is_immutable_and_existing_content_is_never_overwritten(self):
        plan = fixture_plan()
        first = self.studio.create_deck(plan, self.source, "outline")
        again = self.studio.create_deck(plan, self.source, "outline")
        self.assertEqual(first["id"], again["id"])
        changed = copy.deepcopy(plan)
        changed["pages"][0]["title"] = "不能覆盖的新标题"
        self.error("DECK_EXISTS", self.studio.create_deck, changed, self.source, "outline")
        other = Studio(self.root, "existing")
        other.demo()
        self.error("PROJECT_NOT_EMPTY", other.create_deck, plan, self.source, "outline")

    def test_model_cannot_label_invented_plan_as_user_supplied_local_outline(self):
        job = self.studio.enqueue("请基于我的项目说明先提出整稿计划。")
        self.error("OUTLINE_SOURCE_MISMATCH", self.studio.apply_plan, job["jobId"], {
            "reply": "不应采信的模型声明", "actions": [{"type": "deck_start", **fixture_plan()}]})
        self.assertIsNone(self.studio.deck_state())
        self.assertEqual(self.studio.state()["slides"], [])

    def test_deck_task_cannot_modify_a_completed_page(self):
        self.start()
        self.studio.run_pending()
        pending = self.studio.next_job()["job"]
        sid = self.studio.state()["slides"][0]["id"]
        scene = self.studio.get_scene(sid)
        self.error("SCOPE_VIOLATION", self.studio.apply_plan, pending["id"], {"reply": "越界测试", "actions": [{"type": "scene_patch", "slide_id": sid,
            "base_scene_revision": scene["sceneRevision"], "changes": [{"objectId": "title", "properties": {"text": "不应出现"}}]}]})
        self.assertEqual(self.studio.get_scene(sid), scene)

    def test_ordinary_chat_cannot_inject_an_unplanned_page(self):
        self.start()
        self.finish()
        queued = self.studio.enqueue("在这套里额外加一页，不要记录计划变化")
        self.error("SCOPE_VIOLATION", self.studio.apply_plan, queued["jobId"], {
            "reply": "不应新增", "actions": [{"type": "slide_add", **fixture_plan()["pages"][0]}]})
        self.assertEqual(len(self.studio.state()["slides"]), 3)


if __name__ == "__main__":
    unittest.main()
