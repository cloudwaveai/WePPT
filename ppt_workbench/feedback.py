"""Explicit, lossless routing of a user's feedback to existing page IDs.

This is a deterministic command parser, not an interpretation of ordinary chat.
It accepts ``整稿修改`` followed by page entries, or page entries starting on the
first nonempty line. Every nonempty line must be accounted for. A page's supplied
instruction remains its instruction; this module adds no facts or approvals.
"""
from __future__ import annotations

import copy
import re

from .core import EngineError


MAX_FEEDBACK_PAGES = 30
MAX_FEEDBACK_CHARS = 100_000
_PAGE = re.compile(r"第[ \t]*([0-9]+)[ \t]*页[ \t]*[:：]")
_PAGE_ATTEMPT = re.compile(r"第[^\r\n:：;；]{1,30}?页[ \t]*[:：]")
_NEXT_PAGE = re.compile(r"[;；][ \t]*(?=第(?:[ \t]*[0-9]+[ \t]*|[^\r\n;；]{0,30}?)页)")
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"|“[^”]*”|「[^」]*」|『[^』]*』|`[^`]*`')


def _error(message, code="INVALID_FEEDBACK", details=None):
    raise EngineError(code, message, details)


def validate_feedback_action(action):
    """Validate one standalone batch action and return a detached copy.

    Target existence, current content/scene revisions, and object membership
    are checked atomically by Studio, against the user's submission baseline.
    The action carries only routing and the supplied change instructions.
    """
    if not isinstance(action, dict) or set(action) != {"type", "edits"} or action.get("type") != "deck_feedback":
        _error("整稿反馈只接受 type=deck_feedback 和 edits；不能夹带审核、来源或其他字段。")
    edits = action["edits"]
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_FEEDBACK_PAGES:
        _error(f"整稿反馈需要 1 至 {MAX_FEEDBACK_PAGES} 个不同页面的修改。")
    seen = set()
    for index, edit in enumerate(edits, 1):
        if not isinstance(edit, dict) or not {"slide_id", "instruction"}.issubset(edit) or set(edit) - {"slide_id", "instruction", "object_id"}:
            _error(f"第 {index} 项只接受 slide_id、instruction 和可选 object_id。")
        for field in ("slide_id", "object_id"):
            if field not in edit:
                continue
            value = edit[field]
            if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 256 or "\n" in value or "\r" in value:
                _error(f"第 {index} 项的 {field} 必须为非空、无首尾空白的标识符。")
        instruction = edit["instruction"]
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > MAX_FEEDBACK_CHARS:
            _error(f"第 {index} 项需要非空的修改指令，最多 {MAX_FEEDBACK_CHARS:,} 字。")
        if edit["slide_id"] in seen:
            _error("同一页只能出现一次，请把这一页的要求合并为一条。", "FEEDBACK_DUPLICATE_PAGE", {"slideId": edit["slide_id"]})
        seen.add(edit["slide_id"])
    return copy.deepcopy(action)


def _segments(line):
    """Split only explicit next-page delimiters, preserving quoted literals."""
    quoted = [match.span() for match in _QUOTED.finditer(line)]
    start = 0
    for match in _NEXT_PAGE.finditer(line):
        if any(left <= match.start() < right for left, right in quoted):
            continue
        yield line[start:match.start()]
        start = match.end()
    yield line[start:]


def parse_feedback(message, outline):
    """Return a deck_feedback action, or None for ordinary conversation.

    Examples::

        整稿修改
        第1页：标题改为：用户指定的准确标题
        第4页：保留图片；正文只保留用户给出的三项

        第1页：标题改为：用户的标题；第4页：背景改为：#ffffff

    A bare single explicit page entry is also supported. Ordinary commands such
    as ``标题改为：...`` or ``请把第1页调整一下`` are left to the selected page or
    model executor. No unmatched preamble, trailing line, or malformed page
    entry is silently skipped. Numbers address the supplied visible page order,
    not a guess based on page IDs or titles.
    """
    if not isinstance(message, str):
        return None
    text = message.lstrip("\ufeff").strip()
    explicit = text.startswith("整稿修改")
    if explicit:
        text = text[len("整稿修改"):].lstrip()
        if text.startswith((":", "：")):
            text = text[1:].lstrip()
    elif not (_PAGE.match(text) or _PAGE_ATTEMPT.match(text)):
        return None
    if len(message) > MAX_FEEDBACK_CHARS:
        _error(f"整稿反馈超过 {MAX_FEEDBACK_CHARS:,} 字，请减少本轮内容。")
    if not text:
        _error("请写明每一页的修改，例如：第1页：标题改为：你的标题。")
    if not isinstance(outline, list) or any(not isinstance(page, dict) or not isinstance(page.get("id"), str) or not page["id"].strip() for page in outline):
        _error("无法取得明确的当前页面列表，请刷新后重试。", "INVALID_FEEDBACK_OUTLINE")
    if len({page["id"] for page in outline}) != len(outline):
        _error("当前页面列表有重复标识符，不能安全分派整稿反馈。", "INVALID_FEEDBACK_OUTLINE")

    edits = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        for raw in _segments(line):
            segment = raw.strip()
            match = _PAGE.match(segment)
            if not match:
                _error("每一行修改都需要明确页码，格式为“第1页：修改内容”；以下文字尚未分派，整批未执行。",
                       "FEEDBACK_UNPARSED_TEXT", {"line": line_number, "text": segment})
            if len(match.group(1)) > 8:
                _error("页码超出当前稿件范围，整批未执行。", "FEEDBACK_PAGE_NOT_FOUND", {"pageCount": len(outline)})
            number = int(match.group(1))
            if not 1 <= number <= len(outline):
                _error(f"第 {number} 页不存在；当前共有 {len(outline)} 页，整批未执行。",
                       "FEEDBACK_PAGE_NOT_FOUND", {"pageNumber": number, "pageCount": len(outline)})
            instruction = segment[match.end():].strip()
            if not instruction:
                _error(f"第 {number} 页没有修改指令，整批未执行。")
            # A second unquoted page header without a delimiter is ambiguous.
            # Reject instead of silently treating it as part of the first page.
            quoted = [quoted_match.span() for quoted_match in _QUOTED.finditer(instruction)]
            for extra in list(_PAGE.finditer(instruction)) + list(_PAGE_ATTEMPT.finditer(instruction)):
                if not any(left <= extra.start() < right for left, right in quoted):
                    _error("多个页面请用换行或分号分隔；这条反馈存在未分隔的页码，整批未执行。",
                           "FEEDBACK_UNPARSED_TEXT", {"line": line_number, "text": instruction})
            edits.append({"slide_id": outline[number - 1]["id"], "instruction": instruction})
    return validate_feedback_action({"type": "deck_feedback", "edits": edits})


def parse_feedback_with_intake(message, outline, *, page_count=None):
    """Parse an entirely explicit settings + page-feedback submission.

    A natural-language or otherwise unclassified line returns None so a real
    model can consider the *complete* message; the deterministic path never
    applies only the recognisable half. Malformed explicit page entries still
    raise the same errors as parse_feedback before any mutation is dispatched.
    """
    from .intake import is_intake_metadata_message, parse_intake_metadata
    if not isinstance(message, str):
        return None
    settings, feedback = [], []
    lines = [line.strip() for line in message.lstrip("\ufeff").splitlines() if line.strip()]
    if lines and lines[0] in {"补充设置", "补充设置：", "补充设置:", "补充项目设置", "补充项目设置：", "补充项目设置:"}:
        lines.pop(0)
    for line in lines:
        if is_intake_metadata_message(line):
            settings.append(line)
        elif line.startswith("整稿修改") or _PAGE.match(line) or _PAGE_ATTEMPT.match(line):
            feedback.append(line)
        else:
            return None
    if not settings or not feedback:
        return None
    # Parsing is complete before the caller begins its atomic mutation scope.
    action = parse_feedback("\n".join(feedback), outline)
    if action is None:
        return None
    parsed = parse_intake_metadata("\n".join(settings), page_count=len(outline) if page_count is None else page_count)
    return {"intake": parsed, "feedback": action}
