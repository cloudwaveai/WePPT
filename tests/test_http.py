import http.client
import json
import tempfile
import threading
import time
import unittest

from ppt_workbench.server import create_http_server
from ppt_workbench.core import EngineError


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = create_http_server(self.temp.name, "web", 0, "manual", "test-browser-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, method, path, body=None, *, authorized=True, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"X-Studio-Token": "test-browser-token"} if authorized else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        result = conn.getresponse()
        data = result.read()
        answer = (result.status, dict(result.getheaders()), data)
        conn.close()
        return answer

    def test_mapping_is_get_only_and_force_logo_placement(self):
        import base64
        from ppt_workbench import logo
        status, _, data = self.request("GET", "/api/derive/mapping")
        self.assertEqual((status, json.loads(data)["error"]["code"]), (400, "NOT_DERIVED"))
        status, _, data = self.request("POST", "/api/derive/mapping", {})
        self.assertEqual((status, json.loads(data)["error"]["code"]), (404, "NOT_FOUND"))
        studio = self.server.studio
        studio.demo()
        folder = studio.wb.project_dir(studio.project_id) / "brand"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "logo-original.png").write_bytes(b"\x89PNG\r\n\x1a\n1234")
        logo.save_logo_record(studio, {"width": 120, "height": 60, "hasAlpha": True, "removedBackground": True,
            "tone": "dark", "meanColor": "#1F2329", "variants": {"original": "logo-original.png"},
            "preview": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n1").decode()},
            {"position": "auto", "size": "medium", "pages": "all"})
        sid = studio.state()["slides"][0]["id"]
        status, _, data = self.request("POST", "/api/logo/place", {"slideId": sid, "sceneRevision": studio.get_scene(sid)["sceneRevision"]})
        self.assertEqual(status, 200, data)
        self.assertTrue(any(o["id"] == "brand-logo" for o in studio.get_scene(sid)["scene"]["objects"]))

    def test_diagram_fallback_http_scope_revision_and_idempotency(self):
        from test_diagram_design import SPEC
        studio = self.server.studio
        job = studio.enqueue('原生图解')
        result = studio.apply_plan(job['jobId'], {'reply': '完成', 'actions': [
            {'type': 'slide_add', 'title': '产品流程', 'user_intent': '流程', 'role': 'content', 'diagram': SPEC}]})
        sid = result['slideId']
        current = studio.get_scene(sid)
        body = {'slideId': sid, 'sceneRevision': current['sceneRevision'], 'requestId': 'http-diagram'}
        endpoint = '/api/diagram/image'
        self.assertEqual(self.request('POST', endpoint, body, authorized=False)[0], 403)
        self.assertEqual(self.request('POST', endpoint, body, extra={'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(self.request('POST', endpoint, {**body, 'sceneRevision': body['sceneRevision']-1})[0], 409)
        status, _, raw = self.request('POST', endpoint, body)
        self.assertEqual(status, 200, raw)
        status, _, raw = self.request('POST', endpoint, body)
        self.assertEqual(status, 200, raw)
        self.assertTrue(json.loads(raw)['deduplicated'])
        self.assertEqual(studio.get_scene(sid)['scene'], current['scene'])

    def test_template_match_is_retired_and_access_checked(self):
        self.server.studio.demo()
        before = self.server.studio.get_scene('S003')
        body = {'slideId': 'S003', 'sceneRevision': before['sceneRevision']}
        endpoint = '/api/templates/match'
        self.assertEqual(self.request('POST', endpoint, body, authorized=False)[0], 403)
        self.assertEqual(self.request('POST', endpoint, body, extra={'Origin': 'https://example.com'})[0], 403)
        status, _, raw = self.request('POST', endpoint, body)
        self.assertEqual(status, 410)
        self.assertEqual(json.loads(raw)['error']['code'], 'TEMPLATE_RETIRED')
        self.assertEqual(self.server.studio.get_scene('S003'), before)

    def test_retired_smart_matching_never_calls_model(self):
        from unittest.mock import patch
        from ppt_workbench import jev_recommendations as jev
        with patch.object(jev, '_request') as request:
            endpoint = '/api/templates/recommendations'
            self.assertEqual(self.request('POST', endpoint, {}, authorized=False)[0], 403)
            self.assertEqual(self.request('POST', endpoint, {})[0], 410)
            request.assert_not_called()

    def test_retired_reference_images_are_no_longer_served(self):
        from ppt_workbench.server import REFERENCE_ASSETS
        for url in REFERENCE_ASSETS:
            self.assertEqual(self.request('GET', url, authorized=False)[0], 401)
            self.assertEqual(self.request('GET', url)[0], 410)

    def test_independent_guidance_persistence_conflicts_and_isolation(self):
        for kind in ('draft', 'experience'):
            path = '/api/guide/' + kind
            self.assertEqual(self.request('GET', path, authorized=False)[0], 401)
            initial = json.loads(self.request('GET', path)[2])
            self.assertEqual(initial['revision'], 0)
            document = {'pages': [{'title': '真实标题'}]} if kind == 'draft' else {'qa': [{'question': '为什么', 'answer': '真实回答'}], 'curated': ['cover']}
            saved = self.request('POST', path, {'revision': 0, 'document': document})
            self.assertEqual(saved[0], 200, saved[2])
            self.assertEqual(json.loads(saved[2])['revision'], 1)
            self.assertEqual(self.request('POST', path, {'revision': 0, 'document': {}})[0], 409)
            self.assertEqual(json.loads(self.request('GET', path)[2])['document'], document)
            self.assertEqual(self.request('POST', path, {'revision': 1, 'document': {}}, extra={'Origin': 'https://example.com'})[0], 403)
        pid = json.loads(self.request('POST', '/api/projects', {'title': '独立项目'})[2])['projectId']
        other = json.loads(self.request('GET', '/api/guide/experience?project=' + pid)[2])
        self.assertEqual(other['document'], {})
        self.assertEqual(self.server.studio.state()['slides'], [])
        self.assertEqual(self.request('POST', '/api/guide/draft', {'revision': 1, 'document': 'invalid'})[0], 400)

    def test_page_recommendations_return_expression_and_role(self):
        self.assertEqual(self.request('POST', '/api/demo', {})[0], 200)
        state = json.loads(self.request('GET', '/api/state')[2])
        sid = state['selectedSlideId']
        response = self.request('GET', '/api/templates/recommendations?slideId=' + sid)
        self.assertEqual(response[0], 200)
        result = json.loads(response[2])
        self.assertEqual(result['slideId'], sid)
        self.assertIn('relationship', result['expressionPlan'])
        self.assertTrue(result['recommendations'])
        self.assertTrue(all(result['role'] in item['roles'] for item in result['recommendations']))

    def test_incremental_state_never_hides_project_changes(self):
        first = json.loads(self.request('GET', '/api/state')[2])
        path = f'/api/state?since={first["version"]}&sinceProject={first["projectId"]}'
        unchanged = json.loads(self.request('GET', path)[2])
        self.assertEqual(unchanged, {'unchanged': True, 'projectId': first['projectId'], 'version': first['version']})
        wrong_project = json.loads(self.request('GET', path.replace('sinceProject=web', 'sinceProject=another'))[2])
        self.assertIn('messages', wrong_project)
        self.request('POST', '/api/demo', {})
        changed = json.loads(self.request('GET', path)[2])
        self.assertIn('slides', changed)
        self.assertGreater(changed['version'], first['version'])
        self.assertIn('messages', json.loads(self.request('GET', '/api/state')[2]))

    def test_browser_images_share_original_bytes_and_remain_project_scoped(self):
        import base64, hashlib, html, re
        from test_studio import PNG
        self.request('POST', '/api/demo', {})
        studio = self.server.studio
        sid = studio.state()['selectedSlideId']
        current = studio.get_scene(sid)
        scene = current['scene']
        scene['objects'].append({'id': 'real-image', 'type': 'image', 'src': 'data:image/png;base64,' + PNG,
                                 'x': 850, 'y': 300, 'w': 200, 'h': 200})
        studio.put_scene(sid, current['contentRevision'], scene)
        self.assertIn(PNG.encode(), self.request('GET', '/api/preview/' + sid)[2])
        self.server.open_access = True
        result = self.request('GET', '/api/preview/' + sid)
        self.server.open_access = False
        markup = result[2].decode()
        self.assertNotIn(PNG, markup)
        url = html.unescape(re.search(r'src="(/api/scene-image[^"]+)"', markup)[1])
        self.assertEqual(self.request('GET', url, authorized=False)[0], 401)
        status, headers, raw = self.request('GET', url)
        self.assertEqual(status, 200)
        self.assertEqual(raw, base64.b64decode(PNG))
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertIn('private', headers['Cache-Control'])
        self.assertEqual(self.request('GET', url.replace(hashlib.sha256(raw).hexdigest(), '0' * 64))[0], 404)
        other = json.loads(self.request('POST', '/api/projects', {'title': '独立图片项目'})[2])['projectId']
        self.assertNotEqual(self.request('GET', url.replace('project=web', 'project=' + other))[0], 200)
        metadata = self.request('GET', '/api/scene?slide=' + sid + '&metadata=1')[2]
        full = self.request('GET', '/api/scene?slide=' + sid)[2]
        self.assertNotIn(PNG.encode(), metadata)
        self.assertIn(PNG.encode(), full)

    def test_retired_template_preview_does_not_modify_saved_page(self):
        self.server.studio.demo()
        sid = self.server.studio.state()['selectedSlideId']
        before = self.server.studio.get_scene(sid)
        path = '/api/templates/preview?template=reference-04-09&slideId=' + sid
        self.assertEqual(self.request('GET', path, authorized=False)[0], 401)
        self.assertEqual(self.request('GET', path)[0], 410)
        self.assertEqual(self.server.studio.get_scene(sid), before)

    def test_chat_object_edit_preview_and_download_are_real(self):
        self.assertEqual(self.request("POST", "/api/demo", {})[0], 200)
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual(len(state["slides"]), 3)
        sid = state["selectedSlideId"]
        before = self.server.studio.get_scene(sid)
        reply = self.request("POST", "/api/chat", {"message": "标题改为：HTTP 流程已验证", "slideId": sid,
                                                   "objectId": "title", "clientMessageId": "browser-once"})
        self.assertEqual(reply[0], 200, reply[2])
        self.assertEqual(json.loads(reply[2])["status"], "complete")
        after = self.server.studio.get_scene(sid)
        self.assertEqual(after["sceneRevision"], before["sceneRevision"] + 1)
        preview = self.request("GET", after["previewUrl"])
        self.assertEqual(preview[0], 200)
        self.assertIn("HTTP 流程已验证".encode(), preview[2])
        exported = self.request("GET", "/api/export?format=html")
        self.assertEqual(exported[0], 200)
        self.assertIn("attachment", exported[1]["Content-Disposition"])
        self.assertTrue(exported[2].lstrip().lower().startswith(b"<!doctype html"))

    def test_content_guide_assets_are_authenticated_and_read_only(self):
        before = self.server.studio.state()
        assets = {"/guide.html": "text/html", "/guide.js": "application/javascript",
                  "/guide.css": "text/css", "/guide-experience.json": "application/json"}
        for path, content_type in assets.items():
            self.assertEqual(self.request("GET", path, authorized=False)[0], 401)
            response = self.request("GET", path + "?project=web")
            self.assertEqual(response[0], 303 if path == '/guide.html' else 410, response[2])
        self.assertEqual(self.server.studio.state()["messages"], before["messages"])
        self.assertEqual(self.server.studio.state()["slides"], before["slides"])

    def test_project_management_keeps_tabs_and_previews_separate(self):
        self.request("POST", "/api/demo", {})
        original = self.server.studio.state()
        status, _, data = self.request("POST", "/api/projects", {"title": "第二份演示稿"})
        self.assertEqual(status, 200, data)
        project_id = json.loads(data)["projectId"]
        target = {"X-WePPT-Project": project_id}
        state = json.loads(self.request("GET", "/api/state", extra=target)[2])
        self.assertEqual(state["project"]["title"], "第二份演示稿")
        self.assertEqual(state["slides"], [])
        self.request("POST", "/api/demo", {}, extra=target)
        new_studio = self.server.studios[project_id]
        sid = new_studio.state()["selectedSlideId"]
        self.request("POST", "/api/chat", {"message": "标题改为：独立项目", "slideId": sid}, extra=target)
        preview = new_studio.get_scene(sid)["previewUrl"]
        self.assertIn("独立项目".encode(), self.request("GET", preview)[2])
        self.assertEqual(self.server.studio.state()["slides"], original["slides"])
        listing = json.loads(self.request("GET", "/api/projects")[2])["projects"]
        self.assertEqual({p["projectId"] for p in listing}, {"web", project_id})
        self.assertEqual(self.request("POST", "/api/projects", {"title": " "})[0], 400)
        self.assertEqual(self.request("GET", "/api/state?project=missing")[0], 404)
        self.assertEqual(self.request("GET", "/api/projects", authorized=False)[0], 401)

    def test_missing_logo_template_request_after_server_restart(self):
        self.request("POST", "/api/demo", {})
        studio = self.server.studio
        sid = studio.state()["selectedSlideId"]
        project = studio.wb.get_project("web")
        studio.wb.update_project("web", project["revision"], {"logoPolicy": "company", "logoReference": "absent.svg"})
        studio.generate_scene(sid)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.server = create_http_server(self.temp.name, "web", 0, "manual", "test-browser-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        state = json.loads(self.request("GET", "/api/state")[2])
        slide = next(s for s in state["slides"] if s["id"] == sid)
        self.assertFalse(slide["stale"])
        self.assertTrue(slide["previewMaterialUnavailable"])
        response = self.request("POST", "/api/template", {"slideId": sid, "sceneRevision": slide["sceneRevision"], "templateId": "editorial"})
        self.assertEqual(response[0], 410, response[2])
        context = self.server.studio.context({"slideId": sid})
        self.assertIsNone(context["selectedTemplateId"])
        self.assertNotEqual(context["currentSceneTemplateId"], "editorial")
        self.assertFalse(self.server.studio.wb.gate("web")["ready"])

    def test_curated_catalog_scene_edit_and_project_routing(self):
        for path in ('/api/templates', '/api/templates/preview?template=clean', '/api/scene?slide=S001'):
            self.assertEqual(self.request('GET', path, authorized=False)[0], 401)
        cards = json.loads(self.request('GET', '/api/templates')[2])['templates']
        self.assertEqual(len(cards), 50)
        self.assertTrue(all(c['referenceOnly'] and c['id'].startswith('curated-') for c in cards))
        for card in cards:
            status, headers, raw = self.request('GET', card['previewUrl'])
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'image/jpeg')
            self.assertTrue(raw.startswith(bytes.fromhex('ffd8')))
        pid = json.loads(self.request('POST', '/api/projects', {'title': '案例项目'})[2])['projectId']
        headers = {'X-WePPT-Project': pid}
        self.assertEqual(self.request('POST', '/api/template', {'templateId': 'dark'}, extra=headers)[0], 410)
        self.request('POST', '/api/demo', {}, extra=headers)
        state = json.loads(self.request('GET', '/api/state', extra=headers)[2])
        sid = state['selectedSlideId']
        current = json.loads(self.request('GET', '/api/scene?slide=' + sid, extra=headers)[2])
        edit = {'slideId': sid, 'sceneRevision': current['sceneRevision'],
                'changes': [{'objectId': 'title', 'properties': {'text': '保留历史稿编辑'}}]}
        edited = self.request('POST', '/api/edit', edit, extra=headers)
        self.assertEqual(edited[0], 200, edited[2])
        self.assertIn('保留历史稿编辑'.encode(), self.request('GET', json.loads(edited[2])['previewUrl'])[2])
        self.assertEqual(self.request('POST', '/api/edit', edit, extra=headers)[0], 409)
        self.assertEqual(self.server.studio.state()['slides'], [])

    def test_cookie_bootstrap_and_cross_site_mutations(self):
        self.assertEqual(self.request("GET", "/api/state", authorized=False)[0], 401)
        status, headers, _ = self.request("GET", "/?token=test-browser-token", authorized=False)
        self.assertEqual(status, 303)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(self.request("GET", "/api/state", authorized=False,
                                    extra={"Cookie": "ppt_studio=test-browser-token"})[0], 200)
        self.assertEqual(self.request("POST", "/api/demo", {}, extra={"Origin": "https://other.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", extra={"Host": "other.example"})[0], 403)

    def test_stale_request_is_error_and_no_arbitrary_file_route(self):
        self.request("POST", "/api/demo", {})
        state = json.loads(self.request("GET", "/api/state")[2])
        sid = state["selectedSlideId"]
        response = self.request("POST", "/api/review", {"slideId": sid, "sceneRevision": 99})
        self.assertEqual(response[0], 409)
        self.assertEqual(json.loads(response[2])["error"]["code"], "STALE_REVISION")
        self.assertEqual(self.request("GET", "/../../workbench.sqlite")[0], 404)

    def test_project_server_lock_and_interrupted_job_recovery(self):
        studio = self.server.studio
        pending = studio.enqueue("请先讨论我的真实想法，不要生成页面。")
        with studio.wb.atomic() as db:
            db.execute("UPDATE studio_jobs SET status='running' WHERE id=?", (pending["jobId"],))
            db.execute("UPDATE studio_messages SET status='running' WHERE id=?", (studio.job(pending["jobId"])["message_id"],))
        with self.assertRaises(EngineError) as raised:
            create_http_server(self.temp.name, "web", 0)
        self.assertEqual(raised.exception.code, "STUDIO_ALREADY_RUNNING")
        self.assertEqual(studio.job(pending["jobId"])["status"], "running")
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.server = create_http_server(self.temp.name, "web", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.assertEqual(self.server.studio.job(pending["jobId"])["status"], "queued")
        self.assertEqual(self.server.studio.next_job()["job"]["id"], pending["jobId"])

    def test_real_http_outline_pipeline_and_revision_target(self):
        switched = self.request("POST", "/api/agent", {"mode": "outline"})
        self.assertEqual(switched[0], 200, switched[2])
        self.assertEqual(json.loads(switched[2])["agent"]["mode"], "outline")
        source = "按大纲排版\n# 接口测试整稿\n## 封面｜明确的测试封面\n结论：测试整稿流程\n这是测试输入，不是真实客户案例。\n## 内容｜明确的测试正文\n结论：保留用户内容\n每个页面拥有独立版本。\n## 结束｜明确的测试结尾\n结论：完成当前稿件\n从界面下载实际文件。"
        submitted = self.request("POST", "/api/chat", {"message": source, "clientMessageId": "outline-http-1"})
        self.assertEqual(submitted[0], 200, submitted[2])
        premature = self.request("GET", "/api/export?format=html")
        self.assertNotEqual(premature[0], 200)
        self.assertEqual(json.loads(premature[2])["error"]["code"], "DECK_INCOMPLETE")
        paused = self.request("POST", "/api/deck/control", {"action": "pause"})
        self.assertEqual(json.loads(paused[2])["deck"]["status"], "paused")
        self.server.start_worker()
        self.assertEqual(self.request("POST", "/api/deck/control", {"action": "resume"})[0], 200)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = json.loads(self.request("GET", "/api/state")[2])
            if state["deck"]["status"] == "complete":
                break
            time.sleep(0.05)
        self.assertEqual(state["deck"]["status"], "complete", state["deck"])
        self.assertEqual(len(state["slides"]), 3)
        self.assertEqual(state["deck"]["revisionCount"], 0)
        other = state["slides"][1:]
        sid = state["slides"][0]["id"]
        for number in range(1, 5):
            edited = self.request("POST", "/api/chat", {"message": f"标题改为：第{number}次明确修改", "slideId": sid,
                "objectId": "title", "clientMessageId": f"revision-{number}"})
            self.assertEqual(edited[0], 200, edited[2])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = json.loads(self.request("GET", "/api/state")[2])
                if state["deck"]["revisionCount"] == number:
                    break
                time.sleep(0.05)
            self.assertEqual(state["deck"]["revisionCount"], number)
            self.assertEqual(state["deck"]["withinRevisionTarget"], number <= 3)
        self.assertEqual(other, state["slides"][1:])
        exported = self.request("GET", "/api/export?format=html")
        self.assertEqual(exported[0], 200, exported[2])
        self.assertIn("第4次明确修改".encode(), exported[2])
        self.assertIn("明确的测试结尾".encode(), exported[2])

    def test_mode_change_validation_and_state_survive_http_reconnect(self):
        self.assertEqual(self.request("POST", "/api/agent", {"mode": "outline"})[0], 200)
        bad = self.request("POST", "/api/agent", {"mode": "arbitrary-command"})
        self.assertEqual(bad[0], 400)
        from ppt_workbench.studio import Studio
        self.assertEqual(Studio(self.temp.name, "web", create=False).agent_mode, "outline")

    def test_answer_to_blocked_page_does_not_edit_last_finished_page(self):
        studio = self.server.studio
        plan = {"title": "提问绑定测试", "pages": [
            {"title": "已完成页", "user_intent": "保留本页", "role": "cover", "key_points": "原有文字"},
            {"title": "需要回答的页", "user_intent": "需要用户选择", "role": "content"}]}
        studio.create_deck(plan, "用户需要两页测试，第二页要先提问。", "agent")
        first = studio.next_job()["job"]
        done = studio.apply_plan(first["id"], {"reply": "测试第一页完成", "actions": [{"type": "slide_add", **plan["pages"][0]}]})
        sid = done["slideId"]
        before = studio.get_scene(sid)
        second = studio.next_job()["job"]
        studio.apply_plan(second["id"], {"reply": "第二页需要选择。", "actions": [], "questions": [
            {"question": "希望强调哪一项？", "choices": ["清晰", "完整"]}]})
        question_id = studio.deck_state()["pendingQuestionMessageId"]
        self.assertTrue(question_id)
        reply = self.request("POST", "/api/chat", {"message": "我选择清晰，并保留现有资料。",
            "choiceMessageId": question_id, "replyToDeckPage": True, "clientMessageId": "answer-once"})
        self.assertEqual(reply[0], 200, reply[2])
        after = studio.get_scene(sid)
        self.assertEqual(before, after)
        self.assertEqual(studio.deck_state()["revisionCount"], 0)
        retried = self.request("POST", "/api/deck/control", {"action": "retry"})
        self.assertEqual(retried[0], 200, retried[2])
        context = studio.next_job()["context"]
        self.assertIn("我选择清晰", json.dumps(context["currentDeckPage"]["supplementalAnswers"], ensure_ascii=False))

    def wait_for_round_output(self, number):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = json.loads(self.request("GET", "/api/state")[2])
            if state["delivery"]["outputCount"] >= number:
                return state
            time.sleep(0.05)
        self.fail("Round did not produce an output: " + json.dumps(state["delivery"], ensure_ascii=False))

    def post_synthetic_measurements(self):
        # Server-contract fixtures only. No browser was run for this test.
        from test_quality import fixture_report
        for _ in range(4):
            state = json.loads(self.request("GET", "/api/state")[2])
            pending = state["quality"]["browser"]["pendingSlideIds"]
            if not pending:
                return state
            for sid in pending:
                current = self.server.studio.get_scene(sid)
                response = self.request("POST", "/api/quality/report", {"slideId": sid,
                    "sceneRevision": current["sceneRevision"], "report": fixture_report(current["scene"])})
                self.assertEqual(response[0], 200, response[2])
        self.fail("Synthetic measurement fixtures did not settle")

    def test_three_inputs_over_http_include_batch_and_whole_deck_confirmation(self):
        self.request("POST", "/api/agent", {"mode": "outline"})
        self.server.start_worker()
        source = """按大纲排版
# 三轮接口测试
用途：验证程序行为
听众：程序测试人员
目标：完成明确测试
展示方式：独立阅读
Logo策略：不使用
数据策略：无需外部资料
本稿各页依据要求：无需外部依据

## 封面｜测试封面
结论：这是一份专用测试输入
程序接口检查，不属于真实UI验收。

## 内容｜中间测试页
结论：这一页保持不动
这段文字来自测试输入。

## 结束｜测试结尾
结论：检查完整输出
不包含任何外部事实、客户案例或统计数据。
"""
        first = self.request("POST", "/api/chat", {"message": source, "scope": "deck", "clientMessageId": "http-round-1"})
        self.assertEqual(first[0], 200, first[2])
        state = self.wait_for_round_output(1)
        self.assertEqual(len(state["slides"]), 3)
        self.assertFalse(state["delivery"]["targetSatisfied"])
        self.assertEqual(state["delivery"]["inputCount"], 1)
        self.assertEqual(state["quality"]["browser"]["measured"], 0)
        self.post_synthetic_measurements()
        untouched = self.server.studio.get_scene("S002")
        second = self.request("POST", "/api/chat", {"message": "整稿修改\n第1页：标题改为：用户指定的测试封面\n第3页：标题改为：用户指定的测试结尾",
            "scope": "deck", "clientMessageId": "http-round-2"})
        self.assertEqual(second[0], 200, second[2])
        self.wait_for_round_output(2)
        state = self.post_synthetic_measurements()
        self.assertEqual(self.server.studio.get_scene("S002"), untouched)
        self.assertEqual(set(state["delivery"]["rounds"][-1]["changedSlideIds"]), {"S001", "S003"})
        self.assertTrue(state["quality"]["readyToReview"], state["quality"])
        review = {"sceneRevisions": {p["id"]: p["sceneRevision"] for p in state["slides"]},
            "statement": "测试操作者声明：已检查本测试稿的完整内容与版式。此记录不是真实UI验收。", "clientMessageId": "http-round-3"}
        third = self.request("POST", "/api/review/deck", review)
        self.assertEqual(third[0], 200, third[2])
        state = json.loads(third[2])
        self.assertEqual((state["delivery"]["inputCount"], state["delivery"]["outputCount"]), (3, 3))
        self.assertTrue(state["delivery"]["targetSatisfied"], state["delivery"])
        self.assertEqual(self.request("POST", "/api/review/deck", review)[0], 200)
        self.assertEqual(json.loads(self.request("GET", "/api/state")[2])["delivery"]["inputCount"], 3)
        for fmt in ("html", "pptx"):
            exported = self.request("GET", "/api/export?format=" + fmt + "&strict=1")
            self.assertEqual(exported[0], 200, exported[2][:400])
            self.assertIn("release-", exported[1]["Content-Disposition"])
        current = self.server.studio.get_scene("S001")
        undo = self.request("POST", "/api/undo", {"slideId": "S001", "sceneRevision": current["sceneRevision"], "clientMessageId": "http-undo-4"})
        self.assertEqual(undo[0], 200, undo[2])
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual(state["delivery"]["inputCount"], 4)
        self.assertFalse(state["delivery"]["withinTarget"])
        self.assertFalse(state["delivery"]["targetSatisfied"])

    def test_quality_reports_reject_stale_or_approval_fields_without_new_inputs(self):
        from test_quality import fixture_report
        self.request("POST", "/api/demo", {})
        before = self.server.studio.get_scene("S001")
        report = fixture_report(before["scene"])
        invalid = self.request("POST", "/api/quality/report", {"slideId": "S001", "sceneRevision": before["sceneRevision"],
            "report": {**report, "approved": True}})
        self.assertEqual(invalid[0], 400)
        self.assertEqual(json.loads(invalid[2])["error"]["code"], "INVALID_QUALITY_REPORT")
        self.request("POST", "/api/chat", {"message": "标题改为：新的测试标题", "slideId": "S001", "objectId": "title", "clientMessageId": "change-one"})
        stale = self.request("POST", "/api/quality/report", {"slideId": "S001", "sceneRevision": before["sceneRevision"], "report": report})
        self.assertNotEqual(stale[0], 200)
        self.assertEqual(json.loads(stale[2])["error"]["code"], "QUALITY_STALE_REPORT")
        count = self.server.studio.delivery_state()["inputCount"]
        checked = self.request("POST", "/api/quality/check", {"autoFix": True})
        self.assertEqual(checked[0], 200, checked[2])
        self.assertEqual(self.server.studio.delivery_state()["inputCount"], count)


if __name__ == "__main__":
    unittest.main()
