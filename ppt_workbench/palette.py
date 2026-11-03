"""User-chosen colour palettes: one primary plus one or two secondary colours.

Preferences are stored per project, injected into new-deck generation and
applied deterministically to existing scenes by remapping exact colour roles.
"""
from __future__ import annotations

import colorsys
import copy
import json
import re

from .core import EngineError, _json, _now


PALETTE_PRESETS = [
    {"name": "商务蓝", "primary": "#1F4E9E", "secondary": ["#2BB3C0", "#F2A541"]},
    {"name": "科技紫", "primary": "#5B3FD9", "secondary": ["#22C1C3", "#FF6B8B"]},
    {"name": "沉稳墨绿", "primary": "#1E6B52", "secondary": ["#C9A227", "#7FB7A4"]},
    {"name": "活力橙", "primary": "#E8590C", "secondary": ["#1C7ED6", "#FAB005"]},
    {"name": "学术红", "primary": "#A61E4D", "secondary": ["#364FC7", "#868E96"]},
    {"name": "极简黑", "primary": "#212529", "secondary": ["#E03131", "#ADB5BD"]},
    {"name": "清新青", "primary": "#0CA678", "secondary": ["#4DABF7", "#FFD43B"]},
    {"name": "高级金", "primary": "#B08D57", "secondary": ["#2F3E46", "#84A98C"]},
]

PALETTE_INSTRUCTION = ("用户指定的主色和辅色：主色用于标题强调、关键数字与主要色块；"
                       "辅色用于次级强调和图形区分；不要引入其他高饱和色，背景、文字和灰阶等中性色可自行选择。")

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def fail(code, message):
    raise EngineError(code, message)


def _hex(value):
    return isinstance(value, str) and bool(_HEX.fullmatch(value))


def normalize_palette(value):
    """Validate a palette body, upper-case every colour."""
    if not isinstance(value, dict):
        fail("INVALID_PALETTE", "配色需要主色与 1–2 个辅色。")
    primary = value.get("primary")
    secondary = value.get("secondary")
    if not _hex(primary):
        fail("INVALID_PALETTE", "主色需要 #RRGGBB。")
    if not isinstance(secondary, list) or not 1 <= len(secondary) <= 2 or any(not _hex(c) for c in secondary):
        fail("INVALID_PALETTE", "辅色需要 1–2 个 #RRGGBB。")
    colours = [primary.upper()] + [c.upper() for c in secondary]
    if len(set(colours)) != len(colours):
        fail("INVALID_PALETTE", "主色与辅色不能重复。")
    return {"primary": colours[0], "secondary": colours[1:]}


def palette(studio):
    with studio.wb._connection() as db:
        row = db.execute("SELECT body FROM studio_palette_preferences WHERE project_id=?",
                         (studio.project_id,)).fetchone()
    return json.loads(row["body"]) if row else None


def set_palette(studio, value):
    if value is None:
        body = None
    else:
        body = normalize_palette(value)
    with studio.wb.atomic() as db:
        if body is None:
            db.execute("DELETE FROM studio_palette_preferences WHERE project_id=?", (studio.project_id,))
        else:
            db.execute("INSERT OR REPLACE INTO studio_palette_preferences VALUES (?,?)",
                       (studio.project_id, _json(body)))
        studio._touch(db)
    return body


def _luminance(value):
    channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def _contrast(a, b):
    x, y = sorted((_luminance(a), _luminance(b)))
    return (y + .05) / (x + .05)


def _text_background(scene, obj):
    """Topmost opaque rect/ellipse containing the text box, else scene background."""
    from .quality import _contains, _inside_ellipse
    background = scene["background"]
    corners = [(obj["x"], obj["y"]), (obj["x"] + obj["w"], obj["y"]),
               (obj["x"], obj["y"] + obj["h"]), (obj["x"] + obj["w"], obj["y"] + obj["h"])]
    for prior in scene["objects"]:
        if prior["id"] == obj["id"]:
            break
        if (prior["type"] in ("rect", "ellipse") and prior.get("fill") not in (None, "none")
                and prior.get("opacity", 1) >= .99 and not prior.get("rotation")
                and _contains(prior, obj)
                and (prior["type"] == "rect" or all(_inside_ellipse(prior, x, y) for x, y in corners))):
            background = prior["fill"]
        elif prior["type"] == "image" and _contains(prior, obj):
            return None
    return background


def recolor_scene(scene, mapping):
    """Swap exact hex matches (case-insensitive) and keep unreadable text colours."""
    lower = {key.lower(): value.upper() for key, value in mapping.items() if _hex(key) and _hex(value)}

    def swap(value):
        return lower.get(value.lower(), value) if isinstance(value, str) else value

    result = copy.deepcopy(scene)
    if "background" in result:
        result["background"] = swap(result["background"])
    for obj in result.get("objects", []):
        for field in ("fill", "stroke", "color", "emphasisColor"):
            if field in obj:
                obj[field] = swap(obj[field])
    original = {o.get("id"): o for o in scene.get("objects", [])}
    for obj in result.get("objects", []):
        before = original.get(obj.get("id"))
        if obj.get("type") != "text" or before is None:
            continue
        background = _text_background(result, obj)
        if not background or not _hex(background):
            continue
        if obj.get("color") != before.get("color") and _hex(before.get("color")) \
                and _contrast(obj["color"], background) < 3:
            obj["color"] = before["color"]
        if obj.get("emphasisColor") != before.get("emphasisColor") and _hex(before.get("emphasisColor")) \
                and _contrast(obj["emphasisColor"], background) < 3:
            obj["emphasisColor"] = before["emphasisColor"]
    return result


def _saturated(value):
    if not _hex(value):
        return False
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    _, s, v = colorsys.rgb_to_hsv(r, g, b)
    return s >= .35 and v >= .25


def detect_scene_colors(scene):
    """Saturated object colours ranked by painted area (text counts 30%)."""
    areas = {}
    for obj in scene.get("objects", []):
        weight = obj.get("w", 0) * obj.get("h", 0) * (.3 if obj.get("type") == "text" else 1)
        for field in ("fill", "color"):
            value = obj.get(field)
            if _saturated(value):
                key = value.upper()
                areas[key] = areas.get(key, 0) + weight
    return sorted(areas, key=lambda c: (-areas[c], c))


def applied_palette(studio):
    """The palette last applied to this project's pages, or None."""
    with studio.wb._connection() as db:
        row = db.execute("SELECT body FROM studio_palette_applied WHERE project_id=?",
                         (studio.project_id,)).fetchone()
    return json.loads(row["body"]) if row else None


def _mapping_for(studio, db, scene, chosen):
    """Ordered recolour sources: (a) last-applied palette when it changes this
    page, (b) deck design colours, (c) per-scene colour detection."""
    last = applied_palette(studio)
    if last:
        mapping = {last["primary"].upper(): chosen["primary"]}
        for index, colour in enumerate(last.get("secondary", [])):
            if index < len(chosen["secondary"]):
                mapping[colour.upper()] = chosen["secondary"][index]
        if recolor_scene(scene, mapping) != scene:
            return mapping
    design = None
    deck = studio._deck_row(db)
    if deck:
        design = json.loads(deck["plan"]).get("design")
    mapping = {}
    if isinstance(design, dict):
        pairs = [(design.get("accent"), chosen["primary"]),
                 (design.get("secondary"), chosen["secondary"][0]),
                 (design.get("tertiary"), chosen["secondary"][1] if len(chosen["secondary"]) > 1 else None)]
        mapping = {old.upper(): new for old, new in pairs if _hex(old) and new}
    if mapping:
        return mapping
    detected = detect_scene_colors(scene)
    targets = [chosen["primary"]] + chosen["secondary"]
    return {old: new for old, new in zip(detected, targets)}


def apply_palette(studio, scope="page", slide_id=None, scene_revision=None):
    """Recolour one page or the whole deck; unchanged and stale pages are skipped."""
    chosen = palette(studio)
    if chosen is None:
        fail("PALETTE_MISSING", "请先选择配色，再应用到页面。")
    from .editor import _history, _save_history
    if scope not in {"page", "deck"}:
        fail("INVALID_REQUEST", "配色范围只能是 page 或 deck。")
    if scope == "page" and not isinstance(slide_id, str):
        fail("INVALID_REQUEST", "请指定要应用配色的页面。")
    targets = [slide_id] if scope == "page" else [s["id"] for s in studio.state()["slides"]]
    changed, skipped = [], []
    with studio.wb.atomic() as db:
        for sid in targets:
            try:
                current = studio.get_scene(sid)
            except EngineError as exc:
                if exc.code == "SCENE_MISSING":
                    skipped.append({"slideId": sid, "reason": "missing"})
                    continue
                raise
            if scope == "page" and scene_revision is not None:
                studio.wb._revision(current["sceneRevision"], scene_revision)
            if current["stale"]:
                skipped.append({"slideId": sid, "reason": "stale"})
                continue
            mapping = _mapping_for(studio, db, current["scene"], chosen)
            recolored = recolor_scene(current["scene"], mapping)
            if recolored == current["scene"]:
                skipped.append({"slideId": sid, "reason": "unchanged"})
                continue
            undo, _ = _history(studio, db, sid, current["sceneRevision"])
            result = studio.put_scene(sid, current["contentRevision"], recolored, "应用配色")
            if result.get("unchanged"):
                skipped.append({"slideId": sid, "reason": "unchanged"})
                continue
            undo.append({"before": current["scene"], "after": result["scene"]})
            _save_history(studio, db, sid, result["sceneRevision"], undo, [])
            changed.append(sid)
        db.execute("INSERT OR REPLACE INTO studio_palette_preferences VALUES (?,?)",
                   (studio.project_id, _json(chosen)))
        if changed:
            db.execute("INSERT OR REPLACE INTO studio_palette_applied VALUES (?,?)",
                       (studio.project_id, _json(chosen)))
        studio._touch(db)
    return {"changedSlides": changed, "skipped": skipped, "state": studio.state()}
