"""Reusable opening layouts extracted from the user's original PPT pages."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .rendering import MAX_OBJECTS, validate_scene
from .template_content import fit_text, strip_template_decoration

DATA = Path(__file__).with_name("data") / "opening-templates"
ROLE_NAMES = {"cover": "封面", "toc": "目录", "chapter": "章节页"}
# Keep source variants addressable for existing projects without repeating one style.
STYLE_TEMPLATES = {"opening-02-01-cover", "opening-04-02-toc", "opening-05-02-chapter"}


def entries():
    path = DATA / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))["templates"] if path.exists() else []


def has_template(template_id):
    return any(item["id"] == template_id for item in entries())


def catalog():
    cards = []
    for item in entries():
        role = item["role"]
        source = item["sourceFile"]
        name = f'深蓝科技 · {ROLE_NAMES[role]}'
        cards.append(dict(id=item["id"], name=name, title=name,
                          description="统一科技背景与品牌位置，标题和署名使用可替换的内容槽位。",
                          role=role, roles=[role], roleName=ROLE_NAMES[role],
                          family="opening", familyName="PPT 原页", tags=[role, source],
                          sourceLabel="深蓝科技 · 系列模板",
                          source=source, sourcePage=item["sourcePage"], opening=True,
                          legacy=item["id"] not in STYLE_TEMPLATES, styleId="deep-blue-tech",
                          use="固定开场版式，替换标题与内容后检查文字容量。",
                          inputs=["标题", "副标题与正文"],
                          checks=[warning["detail"] for warning in item.get("limitations", [])],
                          fidelity=item.get("fidelity")))
    return cards


def sample_scene(template_id):
    item = next(item for item in entries() if item["id"] == template_id)
    scene = json.loads((DATA / item["scene"]).read_text(encoding="utf-8"))
    scene["templateId"] = template_id
    role = item["role"]
    for obj in scene["objects"]:
        if obj["type"] == "text":
            binding = obj.get("binding", "")
            if binding == "title":
                obj["text"] = {"cover": "演示主标题", "toc": "目录", "chapter": "章节名称"}[role]
            elif binding == "takeaway":
                obj["text"] = "公司名称 · 汇报人 · 日期" if role == "cover" else "本章概要与说明"
            elif binding.startswith("keyPoints:"):
                obj["text"] = f'章节 {int(binding.split(":")[1]) + 1:02d} · 章节名称'
            elif not (obj["text"].strip().isdigit() or obj["text"].strip() == "→"):
                obj["text"] = "CONTENTS" if role == "toc" else ""
        elif obj["type"] == "image" and obj["w"] < 350 and obj["h"] < 120:
            # Brand marks belong to the user's deck, not to a reusable layout.
            replacement = {"id": obj["id"], "type": "text", "text": "LOGO",
                           "x": obj["x"], "y": obj["y"], "w": obj["w"], "h": obj["h"],
                           "fontSize": 20, "color": "#A9C8E5", "bold": True}
            obj.clear()
            obj.update(replacement)
    if role == "toc":
        scene["background"] = "#091A31"
        for obj in scene["objects"]:
            if obj["type"] == "text":
                obj["color"] = "#8DBDFF" if obj["text"].strip().isdigit() else "#EAF2FC"
            elif obj["type"] == "line":
                obj["stroke"] = "#304A68"
    return validate_scene(scene)


def template_for_role(template_id, role):
    items = entries()
    selected = next(item for item in items if item["id"] == template_id)
    if selected["role"] == role:
        return template_id
    return next((item["id"] for item in items if item["id"] in STYLE_TEMPLATES and item["role"] == role), None)


def apply_template(scene, template_id):
    original = strip_template_decoration(validate_scene(scene))
    result = sample_scene(template_id)
    sx, sy = original["width"] / result["width"], original["height"] / result["height"]
    slots = {}
    fixed = []
    for obj in result["objects"]:
        for key in ("x", "w"):
            obj[key] *= sx
        for key in ("y", "h"):
            obj[key] *= sy
        if obj["type"] == "text":
            obj["fontSize"] = max(10, min(160, obj["fontSize"] * sy))
        if "radius" in obj:
            obj["radius"] *= min(sx, sy)
        if "strokeWidth" in obj:
            obj["strokeWidth"] = min(24, obj["strokeWidth"] * min(sx, sy))
        if obj.get("binding"):
            slots[obj["binding"]] = obj
        elif obj["type"] != "text" or obj.get("text", "").strip().isascii():
            fixed.append(obj)
    result.update(width=original["width"], height=original["height"], slideId=original["slideId"])
    result["objects"] = []
    used_ids = {obj["id"] for obj in original["objects"]}
    for i, obj in enumerate(fixed[:max(0, MAX_OBJECTS - len(original['objects']))]):
        obj["id"] = f"opening.fixed.{i}"
        while obj["id"] in used_ids:
            obj["id"] += "x"
        used_ids.add(obj["id"])
        result["objects"].append(obj)
    text = [obj for obj in original["objects"] if obj["type"] == "text"]
    extras = [obj for obj in text if obj.get("binding", obj["id"]) not in slots]
    width, height = original["width"], original["height"]
    for source in original["objects"]:
        obj = copy.deepcopy(source)
        if obj["type"] == "text":
            slot = slots.get(obj.get("binding", obj["id"]))
            if slot:
                content = {key: obj[key] for key in ("id", "text", "binding") if key in obj}
                obj = copy.deepcopy(slot)
                obj.pop('binding', None)
                obj.update(content)
            else:
                index = extras.index(source)
                # Extra content is retained in a visible area; never hide it in tiny text.
                row_h = min(height * .12, height * .34 / max(1, len(extras)))
                obj.update(x=width * .1, y=height * .62 + index * row_h,
                           w=width * .8, h=max(1, row_h - 2),
                           fontSize=max(10, min(22 * sy, row_h * .42)),
                           color=next(iter(slots.values())).get("color", "#173B53") if slots else "#173B53",
                           opacity=1)
        elif obj["type"] != "image":
            # Source template supplies ornaments; preserve prior IDs without duplicate decoration.
            obj["opacity"] = 0
        fit_text(obj)
        result["objects"].append(obj)
    result["title"] = original.get("title", "")
    result["notes"] = original.get("notes", "")
    result["bindingSeparator"] = original.get("bindingSeparator", "\n")
    return validate_scene(result)
