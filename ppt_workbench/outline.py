"""Explicit, deterministic Markdown outline input; this module never calls a model.

The caller keeps the original chat message as the authoritative source. Parsing
only assigns the supplied text to page slots; it does not invent wording, facts,
illustrations, or an approval. Heading kinds choose existing basic renderers.
"""
from __future__ import annotations

import json
import re

from .core import EngineError, ROLES
from .intake import is_page_metadata_line

MAX_OUTLINE_CHARS = 100_000
MAX_DECK_PLAN_BYTES = 1024 * 1024
MIN_DECK_PAGES = 2
MAX_DECK_PAGES = 30
PAGE_KINDS = {
    "封面": ("cover", "cover"),
    "目录": ("toc", "toc"),
    "章节": ("chapter", "chapter"),
    "对比": ("content", "compare"),
    "并列": ("content", "parallel"),
    "流程": ("content", "process"),
    "内容": ("content", "claim-proof"),
    "结束": ("ending", "ending"),
}


def _error(message, code="INVALID_OUTLINE", details=None):
    raise EngineError(code, message, details)


def validate_deck_plan(plan, *, error_code="INVALID_DECK_PLAN"):
    """Check plan shape without trusting its provenance; return a detached copy.

    Source attribution and project/slide mutations belong to Studio. A plan does
    not assert that the user authored its proposed wording or approved it.
    """
    try:
        encoded = json.dumps(plan, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_DECK_PLAN_BYTES:
            _error("整稿计划过大，请减少每页材料或拆分演示。", error_code)
        clean = json.loads(encoded)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        _error("整稿计划必须是有效 JSON 对象。", error_code)
    if not isinstance(clean, dict) or not {"title", "pages", "execution"}.issubset(clean) or set(clean) - {"title", "pages", "execution", "design", "strategy"}:
        _error("整稿计划需要且只接受 title、pages、execution。", error_code)

    if "design" in clean:
        from .page_design import validate_design
        validate_design(clean["design"])

    if "strategy" in clean:
        from .deck_design import validate_strategy
        validate_strategy(clean["strategy"])

    def text(value, field, required=True):
        if not isinstance(value, str) or len(value) > MAX_OUTLINE_CHARS or (required and not value.strip()):
            _error(f"整稿计划的 {field} 必须为有效文本。", error_code)

    text(clean["title"], "title")
    if not isinstance(clean["execution"], str) or clean["execution"] not in {"agent", "outline"}:
        _error("整稿 execution 只能为 agent 或 outline。", error_code)
    if not isinstance(clean["pages"], list) or not MIN_DECK_PAGES <= len(clean["pages"]) <= MAX_DECK_PAGES:
        _error(f"整稿需要 {MIN_DECK_PAGES} 至 {MAX_DECK_PAGES} 页。", error_code)
    required = {"title", "user_intent", "role"}
    optional = {"template_id", "takeaway", "key_points", "diagram", "composition", "designBrief", "template_images"}
    for number, page in enumerate(clean["pages"], 1):
        if not isinstance(page, dict) or not required.issubset(page) or set(page) - required - optional:
            extra = sorted(set(page) - required - optional) if isinstance(page, dict) else []
            _error(f"第 {number} 页字段不符合整稿计划协议。", error_code, {"page": number, "unknownFields": extra})
        text(page["title"], f"第 {number} 页 title")
        text(page["user_intent"], f"第 {number} 页 user_intent")
        if not isinstance(page["role"], str) or page["role"] not in ROLES - {""}:
            _error(f"第 {number} 页 role 无效。", error_code)
        for field in optional - {"diagram", "composition", "designBrief", "template_images"}:
            if field in page:
                text(page[field], f"第 {number} 页 {field}", required=False)
        if "template_images" in page:
            ids = page['template_images']
            if not isinstance(ids, list) or len(ids) > 3 or any(not isinstance(a, str) or not a or len(a) > 100 for a in ids):
                _error(f"第 {number} 页 template_images 需要最多 3 个本项目图片 ID。", error_code)
        if "composition" in page:
            from .page_design import validate_composition
            validate_composition(page["composition"])
            if "designBrief" in page or "strategy" in clean:
                from .deck_design import normalize_brief
                page["designBrief"] = normalize_brief(page.get("designBrief"), page["composition"], page.get("title", ""))
        if "designBrief" in page:
            from .deck_design import validate_brief
            validate_brief(page["designBrief"])
        elif "strategy" in clean:
            _error(f"第 {number} 页缺少 designBrief。", error_code)
        if "diagram" in page:
            from .diagram_design import validate_spec
            validate_spec(page['diagram'])
    return clean


def parse_outline(message):
    """Parse only an explicitly requested local outline, otherwise return None.

    Format: first nonempty line ``按大纲排版``; one ``# 整稿标题``; then
    ``## 类型｜页标题`` and supplied page text. ``结论：...`` assigns takeaway.
    Other lines remain in key_points, including blank lines and list markers.
    Explicit per-page evidence policy lines stay in user_intent but are not
    painted as slide body text. Preamble choices are applied separately by the
    intake controller; this parser itself does not mutate a project.
    """
    if not isinstance(message, str):
        return None
    lines = message.lstrip("\ufeff").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or not re.fullmatch(r"按大纲排版\s*[：:]?", lines[0].strip()):
        return None
    if len(message) > MAX_OUTLINE_CHARS:
        _error("大纲超过 100,000 字，请拆分材料。")

    title = None
    pages = []
    current = None
    fence = None

    def finish_page():
        if current is None:
            return
        raw_lines = current["lines"]
        body = []
        takeaway = None
        page_fence = None
        for line in raw_lines[1:]:
            stripped = line.lstrip()
            fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
            if page_fence:
                if fence_match and fence_match.group(1)[0] == page_fence[0] and len(fence_match.group(1)) >= len(page_fence):
                    page_fence = None
                body.append(line)
                continue
            if fence_match:
                page_fence = fence_match.group(1)
                body.append(line)
                continue
            if is_page_metadata_line(line):
                continue
            conclusion = re.fullmatch(r"\s*结论[：:]\s*(.*)", line)
            if conclusion:
                if takeaway is not None:
                    _error(f"第 {len(pages) + 1} 页出现多条“结论”，请只保留一条，其余移入正文。")
                takeaway = conclusion.group(1)
                if not takeaway.strip():
                    _error(f"第 {len(pages) + 1} 页的结论为空。")
            else:
                body.append(line)
        points = "\n".join(body).strip("\n")
        if not points.strip() and not takeaway:
            _error(f"第 {len(pages) + 1} 页只有标题，请补充本页内容或结论。")
        role, template = PAGE_KINDS[current["kind"]]
        page = {"title": current["title"], "user_intent": "\n".join(raw_lines).strip("\n"),
                "role": role, "template_id": template, "key_points": points}
        if takeaway is not None:
            page["takeaway"] = takeaway
        pages.append(page)

    for line in lines[1:]:
        stripped = line.lstrip()
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence:
            if fence_match and fence_match.group(1)[0] == fence[0] and len(fence_match.group(1)) >= len(fence):
                fence = None
            if current is not None:
                current["lines"].append(line)
            continue
        if fence_match:
            fence = fence_match.group(1)
            if current is not None:
                current["lines"].append(line)
            continue
        deck_heading = re.fullmatch(r"#\s+(.+?)\s*", line)
        if deck_heading:
            if title is not None or current is not None:
                _error("整稿标题只写一次，放在所有页面之前：# 整稿标题。")
            title = deck_heading.group(1).strip()
            continue
        if re.match(r"^##(?:\s|$)", line):
            if title is None:
                _error("请先写整稿标题，例如：# 项目介绍。")
            match = re.fullmatch(r"##\s+([^｜|]+)[｜|](.+?)\s*", line)
            if not match or not match.group(2).strip():
                _error("页面标题格式为：## 类型｜页标题，例如：## 内容｜核心能力。")
            kind, page_title = match.group(1).strip(), match.group(2).strip()
            if kind not in PAGE_KINDS:
                _error("页面类型不支持，请选择：" + "、".join(PAGE_KINDS) + "。", details={"kind": kind})
            finish_page()
            current = {"kind": kind, "title": page_title, "lines": [line]}
            continue
        if current is not None:
            current["lines"].append(line)
    if fence:
        _error("大纲中有未结束的代码围栏，请补上结尾标记。")
    finish_page()
    if not title:
        _error("请提供整稿标题，例如：# 项目介绍。")
    return validate_deck_plan({"title": title, "pages": pages, "execution": "outline"}, error_code="INVALID_OUTLINE")
