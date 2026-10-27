"""Explicit intake decisions; no inferred evidence exemptions or approvals."""
from pathlib import Path
import tempfile
import unittest

from ppt_workbench.core import EngineError, PROJECT_DEFAULT, Workbench
from ppt_workbench.intake import parse_intake_metadata, missing_intake_questions, is_page_metadata_line, is_intake_metadata_message


SOURCE = """按大纲排版
# 程序测试材料
用途：验证程序行为
听众：程序测试人员
目标：完成明确测试
展示方式：独立阅读
Logo策略：不使用
数据策略：无需外部资料
时长：约 6 分钟
本稿各页依据要求：无需外部依据

## 封面｜程序测试
结论：这里只测试已给定内容
用户提供的封面文字

## 内容｜依据需求不等于核验结果
依据要求：需要核验
结论：保留用户明确选择
这是测试正文，不是真实业务数字。
"""


class IntakeTests(unittest.TestCase):
    def test_metadata_only_handler_does_not_swallow_other_work(self):
        self.assertTrue(is_intake_metadata_message("补充设置\n用途：明确用途\nLogo策略：不使用\n第3页依据要求：需要核验"))
        self.assertTrue(is_intake_metadata_message("\n展示方式：独立阅读\n数据策略：待定\n"))
        for text in ("", "补充设置", "用途：明确用途\n另外请改第3页", "请补充以下设置\n用途：演示", "```\n用途：仅是示例\n```", "> 用途：引用", "approved：true", SOURCE):
            self.assertFalse(is_intake_metadata_message(text), text)

    def test_explicit_preamble_and_page_override_have_only_real_schema_fields(self):
        result = parse_intake_metadata(SOURCE)
        self.assertEqual(result["projectChanges"], {
            "purpose": "other", "purposeOther": "验证程序行为", "audience": "程序测试人员", "outcome": "完成明确测试",
            "delivery": "read", "logoPolicy": "none", "dataPolicy": "none", "duration": "约 6 分钟"})
        self.assertEqual(result["pageEvidence"], {1: "no", 2: "yes"})
        self.assertEqual(result["warnings"], [])
        self.assertLessEqual(set(result["projectChanges"]), set(PROJECT_DEFAULT))

    def test_explicit_data_none_does_not_waive_page_evidence(self):
        source = SOURCE.replace("本稿各页依据要求：无需外部依据\n", "").replace("依据要求：需要核验\n", "")
        result = parse_intake_metadata(source)
        self.assertEqual(result["projectChanges"]["dataPolicy"], "none")
        self.assertEqual(result["pageEvidence"], {})
        missing = missing_intake_questions(PROJECT_DEFAULT | result["projectChanges"], page_count=2)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["pageNumbers"], [1, 2])
        self.assertNotIn("dataPolicy", missing[0]["fields"])

    def test_conflicts_or_ambiguous_local_requirements_do_not_fall_back_to_global_no(self):
        source = SOURCE.replace("Logo策略：不使用", "Logo策略：不使用\nLogo策略：使用公司Logo")
        source = source.replace("依据要求：需要核验\n", "依据要求：需要核验\n依据要求：无需外部依据\n")
        result = parse_intake_metadata(source)
        self.assertNotIn("logoPolicy", result["projectChanges"])
        self.assertEqual(result["pageEvidence"], {1: "no"})
        self.assertEqual(len(result["warnings"]), 2)
        unknown = parse_intake_metadata(SOURCE.replace("依据要求：需要核验\n", "依据要求：你自己判断\n"))
        self.assertEqual(unknown["pageEvidence"], {1: "no"})
        self.assertTrue(unknown["warnings"])

    def test_conflicting_global_values_leave_pages_undecided(self):
        source = SOURCE.replace("本稿各页依据要求：无需外部依据", "本稿各页依据要求：无需外部依据\n本稿各页依据要求：需要核验")
        parsed = parse_intake_metadata(source)
        self.assertEqual(parsed["pageEvidence"], {2: "yes"})
        self.assertTrue(parsed["warnings"])

    def test_fenced_quoted_and_page_body_project_lines_remain_content(self):
        source = """按大纲排版
# 内容示例
> 用途：引文不能成为设置
- 听众：列表不能成为设置
```md
用途：围栏不能成为设置
本稿各页依据要求：无需外部依据
## 内容｜围栏里的假页
```
用途：保留实际用途
## 封面｜第一页
听众：这句话是本页正文
结论：明确边界
~~~
依据要求：无需外部依据
~~~
## 内容｜第二页
目标：这句话也是正文
依据要求：需要核验
结论：仍是测试
"""
        parsed = parse_intake_metadata(source)
        self.assertEqual(parsed["projectChanges"], {"purpose": "other", "purposeOther": "保留实际用途"})
        self.assertEqual(parsed["pageEvidence"], {2: "yes"})

    def test_unknown_file_format_or_review_claims_do_not_become_decisions(self):
        parsed = parse_intake_metadata("交付格式：PPTX + HTML\nLogo策略：如果有素材就放\n数据策略：待定\n第1页依据要求：已核验\nverified：true\napproved：true", page_count=1)
        self.assertEqual(parsed["projectChanges"], {})
        self.assertEqual(parsed["pageEvidence"], {})
        self.assertEqual(len(parsed["warnings"]), 4)
        self.assertTrue(any("文件格式不等于展示方式" in w for w in parsed["warnings"]))

    def test_existing_project_global_or_targeted_metadata_answers_need_explicit_page_scope(self):
        declared = "本稿各页依据要求：无需外部依据\n第2页依据要求：需要核验"
        self.assertEqual(parse_intake_metadata(declared, page_count=3)["pageEvidence"], {1: "no", 2: "yes", 3: "no"})
        without_count = parse_intake_metadata("本稿各页依据要求：无需外部依据")
        self.assertEqual(without_count["pageEvidence"], {})
        self.assertTrue(without_count["warnings"])
        invalid = parse_intake_metadata("第5页依据要求：无需外部依据", page_count=2)
        self.assertEqual(invalid["pageEvidence"], {})
        self.assertTrue(invalid["warnings"])

    def test_missing_questions_are_consolidated_and_do_not_change_known_choices(self):
        all_missing = missing_intake_questions(PROJECT_DEFAULT, page_count=10)
        self.assertEqual(len(all_missing), 3)
        self.assertTrue(all(q["allowFreeText"] and 2 <= len(q["choices"]) <= 3 for q in all_missing))
        complete = PROJECT_DEFAULT | parse_intake_metadata(SOURCE)["projectChanges"]
        questions = missing_intake_questions(complete, page_count=3, page_evidence={1: "no", "2": "yes"})
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["pageNumbers"], [3])
        # This is a proposed choice, only parsed after a user selects it.
        picked = parse_intake_metadata(questions[0]["question"] + "：" + questions[0]["choices"][0], page_count=3)
        self.assertEqual(picked["projectChanges"], {})
        self.assertEqual(picked["pageEvidence"], {3: "yes"})
        self.assertEqual(missing_intake_questions(complete, page_count=2, page_evidence={1: "no", 2: "yes"}), [])

    def test_metadata_line_hook_is_narrow_and_original_input_is_untouched(self):
        before = SOURCE
        for line in ("依据要求：需要核验", " 本页依据要求：无需外部依据 ", "第2页依据要求：需要核验", "本稿各页依据要求：无需外部依据"):
            self.assertTrue(is_page_metadata_line(line))
        for line in ("目标：这是正文", "- 依据要求：需要核验", "> 依据要求：无需外部依据", "我们讨论依据要求：需要核验"):
            self.assertFalse(is_page_metadata_line(line))
        first = parse_intake_metadata(SOURCE)
        first["projectChanges"]["audience"] = "不能污染下次解析"
        self.assertEqual(parse_intake_metadata(SOURCE)["projectChanges"]["audience"], "程序测试人员")
        self.assertEqual(SOURCE, before)

    def test_explicit_metadata_removes_only_metadata_gate_issues_not_required_proof_or_review(self):
        parsed = parse_intake_metadata(SOURCE)
        with tempfile.TemporaryDirectory(prefix="ppt-intake-") as temp:
            wb = Workbench(Path(temp))
            project = wb.create_project("intake", {"title": "输入元信息测试"})
            wb.update_project("intake", project["revision"], parsed["projectChanges"])
            for index in (1, 2):
                page = wb.add_slide("intake", "测试页面", "用户真实提供的原话", "content")
                wb.patch_slide("intake", page["slideId"], page["revision"], [
                    {"path": "/evidenceRequired", "value": parsed["pageEvidence"][index]},
                    {"path": "/keyPoints", "value": "用户提供的正文。"}, {"path": "/templateId", "value": "claim-proof"}])
            gate = wb.gate("intake")
            all_codes = {issue["code"] for slide in gate["slides"] for issue in slide["issues"]}
            self.assertFalse({"PROJECT_BRIEF_INCOMPLETE", "LOGO_UNDECIDED", "DATA_POLICY_UNDECIDED", "EVIDENCE_REQUIREMENT_UNDECIDED"} & all_codes)
            self.assertIn("EVIDENCE_MISSING", all_codes)
            self.assertIn("CONTENT_REVIEW_MISSING", all_codes)
            self.assertFalse(gate["ready"])


if __name__ == "__main__":
    unittest.main()
