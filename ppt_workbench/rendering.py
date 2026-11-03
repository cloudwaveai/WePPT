"""Editable slide scenes shared by the browser preview and PPTX exporter.

The scene is the editable source of truth. HTML is a rendering of that source;
PPTX objects use the same geometry and stable object IDs. Browser and Office
font metrics can differ, so actual PowerPoint rendering remains a separate check.
"""
from __future__ import annotations

import base64
import copy
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .core import EngineError

SCENE_SCHEMA = "ppt-scene"
MAX_OBJECTS = 240
MAX_IMAGE_BYTES = 8 * 1024 * 1024
BASE_FIELDS = {"id", "type", "x", "y", "w", "h", "opacity"}
TYPE_FIELDS = {
    "text": {"text", "fontSize", "color", "bold", "align", "valign", "fontFamily", "lineHeight", "italic", "binding", "textSource",
             "letterSpacing", "emphasis", "emphasisColor"},
    "rect": {"fill", "stroke", "strokeWidth", "radius", "rotation", "shadow"},
    "ellipse": {"fill", "stroke", "strokeWidth", "rotation", "shadow"},
    "line": {"stroke", "strokeWidth", "startArrow", "endArrow"},
    "image": {"src", "fit", "alt"},
}
SHADOWS = {"soft": "0 8px 24px rgba(15,23,42,.14)", "lift": "0 16px 40px rgba(15,23,42,.26)"}
MAX_EMPHASIS = 8
COLORS = {"ink": "#12243C", "muted": "#64758A", "blue": "#3459E6",
          "teal": "#168C82", "orange": "#D68438", "paper": "#FFFFFF", "line": "#DCE4ED"}


def _fail(code, message, details=None):
    raise EngineError(code, message, details)


def _number(value, name, low, high):
    if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= high:
        _fail("INVALID_SCENE", f"{name} 必须是 {low} 到 {high} 之间的有限数值。")
    return value


def _finite(value):
    """A finite number for optional decoration, else None (the style is then dropped)."""
    return value if type(value) in {int, float} and math.isfinite(value) else None


def _clamped(value, name, low, high):
    """Style-only numbers (font size, line height, opacity, stroke, radius): an
    out-of-range model value is clamped instead of blocking the page; non-numbers
    still fail. Positions and sizes are never clamped here."""
    if _finite(value) is None:
        _fail("INVALID_SCENE", f"{name} 必须是 {low} 到 {high} 之间的有限数值。")
    return min(high, max(low, value))


def _string(value, name, max_length=20000):
    if not isinstance(value, str) or len(value) > max_length:
        _fail("INVALID_SCENE", f"{name} 必须是长度不超过 {max_length} 的文本。")
    # XML 1.0, used by PPTX, does not permit these code points.
    if any(ord(c) < 32 and c not in "\t\n\r" for c in value):
        _fail("INVALID_SCENE", f"{name} 含有不支持的控制字符。")
    return value


def _color(value, name, allow_none=False):
    if allow_none and value == "none":
        return value
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        _fail("INVALID_SCENE", f"{name} 必须是 #RRGGBB 颜色。")
    return value.upper()


def validate_scene(scene):
    """Validate a complete 16:9 scene and return a normalized independent copy."""
    if not isinstance(scene, dict):
        _fail("INVALID_SCENE", "页面场景必须为对象。")
    allowed = {"schema", "schemaVersion", "slideId", "width", "height", "background", "objects", "title", "notes", "templateId", "bindingSeparator", "diagram"}
    unknown = set(scene) - allowed
    if unknown:
        _fail("INVALID_SCENE", "页面场景包含未知字段。", sorted(unknown))
    s = copy.deepcopy(scene)
    if s.get("schema") != SCENE_SCHEMA or type(s.get("schemaVersion")) is not int or s["schemaVersion"] != 1:
        _fail("INVALID_SCENE", "需要 ppt-scene schemaVersion 1。")
    if not isinstance(s.get("slideId"), str) or not re.fullmatch(r"S\d{3,8}", s["slideId"]):
        _fail("INVALID_SCENE", "页面必须有稳定的 S001 类 ID。")
    width = _number(s.get("width", 1280), "width", 640, 3840)
    height = _number(s.get("height", 720), "height", 360, 2160)
    if abs(width / height - 16 / 9) > 0.001:
        _fail("INVALID_SCENE", "当前渲染器使用 16:9 画布。")
    s["width"], s["height"] = width, height
    s["background"] = _color(s.get("background", "#FFFFFF"), "background")
    if not isinstance(s.get("bindingSeparator", "\n"), str) or s.get("bindingSeparator", "\n") not in {"\n", "\n\n"}:
        _fail("INVALID_SCENE", "bindingSeparator 只能是换行或空行。")
    s["bindingSeparator"] = s.get("bindingSeparator", "\n")
    for field in ("title", "notes", "templateId"):
        if field in s:
            _string(s[field], field)
    objects = s.get("objects")
    if not isinstance(objects, list) or not 1 <= len(objects) <= MAX_OBJECTS:
        _fail("INVALID_SCENE", f"页面需要 1 到 {MAX_OBJECTS} 个对象。")
    seen, bindings = set(), set()
    for obj in objects:
        if not isinstance(obj, dict):
            _fail("INVALID_SCENE", "页面对象必须为对象。")
        oid, kind = obj.get("id"), obj.get("type")
        if not isinstance(oid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", oid) or oid in seen:
            _fail("INVALID_SCENE", "对象 ID 必须唯一，且只使用字母、数字及 _ . : -。")
        seen.add(oid)
        if not isinstance(kind, str) or kind not in TYPE_FIELDS:
            _fail("INVALID_SCENE", f"对象 {oid} 的类型不支持。")
        unknown = set(obj) - BASE_FIELDS - TYPE_FIELDS[kind]
        if unknown:
            _fail("INVALID_SCENE", f"对象 {oid} 含未知属性。", sorted(unknown))
        x, y = _number(obj.get("x"), oid + ".x", 0, width), _number(obj.get("y"), oid + ".y", 0, height)
        w = _number(obj.get("w"), oid + ".w", 0 if kind == "line" else 1, width)
        h = _number(obj.get("h"), oid + ".h", 0 if kind == "line" else 1, height)
        if x + w > width + 0.01 or y + h > height + 0.01 or (kind == "line" and w == h == 0):
            _fail("SCENE_OUT_OF_BOUNDS", f"对象 {oid} 超出画布，或线段长度为零。")
        obj["opacity"] = _clamped(obj.get("opacity", 1), oid + ".opacity", 0, 1)
        if kind == "text":
            if "textSource" in obj:
                source = obj["textSource"]
                if (not isinstance(source, dict) or set(source) != {"ref", "start", "end"}
                        or not isinstance(source["ref"], str)
                        or not re.fullmatch(r"block\.[A-Za-z][A-Za-z0-9_-]{0,30}\.(heading|body)", source["ref"])
                        or type(source["start"]) is not int or type(source["end"]) is not int
                        or not 0 <= source["start"] < source["end"] <= 3000):
                    _fail("INVALID_SCENE", "textSource 必须是有效的原文范围。")
            if "binding" in obj:
                binding = obj["binding"]
                if not isinstance(binding, str) or not re.fullmatch(r"title|takeaway|keyPoints:\d{1,3}", binding) or binding in bindings:
                    _fail("INVALID_SCENE", "文本 binding 必须唯一，使用 title、takeaway 或 keyPoints:0 等格式。")
                bindings.add(binding)
            obj["text"] = _string(obj.get("text", ""), oid + ".text")
            obj["fontSize"] = _clamped(obj.get("fontSize", 30), oid + ".fontSize", 10, 160)
            obj["color"] = _color(obj.get("color", COLORS["ink"]), oid + ".color")
            for field in ("bold", "italic"):
                if type(obj.get(field, False)) is not bool:
                    _fail("INVALID_SCENE", f"{oid}.{field} 必须是布尔值。")
                obj[field] = obj.get(field, False)
            for field, choices, default in (("align", {"left", "center", "right"}, "left"),
                                             ("valign", {"top", "middle", "bottom"}, "top")):
                if not isinstance(obj.get(field, default), str) or obj.get(field, default) not in choices:
                    _fail("INVALID_SCENE", f"{oid}.{field} 取值不支持。")
                obj[field] = obj.get(field, default)
            obj["lineHeight"] = _clamped(obj.get("lineHeight", 1.35), oid + ".lineHeight", 1, 2.5)
            family = obj.get("fontFamily", "Microsoft YaHei")
            if not isinstance(family, str) or not re.fullmatch(r"[\w \-\u3400-\u9fff]{1,80}", family):
                _fail("INVALID_SCENE", f"{oid}.fontFamily 不是支持的字体名。")
            obj["fontFamily"] = family
            # Optional decoration is normalized, never allowed to block a page:
            # a model formatting slip drops the style, the words stay untouched.
            if "letterSpacing" in obj:
                spacing = _finite(obj["letterSpacing"])
                if spacing is None:
                    del obj["letterSpacing"]
                else:
                    obj["letterSpacing"] = min(40, max(-5, spacing))
            if "emphasisColor" in obj:
                accent = obj["emphasisColor"]
                if isinstance(accent, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", accent):
                    obj["emphasisColor"] = accent.upper()
                else:
                    del obj["emphasisColor"]
            if "emphasis" in obj:
                phrases = obj["emphasis"]
                phrases = [phrases] if isinstance(phrases, str) else phrases if isinstance(phrases, list) else []
                # Highlights only style existing words: malformed, stale or extra
                # phrases are dropped instead of inventing or blocking text.
                kept = list(dict.fromkeys(p for p in phrases if isinstance(p, str) and p.strip()
                                          and len(p) <= 80 and p in obj["text"]))[:MAX_EMPHASIS]
                if kept:
                    obj["emphasis"] = kept
                else:
                    del obj["emphasis"]
        elif kind in ("rect", "ellipse"):
            obj["fill"] = _color(obj.get("fill", "none"), oid + ".fill", True)
            obj["stroke"] = _color(obj.get("stroke", "none"), oid + ".stroke", True)
            obj["strokeWidth"] = _clamped(obj.get("strokeWidth", 1), oid + ".strokeWidth", 0, 24)
            if kind == "rect":
                obj["radius"] = _clamped(obj.get("radius", 0), oid + ".radius", 0, min(w, h) / 2)
            if "rotation" in obj:
                angle = _finite(obj["rotation"])
                if angle is None:
                    del obj["rotation"]
                else:
                    obj["rotation"] = angle if -180 <= angle <= 180 else ((angle + 180) % 360) - 180
            if "shadow" in obj and obj["shadow"] not in {"none", *SHADOWS}:
                del obj["shadow"]
        elif kind == "line":
            obj["stroke"] = _color(obj.get("stroke", COLORS["line"]), oid + ".stroke")
            obj["strokeWidth"] = _clamped(obj.get("strokeWidth", 2), oid + ".strokeWidth", 0.1, 24)
            for key in ("startArrow", "endArrow"):
                if key in obj and type(obj[key]) is not bool:
                    _fail("INVALID_SCENE", f"{oid}.{key} 必须是布尔值。")
        elif kind == "image":
            src = obj.get("src")
            if not isinstance(src, str) or not re.fullmatch(r"data:image/(png|jpeg);base64,[A-Za-z0-9+/=\r\n]+", src):
                _fail("INVALID_SCENE_IMAGE", "图片只接受 PNG/JPEG data URL，不加载远程地址。")
            try:
                raw = base64.b64decode(src.split(",", 1)[1].replace("\n", "").replace("\r", ""), validate=True)
            except ValueError:
                _fail("INVALID_SCENE_IMAGE", "图片 base64 无效。")
            mime = src.split(";", 1)[0]
            valid_magic = raw.startswith(b"\x89PNG\r\n\x1a\n") if mime.endswith("png") else raw.startswith(b"\xff\xd8\xff")
            if not valid_magic or len(raw) > MAX_IMAGE_BYTES:
                _fail("INVALID_SCENE_IMAGE", "图片格式不匹配或超过 8 MiB。")
            if not isinstance(obj.get("fit", "contain"), str) or obj.get("fit", "contain") not in {"contain", "cover"}:
                _fail("INVALID_SCENE_IMAGE", "图片 fit 只支持 contain 或 cover。")
            obj["fit"] = obj.get("fit", "contain")
            obj["alt"] = _string(obj.get("alt", oid), oid + ".alt", 1000)
    if 'diagram' in s:
        from .diagram_design import validate_metadata
        validate_metadata(s['diagram'], objects)
    point_indices = sorted(int(b.split(":")[1]) for b in bindings if b.startswith("keyPoints:"))
    if point_indices != list(range(len(point_indices))):
        _fail("INVALID_SCENE", "keyPoints 绑定索引必须从 0 连续排列，避免丢失正文段落。")
    bound_title = next((o["text"] for o in objects if o.get("binding") == "title"), None)
    if bound_title is not None:
        s["title"] = bound_title
    return s


def patch_scene(scene, changes):
    """Apply property-only edits to named objects; IDs/type/order cannot change."""
    s = validate_scene(scene)
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_OBJECTS:
        _fail("INVALID_SCENE_PATCH", "修改需要非空的对象属性数组。")
    by_id = {obj["id"]: obj for obj in s["objects"]}
    changed = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"objectId", "properties"}:
            _fail("INVALID_SCENE_PATCH", "每项修改必须仅含 objectId 和 properties。")
        oid, properties = change["objectId"], change["properties"]
        if not isinstance(oid, str) or oid not in by_id:
            _fail("SCENE_OBJECT_NOT_FOUND", "未找到要修改的页面对象。", {"objectId": oid})
        if oid in changed:
            _fail("INVALID_SCENE_PATCH", "同一对象请在一个 properties 中提交所有修改。")
        changed.add(oid)
        obj = by_id[oid]
        if not isinstance(properties, dict) or not properties:
            _fail("INVALID_SCENE_PATCH", "properties 不能为空。")
        allowed = ((BASE_FIELDS - {"id", "type"}) | TYPE_FIELDS[obj["type"]]) - {"binding"}
        if set(properties) - allowed:
            _fail("SCENE_SCOPE_VIOLATION", "不能通过局部补丁更换 ID、类型或其他对象。", {"objectId": oid})
        obj.update(copy.deepcopy(properties))
    return validate_scene(s)


def edit_scene_objects(scene, operations):
    """Apply atomic structural edits and return a validated independent scene.

    Operations are applied in order: {"op":"add", "object": {...},
    "index": N} (index optional, defaults to end), {"op":"delete",
    "objectId": ID}, or {"op":"reorder", "objectId": ID, "index": N}.
    Indices are zero-based positions in the resulting object list. Added objects
    cannot introduce content bindings; bound objects cannot be deleted. Existing
    objects retain their IDs, properties and bindings. The input is never changed,
    including when an operation or final scene fails validation.
    """
    s = validate_scene(scene)
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OBJECTS:
        _fail("INVALID_SCENE_OPERATION", "操作需要非空的对象操作数组。")
    objects = s["objects"]
    for operation in operations:
        if not isinstance(operation, dict):
            _fail("INVALID_SCENE_OPERATION", "对象操作必须为对象。")
        op = operation.get("op")
        if op == "add":
            if set(operation) not in ({"op", "object"}, {"op", "object", "index"}):
                _fail("INVALID_SCENE_OPERATION", "add 需要 object 和可选 index。")
            obj = operation["object"]
            if not isinstance(obj, dict):
                _fail("INVALID_SCENE_OPERATION", "新增对象必须为对象。")
            if "binding" in obj:
                _fail("SCENE_SCOPE_VIOLATION", "新增对象不能设置内容绑定。")
            index = operation.get("index", len(objects))
            if type(index) is not int or not 0 <= index <= len(objects):
                _fail("INVALID_SCENE_OPERATION", "新增位置超出范围。")
            objects.insert(index, copy.deepcopy(obj))
        elif op == "delete" or op == "reorder":
            expected = {"op", "objectId"} | ({"index"} if op == "reorder" else set())
            if set(operation) != expected:
                _fail("INVALID_SCENE_OPERATION", "对象操作字段不正确。")
            oid = operation["objectId"]
            position = next((i for i, obj in enumerate(objects) if obj.get("id") == oid), None)
            if not isinstance(oid, str) or position is None:
                _fail("SCENE_OBJECT_NOT_FOUND", "未找到页面对象。", {"objectId": oid})
            if op == "delete":
                if "binding" in objects[position]:
                    _fail("SCENE_SCOPE_VIOLATION", "不能删除绑定内容的对象。", {"objectId": oid})
                objects.pop(position)
                if oid in s.get('diagram', {}).get('objectIds', []):
                    s.pop('diagram')
            else:
                index = operation["index"]
                if type(index) is not int or not 0 <= index < len(objects):
                    _fail("INVALID_SCENE_OPERATION", "排序位置超出范围。")
                objects.insert(index, objects.pop(position))
        else:
            _fail("INVALID_SCENE_OPERATION", "不支持的对象操作。")
    return validate_scene(s)


def _css_number(n):
    return format(n, ".6g")


def emphasis_segments(text, phrases):
    """Split text into (segment, emphasized) runs; leftmost, longest phrase wins.

    The PPTX exporter implements the same scan so both renderers agree.
    """
    ordered = sorted(set(phrases or ()), key=len, reverse=True)
    segments, plain, index = [], "", 0
    while index < len(text):
        match = next((p for p in ordered if text.startswith(p, index)), None)
        if match:
            if plain:
                segments.append((plain, False))
                plain = ""
            segments.append((match, True))
            index += len(match)
        else:
            plain += text[index]
            index += 1
    if plain:
        segments.append((plain, False))
    return segments


def _shape_style(obj):
    style = ""
    if obj.get("shadow") in SHADOWS:
        style += f"box-shadow:{SHADOWS[obj['shadow']]};"
    if obj.get("rotation"):
        style += f"transform:rotate({_css_number(obj['rotation'])}deg);transform-origin:center;"
    return style


def render_html(scene, interactive=True):
    """Self-contained preview, with only fixed script and escaped user strings."""
    s = validate_scene(scene)
    parts = []
    for obj in s["objects"]:
        oid, kind = obj["id"], obj["type"]
        style = f"left:{obj['x']}px;top:{obj['y']}px;width:{obj['w']}px;height:{obj['h']}px;opacity:{obj['opacity']};"
        attrs = f'data-object-id="{html.escape(oid, quote=True)}" data-type="{kind}"'
        if interactive:
            attrs += f' tabindex="0" role="button" aria-label="选择 {html.escape(oid, quote=True)}"'
        if kind == "text":
            justify = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}[obj["valign"]]
            style += (f"font-size:{obj['fontSize']}px;color:{obj['color']};font-weight:{700 if obj['bold'] else 400};"
                      f"font-style:{'italic' if obj['italic'] else 'normal'};text-align:{obj['align']};"
                      f"line-height:{obj['lineHeight']};font-family:'{obj['fontFamily']}', 'Noto Sans CJK SC', sans-serif;justify-content:{justify};")
            if obj.get("letterSpacing"):
                style += f"letter-spacing:{_css_number(obj['letterSpacing'])}px;"
            if obj.get("emphasis"):
                accent = html.escape(obj.get("emphasisColor", obj["color"]), quote=True)
                content = "".join(f'<span class="text-em" style="color:{accent};font-weight:700">{html.escape(part)}</span>'
                                  if emphasized else html.escape(part)
                                  for part, emphasized in emphasis_segments(obj["text"], obj["emphasis"]))
            else:
                content = html.escape(obj["text"])
            parts.append(f'<div class="object text" {attrs} style="{html.escape(style, quote=True)}"><span class="text-content">{content}</span></div>')
        elif kind in ("rect", "ellipse"):
            radius = "50%" if kind == "ellipse" else f"{obj['radius']}px"
            style += (f"background:{'transparent' if obj['fill']=='none' else obj['fill']};"
                      f"border:{obj['strokeWidth']}px solid {'transparent' if obj['stroke']=='none' else obj['stroke']};border-radius:{radius};"
                      + _shape_style(obj))
            parts.append(f'<div class="object {kind}" {attrs} style="{html.escape(style, quote=True)}"></div>')
        elif kind == "line":
            # An SVG line is editable in the scene and exported as a native PPT line.
            length = math.hypot(obj["w"], obj["h"])
            angle = math.degrees(math.atan2(obj["h"], obj["w"]))
            style = (f"left:{obj['x']}px;top:{obj['y']}px;width:{length}px;height:{obj['strokeWidth']}px;"
                     f"background:{obj['stroke']};opacity:{obj['opacity']};transform:rotate({angle}deg);transform-origin:0 0;")
            tips=[]
            head=min(max(8,obj['strokeWidth']*4),length/2)
            center=obj['strokeWidth']/2
            for end in ('start','end'):
                if obj.get(end+'Arrow'):
                    tip=0 if end=='start' else length
                    base=head if end=='start' else length-head
                    tips.append(f'<polygon data-arrow="{end}" points="{tip},{center} {base},{center-head/2} {base},{center+head/2}" fill="{obj["stroke"]}"/>')
            arrows=(f'<svg width="{length}" height="{obj["strokeWidth"]}" style="position:absolute;inset:0;overflow:visible;pointer-events:none">'+''.join(tips)+'</svg>') if tips else ''
            parts.append(f'<div class="object line" {attrs} style="{style}">{arrows}</div>')
        else:
            style += f"object-fit:{obj['fit']};"
            parts.append(f'<img class="object image" {attrs} src="{obj["src"]}" alt="{html.escape(obj["alt"], quote=True)}" style="{style}">')
    width, height = s["width"], s["height"]
    script = f"""
const slide=document.getElementById('slide');
const resize=()=>{{const scale=Math.min(innerWidth/{width},innerHeight/{height});slide.style.transform='translate(-50%,-50%) scale('+scale+')';}};
addEventListener('resize',resize);resize();requestAnimationFrame(resize);document.fonts.ready.then(resize);
parent.postMessage({{type:'ppt-ready'}},'*');
"""
    if interactive:
        script += """
function selectObject(el){document.querySelectorAll('.selected').forEach(n=>n.classList.remove('selected'));el.classList.add('selected');parent.postMessage({type:'ppt-select',objectId:el.dataset.objectId},'*');}
document.addEventListener('click',e=>{const el=e.target.closest('[data-object-id]');if(el)selectObject(el);});
document.addEventListener('keydown',e=>{if(e.target.isContentEditable)return;if((e.key==='Enter'||e.key===' ')&&e.target.dataset.objectId){e.preventDefault();selectObject(e.target);}});
document.addEventListener('dblclick',e=>{const el=e.target.closest('.text');if(!el)return;const content=el.querySelector('.text-content');selectObject(el);content.contentEditable='plaintext-only';content.focus();parent.postMessage({type:'ppt-edit',objectId:el.dataset.objectId,text:content.innerText},'*');});
document.addEventListener('input',e=>{const el=e.target.closest('.text');if(el && e.target.isContentEditable)parent.postMessage({type:'ppt-edit',objectId:el.dataset.objectId,text:el.querySelector('.text-content').innerText},'*');});
addEventListener('message',e=>{if(e.source!==parent)return;if(e.data?.type==='ppt-highlight'){document.querySelectorAll('.selected').forEach(n=>n.classList.remove('selected'));const el=[...document.querySelectorAll('[data-object-id]')].find(n=>n.dataset.objectId===e.data.objectId);if(el)el.classList.add('selected');}});
function reportOverflow(){const ids=[...document.querySelectorAll('.text')].filter(el=>el.scrollHeight>el.clientHeight+2||el.scrollWidth>el.clientWidth+2).map(el=>el.dataset.objectId);parent.postMessage({type:'ppt-overflow',objectIds:ids},'*');}
document.fonts.ready.then(reportOverflow);setTimeout(reportOverflow,150);
"""
        script += """
// Editing gestures are proposals to the parent; only its versioned API persists them.
const originalGeometry=new Map([...document.querySelectorAll('[data-object-id]')].map(el=>[el.dataset.objectId,{left:el.style.left,top:el.style.top,width:el.style.width,height:el.style.height}]));
const handles=document.createElement('div');handles.id='selection-handles';handles.hidden=true;slide.append(handles);
for(const corner of ['nw','ne','sw','se']){const handle=document.createElement('span');handle.className='resize-handle '+corner;handle.dataset.corner=corner;handles.append(handle);}
function updateHandles(){const el=document.querySelector('.object.selected');handles.hidden=!el || !!el.querySelector('[contenteditable]') || el.dataset.type==='line';if(!handles.hidden){for(const [style,value] of Object.entries({left:el.style.left,top:el.style.top,width:el.style.width,height:el.style.height}))handles.style[style]=value;}}
const observeSelection=new MutationObserver(updateHandles);document.querySelectorAll('.object').forEach(el=>observeSelection.observe(el,{attributes:true,attributeFilter:['class']}));
let gesture=null;
document.addEventListener('pointerdown',e=>{
  if(e.button!==0 || e.target.isContentEditable)return;
  const corner=e.target.dataset.corner;
  const el=corner?document.querySelector('.object.selected'):e.target.closest('[data-object-id]');
  if(!el)return;
  if(el.querySelector('[contenteditable]'))return;
  const scale=slide.getBoundingClientRect().width/slide.offsetWidth;
  gesture={el,corner,scale,startX:e.clientX,startY:e.clientY,x:parseFloat(el.style.left),y:parseFloat(el.style.top),w:parseFloat(el.style.width),h:parseFloat(el.style.height),moved:false,pointerId:e.pointerId};
  if(corner)e.preventDefault();
});
document.addEventListener('pointermove',e=>{
  if(!gesture || gesture.pointerId!==e.pointerId)return;
  const g=gesture,dx=(e.clientX-g.startX)/g.scale,dy=(e.clientY-g.startY)/g.scale;
  if(!g.moved && Math.hypot(e.clientX-g.startX,e.clientY-g.startY)<4)return;
  if(!g.moved){selectObject(g.el);g.el.setPointerCapture(e.pointerId);g.moved=true;}
  e.preventDefault();
  let x=g.x,y=g.y,w=g.w,h=g.h;
  if(!g.corner){x=Math.max(0,Math.min(slide.offsetWidth-w,g.x+dx));y=Math.max(0,Math.min(slide.offsetHeight-h,g.y+dy));}
  else{
    const west=g.corner.includes('w'),north=g.corner.includes('n');
    w=Math.max(10,g.w+(west?-dx:dx));h=Math.max(10,g.h+(north?-dy:dy));
    // Images always preserve their existing display aspect ratio.
    if(g.el.dataset.type==='image' || e.shiftKey){const ratio=g.w/g.h;h=w/ratio;}
    const maxW=west?g.x+g.w:slide.offsetWidth-g.x,maxH=north?g.y+g.h:slide.offsetHeight-g.y;
    if(g.el.dataset.type==='image' || e.shiftKey){const factor=Math.min(1,maxW/w,maxH/h);w*=factor;h*=factor;}else{w=Math.min(w,maxW);h=Math.min(h,maxH);}
    x=west?g.x+g.w-w:g.x;y=north?g.y+g.h-h:g.y;
  }
  g.properties={x:Math.round(x*100)/100,y:Math.round(y*100)/100,...(g.corner?{w:Math.round(w*100)/100,h:Math.round(h*100)/100}:{})};
  Object.assign(g.el.style,{left:x+'px',top:y+'px',width:w+'px',height:h+'px'});updateHandles();
});
document.addEventListener('pointerup',e=>{if(!gesture || gesture.pointerId!==e.pointerId)return;const g=gesture;gesture=null;if(g.moved){g.el.releasePointerCapture(e.pointerId);parent.postMessage({type:'ppt-geometry',objectId:g.el.dataset.objectId,properties:g.properties},'*');}});
document.addEventListener('pointercancel',()=>{if(gesture){Object.assign(gesture.el.style,originalGeometry.get(gesture.el.dataset.objectId));gesture=null;updateHandles();}});
document.addEventListener('dragstart',e=>e.preventDefault());
document.addEventListener('click',e=>{if(e.target===slide){document.querySelectorAll('.selected').forEach(el=>el.classList.remove('selected'));parent.postMessage({type:'ppt-clear'},'*');}});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();parent.postMessage({type:'ppt-save'},'*');return;}
  if(e.target.isContentEditable){if(e.key==='Escape'){e.target.removeAttribute('contenteditable');updateHandles();}return;}
  if((e.ctrlKey||e.metaKey)&&['z','y'].includes(e.key.toLowerCase())){e.preventDefault();parent.postMessage({type:'ppt-history',action:e.shiftKey||e.key.toLowerCase()==='y'?'redo':'undo'},'*');return;}
  const el=document.querySelector('.object.selected');if(!el)return;
  const step=e.shiftKey?10:1;const direction={ArrowLeft:[-step,0],ArrowRight:[step,0],ArrowUp:[0,-step],ArrowDown:[0,step]}[e.key];
  if(direction){e.preventDefault();parent.postMessage({type:'ppt-geometry',objectId:el.dataset.objectId,properties:{x:Math.max(0,Math.min(slide.offsetWidth-parseFloat(el.style.width),parseFloat(el.style.left)+direction[0])),y:Math.max(0,Math.min(slide.offsetHeight-parseFloat(el.style.height),parseFloat(el.style.top)+direction[1]))}},'*');}
});
addEventListener('message',e=>{if(e.source!==parent)return;if(e.data?.type==='ppt-reset-geometry'){const el=[...document.querySelectorAll('[data-object-id]')].find(n=>n.dataset.objectId===e.data.objectId);if(el){Object.assign(el.style,originalGeometry.get(el.dataset.objectId));updateHandles();}}});

// Reports geometry only. The parent binds the iframe to its exact revision;
// the server validates every object and never interprets this as approval.
function reportQuality(){
  const objects=[...document.querySelectorAll('[data-object-id]')].map(el=>{
    const item={objectId:el.dataset.objectId,type:el.dataset.type,clientWidth:el.clientWidth,clientHeight:el.clientHeight,scrollWidth:el.scrollWidth,scrollHeight:el.scrollHeight};
    if(item.type==='image')item.imageLoaded=el.complete&&el.naturalWidth>0;
    return item;
  });
  const overflowIds=objects.filter(o=>o.type==='text'&&(o.scrollHeight>o.clientHeight+2||o.scrollWidth>o.clientWidth+2)).map(o=>o.objectId);
  const report={schema:'ppt-browser-measurement',schemaVersion:1,slideId:QUALITY_SLIDE_ID,width:QUALITY_WIDTH,height:QUALITY_HEIGHT,fontsReady:document.fonts.status==='loaded',imagesLoaded:objects.filter(o=>o.type==='image').every(o=>o.imageLoaded),objects,overflowIds};
  parent.postMessage({type:'ppt-quality',report},'*');
}
let qualityFrame=0,qualityTimer=0;
// Background measurement frames are offscreen, sandboxed (cross-origin) frames: Chrome
// throttles their rendering and may never run animation frames, so a timer also reports.
function scheduleQuality(){cancelAnimationFrame(qualityFrame);clearTimeout(qualityTimer);qualityFrame=requestAnimationFrame(()=>requestAnimationFrame(reportQuality));qualityTimer=setTimeout(reportQuality,250);}
document.fonts.ready.then(scheduleQuality);
Promise.all([...document.querySelectorAll('img')].map(img=>img.complete?Promise.resolve():new Promise(resolve=>{img.addEventListener('load',resolve,{once:true});img.addEventListener('error',resolve,{once:true});}))).then(scheduleQuality);
setTimeout(scheduleQuality,300);setTimeout(scheduleQuality,1500);
""".replace("QUALITY_SLIDE_ID", json.dumps(s["slideId"])).replace("QUALITY_WIDTH", str(width)).replace("QUALITY_HEIGHT", str(height))
    else:
        script += """
addEventListener('keydown',e=>{let step;if(['ArrowRight','PageDown',' '].includes(e.key))step=1;else if(['ArrowLeft','PageUp'].includes(e.key))step=-1;else if(e.key==='Home')step='first';else if(e.key==='End')step='last';if(step!==undefined){e.preventDefault();parent.postMessage({type:'ppt-navigate',step},'*');}});
"""
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(s.get('title',s['slideId']))}</title>
<style>*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}}#slide{{position:absolute;left:50%;top:50%;width:{width}px;height:{height}px;transform-origin:center;background:{s['background']};overflow:hidden}}.object{{position:absolute}}.text{{display:flex;flex-direction:column;overflow:hidden}}.text-content{{white-space:pre-wrap;overflow-wrap:anywhere;flex:0 0 auto}}.selected{{outline:3px solid #647CFF!important;outline-offset:5px}}[role=button]{{cursor:pointer}}.image{{display:block}}#selection-handles{{position:absolute;pointer-events:none;outline:1px solid #B7472A;z-index:1000}}.resize-handle{{position:absolute;width:10px;height:10px;background:white;border:1px solid #B7472A;pointer-events:auto}}.resize-handle.nw{{left:-5px;top:-5px;cursor:nwse-resize}}.resize-handle.ne{{right:-5px;top:-5px;cursor:nesw-resize}}.resize-handle.sw{{left:-5px;bottom:-5px;cursor:nesw-resize}}.resize-handle.se{{right:-5px;bottom:-5px;cursor:nwse-resize}}[contenteditable]{{outline:none;cursor:text}}@media print{{html,body{{width:1280px;height:720px}}#slide{{left:0;top:0;transform:scale({1280/width})!important;transform-origin:top left}}.selected{{outline:none!important}}}}@page{{size:13.333333in 7.5in;margin:0}}</style></head><body><main id="slide" aria-label="演示页面">{''.join(parts)}</main><script>{script}</script></body></html>'''


def _text_obj(oid, text, x, y, w, h, size=30, color=None, bold=False, **extra):
    return {"id": oid, "type": "text", "x": x, "y": y, "w": w, "h": h,
            "text": text, "fontSize": size, "color": color or COLORS["ink"], "bold": bold, **extra}


def _rect(oid, x, y, w, h, fill, **extra):
    return {"id": oid, "type": "rect", "x": x, "y": y, "w": w, "h": h, "fill": fill, **extra}


def _line(oid, x, y, w, h=0, color=None, stroke=2):
    return {"id": oid, "type": "line", "x": x, "y": y, "w": w, "h": h,
            "stroke": color or COLORS["line"], "strokeWidth": stroke}


def scene_from_slide(slide, project, template=None):
    """Create a starter layout from supplied content without inventing claims.

    Built-in geometry covers golden pages, comparisons, parallel items and steps.
    Other template IDs use a readable general layout; agents can replace it with
    a custom scene. Long text is retained and reported as overflow by the viewer.
    """
    if not isinstance(slide, dict) or not isinstance(project, dict):
        _fail("INVALID_SCENE", "需要页面与项目记录。")
    sid = slide.get("id", "S001")
    title = str(slide.get("title") or "未命名页面")
    takeaway = str(slide.get("takeaway") or "").strip()
    raw = str(slide.get("keyPoints") or "").strip()
    used_intent = False
    if not takeaway and not raw:
        raw = str(slide.get("userIntent") or "").strip()
        if not raw and slide.get("userInputs"):
            raw = "\n".join(str(i.get("text", "")) for i in slide["userInputs"])
        used_intent = bool(raw)
    role = slide.get("role") or "content"
    tid = slide.get("templateId") or role
    if template and isinstance(template, dict):
        tid = template.get("id", template.get("template", {}).get("id", tid))
    entries = [line.strip() for line in re.split(r"\n+", raw) if line.strip()]
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", raw) if block.strip()]
    separator = "\n"
    if tid in {"compare", "change", "tradeoff", "before-after", "team-two", "case-compare"} and len(paragraphs) >= 2:
        entries = paragraphs
        separator = "\n\n"
    s = {"schema": SCENE_SCHEMA, "schemaVersion": 1, "slideId": sid,
         "width": 1280, "height": 720, "background": COLORS["paper"],
         "title": title, "templateId": tid, "objects": [], "bindingSeparator": separator,
         "notes": "基础排版保留所提供文案；请在实际预览中确认表达与溢出。" + (" 本页暂用用户原话作为草稿。" if used_intent else "")}
    objects = s["objects"]
    footer = ""  # New starter pages never repeat the deck title as a footer.
    page_number = str(int(sid[1:])).zfill(2) if re.fullmatch(r"S\d+", sid) else sid
    if role == "cover" or tid.startswith("cover"):
        s["background"] = "#102544"
        objects.extend([
            _rect("cover.accent", 72, 90, 64, 7, "#42D6B2"),
            _text_obj("title", title, 72, 160, 1100, 240, 66, "#FFFFFF", True, lineHeight=1.16),
        ])
        if takeaway:
            objects.append(_text_obj("takeaway", takeaway, 76, 430, 1080, 86 if raw else 180, 30, "#BCCBE2", lineHeight=1.4))
        if raw:
            objects.append(_text_obj("body-1", raw, 76, 538 if takeaway else 430, 1080, 100 if takeaway else 180, 27, "#BCCBE2", lineHeight=1.35))
        if footer and footer != title:
            objects.append(_text_obj("footer.project", footer, 76, 654, 1070, 28, 18, "#8DA8CC"))
    elif role == "chapter" or tid.startswith("chapter"):
        s["background"] = "#F1F5FB"
        chapter_match = re.search(r"第([零一二三四五六七八九十百\d]+)章", title)
        # Keep the explicit chapter label legible: a lone Chinese "一" looks
        # like a decorative rule rather than a chapter indicator.
        chapter_mark = chapter_match.group(0) if chapter_match else "章节"
        chapter_mark_size = min(118, 430 / max(1, len(chapter_mark)))
        objects.extend([
            _text_obj("chapter.number", chapter_mark, 72, 60, 460, 230, chapter_mark_size, "#D4DFF0", True, lineHeight=1.0),
            _rect("chapter.accent", 76, 286, 66, 7, COLORS["blue"]),
            _text_obj("title", title, 72, 320, 1100, 140, 56, COLORS["ink"], True, lineHeight=1.2),
        ])
        if takeaway:
            objects.append(_text_obj("takeaway", takeaway, 76, 484, 1080, 70 if raw else 160, 28, COLORS["muted"]))
        if raw:
            objects.append(_text_obj("body-1", raw, 76, 566 if takeaway else 484, 1080, 110 if takeaway else 180, 26, COLORS["muted"], lineHeight=1.3))
    else:
        objects.extend([
            _rect("header.accent", 64, 62, 7, 46, COLORS["blue"]),
            _text_obj("title", title, 92, 54, 1112, 104, 48, bold=True, lineHeight=1.12),
            _line("footer.rule", 72, 660, 1136),
            _text_obj("footer.number", page_number, 1130, 679, 76, 24, 17, COLORS["muted"], align="right"),
        ])
        if footer and footer != title:
            objects.append(_text_obj("footer.project", footer, 72, 679, 1020, 24, 17, COLORS["muted"]))
        start_y = 204 if takeaway else 182
        if takeaway:
            objects.append(_text_obj("takeaway", takeaway, 76, 154, 1120, 68, 27, COLORS["muted"], lineHeight=1.25))
            start_y = 252
        if role == "toc" or tid.startswith("toc"):
            if entries and len(entries) <= 8:
                n = len(entries)
                row_h = min(92, (620 - start_y) / n)
                for i, text in enumerate(entries):
                    y = start_y + i * row_h
                    objects.extend([
                        _text_obj(f"item.{i+1}.number", str(i+1).zfill(2), 80, y, 90, row_h-10, min(36, row_h * .5), COLORS["blue"], True),
                        _text_obj(f"body-{i+1}", text, 204, y + 2, 950, row_h-10, max(18, min(32, row_h*.4)), lineHeight=1.2),
                    ])
                    if i < n - 1:
                        objects.append(_line(f"item.{i+1}.rule", 204, y+row_h-10, 950))
            elif entries:
                objects.append(_text_obj("body-1", raw, 80, start_y, 1100, 630-start_y, 25, lineHeight=1.4))
            elif not takeaway:
                objects.append(_text_obj("body-1", "[补充本次材料的章节名称]", 80, 250, 1100, 180, 32, COLORS["muted"]))
        elif ((tid in {"compare", "change", "tradeoff", "before-after", "team-two"} and len(entries) == 2)
              or (tid in {"parallel", "case-compare"} and 2 <= len(entries) <= 4)):
            gap, count = 36, len(entries)
            w = (1128 - gap * (count-1)) / count
            accents = [COLORS["blue"], COLORS["teal"], COLORS["orange"], "#8959B3"]
            for i, text in enumerate(entries):
                x = 76 + i*(w+gap)
                objects.extend([
                    _rect(f"item.{i+1}.accent", x, start_y, 54, 6, accents[i]),
                    _text_obj(f"body-{i+1}", text, x, start_y + 38, w, 600-start_y, 32 if count <= 2 else 27, lineHeight=1.48),
                ])
                if i < count-1:
                    objects.append(_line(f"item.{i+1}.divider", x+w+gap/2, start_y+2, 0, 600-start_y, "#DCE4ED", 1))
        elif tid in {"process", "timeline", "roadmap", "user-journey"} and 2 <= len(entries) <= 6:
            n = len(entries)
            col = 1120/n
            y = start_y + 55
            objects.append(_line("process.rule", 104, y+27, 1038, 0, "#CCD7EA", 3))
            for i, text in enumerate(entries):
                x = 76 + i*col
                color = COLORS["teal"] if i == n-1 else COLORS["blue"]
                objects.extend([
                    _rect(f"step.{i+1}.dot", x, y, 56, 56, color, radius=28),
                    _text_obj(f"step.{i+1}.number", str(i+1).zfill(2), x, y+8, 56, 40, 26, "#FFFFFF", True, align="center", lineHeight=1.2),
                    _text_obj(f"body-{i+1}", text, x, y+92, col-30, 230, 28 if n<5 else 23, lineHeight=1.45),
                ])
        else:
            body = raw
            if not body and not takeaway:
                body = "[补充本页需要表达的内容]"
            if body:
                text_size = 34 if len(body) < 160 else (30 if len(body) < 350 else 25)
                if role == "ending":
                    text_size = 38 if len(body) < 140 else 30
                objects.append(_text_obj("body-1", body, 80, start_y+12, 1110, 622-start_y, text_size, lineHeight=1.5))
    for obj in objects:
        if obj["type"] != "text":
            continue
        if obj["id"] in {"title", "takeaway"}:
            obj["binding"] = obj["id"]
        elif re.fullmatch(r"body-\d+", obj["id"]):
            obj["binding"] = "keyPoints:" + str(int(obj["id"].split("-")[1])-1)
    return validate_scene(s)


def export_html_deck(scenes, title=""):
    """Standalone deck with previous/next keys, an index and print-all styling."""
    _string(title, "title")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 200:
        _fail("INVALID_SCENE", "导出需要 1 到 200 页场景。")
    normalized = [validate_scene(scene) for scene in scenes]
    if len({s["slideId"] for s in normalized}) != len(normalized):
        _fail("INVALID_SCENE", "导出页面 ID 不能重复。")
    frames = []
    for i, scene in enumerate(normalized):
        preview = render_html(scene, interactive=False)
        frames.append(f'<section class="page{" active" if i==0 else ""}" data-index="{i}"><iframe title="{html.escape(scene.get("title",scene["slideId"]),quote=True)}" sandbox="allow-scripts" srcdoc="{html.escape(preview,quote=True)}"></iframe></section>')
    label = html.escape(title or normalized[0].get("title", "演示文稿"))
    bridge = """addEventListener('message',e=>{if(!pages.some(p=>p.querySelector('iframe').contentWindow===e.source)||e.data?.type!=='ppt-navigate')return;const step=e.data.step;if(step===1||step===-1)show(current+step);else if(step==='first')show(0);else if(step==='last')show(pages.length-1);});"""
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{label}</title>
<style>*{{box-sizing:border-box}}html,body{{margin:0;background:#111a2a;color:white;font:15px system-ui,sans-serif;min-height:100%}}main{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:36px 20px 86px}}.page{{display:none;width:min(1280px,calc(100vw - 40px),calc((100vh - 122px) * 1.777777778));aspect-ratio:16/9;background:white;box-shadow:0 25px 80px #0005}}.page.active{{display:block}}iframe{{width:100%;height:100%;border:0;display:block}}nav{{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);display:flex;gap:18px;align-items:center;background:#24324d;border:1px solid #42516e;border-radius:30px;padding:9px 17px}}button{{border:0;color:white;background:transparent;font:inherit;cursor:pointer;padding:6px 12px}}button:disabled{{opacity:.3;cursor:default}}#counter{{font-variant-numeric:tabular-nums;min-width:65px;text-align:center}}@media print{{html,body{{background:white}}main{{display:block;padding:0;min-height:0}}.page,.page.active{{display:block;width:1280px;height:720px;aspect-ratio:auto;box-shadow:none;break-after:page;page-break-after:always}}.page:last-child{{break-after:auto}}nav{{display:none}}}}@page{{size:13.333333in 7.5in;margin:0}}</style></head><body><main>{''.join(frames)}</main><nav aria-label="演示控制"><button id="prev" type="button">← 上一页</button><span id="counter"></span><button id="next" type="button">下一页 →</button><button type="button" id="print">打印</button></nav>
<script>const pages=[...document.querySelectorAll('.page')];let current=0;function show(n){{current=Math.max(0,Math.min(pages.length-1,n));pages.forEach((p,i)=>p.classList.toggle('active',i===current));document.getElementById('counter').textContent=(current+1)+' / '+pages.length;document.getElementById('prev').disabled=current===0;document.getElementById('next').disabled=current===pages.length-1;}}document.getElementById('prev').onclick=()=>show(current-1);document.getElementById('next').onclick=()=>show(current+1);document.getElementById('print').onclick=()=>print();addEventListener('keydown',e=>{{if(['ArrowRight','PageDown',' '].includes(e.key)){{e.preventDefault();show(current+1);}}if(['ArrowLeft','PageUp'].includes(e.key)){{e.preventDefault();show(current-1);}}if(e.key==='Home')show(0);if(e.key==='End')show(pages.length-1);}});{bridge}show(0);</script></body></html>'''


def export_pptx(scenes, output_path, title=""):
    """Write an editable PowerPoint via PptxGenJS using this exact scene model."""
    _string(title, "title")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 200:
        _fail("INVALID_SCENE", "导出需要 1 到 200 页场景。")
    normalized = [validate_scene(scene) for scene in scenes]
    if len({s["slideId"] for s in normalized}) != len(normalized):
        _fail("INVALID_SCENE", "导出页面 ID 不能重复。")
    node = shutil.which("node")
    if not node:
        _fail("PPTX_DEPENDENCY_MISSING", "可编辑 PPTX 导出需要 Node.js 和 pptxgenjs 4.0.1。HTML 预览仍可使用。")
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".pptx":
        _fail("INVALID_OUTPUT_PATH", "PPTX 导出路径必须使用 .pptx 后缀。")
    target.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name("export-pptx.mjs")
    descriptor, temp_name = tempfile.mkstemp(prefix=".ppt-workbench-", suffix=".pptx", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        try:
            result = subprocess.run([node, str(script), str(temporary)], input=json.dumps({"scenes": normalized, "title": title}, ensure_ascii=False),
                                    text=True, capture_output=True, timeout=90, check=False)
        except subprocess.TimeoutExpired:
            _fail("PPTX_EXPORT_TIMEOUT", "PPTX 导出超时，文件未被视为完成。")
        if result.returncode:
            try:
                error = json.loads(result.stderr.strip().splitlines()[-1])
                code, message = error.get("code", "PPTX_EXPORT_FAILED"), error.get("message", "PPTX 导出失败。")
            except (ValueError, IndexError):
                code, message = "PPTX_EXPORT_FAILED", "PPTX 导出失败。请检查 Node.js 与 pptxgenjs 安装。"
            _fail(code, message)
        try:
            exporter_info = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            _fail("PPTX_EXPORT_FAILED", "导出器未返回完整结果。")
        try:
            with zipfile.ZipFile(temporary) as package:
                if package.testzip() is not None or "ppt/presentation.xml" not in package.namelist():
                    _fail("PPTX_EXPORT_FAILED", "导出结果不是完整的演示文稿文件。")
        except (OSError, zipfile.BadZipFile):
            _fail("PPTX_EXPORT_FAILED", "导出器未写出完整的 PPTX 文件。")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(target), "slideCount": len(normalized), "bytes": target.stat().st_size,
            "editable": True, "renderer": "pptxgenjs", "rendererVersion": exporter_info.get("rendererVersion", "unknown"),
            "limitations": ["浏览器与 PowerPoint 的字体度量可能不同，交付前需检查实际演示效果。"]}
