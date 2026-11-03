"""Local visual templates: geometry and color only, never generated content."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from .core import EngineError
from .rendering import validate_scene
from .template_content import fit_text
from .template_categories import annotate_category
from . import design_map, opening_templates, semantic_planning, reference_templates


_TEMPLATES = (
    ("clean", "清简", "清晰留白与蓝色细节，适合通用汇报。", ["general", "summary", "content"], "#FFFFFF", "#172C45", "#365ADB"),
    ("editorial", "编排", "暖纸色与侧栏构图，适合观点和故事。", ["story", "title", "cover"], "#F6F2EA", "#292D32", "#A45135"),
    ("parallel", "并列", "均衡分栏，让多个观点各有位置。", ["parallel", "features", "toc"], "#F5F8FC", "#172C45", "#266C78"),
    ("comparison", "对照", "双栏对照，适合方案与前后变化。", ["compare", "comparison", "before-after"], "#FAF9F6", "#253044", "#6751A0"),
    ("steps", "步骤", "顺序排列的内容区，适合流程与计划。", ["process", "steps", "roadmap"], "#F4F8F5", "#193C32", "#28775A"),
    ("dark", "夜色", "深色底与薄荷绿点缀，适合开场与收束。", ["cover", "ending", "statement"], "#142335", "#F0F5FA", "#68D5B5"),
)


_DATA = Path(__file__).with_name("data")
_SCENARIOS = json.loads((_DATA / "bbstack-templates.json").read_text(encoding="utf-8"))
_STRUCTURE = json.loads((_DATA / "bbstack-structure.json").read_text(encoding="utf-8"))
_FAMILIES = dict(_SCENARIOS["families"])
_ROLES = {role["id"]: role for role in _STRUCTURE["roles"]}


def _reference_catalog():
    entries = []
    for source in _SCENARIOS["templates"] + _SCENARIOS.get("localTemplates", []):
        entry = copy.deepcopy(source)
        tid = entry["id"]
        role = next((r["id"] for r in _STRUCTURE["roles"] if tid in r["templateIds"]), "content")
        if tid == "toc-sidebar":
            role = "toc"
        if entry["family"] == "message":
            entry["sourceFamily"] = "message"
            entry["family"] = "argument"
        sections = [copy.deepcopy(s) for s in _STRUCTURE["appendixSections"] if tid in s["templateIds"]]
        roles = [role] + (["appendix"] if sections else [])
        entry.update(name=entry["title"], description=entry["short"], role=role, roles=roles,
                     roleName=_ROLES[role]["title"], rolePurpose=_ROLES[role]["purpose"],
                     familyName=_FAMILIES[entry["family"]], appendixSections=sections,
                     source="https://ppt.bbstack.date", legacy=False)
        if source in _SCENARIOS.get("localTemplates", []):
            entry["source"] = _SCENARIOS["localSource"]
            entry["local"] = True
        if tid in _SCENARIOS.get("localEngineRules", {}):
            entry["engineRules"] = copy.deepcopy(_SCENARIOS["localEngineRules"][tid])
        entries.append(entry)
    by_id = {entry["id"]: entry for entry in entries}
    for variant in _STRUCTURE["variants"]["parallel"]:
        entry = copy.deepcopy(by_id[variant["targetTemplate"]])
        entry.update(copy.deepcopy(variant))
        entry.update(name=variant["title"], description=variant["when"], use=variant["when"],
                     variantOf=variant["targetTemplate"])
        entry["fixed"].append(variant["rule"])
        entries.append(entry)
    return entries


_REFERENCE = {entry["id"]: entry for entry in _reference_catalog()}


def catalog():
    """Reference entries first; legacy IDs remain selectable by older clients."""
    entries = opening_templates.catalog() + copy.deepcopy(list(_REFERENCE.values()))
    for tid, name, description, tags, *_ in _TEMPLATES:
        if tid not in _REFERENCE:
            entries.append(dict(id=tid, name=name, title=name, description=description, tags=list(tags),
                                role="content", roles=list(_ROLES), family="legacy", familyName="经典模板",
                                use=description, inputs=[], checks=[], legacy=True))
    entries += reference_templates.catalog(entries)
    for entry in entries:
        annotate_category(entry)
        if entry["id"] in _REFERENCE:
            entry["sourceLabel"] = "本地新增版式" if entry.get("local") else "设计地图 · 原版布局"
        entry["previewUrl"] = "/api/templates/preview?template=" + entry["id"]
    return entries


def recommend_templates(role, text="", limit=6, *, page=None, taste=None):
    """Rank role-compatible layouts; optionally supply a structured slide as page."""
    role = role if role in _ROLES else "content"
    plan = semantic_planning.plan_page_expression(page, text=text)
    matching = [t for t in catalog() if not t.get("legacy") and role in t.get("roles", [])]
    features = (taste or {}).get("features") or {}
    def taste_bonus(template):
        value = 0
        for key in ("family", "browseCategory", "baseTemplateId", "source", "styleId"):
            value += features.get(key, {}).get(template.get(key), 0)
        return min(10, 6 * value)
    def score(template):
        base = dict(template, id=template.get("baseTemplateId", template["id"]))
        value = semantic_planning.template_score(base, plan)
        if template.get("reference"):
            value += 2  # Prefer approved references only among comparable relationships.
        return value + taste_bonus(template)
    ranked, seen = [], set()
    for template in sorted(matching, key=score, reverse=True):
        layout = template.get("baseTemplateId", template["id"])
        if layout in seen and limit <= 6:
            continue
        seen.add(layout)
        template["recommendationReason"] = ("参考：" + template["use"] + "；" + template["capacityLabel"]
                                            if template.get("reference") else template.get("use", ""))
        if taste_bonus(template) >= 3:
            template["recommendationReason"] += "；接近你常用的风格"
            template["tasteMatch"] = True
        ranked.append(template)
    return ranked[:limit]


def recover_generated_template(template_id, role, *, page=None, known_ids=None):
    """Resolve model-generated identifiers against selectable, role-compatible layouts."""
    entries = {entry["id"]: entry for entry in catalog()}
    known = set(entries) if known_ids is None else set(known_ids) & set(entries)
    if template_id in {"", "custom"}:
        return template_id
    entry = entries.get(template_id)
    if entry and template_id in known and role in entry.get("roles", []):
        return template_id
    candidates = recommend_templates(role, page=page, limit=len(entries))
    return next((candidate["id"] for candidate in candidates if candidate["id"] in known), "")


def template_for_role(template_id, role):
    """Adapt a deck preference to a page role without changing legacy themes."""
    if reference_templates.base_id(template_id):
        entry = next(t for t in catalog() if t["id"] == template_id)
        if role in entry["roles"]:
            return template_id
        return template_for_role(entry["baseTemplateId"], role)
    if opening_templates.has_template(template_id):
        return opening_templates.template_for_role(template_id, role) or {
            "ending": "ending", "appendix": "table", "content": "claim-proof"}.get(role, "cover")
    if template_id not in _REFERENCE:
        _template(template_id)
        return template_id
    entry = _REFERENCE[template_id]
    if role in entry["roles"]:
        return template_id
    return {"cover": "cover", "toc": "toc", "chapter": "chapter", "ending": "ending",
            "appendix": "table", "content": "claim-proof"}.get(role, template_id)


def _template(template_id):
    for item in _TEMPLATES:
        if item[0] == template_id:
            return item
    raise EngineError("UNKNOWN_TEMPLATE", "未找到视觉模板。", {"templateId": template_id})


def apply_template(scene, template_id):
    """Preserve every object, text string, binding and image payload in a new layout.

    Long content is retained verbatim; browser quality measurement remains the
    authority on overflow. No data or chart objects are introduced.
    """
    from .template_content import strip_template_decoration, reflow_overlapping_text
    base = reference_templates.base_id(template_id)
    if base:
        result = apply_template(scene, base)
        result["templateId"] = template_id
        return result
    scene = validate_scene(scene)
    scene.pop("diagram", None)  # A different layout no longer has the original diagram topology.
    scene = strip_template_decoration(scene)
    if opening_templates.has_template(template_id):
        result = opening_templates.apply_template(scene, template_id)
        reflow_overlapping_text(result)
        return validate_scene(result)
    if design_map.has_template(template_id):
        result = design_map.apply_template(scene, template_id)
        reflow_overlapping_text(result)
        return validate_scene(result)
    if template_id in _REFERENCE:
        result = _apply_reference(scene, _REFERENCE[template_id])
        reflow_overlapping_text(result)
        return validate_scene(result)
    _, _, _, _, background, ink, accent = _template(template_id)
    result = validate_scene(scene)
    result["templateId"] = template_id
    result["background"] = background
    width, height = result["width"], result["height"]
    sx, sy = width / 1280, height / 720

    def box(obj, x, y, w, h):
        obj.update(x=x * sx, y=y * sy, w=w * sx, h=h * sy)

    titles, takeaways, footers, body, images = [], [], [], [], []
    decoration = 0
    for obj in result["objects"]:
        kind, oid = obj["type"], obj["id"]
        if kind == "text":
            obj.update(color=ink, align="left", valign="top")
            binding = obj.get("binding", oid)
            if binding == "title":
                titles.append(obj)
            elif binding == "takeaway":
                takeaways.append(obj)
            elif oid.startswith("footer."):
                footers.append(obj)
            else:
                body.append(obj)
        elif kind == "image":
            images.append(obj)
        else:
            # Old ornaments can imply obsolete grouping; retain their IDs but
            # use a single accent and suppress the remaining decoration.
            obj["opacity"] = 1 if decoration == 0 else 0
            if kind in ("rect", "ellipse"):
                obj.update(fill=accent, stroke="none", **({"radius": 0} if kind == "rect" else {}))
                box(obj, 64, 58, 7, 64)
            else:
                obj.update(stroke=accent, strokeWidth=3)
                box(obj, 64, 58, 0, 64)
            decoration += 1

    editorial = template_id == "editorial"
    title_x, title_w = (76, 330) if editorial else (92, 1110)
    for i, obj in enumerate(titles):
        box(obj, title_x, 58 + i * 100 / max(1, len(titles)), title_w, 200 if editorial else 100 / len(titles))
        obj.update(fontSize=42 * sy, bold=True, lineHeight=1.15)
    for i, obj in enumerate(takeaways):
        box(obj, 76 if editorial else 92, (300 if editorial else 170) + i * 90 / len(takeaways),
            330 if editorial else 1100, 120 if editorial else 90 / len(takeaways))
        obj.update(fontSize=24 * sy, color=accent, lineHeight=1.3)
    for i, obj in enumerate(footers):
        box(obj, 76 + i * 1128 / len(footers), 675, 1128 / len(footers) - 12, 28)
        obj.update(fontSize=16 * sy, color=accent)

    left, top, area_w, area_h = (470, 76, 730, 560) if editorial else (92, 282 if takeaways else 200, 1108, 350 if takeaways else 432)
    if images:
        image_x = left + area_w * .65 if body else left
        image_w = area_w * .35 if body else area_w
        for i, obj in enumerate(images):
            box(obj, image_x + 16, top + i * area_h / len(images), image_w - 16, max(1, area_h / len(images) - 16))
        if body:
            area_w *= .61
    columns = 1
    if template_id == "parallel":
        columns = min(3, max(1, len(body)))
    elif template_id == "comparison":
        columns = min(2, max(1, len(body)))
    elif template_id == "steps":
        columns = min(4, max(1, len(body)))
    rows = max(1, math.ceil(len(body) / columns))
    for i, obj in enumerate(body):
        col, row = i % columns, i // columns
        cell_w, cell_h = area_w / columns, area_h / rows
        box(obj, left + col * cell_w, top + row * cell_h, max(1, cell_w - 24), max(1, cell_h - 18))
        obj.update(fontSize=max(10, min(30 * sy, cell_h * .24)), lineHeight=1.4)
    for obj in result["objects"]:
        fit_text(obj)
    reflow_overlapping_text(result)
    return validate_scene(result)


def _cells(count, area, columns=1):
    x, y, w, h = area
    columns = max(1, columns)
    rows = max(1, math.ceil(count / columns))
    return [(x + (i % columns) * w / columns, y + (i // columns) * h / rows,
             w / columns - 20, h / rows - 16) for i in range(count)]


def _content_cells(count, area, entry):
    """Arrange existing text blocks; geometry never encodes invented quantities."""
    tid, family = entry["visual"], entry["family"]
    x, y, w, h = area
    if tid == "case-scorecard":
        return _cells(count, area, min(3, max(1, count)))
    if tid == "portfolio-grid":
        return _cells(count, area, min(4, max(1, math.ceil(math.sqrt(count)))))
    if tid in {"guide-split", "feature-hero", "landscape-path", "kpi-hero"} and count > 1:
        return [(x, y, w * .42, h - 16)] + _cells(count - 1, (x + w * .48, y, w * .52, h))
    if tid in {"parallel-two", "compare", "change", "tradeoff", "before-after", "team-two", "case-compare", "mapping", "vs-cards", "before-after-case"}:
        return _cells(count, area, min(2, max(1, count)))
    if tid == "parallel-four":
        return _cells(count, area, min(2, max(1, count)))
    if tid in {"parallel-long", "parallel-missing", "swimlane", "gantt", "table", "roles", "faq"}:
        return _cells(count, area)
    if tid in {"hierarchy", "organization", "branch"} and count > 1:
        return [(x + w * .24, y, w * .52, h * .28)] + _cells(count - 1, (x, y + h * .36, w, h * .64), min(3, count - 1))
    if tid in {"hub", "feature-map", "boundary", "zoom"} and count > 1:
        return [(x, y + h * .2, w * .36, h * .6)] + _cells(count - 1, (x + w * .44, y, w * .56, h))
    if tid in {"quote", "executive", "claim-proof", "problem", "cause", "case", "parallel-priority"} and count > 1:
        return [(x, y, w * .44, h - 16)] + _cells(count - 1, (x + w * .5, y, w * .5, h))
    if tid == "loop":
        return _cells(count, area, min(2, max(1, count)))
    if family in {"compare", "process", "proof"} or tid in {"multidevice", "user-journey"}:
        return _cells(count, area, min(3, max(1, count)))
    # Data remains an editable text ledger, including real supplied numbers.
    return _cells(count, area)


def _apply_reference(scene, entry):
    result = validate_scene(scene)
    result["templateId"] = entry["id"]
    role, family, visual = entry["role"], entry["family"], entry["visual"]
    background, ink, accent = {
        "golden": ("#F6F2EA", "#292D32", "#A45135"),
        "argument": ("#FFFFFF", "#172C45", "#365ADB"),
        "compare": ("#F5F8FC", "#172C45", "#266C78"),
        "process": ("#F4F8F5", "#193C32", "#28775A"),
        "structure": ("#FAF9F6", "#253044", "#6751A0"),
        "data": ("#FFFFFF", "#172C45", "#365ADB"),
        "product": ("#F5F8FC", "#172C45", "#266C78"),
        "proof": ("#F6F2EA", "#292D32", "#A45135"),
    }[family]
    if visual == "kpi-hero":
        background, ink, accent = "#102544", "#F0F5FA", "#68D5B5"
    result["background"] = background
    sx, sy = result["width"] / 1280, result["height"] / 720

    def place(obj, cell, size=28):
        x, y, w, h = cell
        obj.update(x=x * sx, y=y * sy, w=max(1, w * sx), h=max(1, h * sy))
        if obj["type"] == "text":
            obj.update(fontSize=max(10, min(160, size * sy)), color=ink, align="left", valign="top", lineHeight=1.3)

    titles, takeaways, body, footers, images = [], [], [], [], []
    ornaments = []
    for obj in result["objects"]:
        if obj["type"] == "text":
            binding = obj.get("binding", obj["id"])
            group = titles if binding == "title" else takeaways if binding == "takeaway" else footers if obj["id"].startswith("footer.") else body
            group.append(obj)
        elif obj["type"] == "image":
            images.append(obj)
        else:
            ornaments.append(obj)
    for i, obj in enumerate(ornaments):
        obj["opacity"] = 1 if i == 0 else 0
        if obj["type"] in ("rect", "ellipse"):
            obj.update(fill=accent, stroke="none", **({"radius": 0} if obj["type"] == "rect" else {}))
            place(obj, (64, 58, 7, 64))
        else:
            obj.update(stroke=accent, strokeWidth=3)
            place(obj, (64, 58, 0, 64))

    if role == "cover":
        title_area, takeaway_area, body_area = (92, 140, 1090, 210), (92, 366, 1090, 80), (92, 488, 1090, 150)
    elif role == "chapter":
        title_area, takeaway_area, body_area = (92, 204, 1090, 180), (92, 410, 1090, 80), (92, 516, 1090, 122)
    elif role == "ending":
        title_area, takeaway_area, body_area = (92, 94, 1090, 160), (92, 274, 1090, 80), (92, 388, 1090, 250)
    else:
        title_area = (92, 58, 1090, 106)
        takeaway_area = (92, 176, 1090, 80)
        body_area = (92, 280 if takeaways else 200, 1090, 358 if takeaways else 438)

    if visual == "toc-sidebar":
        title_area, takeaway_area = (92, 150, 280, 180), (92, 366, 280, 150)
        body_area = (450, 120, 750, 518)
        if ornaments and ornaments[0]["type"] == "rect":
            place(ornaments[0], (64, 90, 8, 548))
    # Image-led pages use a large real asset beside the complete text stack.
    image_led = visual in {"cover-photo", "chapter-image", "focus", "demo", "photo-story"}
    if images and image_led:
        for name, area in (("title", title_area), ("takeaway", takeaway_area), ("body", body_area)):
            narrowed = (area[0], area[1], 450, area[3])
            if name == "title":
                title_area = narrowed
            elif name == "takeaway":
                takeaway_area = narrowed
            else:
                body_area = narrowed
        image_area = (590, 90, 610, 548)
    elif images:
        x, y, w, h = body_area
        image_area = (x + w * .64, y, w * .36, h)
        body_area = (x, y, w * .6, h)
    else:
        image_area = body_area
    for obj, cell in zip(titles, _cells(len(titles), title_area)):
        place(obj, cell, 50 if role in {"cover", "chapter", "ending"} else 40)
        obj["bold"] = True
    for obj, cell in zip(takeaways, _cells(len(takeaways), takeaway_area)):
        place(obj, cell, 24)
        obj["color"] = accent
    for obj, cell in zip(footers, _cells(len(footers), (92, 674, 1110, 40), max(1, len(footers)))):
        place(obj, cell, 16)
    if role == "toc":
        cells = _cells(len(body), body_area, min(2, max(1, len(body))) if visual == "toc-grouped" else 1)
    elif role in {"cover", "chapter", "ending"}:
        cells = _cells(len(body), body_area)
    else:
        cells = _content_cells(len(body), body_area, entry)
    for obj, cell in zip(body, cells):
        place(obj, cell, min(28, max(10, cell[3] * .25)))
    for obj, cell in zip(images, _cells(len(images), image_area, min(2, len(images)))):
        place(obj, cell)
    for obj in result["objects"]:
        fit_text(obj)
    return validate_scene(result)


def sample_scene(template_id):
    base = reference_templates.base_id(template_id)
    if base:
        result = sample_scene(base)
        result["templateId"] = template_id
        return result
    if opening_templates.has_template(template_id):
        return opening_templates.sample_scene(template_id)
    if design_map.has_template(template_id):
        return design_map.sample_scene(template_id)
    if template_id in _REFERENCE:
        entry = _REFERENCE[template_id]
        example = entry["example"]
        if entry.get("local") and entry["visual"] not in {"kpi-hero", "case-scorecard", "landscape-path"}:
            from .local_renderer import scene_from_slide
            return scene_from_slide({"id": "S001", "templateId": template_id, "role": entry["role"],
                                     "title": example["title"],
                                     "keyPoints": "\n\n".join(slot["text"].replace("\\n", "\n") for slot in example["slots"])}, {})
        objects = [{"id": "accent", "type": "rect", "x": 64, "y": 58, "w": 7, "h": 64, "fill": "#365ADB"},
                   {"id": "title", "type": "text", "binding": "title", "text": example["title"],
                    "x": 80, "y": 80, "w": 1000, "h": 100}]
        for i, slot in enumerate(example["slots"]):
            objects.append({"id": f"body-{i + 1}", "type": "text", "binding": f"keyPoints:{i}",
                            "text": slot["label"] + "\n" + slot["text"], "x": 80, "y": 200, "w": 1000, "h": 100})
        return apply_template({"schema": "ppt-scene", "schemaVersion": 1, "slideId": "S001",
                               "width": 1280, "height": 720, "objects": objects}, template_id)
    _template(template_id)
    objects = [{"id": "accent", "type": "rect", "x": 64, "y": 58, "w": 7, "h": 64, "fill": "#365ADB"}]
    for oid, binding, text in (
        ("title", "title", "让每一个观点，清晰呈现"),
        ("takeaway", "takeaway", "从想法到表达，保留内容本来的声音。"),
        ("body-1", "keyPoints:0", "梳理内容\n围绕一个清晰的主题组织材料。"),
        ("body-2", "keyPoints:1", "安排层次\n让标题、观点与细节各有位置。"),
        ("body-3", "keyPoints:2", "确认表达\n在预览中检查文字与阅读顺序。"),
    ):
        objects.append({"id": oid, "type": "text", "binding": binding, "text": text,
                        "x": 80, "y": 80, "w": 1000, "h": 100})
    return apply_template({"schema": "ppt-scene", "schemaVersion": 1, "slideId": "S001",
                           "width": 1280, "height": 720, "objects": objects}, template_id)
