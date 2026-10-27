"""Subprocess checks for the CLI contract, persistence and stale-write rejection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "state"

    def run_cli(self, *args, input_json=None, input_text=None, expected=0):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if input_json is not None:
            input_text = json.dumps(input_json, ensure_ascii=False)
        completed = subprocess.run(
            [sys.executable, "-m", "ppt_workbench.cli", "--root", str(self.root), *args],
            input=input_text, capture_output=True, text=True, encoding="utf-8", env=env,
            cwd=PACKAGE_ROOT, timeout=20,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
        try:
            return json.loads(completed.stdout)
        except ValueError:
            self.fail(f"CLI did not emit JSON: {completed.stdout!r}; stderr={completed.stderr!r}")

    def create_project(self):
        return self.run_cli("project", "create", "demo", "--brief", "-", input_json={
            "title": "演示", "purpose": "report", "audience": "管理者", "logoPolicy": "none",
        })

    def add_slide(self, title="当前页", intent="这是用户提供的想法"):
        return self.run_cli("slide", "add", "demo", "--title", title, "--intent", intent)

    def test_persisted_single_page_patch_stale_rejection_and_restore(self):
        self.assertEqual(self.create_project()["revision"], 1)
        first = self.add_slide()
        second = self.add_slide("第二页", "第二页原意")
        self.assertEqual((first["slideId"], second["slideId"]), ("S001", "S002"))
        patch = [{"path": "/takeaway", "value": "本页拟用表达"}, {"path": "/templateId", "value": "custom"}]
        updated = self.run_cli("slide", "patch", "demo", "S001", "--base-revision", "1",
                               "--changes", "-", "--summary", "只调整当前页", input_json=patch)
        self.assertEqual(updated["revision"], 2)
        stale = self.run_cli("slide", "patch", "demo", "S001", "--base-revision", "1",
                             "--changes", "-", input_json=patch, expected=1)
        self.assertEqual(stale["error"]["code"], "STALE_REVISION")
        current = self.run_cli("slide", "show", "demo", "S001")
        self.assertEqual(current["slide"]["takeaway"], "本页拟用表达")
        untouched = self.run_cli("slide", "show", "demo", "S002")
        self.assertEqual(untouched["slide"], second["slide"])
        restored = self.run_cli("slide", "restore", "demo", "S001", "--base-revision", "2", "--restore-revision", "1")
        self.assertEqual(restored["revision"], 3)
        self.assertEqual(restored["slide"]["takeaway"], "")
        appended = self.run_cli("slide", "append-input", "demo", "S001", "--base-revision", "3",
                                "--text", "用户补充：请加上执行顺序。", "--source-note", "本次访谈第 2 段")
        self.assertEqual(appended["revision"], 4)
        self.assertEqual(appended["slide"]["userIntent"], first["slide"]["userIntent"])
        self.assertEqual(appended["slide"]["userInputs"][-1]["text"], "用户补充：请加上执行顺序。")
        self.assertEqual(appended["slide"]["userInputs"][-1]["sourceNote"], "本次访谈第 2 段")
        restored_again = self.run_cli("slide", "restore", "demo", "S001", "--base-revision", "4", "--restore-revision", "1")
        self.assertEqual(restored_again["slide"]["userInputs"], appended["slide"]["userInputs"])
        history = self.run_cli("history", "demo", "--slide", "S001")
        self.assertEqual([item["revision"] for item in history["revisions"]], [1, 2, 3, 4, 5])

    def test_review_is_explicit_attestation_and_gate_stays_blocked(self):
        self.create_project()
        self.add_slide()
        self.run_cli("slide", "patch", "demo", "S001", "--base-revision", "1", "--changes", "-",
                     input_json=[{"path": "/takeaway", "value": "待审阅表达"}])
        missing = self.run_cli("review", "demo", "S001", "--base-revision", "2", "--kind", "content", expected=2)
        self.assertEqual(missing["error"]["code"], "CLI_ARGUMENT_ERROR")
        reviewed = self.run_cli("review", "demo", "S001", "--base-revision", "2", "--kind", "content",
                                "--statement", "我已核对本页表达与提供的原意一致。", "--reviewer", "本地操作者")
        self.assertFalse(reviewed["humanIdentityAuthenticated"])
        self.assertEqual(reviewed["slide"]["contentStatus"], "confirmed")
        self.assertEqual(reviewed["reviews"]["content"]["statement"], "我已核对本页表达与提供的原意一致。")
        gate = self.run_cli("gate", "demo", "--slide", "S001", expected=3)
        self.assertFalse(gate["ready"])
        self.assertIn("ARTIFACT_MISSING", {issue["code"] for issue in gate["slides"][0]["issues"]})
        release = self.run_cli("release-manifest", "demo", expected=1)
        self.assertEqual(release["error"]["code"], "RELEASE_GATE_FAILED")

    def test_json_files_project_revision_and_workspace_roundtrip(self):
        self.create_project()
        changes = Path(self.directory.name) / "changes.json"
        changes.write_text(json.dumps({"outcome": "通过预算"}, ensure_ascii=False), encoding="utf-8")
        updated = self.run_cli("project", "update", "demo", "--base-revision", "1", "--changes", str(changes))
        self.assertEqual(updated["workspace"]["project"]["outcome"], "通过预算")
        stale = self.run_cli("project", "update", "demo", "--base-revision", "1", "--changes", str(changes), expected=1)
        self.assertEqual(stale["error"]["code"], "STALE_REVISION")
        self.add_slide()
        destination = Path(self.directory.name) / "exported.json"
        result = self.run_cli("project", "export", "demo", "--output", str(destination))
        self.assertEqual(Path(result["outputPath"]).resolve(), destination.resolve())
        imported = self.run_cli("project", "import", "copy", "--file", str(destination))
        self.assertEqual(imported["workspace"]["slides"][0]["userIntent"], "这是用户提供的想法")
        self.assertIn("importNotice", imported)
        duplicate = self.run_cli("project", "import", "copy", "--file", str(destination), expected=1)
        self.assertEqual(duplicate["error"]["code"], "PROJECT_EXISTS")
        invalid = self.run_cli("project", "create", "invalid", "--brief", "-", input_text="{bad json", expected=2)
        self.assertEqual(invalid["error"]["code"], "INVALID_JSON")
        wrong_type = self.run_cli("project", "create", "wrong", "--brief", "-", input_json=[], expected=2)
        self.assertEqual(wrong_type["error"]["code"], "INVALID_JSON_SHAPE")

    def test_config_and_doctor_only_print_and_keep_interpreter(self):
        for client in ("claude", "codex"):
            config = self.run_cli("config", "--client", client)
            self.assertFalse(config["writesSettings"])
            self.assertIn(os.path.abspath(sys.executable), config["registrationArgv"])
            self.assertIn(str(self.root.resolve()), config["registrationArgv"])
        doctor = self.run_cli("doctor")
        self.assertFalse(doctor["changedSettings"])
        self.assertEqual(doctor["python"]["executable"], os.path.abspath(sys.executable))
        self.assertFalse(self.root.exists(), "read-only config/doctor must not create the state directory")

    def test_outline_deck_persists_and_advances_one_page_at_a_time(self):
        self.create_project()
        source = "按大纲排版\n# CLI测试稿\n## 封面｜用户提供的封面\n结论：仅用于命令测试\n保留这段用户文字。\n## 内容｜用户提供的正文\n结论：按页完成\n正文来自明确输入。"
        self.run_cli("deck", "from-outline", "demo", "--file", "-", input_text=source)
        initial = self.run_cli("deck", "status", "demo")
        self.assertEqual(initial["totalPages"], 2)
        self.assertEqual(initial["completedPages"], 0)
        self.run_cli("deck", "control", "demo", "--action", "pause")
        paused = self.run_cli("deck", "step", "demo")
        self.assertFalse(paused["processed"])
        self.assertEqual(paused["deck"]["completedPages"], 0)
        self.run_cli("deck", "control", "demo", "--action", "resume")
        first = self.run_cli("deck", "step", "demo")
        self.assertTrue(first["processed"])
        self.assertEqual(first["deck"]["completedPages"], 1)
        second = self.run_cli("deck", "step", "demo")
        self.assertEqual(second["deck"]["completedPages"], 2)
        self.assertEqual(second["deck"]["status"], "complete")
        self.assertEqual(second["deck"]["revisionCount"], 0)
        exported = self.run_cli("export", "demo", "--format", "html")
        text = Path(exported["path"]).read_text(encoding="utf-8")
        self.assertIn("保留这段用户文字", text)
        self.assertIn("正文来自明确输入", text)

    def test_chat_rounds_batch_scope_and_quality_are_shared_across_processes(self):
        self.create_project()
        source = "按大纲排版\n# 命令轮次测试\n## 封面｜命令测试封面\n结论：测试原话\n这是程序测试。\n## 内容｜命令测试正文\n结论：检查范围\n这是明确测试材料。"
        first = self.run_cli("chat", "send", "demo", "--scope", "deck", "--client-message-id", "first", "--message", source)
        self.assertTrue(first["roundId"])
        for _ in range(2):
            self.run_cli("deck", "step", "demo")
        one = self.run_cli("delivery", "status", "demo")
        self.assertEqual((one["inputCount"], one["outputCount"]), (1, 1))
        self.assertEqual(self.run_cli("quality", "status", "demo")["browser"]["measured"], 0)
        message = "第1页：标题改为：命令指定第一标题；第2页：标题改为：命令指定第二标题"
        self.run_cli("chat", "send", "demo", "--scope", "deck", "--client-message-id", "second", "--message", message)
        duplicate = self.run_cli("chat", "send", "demo", "--scope", "deck", "--client-message-id", "second", "--message", message)
        self.assertTrue(duplicate["deduplicated"])
        for _ in range(2):
            self.run_cli("deck", "step", "demo")
        quality = self.run_cli("quality", "check", "demo", "--auto-fix")
        self.assertFalse(quality["readyToReview"])
        two = self.run_cli("delivery", "status", "demo")
        self.assertEqual((two["inputCount"], two["outputCount"]), (2, 2))
        self.assertEqual(set(two["rounds"][-1]["changedSlideIds"]), {"S001", "S002"})
        self.assertFalse(two["targetSatisfied"])


if __name__ == "__main__":
    unittest.main()
