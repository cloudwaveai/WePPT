"""Deterministic, advisory page-expression planning from supplied content.

This is a lightweight heuristic, not a content generator or a layout fit check.
"""
from __future__ import annotations

import re

_PATTERNS = {
    "compare": r"对比|比较|竞品|友商|差异|相比|(?:before\s+and\s+after)|\b(?:compare|comparison|versus|vs)\b",
    "cause": r"原因|导致|由于|因为|因此|因果|\b(?:because|causes?|results? in)\b",
    "process": r"流程|步骤|阶段|依次|首先|然后|最后|路线图|\b(?:process|steps?|timeline|roadmap|first|then)\b",
    "evidence": r"证据|案例|实证|研究表明|数据显示|证明|\b(?:evidence|case study|research shows)\b",
    "data": r"数据|指标|趋势|收入|增长率|\b(?:data|metrics?|trend|revenue)\b",
    "structure": r"架构|组织结构|层级|组成|\b(?:architecture|hierarchy|structure)\b",
    "product": r"产品|功能|界面|演示|\b(?:product|features?|demo)\b",
    "parallel": r"并列|优势|特点|要点|\b(?:parallel|pillars|benefits)\b",
}


def _points(value):
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]
    if isinstance(value, str):
        return [s.strip(' \t•-') for s in re.split(r'\n+|[；;]', value) if s.strip(' \t•-')]
    return []


def plan_page_expression(page=None, *, text=""):
    """Return relationship, signals, approximate content load, and supplied assets.

    ``page`` accepts slide fields title, takeaway, keyPoints, userIntent, evidence
    and assets. A text-only caller has unknown assets, not an empty asset list.
    """
    page = page if isinstance(page, dict) else {}
    parts = [str(page.get(k) or "") for k in ("title", "takeaway", "userIntent", "user_intent")]
    points = _points(page.get("keyPoints", page.get("key_points")))
    raw_text = str(text or "")
    combined = "\n".join(parts + points + [raw_text]).lower()
    if not points and raw_text:
        points = _points(raw_text)
    signals = [name for name, pattern in _PATTERNS.items() if re.search(pattern, combined, re.I)]
    evidence = page.get("evidence")
    if isinstance(evidence, list) and any(evidence) and "evidence" not in signals:
        signals.append("evidence")
    if len(points) >= 2 and "parallel" not in signals:
        signals.append("parallel")
    numbers = len(re.findall(r'(?<!\w)\d+(?:[.,]\d+)?%?', combined))
    if numbers >= 2 and "data" not in signals:
        signals.append("data")
    # Strong relational cues take precedence over incidental lists or metrics.
    relationship = next((x for x in ("compare", "cause", "process", "evidence", "structure", "data", "product", "parallel") if x in signals), "general")
    chars = len(re.sub(r'\s+', '', combined))
    assets = page.get("assets")
    image_count = None
    if isinstance(assets, list):
        image_count = sum(1 for a in assets if isinstance(a, dict) and (
            str(a.get("mime", a.get("mimeType", ""))).lower().startswith("image/")
            or str(a.get("type", "")).lower() in {"image", "photo", "screenshot"}
            or re.search(r'\.(?:png|jpe?g|webp|gif)(?:[?#].*)?$', str(a.get("reference", a.get("filename", ""))), re.I)))
    return {"relationship": relationship, "signals": signals,
            "content": {"pointCount": len(points), "characters": chars,
                        "density": "high" if chars > 400 or len(points) > 6 else "medium" if chars > 180 or len(points) > 3 else "low",
                        "numberCount": numbers},
            "assets": {"imageCount": image_count},
            "evidenceCount": len(evidence) if isinstance(evidence, list) else None}


def template_score(template, plan):
    """Score a catalog entry against a plan; higher is a better advisory fit."""
    tid, family = template.get("id", ""), template.get("family", "")
    relation = plan["relationship"]
    preferred = {
        "compare": {"compare", "vs-cards", "tradeoff", "case-compare", "before-after", "change"},
        "cause": {"cause", "problem", "claim-proof"},
        "process": {"process", "timeline", "roadmap", "guide-split", "swimlane"},
        "evidence": {"claim-proof", "evidence-split", "case", "evidence-wall", "case-scorecard"},
        "data": {"table", "bar", "line", "kpi", "kpi-hero"},
        "structure": {"hierarchy", "organization", "hub", "mapping"},
        "product": {"focus", "feature-map", "feature-hero", "demo"},
        "parallel": {"parallel", "pillar-cards", "parallel-two", "parallel-three", "parallel-four", "parallel-long"},
    }
    families = {"compare": "compare", "cause": "argument", "process": "process", "evidence": "proof", "data": "data", "structure": "structure", "product": "product", "parallel": "compare"}
    score = 12 if tid in preferred.get(relation, set()) else 0
    if family == families.get(relation):
        score += 5
    count = plan["content"]["pointCount"]
    if relation == "parallel" and 2 <= count <= 4:
        if tid == {2: "parallel-two", 3: "parallel-three", 4: "parallel-four"}[count]:
            score += 12
        elif tid in {"parallel-two", "parallel-three", "parallel-four"}:
            score -= 6
    if plan["content"]["density"] == "high":
        if tid in {"table", "parallel-long", "swimlane", "faq"}:
            score += 5
        if tid in {"kpi-hero", "feature-hero", "parallel-two", "parallel-three", "parallel-four"}:
            score -= 8
    images = plan["assets"]["imageCount"]
    if tid in {"focus", "demo", "photo-story", "feature-hero", "uneven-images", "cover-photo", "chapter-image"}:
        if images is not None:
            score += 7 if images else -12
    if tid in {"bar", "line", "kpi", "kpi-hero"} and plan["content"]["numberCount"] == 0:
        score -= 5
    return score
