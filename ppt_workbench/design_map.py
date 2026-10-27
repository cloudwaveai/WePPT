"""Faithful static geometry from the original PPT design-map preview renderers.

The JSON scenes are trusted translations, not executable downloaded JavaScript.
Preview text is deliberately confined to sample_scene; applying a template uses
only supplied text and images. Source provenance is recorded in manifest.json.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from .core import EngineError
from .rendering import MAX_OBJECTS, validate_scene
from .template_content import strip_template_decoration, fit_text

_DATA = Path(__file__).with_name("data") / "design-map-scenes"


def has_template(template_id):
    """Whether an ID has a complete source-derived scene."""
    return isinstance(template_id, str) and template_id.replace("-", "").isalnum() and (_DATA / (template_id + ".json")).is_file() and template_id != "manifest"


@lru_cache(maxsize=64)
def _entry(template_id):
    if not has_template(template_id):
        raise EngineError("UNKNOWN_TEMPLATE", "未找到设计地图模板。", {"templateId": template_id})
    return json.loads((_DATA / (template_id + ".json")).read_text(encoding="utf-8"))


def sample_scene(template_id):
    """Return an independent editable source preview, including example labels."""
    return validate_scene(_entry(template_id)["scene"])


def apply_template(scene, template_id):
    """Fit existing content into the source's actual ordered geometry.

    User objects retain their IDs, text, bindings, and image payloads. Static
    example text is never copied. Quantitative source marks are omitted when
    applying data layouts, since they would otherwise fabricate user data.
    """
    result = strip_template_decoration(validate_scene(scene))
    entry = _entry(template_id)
    source = entry["scene"]
    by_id = {o["id"]: o for o in source["objects"]}
    slots = [by_id[k] for k in entry["textSlots"]]
    sx, sy = result["width"] / 1280, result["height"] / 720
    result.update(templateId=template_id, background=source["background"])
    # Only our own previously generated decoration can be removed on reapply.
    # Actual images, including user images with arbitrary IDs, remain intact.
    user = result["objects"]
    titles = [o for o in user if o["type"] == "text" and o.get("binding") == "title"]
    footers = [o for o in user if o["type"] == "text" and o["id"].startswith("footer.")]
    body = [o for o in user if o["type"] == "text" and o not in titles and o not in footers]
    for obj in footers:
        obj.update(x=60 * sx, y=670 * sy, w=1160 * sx, h=32 * sy,
                   fontSize=max(10, min(160, 16 * sy)),
                   color="#A9C8E5" if source["background"] != "#FFFFFF" else "#647A87")
    for obj in user:
        if obj["type"] in {"rect", "line"}:
            # Keep stable IDs while retiring ornaments from the previous layout.
            obj["opacity"] = 0

    def place(obj, slot):
        for key in ("x", "w"):
            obj[key] = slot[key] * sx
        for key in ("y", "h"):
            obj[key] = slot[key] * sy
        if obj["type"] == "text":
            obj['opacity'] = 1
            for key in ("color", "bold", "align", "valign", "lineHeight", "fontFamily"):
                if key in slot:
                    obj[key] = slot[key]
            obj["fontSize"] = max(10, min(160, slot.get("fontSize", 30) * sy))
            # This source caption ink falls just below 4.5:1 when fitted as body text.
            if obj.get("color", "").upper() == "#647A87" and source["background"].upper() == "#FFFFFF":
                obj["color"] = "#607583"
            fit_text(obj)

    for obj in titles:
        place(obj, slots[0])
    # Axis labels, chart annotations and device captions are not body-content slots.
    candidates = [slot for slot in slots[1:] if slot['w'] >= 100 and slot['h'] >= 40]
    body_slots = candidates if len(candidates) >= len(body) else slots[1:] or slots
    if template_id in {'bar', 'line', 'composition', 'waterfall', 'funnel', 'scatter', 'focus'}:
        # With no structured data, show the supplied material as a readable ledger.
        # Tiny chart labels cannot carry paragraphs and illustrative marks are omitted.
        body_slots = [dict(x=80, y=220 + i * 380 / max(1, len(body)), w=1120,
                           h=380 / max(1, len(body)) - 8, fontSize=28,
                           color='#173B53', lineHeight=1.3) for i in range(max(1, len(body)))]
    for i, obj in enumerate(body):
        slot = copy.deepcopy(body_slots[i % len(body_slots)])
        # Extra supplied blocks subdivide a real source slot rather than vanish.
        repeats = (len(body) - 1 - i % len(body_slots)) // len(body_slots) + 1
        if repeats > 1:
            slot["y"] += (i // len(body_slots)) * slot["h"] / repeats
            slot["h"] /= repeats
        place(obj, slot)
    images = [o for o in user if o["type"] == "image"]
    image_slots = entry["imageSlots"]
    if not image_slots:
        # Original slidePreview uses plain rects for image placeholders.
        image_slots = [dict(x=o["x"], y=o["y"], width=o["w"], height=o["h"]) for o in source["objects"] if o["type"] == "rect" and o["w"] > 100 and o["h"] > 90 and o["fill"] in {"#EDF3F5", "#DCE9EF", "#DCECE9"}]
    for i, obj in enumerate(images):
        if image_slots:
            slot = image_slots[i % len(image_slots)]
            count = (len(images) - 1 - i % len(image_slots)) // len(image_slots) + 1
            place(obj, dict(x=slot["x"], y=slot["y"] + (i // len(image_slots)) * slot["height"] / count, w=slot["width"], h=slot["height"] / count))

    existing_ids = {o["id"] for o in user}
    unsafe = set(entry["unsafeDecorations"])
    decorations = []
    for obj in source["objects"]:
        if obj["type"] == "text" or obj["id"] in unsafe:
            continue
        item = copy.deepcopy(obj)
        item["id"] = "design-map.decoration." + str(len(decorations))
        if item["id"] in existing_ids:
            continue
        place(item, obj)
        if "radius" in item:
            item["radius"] *= min(sx, sy)
        if "strokeWidth" in item:
            item["strokeWidth"] = min(24, item["strokeWidth"] * min(sx, sy))
        decorations.append(item)
    # Preserve all original user objects even at the validator object limit.
    result["objects"] = decorations[:max(0, MAX_OBJECTS - len(user))] + user
    return validate_scene(result)
