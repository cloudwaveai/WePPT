"""Cross-project design-taste aggregation. No model calls; read-only signals."""
from __future__ import annotations

import colorsys
import json
import re

_HUE_NAMES = [(15, "红"), (45, "橙"), (75, "黄"), (160, "绿"), (200, "青"), (250, "蓝"), (300, "紫"), (345, "品红")]


def _hue_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return None
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < .25:
        return None
    return next(name for bound, name in _HUE_NAMES if h * 360 <= bound) if h * 360 <= 345 else "红"


def _add(weights, feature, value, amount):
    if value:
        weights.setdefault(feature, {})[value] = weights.setdefault(feature, {}).get(value, 0) + amount


ARCHETYPE_NAMES = {"hero-statement": "大标题主张", "big-number": "大数字", "split-asymmetric": "不对称分栏",
                   "full-bleed-band": "通栏色带", "grid-cards": "卡片网格", "ordered-rows": "有序列表",
                   "timeline": "时间线", "diagram": "图解", "quote": "引言", "comparison": "对比"}


def taste_profile(studio):
    """Weighted feature votes from applied proposals, preferences, scenes, decks."""
    from .templates import catalog
    entries = {t["id"]: t for t in catalog()}
    votes = {}
    signals = 0
    from .owners import owned_project_ids
    mine = owned_project_ids(studio.wb)  # In personal spaces only the visitor's own projects count.
    def rows(sql):
        return [r for r in db.execute(sql).fetchall() if mine is None or r["project_id"] in mine]
    with studio.wb._connection() as db:
        for row in rows("SELECT project_id,template_id FROM studio_template_proposals WHERE applied_revision IS NOT NULL"):
            if row["template_id"] in entries:
                votes[row["template_id"]] = votes.get(row["template_id"], 0) + 3
                signals += 3
        for row in rows("SELECT project_id,template_id FROM studio_template_preferences"):
            if row["template_id"] in entries:
                votes[row["template_id"]] = votes.get(row["template_id"], 0) + 2
                signals += 2
        scenes = rows("SELECT project_id,slide_id,revision,body FROM studio_scenes ORDER BY rowid DESC LIMIT 300")
        latest = {}
        for row in scenes:
            latest.setdefault((row["project_id"], row["slide_id"]), row)
        for key, row in latest.items():
            tid = json.loads(row["body"]).get("templateId")
            if tid in entries:
                votes[tid] = votes.get(tid, 0) + 1
                signals += 1
        palettes = [json.loads(r["body"]) for r in rows("SELECT project_id,body FROM studio_palette_preferences")]
        decks = [json.loads(r["plan"]) for r in rows("SELECT project_id,plan FROM studio_decks")]
        style_rows = rows("""SELECT s.project_id,t.body FROM studio_style_preferences s
            JOIN studio_user_templates t ON t.id=s.template_id""")
    signals += sum(1 for p in palettes if p.get("primary")) \
        + sum(1 for d in decks if isinstance(d, dict) and d.get("design")) + len(style_rows)
    weights = {}
    for tid, amount in votes.items():
        entry = entries.get(tid)
        if not entry:
            continue
        _add(weights, "family", entry.get("family"), amount)
        _add(weights, "browseCategory", entry.get("browseCategory"), amount)
        _add(weights, "baseTemplateId", entry.get("baseTemplateId"), amount)
        _add(weights, "source", entry.get("source"), amount)
        _add(weights, "styleId", entry.get("styleId"), amount)
    archetypes, dark, accent_hues = {}, 0, {}
    briefs = 0
    for plan in decks:
        design = plan.get("design") or {}
        hue = _hue_name(design.get("accent"))
        if hue:
            accent_hues[hue] = accent_hues.get(hue, 0) + 1
        for page in plan.get("pages", []):
            brief = page.get("designBrief") or {}
            briefs += 1
            if brief.get("layoutArchetype"):
                archetypes[brief["layoutArchetype"]] = archetypes.get(brief["layoutArchetype"], 0) + 1
            if brief.get("backgroundTreatment") in {"inverse", "split"}:
                dark += 1
    for hue, n in accent_hues.items():
        _add(weights, "accentHue", hue, n)
    for key, n in archetypes.items():
        _add(weights, "layoutArchetype", key, n)
    dark_share = dark / briefs if briefs else 0
    keywords = []
    for row in style_rows:
        keywords += (json.loads(row["body"]).get("profile") or {}).get("designStyle", {}).get("keywords", [])
    normalized = {feature: {v: n / max(bucket.values()) for v, n in bucket.items()}
                  for feature, bucket in weights.items()}
    parts = []
    if dark_share >= .25:
        parts.append("深色底页")
    top_hue = max(accent_hues, key=accent_hues.get) if accent_hues else None
    palette_hues = [h for h in (_hue_name(p.get("primary")) for p in palettes) if h]
    if not top_hue and palette_hues:
        top_hue = max(set(palette_hues), key=palette_hues.count)
    if top_hue:
        parts.append(top_hue + "系主色")
    if archetypes:
        top = max(archetypes, key=archetypes.get)
        parts.append("常用" + ARCHETYPE_NAMES.get(top, top))
    if keywords:
        parts.append("、".join(list(dict.fromkeys(keywords))[:3]))
    summary = "偏好：" + "、".join(parts[:4]) if parts else None
    return {"features": normalized, "summary": summary,
            "signals": signals, "darkShare": round(dark_share, 3), "keywords": list(dict.fromkeys(keywords))[:6]}
