"""Local outline parsing tests: supplied material only, not model or UI acceptance."""
import copy
import json
from pathlib import Path
import unittest

from ppt_workbench.core import EngineError
from ppt_workbench.outline import PAGE_KINDS, parse_outline, validate_deck_plan


# Explicit source material about the project. This fixture is not an exported
# presentation, a model transcript, or a claim that UI acceptance has passed.
PROJECT_INTRO = """按大纲排版
# PPT 工作台：用对话逐页制作
用途：向体验者介绍项目
听众：产品使用者和团队负责人
Logo：不使用尚未提供的公司 Logo

## 封面｜PPT 工作台
结论：把想法、页面和修改连在一起
项目介绍 · 功能验收材料
2026 年 10 月 25 日

## 目录｜这次介绍什么
结论：从使用问题到制作流程
为什么需要这套工作台
怎样逐页完成演示稿
现在能做什么，哪些还需验证

## 章节｜第一章：从真实内容开始
结论：观点由用户提供，表达和页面逐步打磨
先明确用途、听众和逐页想法。
缺少数据或素材时明确待补项。

## 对比｜两种对话入口
结论：使用同一份项目与页面记录
网页对话
在浏览器提出要求并查看当前页。

Coding Agent 对话
通过 CLI 或 MCP 操作指定项目与页面。

## 并列｜每页都保留什么
结论：原始想法、拟用表达和页面对象分别记录
用户原话
标题、结论与正文
可编辑对象及版本

## 流程｜从大纲到整套初稿
结论：按计划逐页生成，生成完成后再集中反馈
提供用途与逐页大纲
保存页序与本页内容
生成当前页并显示预览
继续下一页，直至初稿完成

## 内容｜怎样精确修改
结论：指定页面和对象，再说清要改的属性
选中标题后，可以只改字号或措辞。
页面对象具有独立 ID。
版本冲突会阻止旧请求覆盖新结果。

## 章节｜第二章：看清能力范围
结论：把可用能力与待验证部分写明
用真实产物检查表达和版式。
不把规则目录当作全部完成的模板效果。

## 内容｜当前能力与验证边界
结论：已有真实页面与导出能力
54 条模板知识，基础程序化版式覆盖常用页面类型。
HTML 预览和可编辑 PPTX 导出已有实现。
0.2 版本运行过 64 项自动化测试。
真实模型全 UI 整稿验收仍需另行完成。

## 结束｜从你的第一份真实大纲开始
结论：先做一套，再按具体页面反馈
提供用途、听众、逐页想法和真实资料。
在预览中指出需要改的位置。
验收目标：整稿修改反馈不超过三次。
"""


class OutlineTests(unittest.TestCase):
    def assert_invalid(self, source):
        with self.assertRaises(EngineError) as caught:
            parse_outline(source)
        self.assertEqual(caught.exception.code, "INVALID_OUTLINE")
        self.assertTrue(caught.exception.message)

    def test_does_not_silently_turn_ordinary_chat_into_local_generation(self):
        for message in (None, 123, "", "请帮我做个 PPT", "请按大纲排版", "这里引用一句话：\n按大纲排版\n# 标题"):
            with self.subTest(message=message):
                self.assertIsNone(parse_outline(message))

    def test_ten_page_project_fixture_preserves_order_and_source_text(self):
        plan = parse_outline(PROJECT_INTRO)
        self.assertEqual(plan["execution"], "outline")
        self.assertEqual(plan["title"], "PPT 工作台：用对话逐页制作")
        self.assertEqual(len(plan["pages"]), 10)
        self.assertEqual(plan["pages"][0]["role"], "cover")
        self.assertEqual(plan["pages"][-1]["role"], "ending")
        self.assertEqual(plan["pages"][5]["title"], "从大纲到整套初稿")
        self.assertEqual(plan["pages"][3]["key_points"], "网页对话\n在浏览器提出要求并查看当前页。\n\nCoding Agent 对话\n通过 CLI 或 MCP 操作指定项目与页面。")
        self.assertIn("0.2 版本运行过 64 项自动化测试。", plan["pages"][8]["key_points"])
        self.assertIn("真实模型全 UI 整稿验收仍需另行完成。", plan["pages"][8]["key_points"])
        # Original page segments remain available; preamble stays in the
        # authoritative chat source and is never silently made into body text.
        for page in plan["pages"]:
            self.assertIn(page["user_intent"].strip(), PROJECT_INTRO)
            self.assertNotIn("听众：产品使用者", page["key_points"])
        self.assertEqual(set(plan), {"title", "execution", "pages"})

    def test_every_supported_kind_uses_a_real_known_template(self):
        source = "按大纲排版：\n# 类型检查\n" + "\n".join(f"## {kind}|第 {n} 页\n只使用用户提供的正文。" for n, kind in enumerate(PAGE_KINDS, 1))
        pages = parse_outline(source)["pages"]
        data = json.loads((Path(__file__).resolve().parents[1]/"ppt_workbench/data/template-rules.json").read_text())
        known = {template["id"] for template in data["templates"]}
        self.assertEqual(len(pages), len(PAGE_KINDS))
        self.assertTrue(all(page["template_id"] in known for page in pages))
        self.assertEqual(pages[3]["template_id"], "compare")
        self.assertEqual(pages[4]["template_id"], "parallel")

    def test_markdown_fences_and_blank_lines_are_material_not_extra_pages(self):
        source = """按大纲排版
# 格式示例
## 内容｜保留材料
结论: 不解析代码围栏里的标题
原始例子：
```markdown
## 封面｜这不是新页面
结论：这不是页面结论
```

- 用户的第一项
- 用户的第二项
## 结束｜结束
谢谢阅读。
"""
        pages = parse_outline(source)["pages"]
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0]["takeaway"], "不解析代码围栏里的标题")
        self.assertIn("## 封面｜这不是新页面\n结论：这不是页面结论", pages[0]["key_points"])
        self.assertIn("```\n\n- 用户的第一项", pages[0]["key_points"])

    def test_incomplete_or_ambiguous_outline_has_a_specific_error(self):
        bad = [
            "按大纲排版", "按大纲排版\n## 内容｜页\n正文", "按大纲排版\n# 标题\n",
            "按大纲排版\n# 标题\n## 内容｜只有一页\n正文",
            "按大纲排版\n# 标题\n## 内容｜标题\n\n## 结束｜结尾\n正文",
            "按大纲排版\n# 标题\n## 类型不存在｜标题\n正文",
            "按大纲排版\n# 标题\n## 内容｜\n正文",
            "按大纲排版\n# 标题\n## 标题但没有类型\n正文",
            "按大纲排版\n# 标题\n## 内容｜页\n结论：\n正文",
            "按大纲排版\n# 标题\n## 内容｜页\n结论：甲\n结论：乙\n正文",
            "按大纲排版\n# 标题\n# 第二个整稿标题\n## 内容｜页\n正文",
            "按大纲排版\n# 标题\n## 内容｜页\n```\n未结束",
        ]
        for source in bad:
            with self.subTest(source=source):
                self.assert_invalid(source)

    def test_page_limit_and_duplicate_titles_keep_distinct_page_positions(self):
        for count in (2, 30):
            source = "按大纲排版\n# 计划\n" + "\n".join(f"## 内容｜相同标题\n第 {n} 页的真实原文" for n in range(count))
            plan = parse_outline(source)
            self.assertEqual(len(plan["pages"]), count)
            self.assertEqual(len({p["key_points"] for p in plan["pages"]}), count)
        self.assert_invalid("按大纲排版\n# 计划\n" + "\n".join("## 内容｜页\n正文" for _ in range(31)))
        self.assert_invalid("按大纲排版\n# 计划\n" + "正"*100_001)

    def test_page_evidence_controls_preserve_source_without_becoming_body(self):
        source = "按大纲排版\n# 明确元信息测试\n## 内容｜第一页\n依据要求：需要核验\n结论：这是实际正文\n保留这句话。\n## 内容｜第二页\n结论：代码示例应保留\n```text\n依据要求：这是一段代码示例\n```"
        plan = parse_outline(source)
        self.assertIn("依据要求：需要核验", plan["pages"][0]["user_intent"])
        self.assertNotIn("依据要求", plan["pages"][0]["key_points"])
        self.assertIn("保留这句话", plan["pages"][0]["key_points"])
        self.assertIn("依据要求：这是一段代码示例", plan["pages"][1]["key_points"])

    def test_plan_validation_rejects_approval_source_and_bad_values(self):
        good = parse_outline(PROJECT_INTRO)
        invalid = [None, {**good, "source_message": "伪造用户原话"}, {**good, "execution": "anything"},
                   {**good, "pages": []}, {**good, "pages": True}]
        for key, value in [("approved", True), ("role", "admin"), ("user_intent", ""), ("key_points", ["不是字符串"])]:
            changed = copy.deepcopy(good)
            changed["pages"][0][key] = value
            invalid.append(changed)
        for plan in invalid:
            with self.subTest(plan=plan), self.assertRaises(EngineError) as caught:
                validate_deck_plan(plan)
            self.assertEqual(caught.exception.code, "INVALID_DECK_PLAN")
        copied = validate_deck_plan(good)
        copied["pages"][0]["title"] = "修改拷贝"
        self.assertEqual(good["pages"][0]["title"], "PPT 工作台")


if __name__ == "__main__":
    unittest.main()
