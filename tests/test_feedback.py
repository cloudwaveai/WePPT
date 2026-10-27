"""Strict explicit batch routing, including inputs we must never partly apply."""
import copy
import unittest

from ppt_workbench.core import EngineError
from ppt_workbench.feedback import parse_feedback, parse_feedback_with_intake, validate_feedback_action


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        # IDs intentionally differ from visible page numbers.
        self.outline = [{"id": sid, "title": title} for sid, title in [
            ("S004", "封面"), ("S010", "重复标题"), ("S015", "重复标题"), ("S021", "结束")]]

    def error(self, code, fn, *args):
        with self.assertRaises(EngineError) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_explicit_prefix_uses_visible_page_order_and_keeps_words(self):
        message = "整稿修改\n第1页：标题改为：用户自己的主题\n第4页：保留图片；正文保留原文， 不要补写成效。"
        result = parse_feedback(message, self.outline)
        self.assertEqual(result, {"type": "deck_feedback", "edits": [
            {"slide_id": "S004", "instruction": "标题改为：用户自己的主题"},
            {"slide_id": "S021", "instruction": "保留图片；正文保留原文， 不要补写成效。"}]})

    def test_first_line_explicit_entries_and_semicolon_variant(self):
        expected = {"type": "deck_feedback", "edits": [
            {"slide_id": "S004", "instruction": "标题改为：A：B"},
            {"slide_id": "S021", "instruction": "背景改为：#ffffff"}]}
        for separator in ("\n", ";", "；", "；   "):
            with self.subTest(separator=separator):
                self.assertEqual(parse_feedback("第1页：标题改为：A：B" + separator + "第4页：背景改为：#ffffff", self.outline), expected)

    def test_colon_prefix_blank_lines_crlf_and_single_explicit_page(self):
        for message in ("\ufeff\n整稿修改：\r\n\r\n第 01 页: 标题改为：保留  双空格\r\n", "整稿修改：第1页：标题改为：保留  双空格", "第1页：标题改为：保留  双空格"):
            with self.subTest(message=message):
                self.assertEqual(parse_feedback(message, self.outline)["edits"], [{"slide_id": "S004", "instruction": "标题改为：保留  双空格"}])

    def test_normal_single_page_chat_and_embedded_page_example_are_not_commands(self):
        for message in (None, {}, "", "标题改为：新的标题", "请把第1页调整一下", "第1页能更简洁吗？", "你看这样行吗？\n第1页：标题改为：只是例子", "这是整稿修改的建议"):
            with self.subTest(message=message):
                self.assertIsNone(parse_feedback(message, self.outline))

    def test_quoted_page_marker_is_literal_instruction_not_new_target(self):
        for quote, close in (("“", "”"), ('"', '"'), ("「", "」"), ("`", "`")):
            instruction = "标题改为：" + quote + "第1页：开场；第2页：介绍" + close
            result = parse_feedback("第1页：" + instruction + "；第4页：标题改为：结束", self.outline)
            self.assertEqual(result["edits"][0]["instruction"], instruction)
            self.assertEqual(len(result["edits"]), 2)

    def test_unmatched_lines_and_inline_page_markers_are_not_discarded(self):
        for message in ("整稿修改\n请整体改得更好看\n第1页：标题改为：A", "第1页：标题改为：A\n另加一页", "第1页：标题改为：A 第4页：标题改为：B", "第1页：标题改为：A；第4页 正文", "整稿修改\n第x页：标题改为：A"):
            with self.subTest(message=message):
                self.error("FEEDBACK_UNPARSED_TEXT", parse_feedback, message, self.outline)

    def test_unknown_or_zero_page_rejected(self):
        for number in (0, 5, 999):
            self.error("FEEDBACK_PAGE_NOT_FOUND", parse_feedback, f"第1页：标题改为：A\n第{number}页：标题改为：B", self.outline)
        self.error("FEEDBACK_PAGE_NOT_FOUND", parse_feedback, "第" + "9" * 5000 + "页：过长页码也应明确拒绝", self.outline)
        self.error("FEEDBACK_PAGE_NOT_FOUND", parse_feedback, "第1页：保留；第" + "9" * 5000 + "页：过长页码也应明确拒绝", self.outline)

    def test_empty_instruction_or_missing_entries_rejected(self):
        for message in ("整稿修改", "整稿修改：", "第1页：", "第1页：；第4页：标题改为：B", "第1页：标题改为：A\n第4页：  "):
            self.error("INVALID_FEEDBACK", parse_feedback, message, self.outline)

    def test_duplicate_page_rejected_even_different_number_spelling(self):
        self.error("FEEDBACK_DUPLICATE_PAGE", parse_feedback, "第1页：标题改为：A；第01页：背景改为：#fff", self.outline)

    def test_invalid_outline_rejected_only_when_feedback_is_explicit(self):
        for outline in (None, [{"title": "无ID"}], [{"id": "S1"}, {"id": "S1"}]):
            self.error("INVALID_FEEDBACK_OUTLINE", parse_feedback, "第1页：标题改为：A", outline)
            self.assertIsNone(parse_feedback("普通聊天", outline))

    def test_valid_action_is_detached_and_object_scope_is_preserved(self):
        action = {"type": "deck_feedback", "edits": [{"slide_id": "S004", "instruction": " 保留原始措辞。 ", "object_id": "title"}]}
        original = copy.deepcopy(action)
        clean = validate_feedback_action(action)
        self.assertEqual(clean, original)
        clean["edits"][0]["instruction"] = "only detached copy changed"
        self.assertEqual(action, original)

    def test_strict_action_fields_do_not_accept_approval_or_source_metadata(self):
        valid = {"type": "deck_feedback", "edits": [{"slide_id": "S004", "instruction": "标题改为：A"}]}
        for key in ("approval", "approved", "source", "sourceText", "review", "project_update"):
            for nested in (False, True):
                action = copy.deepcopy(valid)
                (action["edits"][0] if nested else action)[key] = "untrusted"
                self.error("INVALID_FEEDBACK", validate_feedback_action, action)

    def test_invalid_action_shapes_and_values_rejected(self):
        bad = [None, [], {}, {"type": "deck_feedback", "edits": []}, {"type": "deck_feedback", "edits": ()},
               {"type": "deck_feedback", "edits": [{"slideId": "S004", "instruction": "A"}]},
               {"type": "scene_patch", "edits": [{"slide_id": "S004", "instruction": "A"}]}]
        for field, values in (("slide_id", (None, True, "", " S004 ", "S004\nS010")), ("instruction", (None, [], True, "", " \t\n")), ("object_id", (None, False, [], "", " title "))):
            for value in values:
                edit = {"slide_id": "S004", "instruction": "A"}
                edit[field] = value
                bad.append({"type": "deck_feedback", "edits": [edit]})
        for action in bad:
            with self.subTest(action=action):
                self.error("INVALID_FEEDBACK", validate_feedback_action, action)

    def test_limit_is_thirty_distinct_pages(self):
        edits = [{"slide_id": f"S{i:03d}", "instruction": "用户指定的修改"} for i in range(1, 31)]
        self.assertEqual(len(validate_feedback_action({"type": "deck_feedback", "edits": edits})["edits"]), 30)
        self.error("INVALID_FEEDBACK", validate_feedback_action, {"type": "deck_feedback", "edits": edits + [{"slide_id": "S031", "instruction": "A"}]})
        self.error("FEEDBACK_DUPLICATE_PAGE", validate_feedback_action, {"type": "deck_feedback", "edits": [edits[0], edits[0]]})

    def test_explicit_settings_and_page_feedback_are_parsed_as_one_complete_input(self):
        result = parse_feedback_with_intake("补充设置\n用途：介绍项目\n本稿各页依据要求：无需外部依据\n整稿修改\n第1页：标题改为：用户原话；第4页：标题改为：明确结束", self.outline)
        self.assertEqual(result["intake"]["projectChanges"]["purposeOther"], "介绍项目")
        self.assertEqual(result["intake"]["pageEvidence"], {1: "no", 2: "no", 3: "no", 4: "no"})
        self.assertEqual(result["feedback"]["edits"], [{"slide_id": "S004", "instruction": "标题改为：用户原话"}, {"slide_id": "S021", "instruction": "标题改为：明确结束"}])

    def test_mixed_natural_language_is_not_partly_parsed_as_explicit_commands(self):
        self.assertIsNone(parse_feedback_with_intake("用途：介绍项目\n第1页：标题改为：A\n另外设计一个更好的信息结构", self.outline))
        self.assertIsNone(parse_feedback_with_intake("用途：介绍项目\n请优化第3页", self.outline))
        self.error("FEEDBACK_PAGE_NOT_FOUND", parse_feedback_with_intake, "用途：介绍项目\n第8页：标题改为：未知页", self.outline)


if __name__ == "__main__":
    unittest.main()
