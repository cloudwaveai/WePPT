import copy
"""Round-level acceptance behavior with actual state/scenes, not browser proof."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ppt_workbench.core import EngineError
from ppt_workbench.studio import Studio


OUTLINE = """按大纲排版
# 三轮工作流测试稿
## 封面｜测试封面
结论：只用于程序验收
这些是用户提供的测试内容。
## 内容｜测试第二页
结论：第二页保持独立
保留这段测试文字。
## 内容｜测试第三页
结论：第三页可以被单独修改
不代表真实业务数据。
## 结束｜测试结束页
结论：检查实际生成结果
只用于软件测试。
"""

INTAKE = """用途：内部测试项目介绍
听众：参与验收的项目同事
目标：确认聊天制作与按页修改流程
展示方式：现场讲述
Logo策略：不使用Logo
数据策略：无需外部资料
本稿各页依据要求：无需外部依据
"""


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ppt-delivery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = Studio(self.root, "rounds", agent="outline")

    def drain(self):
        for _ in range(80):
            if not self.s.run_pending():
                return
        self.fail("Work did not settle")

    def initial(self):
        result = self.s.enqueue(OUTLINE, client_message_id="initial", scope="deck")
        self.drain()
        self.measure_all_with_synthetic_fixture()
        return result

    def measure_all_with_synthetic_fixture(self):
        # Explicit server-contract fixture; this is not a real browser result.
        for slide in self.s.state()["slides"]:
            current = self.s.get_scene(slide["id"])
            self.s.record_browser_measurements(slide["id"], current["sceneRevision"], self.synthetic_report(current["scene"]))

    @staticmethod
    def synthetic_report(scene):
        metrics = []
        for obj in scene["objects"]:
            border = 2 * obj.get("strokeWidth", 0) if obj["type"] == "rect" else 0
            w, h = max(0, obj["w"] - border), max(0, obj["h"] - border)
            row = {"objectId": obj["id"], "type": obj["type"], "clientWidth": w, "clientHeight": h, "scrollWidth": w, "scrollHeight": h}
            if obj["type"] == "image":
                row["imageLoaded"] = True
            metrics.append(row)
        return {"schema": "ppt-browser-measurement", "schemaVersion": 1, "slideId": scene["slideId"],
                "width": scene["width"], "height": scene["height"], "fontsReady": True, "imagesLoaded": True,
                "objects": metrics, "overflowIds": []}

    def error(self, code, fn, *args, **kwargs):
        with self.assertRaises(EngineError) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def scenes(self):
        return {p["id"]: self.s.get_scene(p["id"]) for p in self.s.state()["slides"]}

    def test_feedback_image_batch_waits_and_attributes_result(self):
        from ppt_workbench.image_generation import ImageJobs, GeneratedImage
        import base64
        self.initial()
        result = self.s.enqueue("整稿修改\n第3页：生成图片", client_message_id="images", scope="deck")
        with self.s.wb._connection() as db:
            child = db.execute("SELECT job_id FROM studio_feedback_pages WHERE parent_job_id=?", (result["jobId"],)).fetchone()[0]
        scene = self.s.get_scene("S003")
        action = {"type": "image_generate", "slide_id": "S003", "base_scene_revision": scene["sceneRevision"],
                  "images": [{"object_id": "new-image", "prompt": "test", "x": 10, "y": 10, "w": 20, "h": 20}]}
        self.s.apply_plan(child, {"reply": "图片正在生成", "actions": [action]})
        round_id = self.s.job(child)["payload"]["roundId"]
        with self.s.wb._connection() as db:
            self.assertEqual(db.execute("SELECT status FROM studio_delivery_rounds WHERE id=?", (round_id,)).fetchone()[0], "processing")
        class Provider:
            def generate(self, prompt):
                return GeneratedImage(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aM1sAAAAASUVORK5CYII='), 'image/png')
        ImageJobs(self.s).run_batch(child, Provider())
        with self.s.wb._connection() as db:
            row = db.execute("SELECT status,changed_slides FROM studio_delivery_rounds WHERE id=?", (round_id,)).fetchone()
        self.assertNotEqual(row[0], "processing")
        self.assertIn("S003", json.loads(row[1]))
        self.assertTrue(any(o["id"] == "new-image" for o in self.s.get_scene("S003")["scene"]["objects"]))

    def test_continue_skips_failed_image_batch_and_runs_later_feedback(self):
        from ppt_workbench.image_generation import ImageJobs
        self.initial()
        result = self.s.enqueue("整稿修改\n第1页：生成图片\n第3页：标题改为：后续页面", client_message_id="image-fail", scope="deck")
        with self.s.wb._connection() as db:
            children = [r[0] for r in db.execute("SELECT job_id FROM studio_feedback_pages WHERE parent_job_id=? ORDER BY position", (result['jobId'],))]
        original = self.s.get_scene('S001')['scene']
        scene = self.s.get_scene('S001')
        self.s.apply_plan(children[0], {'reply': '图片正在生成', 'actions': [{'type': 'image_generate', 'slide_id': 'S001', 'base_scene_revision': scene['sceneRevision'], 'images': [{'object_id': 'new-image', 'prompt': 'test', 'x': 10, 'y': 10, 'w': 20, 'h': 20}]}]})
        class BadProvider:
            def generate(self, prompt):
                raise RuntimeError('failure')
        ImageJobs(self.s).run_batch(children[0], BadProvider())
        self.assertFalse(self.s.run_pending())
        self.s.enqueue('继续', client_message_id='resume-image', scope='deck')
        self.drain()
        self.assertEqual(self.s.get_scene('S001')['scene'], original)
        self.assertEqual(self.s.wb.get_slide('rounds', 'S003')['slide']['title'], '后续页面')
        with self.s.wb._connection() as db:
            self.assertEqual(db.execute('SELECT status FROM image_generation_batches WHERE id=?', (children[0],)).fetchone()[0], 'failed_skipped')
            self.assertEqual(db.execute('SELECT status FROM studio_delivery_rounds WHERE id=?', (result['roundId'],)).fetchone()[0], 'failed')

    def test_continue_retries_existing_failed_feedback_without_replaying_completed_page(self):
        self.initial()
        result = self.s.enqueue("整稿修改\n第1页：标题改为：已完成\n第3页：标题改为：待继续", client_message_id="interrupted", scope="deck")
        with self.s.wb._connection() as db:
            children = db.execute("SELECT job_id FROM studio_feedback_pages WHERE parent_job_id=? ORDER BY position", (result["jobId"],)).fetchall()
        self.assertTrue(self.s.run_pending())
        self.s.fail_job(children[1][0], EngineError("AGENT_FAILED", "临时失败"))
        revision = self.s.get_scene("S001")["sceneRevision"]
        resumed = self.s.enqueue("继续", client_message_id="resume", scope="deck")
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(self.s.job(children[1][0])["status"], "queued")
        self.drain()
        self.assertEqual(self.s.get_scene("S001")["sceneRevision"], revision)
        self.assertEqual(self.s.wb.get_slide("rounds", "S003")["slide"]["title"], "待继续")
        self.assertTrue(self.s.enqueue("继续", client_message_id="resume", scope="deck")["deduplicated"])

    def test_intent_history_is_scoped_and_survives_short_history_window(self):
        self.initial()
        first = self.s.enqueue("标题改为：第一页决定", "S001", "title", "page-one")
        self.s.enqueue("标题改为：第二页决定", "S002", "title", "page-two")
        for i in range(15):
            self.s.enqueue(f"标题改为：第二页版本{i}", "S002", "title", f"later-{i}")
        current = self.s.enqueue("请调整第一页", "S001", client_message_id="current")
        history = self.s.context(self.s.job(current["jobId"])["payload"])["userIntentHistory"]
        texts = [item["text"] for item in history]
        self.assertIn("标题改为：第一页决定", texts)
        self.assertNotIn("标题改为：第二页决定", texts)
        self.assertIn(OUTLINE, texts)

    def test_three_user_inputs_include_initial_and_batch_edits(self):
        self.initial()
        first = self.s.delivery_state()
        self.assertEqual((first["inputCount"], first["outputCount"]), (1, 1))
        self.assertEqual(first["rounds"][0]["status"], "ready")
        self.assertEqual(len(first["rounds"][0]["changedSlideIds"]), 4)
        before = self.scenes()
        batch = self.s.enqueue("整稿修改\n第1页：标题改为：用户指定封面标题\n第3页：标题改为：用户指定第三页", client_message_id="feedback", scope="deck")
        self.assertTrue(batch["roundId"])
        self.assertEqual(self.s.delivery_state()["inputCount"], 2)
        self.assertEqual(self.s.delivery_state()["outputCount"], 1)
        self.drain()
        self.measure_all_with_synthetic_fixture()
        second = self.s.delivery_state()
        self.assertEqual((second["inputCount"], second["outputCount"]), (2, 2))
        self.assertEqual(set(second["rounds"][-1]["changedSlideIds"]), {"S001", "S003"})
        self.assertEqual(self.s.get_scene("S002"), before["S002"])
        self.assertEqual(self.s.get_scene("S004"), before["S004"])
        self.s.enqueue("标题改为：最后一轮的准确措辞", "S003", "title", "last-input")
        self.measure_all_with_synthetic_fixture()
        final = self.s.delivery_state()
        self.assertEqual((final["inputCount"], final["outputCount"]), (3, 3))
        self.assertTrue(final["withinTarget"])
        self.assertFalse(final["qualityAccepted"])
        self.assertTrue(final["rounds"][0]["snapshotStale"])
        self.assertFalse(final["rounds"][-1]["snapshotStale"])
        self.assertEqual(sum(m.get("isRoundOutput", False) for m in self.s.state()["messages"]), 3)
        self.assertEqual(self.s.export("html")["slideCount"], 4)

    def test_duplicate_send_and_internal_pages_do_not_add_rounds(self):
        first = self.s.enqueue(OUTLINE, client_message_id="one", scope="deck")
        again = self.s.enqueue(OUTLINE, client_message_id="one", scope="deck")
        self.assertTrue(again["deduplicated"])
        self.assertEqual(first["roundId"], again["roundId"])
        self.drain()
        self.s = Studio(self.root, "rounds")
        state = self.s.delivery_state()
        self.assertEqual((state["inputCount"], state["outputCount"]), (1, 1))
        progress = [m for m in self.s.state()["messages"] if m.get("internalProgress")]
        self.assertGreaterEqual(len(progress), 4)
        self.assertFalse(any(m.get("isRoundOutput") for m in progress))

    def test_fourth_input_remains_visible_and_not_falsely_within_target(self):
        self.initial()
        for n in range(2, 5):
            self.s.enqueue(f"标题改为：测试第 {n} 轮", "S001", "title", "input-" + str(n))
        self.s = Studio(self.root, "rounds")
        result = self.s.delivery_state()
        self.assertEqual((result["inputCount"], result["outputCount"]), (4, 4))
        self.assertFalse(result["withinTarget"])
        self.assertNotIn("超过三轮", next(m["text"] for m in self.s.state()["messages"] if m["id"] == result["rounds"][-1]["outputMessageId"]))

    def test_external_scene_change_survives_later_rounds_without_inventing_user_count(self):
        self.initial()
        self.assertTrue(self.s.delivery_state()["interactionAccountingComplete"])
        current = self.s.get_scene("S002")
        self.s.change_scene("S002", current["sceneRevision"], [{"objectId": "title", "properties": {"text": "外部调用明确修改的标题"}}])
        external = self.s.delivery_state()
        self.assertEqual(external["inputCount"], 1)
        self.assertFalse(external["interactionAccountingComplete"])
        self.assertGreater(external["externalChangeCount"], 0)
        events = external["externalChanges"]
        self.s.enqueue("标题改为：第二轮用户明确修改", "S001", "title", "after-external")
        self.s = Studio(self.root, "rounds")
        self.assertEqual(self.s.delivery_state()["externalChanges"], events)
        self.assertFalse(self.s.delivery_state()["targetSatisfied"])

    def test_external_content_only_patch_is_visible_even_before_new_preview(self):
        self.initial()
        page = self.s.wb.get_slide("rounds", "S003")
        self.s.wb.patch_slide("rounds", "S003", page["revision"], [{"path": "/takeaway", "value": "外部CLI补充的文字"}], "外部工具修改")
        state = self.s.delivery_state()
        self.assertEqual(state["inputCount"], 1)
        self.assertEqual(state["externalChanges"][-1]["slideId"], "S003")
        self.assertEqual(state["externalChanges"][-1]["type"], "slide-patched")
        self.assertFalse(state["interactionAccountingComplete"])

    def test_internal_deck_and_batch_mutations_have_round_attribution(self):
        self.initial()
        self.s.enqueue("整稿修改\n第1页：标题改为：明确标题\n第3页：标题改为：另一页明确标题", client_message_id="attributed", scope="deck")
        self.drain()
        state = self.s.delivery_state()
        self.assertTrue(state["interactionAccountingComplete"])
        self.assertEqual(state["externalChangeCount"], 0)

    def test_partial_batch_failure_and_retry_keep_original_baseline_and_count(self):
        self.initial()
        result = self.s.enqueue("整稿修改\n第1页：标题改为：先完成的页\n第3页：标题改为：必须保护旧基准\n第4页：标题改为：等待上一项", client_message_id="batch", scope="deck")
        self.assertTrue(self.s.run_pending())
        third = self.s.get_scene("S003")
        self.s.change_scene("S003", third["sceneRevision"], [{"objectId": "title", "properties": {"text": "并发的较新结果"}}])
        fourth = self.s.get_scene("S004")
        self.drain()
        failed = self.s.delivery_state()
        self.assertEqual(failed["rounds"][-1]["status"], "failed")
        self.assertEqual(failed["rounds"][-1]["error"]["code"], "STALE_REVISION")
        self.assertEqual(self.s.get_scene("S004"), fourth)
        output_id = failed["rounds"][-1]["outputMessageId"]
        self.s.control_delivery("retry", result["roundId"])
        self.drain()
        retried = self.s.delivery_state()
        self.assertEqual((retried["inputCount"], retried["outputCount"]), (2, 2))
        self.assertEqual(retried["rounds"][-1]["outputMessageId"], output_id)
        self.assertEqual(retried["rounds"][-1]["status"], "failed")
        self.assertEqual(self.s.get_scene("S004"), fourth)
        self.assertEqual(self.s.wb.get_slide("rounds", "S003")["slide"]["title"], "并发的较新结果")

    def test_retry_after_transient_error_finishes_same_output_and_round(self):
        self.initial()
        result = self.s.enqueue("整稿修改\n第1页：标题改为：恢复后的明确标题\n第3页：标题改为：继续下一项", client_message_id="batch", scope="deck")
        with patch.object(self.s, "_demo_command", side_effect=EngineError("TEST_TRANSIENT", "临时测试错误")):
            self.s.run_pending()
        failed = self.s.delivery_state()["rounds"][-1]
        self.assertEqual(failed["status"], "failed")
        self.s = Studio(self.root, "rounds")
        self.s.control_delivery("retry", result["roundId"])
        self.drain()
        self.measure_all_with_synthetic_fixture()
        state = self.s.delivery_state()
        self.assertEqual(state["inputCount"], 2)
        self.assertEqual(state["rounds"][-1]["status"], "ready")
        self.assertEqual(state["rounds"][-1]["outputMessageId"], failed["outputMessageId"])
        self.assertEqual(self.s.wb.get_slide("rounds", "S003")["slide"]["title"], "继续下一项")

    def test_feedback_invalid_patch_path_is_corrected_without_partial_mutation(self):
        self.initial();self.s=Studio(self.root,'rounds',agent='codex')
        self.s.enqueue('整稿修改\n第3页：标题换成明确的新标题',client_message_id='invalid-path',scope='deck')
        before=self.s.get_scene('S003');contexts=[]
        from ppt_workbench.agent_bridge import validate_plan
        def run(mode,message,context,**kwargs):
            contexts.append(context)
            if len(contexts)==1:
                return validate_plan({'reply':'修改','actions':[{'type':'slide_patch','slide_id':'S003',
                    'base_revision':before['contentRevision'],'changes':[{'path':'/content/title','value':'明确的新标题'}]}]})
            self.assertEqual(self.s.get_scene('S003'),before)
            return {'reply':'修改','actions':[{'type':'scene_patch','slide_id':'S003',
                'base_scene_revision':before['sceneRevision'],'changes':[{'objectId':'title','properties':{'text':'明确的新标题'}}]}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}),patch('ppt_workbench.agent_bridge.run_turn',side_effect=run):
            self.s.run_pending()
        self.assertEqual(len(contexts),2)
        self.assertIn('/title',contexts[1]['revisionCorrection']['allowedSlidePatchPaths'])
        self.assertEqual(self.s.get_scene('S003')['sceneRevision'],before['sceneRevision']+1)

    def test_invalid_protocol_retry_is_bounded(self):
        self.initial();self.s=Studio(self.root,'rounds',agent='codex')
        j=self.s.enqueue('只改标题','S001',client_message_id='protocol-exhaustion')
        before=self.s.get_scene('S001')
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}),patch('ppt_workbench.agent_bridge.run_turn',side_effect=EngineError('INVALID_AGENT_OUTPUT','错误字段')) as run:
            self.s.run_pending()
        self.assertEqual(run.call_count,3);self.assertEqual(self.s.job(j['jobId'])['status'],'failed')
        self.assertEqual(self.s.get_scene('S001'),before)

    def test_feedback_geometry_error_is_corrected_before_applying_once(self):
        self.initial();self.s=Studio(self.root,'rounds',agent='codex')
        self.s.enqueue('整稿修改\n第3页：改得圆润一些',client_message_id='rounded-feedback',scope='deck')
        before=self.s.get_scene('S003');other=self.s.get_scene('S001');contexts=[]
        def run(mode,message,context,**kwargs):
            contexts.append(context);scene=copy.deepcopy(before['scene'])
            scene['objects'].append({'id':'narrow-accent','type':'rect','x':0,'y':0,'w':5,'h':30,
                                     'fill':'#112233','radius':'round' if len(contexts)==1 else 2.5})
            return {'reply':'调整圆角','actions':[{'type':'scene_replace','slide_id':'S003',
                     'base_revision':before['contentRevision'],'scene':scene}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}),patch('ppt_workbench.agent_bridge.run_turn',side_effect=run):
            self.s.run_pending()
        self.assertEqual(len(contexts),2)
        self.assertEqual(contexts[1]['revisionCorrection']['code'],'INVALID_SCENE')
        self.assertEqual(self.s.get_scene('S003')['sceneRevision'],before['sceneRevision']+1)
        self.assertEqual(self.s.get_scene('S001'),other)

    def test_feedback_geometry_retry_exhaustion_preserves_scene(self):
        self.initial();self.s=Studio(self.root,'rounds',agent='codex')
        self.s.enqueue('整稿修改\n第3页：改得圆润一些',client_message_id='rounded-exhaustion',scope='deck')
        before=self.s.get_scene('S003');child=self.s.next_job()['job'];scene=copy.deepcopy(before['scene'])
        scene['objects'].append({'id':'narrow-accent','type':'rect','x':0,'y':0,'w':5,'h':30,'fill':'#112233','radius':'round'})
        plan={'reply':'调整圆角','actions':[{'type':'scene_replace','slide_id':'S003',
              'base_revision':before['contentRevision'],'scene':scene}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}),patch('ppt_workbench.agent_bridge.run_turn',return_value=plan) as run:
            self.s.run_pending()
        self.assertEqual(run.call_count,3)
        self.assertEqual(self.s.job(child['id'])['status'],'failed')
        self.assertEqual(self.s.get_scene('S003'),before)

    def test_root_question_format_retry_keeps_pages_and_round_count(self):
        self.initial();before=self.scenes()
        self.s=Studio(self.root,'rounds',agent='codex')
        result=self.s.enqueue('补上公司的 Logo',client_message_id='logo-open-question',scope='deck')
        calls=[]
        def run(mode,message,context,**kwargs):
            calls.append(context)
            return {'reply':'请提供公司 Logo 原图。','actions':[],
                    'questions':[{'question':'请上传公司 Logo。','choices':None if len(calls)==1 else []}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}), patch('ppt_workbench.agent_bridge.run_turn',side_effect=run):
            self.s.run_pending()
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1]['revisionCorrection']['code'],'INVALID_AGENT_QUESTION')
        state=self.s.delivery_state()
        self.assertEqual(state['inputCount'],2)
        self.assertEqual(state['rounds'][-1]['id'],result['roundId'])
        self.assertEqual(state['rounds'][-1]['status'],'needs_input')
        self.assertEqual(self.scenes(),before)
        self.assertTrue(any('请上传公司 Logo。' in m['text'] for m in self.s.state()['messages']))

    def test_question_retry_is_bounded_and_never_applies_invalid_plan(self):
        self.initial();before=self.scenes()
        self.s=Studio(self.root,'rounds',agent='codex')
        result=self.s.enqueue('请调整这一页', 'S001', client_message_id='bad-question')
        plan={'reply':'修改','questions':[{'question':'如何处理？','choices':None}],
              'actions':[{'type':'scene_patch','slide_id':'S001','base_scene_revision':self.s.get_scene('S001')['sceneRevision'],
                          'changes':[{'objectId':'title','properties':{'text':'不能应用'}}]}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}), patch('ppt_workbench.agent_bridge.run_turn',return_value=plan) as run:
            self.s.run_pending()
        self.assertEqual(run.call_count,3)
        self.assertEqual(self.s.job(result['jobId'])['status'],'failed')
        self.assertEqual(self.scenes(),before)
        self.assertEqual(self.s.delivery_state()['inputCount'],2)

    def test_all_six_question_choices_are_preserved_in_messages(self):
        self.initial();self.s=Studio(self.root,'rounds',agent='codex')
        result=self.s.enqueue('请让我选择',client_message_id='six-choices',scope='deck')
        choices=[f'方案{i}' for i in range(6)]
        self.s.apply_plan(result['jobId'],{'reply':'请选择','actions':[],
            'questions':[{'question':'选择哪个？','choices':choices}]})
        messages=[m for m in self.s.state()['messages'] if m.get('jobId')==result['jobId'] and m['role']=='assistant']
        self.assertEqual([c['label'] for c in messages[-1]['choices']],choices)

    def test_model_revision_correction_retries_with_original_baselines(self):
        self.initial()
        self.s = Studio(self.root, "rounds", agent="codex")
        page = self.s.get_scene("S003")
        self.s.enqueue("整稿修改\n第3页：更新标题", client_message_id="revision-retry", scope="deck")
        # The explicit batch is dispatched without invoking the model.
        calls = []
        def run(mode, message, context, **kwargs):
            calls.append(context)
            revision = 999 if len(calls) == 1 else page["contentRevision"]
            return {"reply": "更新标题", "actions": [{"type": "slide_patch", "slide_id": "S003",
                    "base_revision": revision, "changes": [{"path": "/title", "value": "修正版本后的标题"}]}]}
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=run):
            self.assertTrue(self.s.run_pending())
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["revisionCorrection"]["field"], "base_revision")
        self.assertEqual(calls[1]["revisionCorrection"]["current"], page["contentRevision"])
        self.assertEqual(self.s.wb.get_slide("rounds", "S003")["slide"]["title"], "修正版本后的标题")

    def test_nested_scene_target_is_corrected_without_cross_page_mutation(self):
        self.initial()
        self.s = Studio(self.root, "rounds", agent="codex")
        self.s.enqueue("整稿修改\n第3页：优化背景", client_message_id="nested-target", scope="deck")
        before=self.s.get_scene('S003');first=self.s.get_scene('S001');contexts=[]
        def run(mode,message,context,**kwargs):
            contexts.append(context)
            scene=copy.deepcopy(before['scene']);scene['background']='#112233'
            scene['slideId']='S001' if len(contexts)==1 else 'S003'
            return {'reply':'优化背景','actions':[{'type':'scene_replace','slide_id':'S003',
                'base_revision':before['contentRevision'],'scene':scene}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}), patch('ppt_workbench.agent_bridge.run_turn',side_effect=run):
            self.s.run_pending()
        self.assertEqual(len(contexts),2)
        self.assertEqual(contexts[1]['revisionCorrection']['current'],'S003')
        self.assertEqual(self.s.get_scene('S001'),first)
        self.assertEqual(self.s.get_scene('S003')['sceneRevision'],before['sceneRevision']+1)

    def test_nested_scene_target_retries_are_bounded(self):
        self.initial()
        self.s = Studio(self.root, "rounds", agent="codex")
        self.s.enqueue("整稿修改\n第3页：优化背景", client_message_id="nested-bounded", scope="deck")
        child=self.s.next_job()['job'];before=self.scenes()
        page=self.s.get_scene('S003');scene=copy.deepcopy(page['scene']);scene['slideId']='S001'
        plan={'reply':'优化背景','actions':[{'type':'scene_replace','slide_id':'S003',
            'base_revision':page['contentRevision'],'scene':scene}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}), patch('ppt_workbench.agent_bridge.run_turn',return_value=plan) as run:
            self.s.run_pending()
        self.assertEqual(run.call_count,3)
        self.assertEqual(self.s.job(child['id'])['status'],'failed')
        self.assertEqual(self.scenes(),before)

    def test_image_target_correction_is_bounded_and_enqueues_only_once(self):
        self.initial()
        self.s = Studio(self.root, "rounds", agent="codex")
        self.s.enqueue("整稿修改\n第3页：生成背景图片", client_message_id="image-target-retry", scope="deck")
        child = self.s.next_job()['job'];before = self.s.get_scene('S003');contexts=[]
        def run(mode, message, context, **kwargs):
            contexts.append(context)
            image={'object_id':'background-new','prompt':'abstract background without words',
                   'x':0,'y':0,'w':1280,'h':720,'placement':'background'}
            if len(contexts)==1:
                image['replace_object_id']='nonexistent-background'
            return {'reply':'生成背景','actions':[{'type':'image_generate','slide_id':'S003',
                'base_scene_revision':before['sceneRevision'],'images':[image]}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}), patch('ppt_workbench.agent_bridge.run_turn',side_effect=run):
            self.assertTrue(self.s.run_pending())
        self.assertEqual(len(contexts),2)
        self.assertEqual(contexts[1]['revisionCorrection']['code'],'IMAGE_INVALID_TARGET')
        self.assertEqual(contexts[1]['revisionCorrection']['details']['objectId'],'nonexistent-background')
        self.assertEqual(self.s.get_scene('S003'),before)
        self.assertEqual(self.s.job(child['id'])['status'],'complete')
        with self.s.wb._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM image_generation_jobs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT status FROM image_generation_batches').fetchone()[0],'pending')

    def test_image_target_repeated_failure_stops_without_starting_generation(self):
        self.initial()
        self.s = Studio(self.root, "rounds", agent="codex")
        self.s.enqueue("整稿修改\n第3页：生成背景图片", client_message_id="image-target-exhausted", scope="deck")
        child=self.s.next_job()['job'];before=self.s.get_scene('S003')
        plan={'reply':'生成背景','actions':[{'type':'image_generate','slide_id':'S003',
            'base_scene_revision':before['sceneRevision'],'images':[{'object_id':'new','replace_object_id':'missing',
                'prompt':'background','x':0,'y':0,'w':1280,'h':720}]}]}
        with patch('ppt_workbench.agent_bridge.diagnose',return_value={'available':True}), patch('ppt_workbench.agent_bridge.run_turn',return_value=plan) as run:
            self.assertTrue(self.s.run_pending())
        self.assertEqual(run.call_count,3)
        self.assertEqual(self.s.job(child['id'])['result']['error']['code'],'IMAGE_INVALID_TARGET')
        self.assertEqual(self.s.get_scene('S003'),before)
        with self.s.wb._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM image_generation_jobs').fetchone()[0],0)

    def test_model_revision_retry_is_bounded_and_real_conflicts_never_retry(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict):
                self.initial() if not self.s.state()["slides"] else None
                self.s = Studio(self.root, "rounds", agent="codex")
                request = self.s.enqueue("整稿修改\n第3页：更新标题", client_message_id="bounded-" + str(conflict), scope="deck")
                child = self.s.next_job()["job"]
                before = self.s.get_scene("S003")
                if conflict:
                    self.s.change_scene("S003", before["sceneRevision"], [{"objectId": "title", "properties": {"text": "并发修改"}}])
                plan = {"reply": "修改", "actions": [{"type": "scene_patch", "slide_id": "S003",
                        "base_scene_revision": 999, "changes": [{"objectId": "title", "properties": {"text": "错误计划"}}]}]}
                with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", return_value=plan) as run:
                    self.assertTrue(self.s.run_pending())
                self.assertEqual(run.call_count, 1 if conflict else 3)
                self.assertEqual(self.s.job(child["id"])["status"], "failed")
                self.assertEqual(self.s.job(child["id"])["result"]["error"]["code"], "STALE_REVISION")
                if not conflict:
                    self.assertEqual(self.s.get_scene("S003"), before)

    def test_revision_retry_stops_if_target_changes_between_attempts(self):
        self.initial()
        self.s = Studio(self.root, "rounds", agent="codex")
        self.s.enqueue("整稿修改\n第3页：更新标题", client_message_id="retry-race", scope="deck")
        child = self.s.next_job()["job"]
        before = self.s.get_scene("S003")
        calls = []
        def run(mode, message, context, **kwargs):
            calls.append(context)
            if len(calls) == 2:
                self.s.change_scene("S003", before["sceneRevision"], [{"objectId": "title", "properties": {"text": "并发修改"}}])
            return {"reply": "修改", "actions": [{"type": "scene_patch", "slide_id": "S003",
                    "base_scene_revision": 999 if len(calls) == 1 else before["sceneRevision"],
                    "changes": [{"objectId": "title", "properties": {"text": "模型修改"}}]}]}
        with patch("ppt_workbench.agent_bridge.diagnose", return_value={"available": True}), patch("ppt_workbench.agent_bridge.run_turn", side_effect=run):
            self.s.run_pending()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["revisionCorrection"]["field"], "base_scene_revision")
        self.assertEqual(self.s.job(child["id"])["result"]["error"]["code"], "STALE_REVISION")
        self.assertEqual(self.s.wb.get_slide("rounds", "S003")["slide"]["title"], "并发修改")

    def test_child_cannot_change_an_unassigned_page(self):
        self.initial()
        self.s.enqueue("整稿修改\n第1页：标题改为：只允许第一页", client_message_id="scope", scope="deck")
        child = self.s.next_job()["job"]
        original = self.scenes()
        plan = {"reply": "错误的测试提议", "actions": [{"type": "scene_patch", "slide_id": "S002", "base_scene_revision": original["S002"]["sceneRevision"],
                "changes": [{"objectId": "title", "properties": {"text": "越界"}}]}]}
        self.error("SCOPE_VIOLATION", self.s.apply_plan, child["id"], plan)
        self.assertEqual(self.scenes(), original)

    def test_invalid_batch_target_rolls_back_entire_dispatch(self):
        self.initial()
        self.s.set_agent_mode("manual")
        job = self.s.enqueue("这一轮给执行器的测试反馈。", client_message_id="invalid-target", scope="deck")
        before = self.scenes()
        self.error("FEEDBACK_PAGE_NOT_FOUND", self.s.apply_plan, job["jobId"], {"reply": "包含错误目标的测试计划", "actions": [
            {"type": "deck_feedback", "edits": [{"slide_id": "S001", "instruction": "标题改为：不应先改"}, {"slide_id": "S999", "instruction": "不存在的目标"}]}]})
        self.assertEqual(before, self.scenes())
        with self.s.wb._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM studio_feedback_pages WHERE parent_job_id=?", (job["jobId"],)).fetchone()[0], 0)

    def test_cancel_rejects_late_child_result_without_extra_round(self):
        self.initial()
        result = self.s.enqueue("整稿修改\n第1页：标题改为：取消后不能写入", client_message_id="cancel", scope="deck")
        child = self.s.next_job()["job"]
        before = self.s.get_scene("S001")
        self.s.control_delivery("cancel", result["roundId"])
        self.error("JOB_CLOSED", self.s.apply_plan, child["id"], {"reply": "迟到的测试结果", "actions": [{"type": "scene_patch", "slide_id": "S001", "base_scene_revision": before["sceneRevision"],
            "changes": [{"objectId": "title", "properties": {"text": "迟到内容"}}]}]})
        self.assertEqual(self.s.get_scene("S001"), before)
        self.assertEqual(self.s.delivery_state()["inputCount"], 2)
        self.assertEqual(self.s.delivery_state()["rounds"][-1]["status"], "cancelled")

    def test_answer_counts_new_round_and_auto_resume_keeps_prior_page(self):
        self.s.set_agent_mode("manual")
        pages = [{"title": "第一张测试页", "role": "cover", "user_intent": "用户的计划"},
                 {"title": "第二张测试页", "role": "content", "user_intent": "需要先明确的用户观点"}]
        self.s.create_deck({"title": "问答测试", "pages": pages}, "用户需要上述两页，均为测试。", "agent")
        first = self.s.next_job()["job"]
        self.s.apply_plan(first["id"], {"reply": "第一张测试页完成", "actions": [{"type": "slide_add", **pages[0]}]})
        second = self.s.next_job()["job"]
        self.s.apply_plan(second["id"], {"reply": "第二页需要用户选择。", "actions": [], "questions": [{"question": "重点是什么？", "choices": ["流程", "能力"]}]})
        old_page = self.s.get_scene("S001")
        self.assertEqual(self.s.delivery_state()["rounds"][0]["status"], "needs_input")
        qid = self.s.deck_state()["pendingQuestionMessageId"]
        result = self.s.enqueue("用户选择：流程。", client_message_id="answer", choice_message_id=qid, reply_to_deck_page=True, scope="deck", auto_resume=True)
        self.assertEqual(self.s.delivery_state()["inputCount"], 2)
        pending = self.s.next_job()
        self.assertTrue(pending["pending"])
        self.assertEqual(pending["job"]["payload"]["roundId"], result["roundId"])
        self.assertIn("用户选择：流程。", json.dumps(pending["context"]["currentDeckPage"]["supplementalAnswers"], ensure_ascii=False))
        self.s.apply_plan(pending["job"]["id"], {"reply": "第二张测试页完成", "actions": [{"type": "slide_add", **pages[1]}]})
        self.assertEqual(self.s.get_scene("S001"), old_page)
        self.assertEqual((self.s.delivery_state()["inputCount"], self.s.delivery_state()["outputCount"]), (2, 2))

    def test_precise_object_edit_does_not_allow_auto_fixes_to_other_objects(self):
        self.initial()
        before = self.s.get_scene("S001")["scene"]
        self.s.enqueue("标题改为：明确的对象修改", "S001", "title", "precise")
        after = self.s.get_scene("S001")["scene"]
        self.assertEqual([o for o in before["objects"] if o["id"] != "title"], [o for o in after["objects"] if o["id"] != "title"])

    def test_without_browser_round_result_is_explicitly_still_checking(self):
        self.s.enqueue(OUTLINE, client_message_id="unmeasured", scope="deck")
        self.drain()
        state = self.s.delivery_state()
        self.assertEqual((state["inputCount"], state["outputCount"]), (1, 1))
        self.assertEqual(state["rounds"][0]["status"], "checking")
        self.assertFalse(state["qualityAccepted"])
        output_id = state["rounds"][0]["outputMessageId"]
        self.measure_all_with_synthetic_fixture()
        measured = self.s.delivery_state()
        self.assertEqual(measured["rounds"][0]["status"], "ready")
        self.assertEqual(measured["rounds"][0]["outputMessageId"], output_id)
        self.assertFalse(measured["qualityAccepted"])

    def test_browser_contract_fix_refreshes_the_same_round_output(self):
        self.s.enqueue(OUTLINE, client_message_id="initial", scope="deck")
        self.drain()
        initial = self.s.delivery_state()["rounds"][0]
        before = self.s.get_scene("S001")
        report = self.synthetic_report(before["scene"])
        # The source-derived cover title has no vertical clearance. Exercise
        # safe enlargement on its body slot, which has space below it.
        next(r for r in report["objects"] if r["objectId"] == "body-1")["scrollHeight"] += 12
        report["overflowIds"] = ["body-1"]
        self.s.record_browser_measurements("S001", before["sceneRevision"], report)
        after = self.s.get_scene("S001")
        self.assertGreater(after["sceneRevision"], before["sceneRevision"])
        self.assertEqual([o["text"] for o in after["scene"]["objects"] if o["type"] == "text"],
                         [o["text"] for o in before["scene"]["objects"] if o["type"] == "text"])
        current = self.s.delivery_state()
        self.assertEqual((current["inputCount"], current["outputCount"]), (1, 1))
        self.assertEqual(current["rounds"][0]["outputMessageId"], initial["outputMessageId"])
        self.assertFalse(current["rounds"][0]["snapshotStale"])
        self.measure_all_with_synthetic_fixture()
        self.assertEqual(self.s.delivery_state()["rounds"][0]["status"], "ready")

    def test_external_mutation_cannot_be_relabelled_as_automatic_round_fix(self):
        self.s.enqueue(OUTLINE, client_message_id="initial", scope="deck")
        self.drain()
        current = self.s.get_scene("S002")
        self.s.change_scene("S002", current["sceneRevision"], [{"objectId": "title", "properties": {"text": "明确的外部修改"}}])
        self.measure_all_with_synthetic_fixture()
        state = self.s.delivery_state()
        self.assertTrue(state["rounds"][0]["snapshotStale"])
        self.assertFalse(state["targetSatisfied"])
        self.assertEqual(state["inputCount"], 1)

    def test_cancelled_failed_batch_cannot_restart_only_one_child(self):
        self.initial()
        batch = self.s.enqueue("整稿修改\n第1页：标题改为：失败后停止\n第3页：标题改为：取消的后续页", client_message_id="cancel-after-error", scope="deck")
        with patch.object(self.s, "_demo_command", side_effect=EngineError("TEST_TRANSIENT", "临时错误")):
            self.s.run_pending()
        self.s.control_delivery("cancel", batch["roundId"])
        before = self.scenes()
        self.error("ROUND_CANCELLED", self.s.control_delivery, "retry", batch["roundId"])
        self.assertFalse(self.s.run_pending())
        self.assertEqual(self.scenes(), before)
        self.assertEqual(self.s.delivery_state()["rounds"][-1]["status"], "cancelled")

    def test_retry_ignores_historical_failed_deck_attempts(self):
        self.s.enqueue(OUTLINE, client_message_id="initial", scope="deck")
        rid = self.s.delivery_state()["rounds"][0]["id"]
        with patch("ppt_workbench.studio.scene_from_slide", side_effect=EngineError("TEST_RENDER_FAIL", "测试渲染失败")):
            self.s.run_pending()
        self.s.control_deck("retry")
        self.drain()
        self.measure_all_with_synthetic_fixture()
        self.assertEqual(self.s.delivery_state()["rounds"][0]["status"], "ready")
        self.error("ROUND_NOT_RETRYABLE", self.s.control_delivery, "retry", rid)
        self.assertFalse(self.s.run_pending())

    def test_feedback_planning_cannot_silently_rebase_after_external_edit(self):
        self.initial()
        self.s.set_agent_mode("manual")
        request = self.s.enqueue("请修改第一页与第三页，这是规划前输入。", client_message_id="planning-baseline", scope="deck")
        current = self.s.get_scene("S003")
        self.s.change_scene("S003", current["sceneRevision"], [{"objectId": "title", "properties": {"text": "规划等待期间的新内容"}}])
        self.error("STALE_REVISION", self.s.apply_plan, request["jobId"], {"reply": "已规划两页反馈", "actions": [
            {"type": "deck_feedback", "edits": [{"slide_id": "S001", "instruction": "标题改为：不应提前应用"},
                                                 {"slide_id": "S003", "instruction": "标题改为：旧反馈不能覆盖"}]}]})
        with self.s.wb._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM studio_feedback_pages WHERE parent_job_id=?", (request["jobId"],)).fetchone()[0], 0)
        self.assertEqual(self.s.wb.get_slide("rounds", "S003")["slide"]["title"], "规划等待期间的新内容")

    def test_content_only_change_after_auto_fix_is_not_absorbed_into_round(self):
        self.s.enqueue(OUTLINE, client_message_id="initial", scope="deck")
        self.drain()
        current = self.s.get_scene("S001")
        report = self.synthetic_report(current["scene"])
        next(r for r in report["objects"] if r["objectId"] == "title")["scrollHeight"] += 12
        report["overflowIds"] = ["title"]
        with patch.object(self.s, "refresh_delivery_quality", return_value=False):
            self.s.record_browser_measurements("S001", current["sceneRevision"], report)
        page = self.s.wb.get_slide("rounds", "S001")
        self.s.wb.patch_slide("rounds", "S001", page["revision"], [{"path": "/keyPoints", "value": "外部刚更新的内容尚未渲染"}])
        self.assertFalse(self.s.refresh_delivery_quality())
        self.assertTrue(self.s.delivery_state()["rounds"][0]["snapshotStale"])

    def test_multi_round_intake_keeps_earlier_user_words_in_new_pages(self):
        self.s.set_agent_mode("manual")
        original = "用户第一轮观点：让用户只需三轮即可制作，原始思想必须保留。"
        first = self.s.enqueue(original, client_message_id="intake-one", scope="deck")
        self.s.apply_plan(first["jobId"], {"reply": "请确定受众。", "actions": [], "questions": [{"question": "给谁看？", "choices": ["内部同事", "客户"]}]})
        second = self.s.enqueue("用户第二轮回答：给内部同事看，按两页介绍。", client_message_id="intake-two", scope="deck")
        pages = [{"title": "用户观点", "role": "cover", "user_intent": "候选页意图", "key_points": original},
                 {"title": "下一步", "role": "ending", "user_intent": "候选结束意图", "key_points": "让内部同事试用"}]
        self.s.apply_plan(second["jobId"], {"reply": "已整理两页计划", "actions": [{"type": "deck_start", "title": "两轮采集测试", "execution": "agent", "pages": pages}]})
        for page in pages:
            pending = self.s.next_job()
            self.assertIn(original, [x["text"] for x in pending["context"]["intakeInputs"]])
            self.s.apply_plan(pending["job"]["id"], {"reply": "测试页完成", "actions": [{"type": "slide_add", **page}]})
        self.assertIn(original, [x["text"] for x in self.s.wb.get_slide("rounds", "S001")["slide"]["userInputs"]])
        self.assertEqual(self.s.delivery_state()["inputCount"], 2)

    def test_explicit_outline_intake_sets_only_supplied_project_and_evidence_fields(self):
        source = OUTLINE.replace("按大纲排版\n", "按大纲排版\n" + INTAKE).replace("## 内容｜测试第三页\n", "## 内容｜测试第三页\n依据要求：需要核验\n")
        self.s.enqueue(source, client_message_id="declared-intake", scope="deck")
        self.drain()
        state = self.s.state()
        self.assertEqual(state["project"]["purposeOther"], "内部测试项目介绍")
        self.assertEqual(state["project"]["audience"], "参与验收的项目同事")
        self.assertEqual(state["project"]["logoPolicy"], "none")
        self.assertEqual(state["project"]["delivery"], "live")
        self.assertEqual([self.s.wb.get_slide("rounds", p["id"])["slide"]["evidenceRequired"] for p in state["slides"]], ["no", "no", "yes", "no"])
        third = self.s.wb.get_slide("rounds", "S003")["slide"]
        self.assertNotIn("依据要求", third["keyPoints"])
        self.assertIn("依据要求：需要核验", third["userIntent"])
        self.assertEqual(third["evidence"], [])
        self.assertFalse(state["delivery"]["qualityAccepted"])
        self.assertTrue(state["delivery"]["interactionAccountingComplete"])

    def test_missing_intake_choices_can_be_combined_into_one_local_answer(self):
        self.initial()
        output = next(m for m in self.s.state()["messages"] if m.get("isRoundOutput"))
        questions = output["intakeQuestions"]
        self.assertEqual(len(questions), 3)
        self.assertEqual({c["groupId"] for c in output["choices"] if c.get("intakeChoice")}, {q["id"] for q in questions})
        selected = []
        for group in ("intake_brief", "intake_presentation", "intake_sources"):
            alternatives = [c for c in output["choices"] if c.get("groupId") == group]
            selected.append(alternatives[-1 if group == "intake_sources" else 0]["value"])
        self.s.enqueue("\n".join(selected), client_message_id="combined-answers", scope="deck")
        self.assertEqual(self.s.delivery_state()["inputCount"], 2)
        last = self.s.delivery_state()["rounds"][-1]
        output = next(m for m in self.s.state()["messages"] if m["id"] == last["outputMessageId"])
        self.assertEqual(output["intakeQuestions"], [])
        self.assertTrue(self.s.delivery_state()["interactionAccountingComplete"])

    def test_metadata_only_followup_keeps_exact_objects_and_counts_one_round(self):
        self.initial()
        before = self.scenes()
        result = self.s.enqueue("补充设置\n" + INTAKE, client_message_id="intake-answer", scope="deck")
        self.assertEqual(result["status"], "complete")
        duplicate = self.s.enqueue("补充设置\n" + INTAKE, client_message_id="intake-answer", scope="deck")
        self.assertTrue(duplicate["deduplicated"])
        for sid, old in before.items():
            now = self.s.get_scene(sid)
            self.assertEqual(old["scene"], now["scene"])
            self.assertFalse(now["stale"])
            self.assertGreater(now["sceneRevision"], old["sceneRevision"])
        self.measure_all_with_synthetic_fixture()
        versions = {p["id"]: p["sceneRevision"] for p in self.s.state()["slides"]}
        self.s.review_deck(versions, "测试操作者已查看所有当前页并认可表达与布局。", "third-review")
        state = self.s.delivery_state()
        self.assertEqual((state["inputCount"], state["outputCount"]), (3, 3))
        self.assertTrue(state["releaseReady"])
        self.assertTrue(state["targetSatisfied"])
        self.assertTrue(state["interactionAccountingComplete"])
        self.assertFalse(self.s.export("html", strict=True)["draft"])

    def test_three_round_flow_combines_missing_settings_and_two_page_feedback(self):
        self.initial()
        original = self.scenes()
        second = INTAKE + "整稿修改\n第1页：标题改为：用户明确的项目主题\n第3页：标题改为：用户明确的交付方式"
        result = self.s.enqueue(second, client_message_id="settings-and-feedback", scope="deck")
        self.assertEqual(result["status"], "complete")
        self.assertEqual((self.s.delivery_state()["inputCount"], self.s.delivery_state()["outputCount"]), (2, 1))
        self.drain()
        self.measure_all_with_synthetic_fixture()
        self.assertEqual(self.s.wb.get_slide("rounds", "S001")["slide"]["title"], "用户明确的项目主题")
        self.assertEqual(self.s.wb.get_slide("rounds", "S003")["slide"]["title"], "用户明确的交付方式")
        for sid in ("S002", "S004"):
            self.assertEqual(self.s.get_scene(sid)["scene"], original[sid]["scene"])
        versions = {p["id"]: p["sceneRevision"] for p in self.s.state()["slides"]}
        self.s.review_deck(versions, "测试操作者确认当前全部页面的内容与版式。", "combined-third-review")
        state = self.s.delivery_state()
        self.assertEqual((state["inputCount"], state["outputCount"]), (3, 3))
        self.assertTrue(state["targetSatisfied"])
        self.assertTrue(state["interactionAccountingComplete"])
        self.assertFalse(self.s.export("html", strict=True)["draft"])

    def test_combined_settings_unknown_page_applies_neither_half(self):
        self.initial()
        original = self.scenes()
        result = self.s.enqueue(INTAKE + "第1页：标题改为：不能部分应用\n第99页：标题改为：不存在", client_message_id="invalid-combined", scope="deck")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.s.wb.get_project("rounds")["workspace"]["project"]["purpose"], "")
        self.assertEqual(self.scenes(), original)

    def test_metadata_does_not_rebind_an_already_stale_scene_over_newer_words(self):
        self.initial()
        old = self.s.wb.get_slide("rounds", "S002")
        self.s.wb.patch_slide("rounds", "S002", old["revision"], [{"path": "/keyPoints", "value": "外部较新的内容，不允许被旧预览覆盖"}])
        result = self.s.enqueue(INTAKE, client_message_id="stale-metadata", scope="deck")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.s.delivery_state()["rounds"][-1]["error"]["code"], "SCENE_STALE")
        self.assertEqual(self.s.wb.get_slide("rounds", "S002")["slide"]["keyPoints"], "外部较新的内容，不允许被旧预览覆盖")
        self.assertEqual(self.s.wb.get_project("rounds")["workspace"]["project"]["purpose"], "")

    def test_evidence_only_choices_show_the_requirement_actually_submitted(self):
        source = OUTLINE.replace("按大纲排版\n", "按大纲排版\n数据策略：用户提供真实资料\n")
        self.s.enqueue(source, client_message_id="data-already-set", scope="deck")
        self.drain()
        output = next(m for m in self.s.state()["messages"] if m.get("isRoundOutput"))
        choices = [c for c in output["choices"] if c.get("groupId") == "intake_sources"]
        self.assertEqual(len(choices), 2)
        for choice in choices:
            requirement = "无需外部依据" if "无需外部依据" in choice["value"] else "需要核验"
            self.assertIn(requirement, choice["label"])
            if requirement == "无需外部依据":
                self.assertNotIn("待核验", choice["label"])

    def test_partial_intake_does_not_infer_page_evidence_or_ignore_mixed_requests(self):
        source = OUTLINE.replace("按大纲排版\n", "按大纲排版\n数据策略：无需外部资料\n")
        self.s.enqueue(source, client_message_id="partial-intake", scope="deck")
        self.drain()
        self.assertTrue(all(self.s.wb.get_slide("rounds", p["id"])["slide"]["evidenceRequired"] == "undecided" for p in self.s.state()["slides"]))
        self.s.enqueue("用途：不应静默只保存这一句\n另外请改第3页的结构", client_message_id="mixed", scope="deck")
        self.assertEqual(self.s.wb.get_project("rounds")["workspace"]["project"]["purpose"], "")
        self.assertEqual(self.s.delivery_state()["rounds"][-1]["status"], "needs_input")

    def test_precise_page_scope_cannot_apply_global_metadata(self):
        self.initial()
        old = self.s.wb.get_project("rounds")["workspace"]["project"]
        result = self.s.enqueue(INTAKE, "S001", "title", "wrong-metadata-scope")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.s.delivery_state()["rounds"][-1]["error"]["code"], "SCOPE_VIOLATION")
        self.assertEqual(self.s.wb.get_project("rounds")["workspace"]["project"], old)

    def test_formal_export_enforces_quality_on_server_even_if_content_gate_is_ready(self):
        self.s.enqueue(OUTLINE.replace("按大纲排版\n", "按大纲排版\n" + INTAKE), client_message_id="export-intake", scope="deck")
        self.drain()
        with patch.object(self.s.wb, "gate", return_value={"ready": True, "slides": []}):
            self.error("RELEASE_GATE_FAILED", self.s.export, "html", None, True)
        self.measure_all_with_synthetic_fixture()
        with patch.object(self.s.wb, "gate", return_value={"ready": True, "slides": []}):
            self.error("RELEASE_GATE_FAILED", self.s.export, "html", None, True)
        versions = {p["id"]: p["sceneRevision"] for p in self.s.state()["slides"]}
        self.s.review_deck(versions, "测试操作者认可当前所有页的表达与版式。", "export-review")
        self.assertFalse(self.s.export("html", strict=True)["draft"])
        changed = self.s.get_scene("S002")
        self.s.change_scene("S002", changed["sceneRevision"], [{"objectId": "title", "properties": {"text": "导出确认之后的外部修改"}}])
        with patch.object(self.s.wb, "gate", return_value={"ready": True, "slides": []}):
            self.error("RELEASE_GATE_FAILED", self.s.export, "html", None, True)

    def test_browser_undo_is_one_counted_idempotent_input(self):
        self.initial()
        before = self.s.get_scene("S001")
        changed = self.s.change_scene("S001", before["sceneRevision"], [{"objectId": "title", "properties": {"text": "撤销包装测试中的临时文字"}}])
        response = self.s.undo_submission("S001", changed["sceneRevision"], "undo-button-once")
        again = self.s.undo_submission("S001", changed["sceneRevision"], "undo-button-once")
        self.assertTrue(again["deduplicated"])
        self.assertEqual(response["roundId"], again["roundId"])
        self.assertEqual(self.s.delivery_state()["inputCount"], 2)
        self.assertEqual(self.s.wb.get_slide("rounds", "S001")["slide"]["title"], "测试封面")

    def test_whole_deck_review_is_one_counted_attestation_and_not_evidence(self):
        self.initial()
        versions = {p["id"]: p["sceneRevision"] for p in self.s.state()["slides"]}
        result = self.s.review_deck(versions, "测试操作者陈述：已查看所有当前页面，认可本轮内容和版式。", "review-all-once")
        self.assertFalse(result["result"]["evidenceVerified"])
        duplicate = self.s.review_deck(versions, "测试操作者陈述：已查看所有当前页面，认可本轮内容和版式。", "review-all-once")
        self.assertTrue(duplicate["deduplicated"])
        state = self.s.delivery_state()
        self.assertEqual((state["inputCount"], state["outputCount"]), (2, 2))
        self.assertTrue(state["qualityAccepted"])
        self.assertFalse(state["releaseReady"])
        self.assertFalse(state["targetSatisfied"])
        self.assertTrue(any(i["code"] == "EVIDENCE_REQUIREMENT_UNDECIDED" for i in state["releaseIssues"]))

    def test_whole_deck_review_rejects_unmeasured_and_changed_versions(self):
        self.s.enqueue(OUTLINE, client_message_id="initial", scope="deck")
        self.drain()
        versions = {p["id"]: p["sceneRevision"] for p in self.s.state()["slides"]}
        statement = "明确的测试操作者陈述。"
        self.error("QUALITY_NOT_READY", self.s.review_deck, versions, statement, "unmeasured-review")
        self.assertEqual(self.s.delivery_state()["inputCount"], 1)
        self.measure_all_with_synthetic_fixture()
        third = self.s.get_scene("S003")
        self.s.change_scene("S003", third["sceneRevision"], [{"objectId": "title", "properties": {"text": "已经改变的页面"}}])
        self.error("STALE_REVISION", self.s.review_deck, versions, statement, "stale-review")
        self.assertFalse(self.s.wb.get_slide("rounds", "S001")["reviews"]["visual"])


if __name__ == "__main__":
    unittest.main()
