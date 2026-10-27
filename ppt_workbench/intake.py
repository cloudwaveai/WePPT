"""Parse explicit intake declarations without inventing project decisions.

Only standalone, named metadata lines are read. Project fields belong to the
outline preamble. Page evidence requirements are declarations of what needs
checking, never evidence-verification results or operator approvals. Callers
keep the complete original input, including metadata, as its source record.
"""
from __future__ import annotations

import re

from .core import EngineError, PROJECT_DEFAULT


_ALIASES = {
    "用途": "purpose", "主要用途": "purpose",
    "听众": "audience", "受众": "audience", "主要听众": "audience",
    "目标": "outcome", "预期结果": "outcome",
    "展示方式": "delivery", "使用方式": "delivery", "交付方式": "delivery", "交付格式": "delivery",
    "时长": "duration", "讲述时长": "duration", "预计时长": "duration",
    "logo": "logoPolicy", "logo策略": "logoPolicy", "标志策略": "logoPolicy",
    "数据策略": "dataPolicy", "资料策略": "dataPolicy", "资料来源策略": "dataPolicy",
}
_DELIVERY = {
    "live": "live", "现场讲述": "live", "现场讲解": "live", "现场演示": "live",
    "read": "read", "独立阅读": "read", "自行阅读": "read",
    "both": "both", "两者兼用": "both", "现场讲述与独立阅读": "both", "现场讲解与独立阅读": "both",
}
_LOGO = {
    "none": "none", "不使用": "none", "不用": "none", "不使用logo": "none", "不用logo": "none",
    "无logo": "none", "本次不使用logo": "none", "不使用公司logo": "none",
    "company": "company", "公司logo": "company", "使用公司logo": "company", "使用准确的公司logo": "company",
    "joint": "joint", "联合logo": "joint", "联合品牌logo": "joint", "使用联合logo": "joint", "使用联合品牌logo": "joint",
}
_DATA = {
    "user": "user", "用户提供": "user", "用户提供真实资料": "user", "仅使用用户提供的资料": "user",
    "research": "research", "需要研究": "research", "需要查找": "research", "协助查找并提交核验": "research",
    "mixed": "mixed", "混合": "mixed", "用户资料与补充研究": "mixed", "用户提供与协助查找": "mixed",
    "none": "none", "无需外部资料": "none", "无需外部事实资料": "none",
}
_EVIDENCE = {"yes": "yes", "需要核验": "yes", "需要依据": "yes", "需要外部依据": "yes",
             "no": "no", "无需外部依据": "no", "无需依据": "no", "不需要外部依据": "no"}
_UNDECIDED = {"", "待定", "未定", "未确定", "未提供", "不确定", "undecided", "tbd", "todo"}
_PAGE_KEY = re.compile(r"第([1-9]\d*)页依据要求")


def _normal(value):
    return re.sub(r"\s+", "", value).lower()


def _field_line(line):
    match = re.fullmatch(r"\s*([^:：\n]+?)\s*[:：]\s*(.*?)\s*", line)
    return (match.group(1).strip(), match.group(2).strip()) if match else None


def is_page_metadata_line(line):
    """Use only outside Markdown fences; keep this line in user_intent."""
    if not isinstance(line, str):
        return False
    pair = _field_line(line)
    return bool(pair and (pair[0] in {"依据要求", "本页依据要求", "本稿各页依据要求"} or _PAGE_KEY.fullmatch(pair[0])))


def is_intake_metadata_message(message):
    """Accept only a complete explicit metadata answer, never mixed requests.

    A caller may strip an exactly matched question/choice wrapper beforehand.
    No natural-language prefix or unrelated instruction is silently consumed.
    """
    if not isinstance(message, str) or len(message) > 100_000:
        return False
    lines = [line.strip() for line in message.lstrip("\ufeff").splitlines() if line.strip()]
    if lines and lines[0] in {"补充设置", "补充设置：", "补充设置:", "补充项目设置", "补充项目设置：", "补充项目设置:"}:
        lines.pop(0)
    if not lines:
        return False
    for line in lines:
        pair = _field_line(line)
        if not pair or not (_normal(pair[0]) in _ALIASES or is_page_metadata_line(line)):
            return False
    return True


def parse_intake_metadata(message, *, page_count=None):
    """Return detached project changes, 1-based page requirements and warnings.

The caller decides whether an explicit local outline/metadata answer is being
handled. Ordinary prose, quoted/list lines, and fenced examples are not fields.
For an existing project, page_count permits a metadata-only answer to explicitly
set a whole-deck evidence requirement. It never derives 'no' from dataPolicy.
"""
    if not isinstance(message, str) or len(message) > 100_000:
        raise EngineError("INVALID_INTAKE", "明确的输入设置需要不超过 100,000 字的文本。")
    if page_count is not None and (type(page_count) is not int or not 0 <= page_count <= 200):
        raise EngineError("INVALID_INTAKE", "已有稿件页数需要是 0 到 200 的整数。")
    changes, warnings, selected, rejected = {}, [], {}, set()
    evidence, evidence_seen, evidence_rejected = {}, set(), set()
    global_value, global_seen, global_rejected = None, False, False
    index, fence = 0, None

    def declare_field(name, value, number, label):
        normalized = _normal(value)
        fields = {"purpose", "purposeOther"} if name == "purpose" else {name}
        if normalized in _UNDECIDED or re.fullmatch(r"\[(?:填写|待补|补充)[^\]]*\]", value):
            candidate = None
        elif name == "purpose":
            candidate = {"purpose": "other", "purposeOther": value}
        elif name in {"audience", "outcome", "duration"}:
            candidate = {name: value}
        else:
            mapping = {"delivery": _DELIVERY, "logoPolicy": _LOGO, "dataPolicy": _DATA}[name]
            parsed = mapping.get(normalized)
            candidate = {name: parsed} if parsed else None
        if candidate is None:
            warnings.append(f"第 {number} 行的“{label}”未明确识别，保留原话且不自动设置。" +
                            ("文件格式不等于展示方式，请明确现场讲述、独立阅读或两者兼用。" if label == "交付格式" else ""))
            rejected.add(name)
            for field in fields:
                changes.pop(field, None)
            return
        if name in rejected:
            return
        if name in selected and selected[name] != candidate:
            warnings.append(f"“{label}”存在相互冲突的明确值，请确认后再应用。")
            rejected.add(name)
            for field in fields:
                changes.pop(field, None)
            return
        selected[name] = candidate
        changes.update(candidate)

    def declare_evidence(target, value, number):
        parsed = _EVIDENCE.get(_normal(value))
        evidence_seen.add(target)
        if parsed is None:
            warnings.append(f"第 {number} 行的依据要求未明确识别；请写“需要核验”或“无需外部依据”。")
            evidence_rejected.add(target)
            evidence.pop(target, None)
        elif target not in evidence_rejected:
            if target in evidence and evidence[target] != parsed:
                warnings.append(f"第 {target} 页的依据要求相互冲突，未自动选择。")
                evidence_rejected.add(target)
                evidence.pop(target, None)
            else:
                evidence[target] = parsed

    for number, line in enumerate(message.lstrip("\ufeff").splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            continue
        if re.fullmatch(r"##\s+[^｜|]+[｜|].+?\s*", line):
            index += 1
            continue
        pair = _field_line(line)
        if not pair:
            continue
        label, value = pair
        explicit_page = _PAGE_KEY.fullmatch(label)
        if explicit_page:
            declare_evidence(int(explicit_page.group(1)), value, number)
        elif label in {"依据要求", "本页依据要求"}:
            if index:
                declare_evidence(index, value, number)
            else:
                warnings.append(f"第 {number} 行未指定页面；全稿策略请明确写“本稿各页依据要求”。")
        elif label == "本稿各页依据要求":
            if index:
                warnings.append(f"第 {number} 行的全稿依据策略位于页面正文，未应用；请放在大纲前言。")
                continue
            parsed = _EVIDENCE.get(_normal(value))
            if parsed is None:
                global_rejected = True
                warnings.append(f"第 {number} 行的全稿依据要求未明确识别，未自动设置。")
            elif global_seen and global_value != parsed:
                global_rejected = True
                warnings.append("全稿依据要求存在冲突，未自动选择。")
            global_seen, global_value = True, parsed
        elif index == 0:
            name = _ALIASES.get(_normal(label))
            if name:
                declare_field(name, value, number, label)
    total = index if index else page_count
    if total is not None:
        for target in list(evidence):
            if target > total:
                evidence.pop(target)
                warnings.append(f"第 {target} 页超出当前明确的页数，依据要求未应用。")
        if global_seen and not global_rejected and global_value:
            for target in range(1, total + 1):
                if target not in evidence_seen:
                    evidence[target] = global_value
    elif global_seen and not global_rejected and global_value:
        warnings.append("已有明确的全稿依据策略，但没有大纲页数；需结合现有稿件页数后应用。")
    assert set(changes) <= set(PROJECT_DEFAULT)
    return {"projectChanges": changes, "pageEvidence": dict(sorted(evidence.items())), "warnings": warnings}


def missing_intake_questions(project, *, page_count=0, page_evidence=None):
    """Consolidate missing intake decisions into at most three chat questions.

Choices are editable examples for the user to select, not inferred settings.
Only missing fields appear in each choice. Caller may convert these to its
existing question/choices schema, retaining free-text answers.
"""
    if not isinstance(project, dict) or type(page_count) is not int or not 0 <= page_count <= 200 or (page_evidence is not None and not isinstance(page_evidence, dict)):
        raise EngineError("INVALID_INTAKE", "缺口检查需要项目字段、页数和按页的依据要求。")
    evidence = page_evidence or {}
    missing = []
    labels = {"purpose": "用途", "audience": "听众", "outcome": "目标", "delivery": "展示方式", "logoPolicy": "Logo策略", "dataPolicy": "数据策略"}
    brief = []
    if not project.get("purpose") or project.get("purpose") == "other" and not str(project.get("purposeOther") or "").strip():
        brief.append("purpose")
    for field in ("audience", "outcome"):
        if not str(project.get(field) or "").strip():
            brief.append(field)
    if brief:
        examples = [
            {"purpose": "介绍方案", "audience": "目标客户", "outcome": "理解方案并讨论下一步"},
            {"purpose": "汇报进展", "audience": "内部团队", "outcome": "对齐进展与后续安排"},
            {"purpose": "讲解知识", "audience": "学习者", "outcome": "理解知识并能实践"},
        ]
        missing.append({"id": "intake_brief", "fields": brief, "question": "请一次补充" + "、".join(labels[k] for k in brief) + "。选项是可修改的示例，也可以直接写你的情况。",
                        "choices": ["\n" + "\n".join(labels[k] + "：" + example[k] for k in brief) for example in examples], "allowFreeText": True})
    format_fields = [field for field in ("delivery", "logoPolicy") if project.get(field, "undecided") in {"", "undecided", None}]
    if format_fields:
        examples = [{"delivery": "现场讲述", "logoPolicy": "不使用Logo"}, {"delivery": "独立阅读", "logoPolicy": "不使用Logo"}, {"delivery": "两者兼用", "logoPolicy": "使用公司Logo"}]
        if format_fields == ["logoPolicy"]:
            examples = [{"logoPolicy": value} for value in ("不使用Logo", "使用公司Logo", "使用联合品牌Logo")]
        missing.append({"id": "intake_presentation", "fields": format_fields, "question": "请明确" + "、".join(labels[k] for k in format_fields) + "；使用品牌Logo时仍需提供准确素材。",
                        "choices": ["\n" + "\n".join(labels[k] + "：" + example[k] for k in format_fields) for example in examples], "allowFreeText": True})
    missing_pages = [n for n in range(1, page_count + 1) if evidence.get(n, evidence.get(str(n), "undecided")) not in {"yes", "no"}]
    data_missing = project.get("dataPolicy", "undecided") in {"", "undecided", None}
    if data_missing or missing_pages:
        fields = (["dataPolicy"] if data_missing else []) + (["pageEvidence"] if missing_pages else [])
        question = "请明确" + ("资料提供方式" if data_missing else "") + ("及" if data_missing and missing_pages else "") + ("第 " + "、".join(map(str, missing_pages)) + " 页是否需要事实依据" if missing_pages else "") + "。声明无需外部资料不会自动取消逐页的依据要求。"
        choices = []
        for data, requirement in (("用户提供真实资料", "需要核验"), ("协助查找并提交核验", "需要核验"), ("无需外部资料", "无需外部依据")):
            lines = ["数据策略：" + data] if data_missing else []
            lines += [f"第{n}页依据要求：{requirement}" for n in missing_pages]
            choices.append("\n" + "\n".join(lines))
        missing.append({"id": "intake_sources", "fields": fields, "pageNumbers": missing_pages, "question": question,
                        "choices": list(dict.fromkeys(choices)), "allowFreeText": True})
    return missing
