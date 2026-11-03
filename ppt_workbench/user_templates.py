"""User-supplied templates: single-page images and 3-page style benchmarks.

Files live under <workbench root>/user-templates/<id>/ so they are shared by
every project. Only normalised PNG renders are ever served or sent to models.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import uuid

from pathlib import Path

from .core import EngineError, _json, _now


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
HEX = re.compile(r"#[0-9a-fA-F]{6}")

ANALYZE_PROMPT = """读取 renderedPreview 中拼合的 3 页对标 PPT（从左到右依次为第 1、2、3 页），提炼可以迁移到其他内容的设计风格。只描述设计，不抄写其中的文字、数据、Logo、人物或品牌名称。actions 返回 []。reply 只输出一个 JSON 对象，不要输出其他文字。字段如下，每项用具体、可执行的中文描述，尽量给出比例、字号层级、颜色十六进制等可度量信息：
{"summary":"一句话风格定位",
"ui":{"grid":"版面网格、分栏与对齐方式","whitespace":"留白与信息密度","hierarchy":"标题、正文、数字的层级与字号对比","containers":"卡片、容器、圆角、描边与阴影的用法"},
"elements":{"shapes":"常用几何图形与装饰元素","lines":"线条、分隔与连接方式","imagery":"图片、插画或图标的使用方式","dataViz":"数字与图表的呈现方式"},
"typography":{"title":"标题字体风格、字重、大致字号","body":"正文字体、字号与行距","accent":"强调方式"},
"color":{"background":"#RRGGBB","ink":"#RRGGBB","primary":"#RRGGBB","secondary":["#RRGGBB"],"usage":"各颜色的使用比例与位置"},
"designStyle":{"keywords":["3–6 个风格关键词"],"mood":"整体气质","pageRhythm":"封面、章节页、正文页之间的节奏差异"},
"avoid":["迁移时不应出现的做法，2–5 条"]}
看不清或无法确认的项写"未能从对标页确认"，不要编造。"""

STYLE_INSTRUCTION = ("用户提供的对标风格：按 profile 迁移版面网格、元素、字体层级、配色和页面节奏；"
                     "只迁移设计，不复制对标页的文字、数据、Logo 或人物；用户内容和事实保持不变。"
                     "与可读性冲突时，优先保证可读和内容完整。")

PROFILE_SHAPE = {
    "summary": str,
    "ui": {"grid": str, "whitespace": str, "hierarchy": str, "containers": str},
    "elements": {"shapes": str, "lines": str, "imagery": str, "dataViz": str},
    "typography": {"title": str, "body": str, "accent": str},
    "color": {"background": "hex", "ink": "hex", "primary": "hex", "secondary": "hexlist", "usage": str},
    "designStyle": {"keywords": "keywords", "mood": str, "pageRhythm": str},
    "avoid": "avoid",
}


def fail(code, message, details=None):
    raise EngineError(code, message, details)


def _text(value, limit=400):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def _clean_text(value):
    return value.strip() if _text(value) else None


def _clean_hex(value):
    return value.upper() if isinstance(value, str) and HEX.fullmatch(value) else None


def _clean_list(value, low, high):
    if not isinstance(value, list) or not low <= len(value) <= high:
        return None
    items = [_clean_text(v) for v in value]
    return items if all(items) else None


def _clean_section(value, shape):
    if not isinstance(value, dict):
        return None
    result = {}
    for key, rule in shape.items():
        item = value.get(key)
        if rule is str:
            cleaned = _clean_text(item)
        elif rule == "hex":
            cleaned = _clean_hex(item)
        elif rule == "hexlist":
            cleaned = item if (isinstance(item, list) and 1 <= len(item) <= 2
                               and all(_clean_hex(c) for c in item)) else None
            if cleaned:
                cleaned = [c.upper() for c in cleaned]
        elif rule == "keywords":
            cleaned = _clean_list(item, 3, 6)
        elif rule == "avoid":
            cleaned = _clean_list(item, 2, 5)
        else:
            cleaned = _clean_section(item, rule)
        if cleaned is None:
            return None
        result[key] = cleaned
    return result


def validate_profile(value):
    cleaned = _clean_section(value, PROFILE_SHAPE)
    if cleaned is None:
        fail("INVALID_STYLE_PROFILE", "风格档案需要完整的 UI、元素、字体、配色、风格与避免字段。")
    return cleaned


def parse_profile_reply(reply):
    """Accept the outermost JSON object in the reply, fenced or not."""
    if not isinstance(reply, str):
        return None
    text = re.sub(r"```(?:json)?", "", reply)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    return _clean_section(value, PROFILE_SHAPE)


def _directory(studio, template_id=None):
    root = studio.wb._inside(studio.wb.root / "user-templates", studio.wb.root)
    if template_id is None:
        return root
    return studio.wb._inside(root / template_id, studio.wb.root)


def _row(row):
    body = json.loads(row["body"])
    pages = body.get("pages") or [{"sha": body["sha256"]}]
    previews = [{"url": f"/api/user-templates/image?id={row['id']}&sha={page['sha']}&index={index}",
                 "sha": page["sha"]} for index, page in enumerate(pages)]
    return {"id": row["id"], "kind": row["kind"], "name": row["name"], "createdAt": row["created_at"],
            "previewUrl": previews[0]["url"], "previews": [p["url"] for p in previews],
            "sha256": body.get("sha256"), "profile": body.get("profile"),
            "analyzedBy": body.get("analyzedBy")}


def list_templates(studio, kind=None):
    with studio.wb._connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS studio_user_templates (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL)""")
        rows = db.execute("SELECT * FROM studio_user_templates ORDER BY created_at,id").fetchall()
    items = [_row(r) for r in rows]
    return [t for t in items if kind is None or t["kind"] == kind]


def _get(studio, template_id, kind=None):
    with studio.wb._connection() as db:
        row = db.execute("SELECT * FROM studio_user_templates WHERE id=?", (template_id,)).fetchone()
    if not row or (kind and row["kind"] != kind):
        fail("TEMPLATE_NOT_FOUND", "没有找到这个用户模板。")
    return row


def _decode_file(file):
    if not isinstance(file, dict):
        fail("INVALID_UPLOAD", "请提供图片文件。")
    filename = str(file.get("filename") or "模板页")[:250]
    mime = file.get("mime")
    if mime not in MAGIC:
        fail("UNSUPPORTED_UPLOAD", "模板页只接受 PNG 或 JPEG。")
    encoded = file.get("base64")
    if not isinstance(encoded, str) or len(encoded) > 12_000_000:
        fail("UPLOAD_TOO_LARGE", "单张图片上限为 8 MB。")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        fail("INVALID_UPLOAD", "图片编码无效。")
    if not data or len(data) > MAX_IMAGE_BYTES:
        fail("UPLOAD_TOO_LARGE", "图片为空或超过 8 MB。")
    if not data.startswith(MAGIC[mime]):
        fail("INVALID_UPLOAD", "图片内容与声明格式不一致。")
    return filename, mime, data


def _data_url(mime, data):
    return "data:" + mime + ";base64," + base64.b64encode(data).decode()


def _image_scene(objects, background="#FFFFFF"):
    return {"schema": "ppt-scene", "schemaVersion": 1, "slideId": "S001",
            "width": 1280, "height": 720, "background": background, "objects": objects}


def _normalise(studio, mime, data, folder, stem):
    """Render the image onto a 1280×720 white canvas; fall back to PNG as-is."""
    scene = _image_scene([{"id": "page", "type": "image", "x": 0, "y": 0, "w": 1280, "h": 720,
                           "src": _data_url(mime, data), "fit": "contain"}])
    try:
        from .design_review import render_candidate
        png, _ = render_candidate(scene, folder / (stem + "-render"))
        return png.read_bytes()
    except EngineError as exc:
        if exc.code != "DESIGN_RENDER_UNAVAILABLE":
            raise
        if mime == "image/png":
            return data
        fail("RENDER_UNAVAILABLE", "JPEG 模板页需要页面渲染器转换为 PNG；请改用 PNG 上传。")


def upload(studio, kind, files):
    if kind not in {"page", "style"}:
        fail("INVALID_REQUEST", "模板类型只能是 page 或 style。")
    if not isinstance(files, list):
        fail("INVALID_UPLOAD", "请提供图片文件列表。")
    if kind == "page" and not 1 <= len(files) <= 5:
        fail("INVALID_UPLOAD", "一次上传 1–5 张图片，每张成为一页模板。")
    if kind == "style" and len(files) != 3:
        fail("INVALID_UPLOAD", "对标风格需要恰好 3 页 PNG 或 JPEG。")
    decoded = [_decode_file(f) for f in files]
    created = []
    if kind == "page":
        for filename, mime, data in decoded:
            tid = "u" + uuid.uuid4().hex[:12]
            folder = _directory(studio, tid)
            folder.mkdir(parents=True)
            png = _normalise(studio, mime, data, folder, "page")
            (folder / "page.png").write_bytes(png)
            body = {"sha256": hashlib.sha256(png).hexdigest(), "sourceMime": mime,
                    "pages": [{"sha": hashlib.sha256(png).hexdigest()}]}
            name = Path(filename).stem.strip()[:60] or "我的模板页"
            with studio.wb.atomic() as db:
                db.execute("INSERT INTO studio_user_templates VALUES (?,?,?,?,?)",
                           (tid, "page", name, _json(body), _now()))
            created.append(tid)
    else:
        tid = "u" + uuid.uuid4().hex[:12]
        folder = _directory(studio, tid)
        folder.mkdir(parents=True)
        pages, objects = [], []
        for index, (filename, mime, data) in enumerate(decoded):
            png = _normalise(studio, mime, data, folder, f"page-{index + 1}")
            (folder / f"page-{index + 1}.png").write_bytes(png)
            pages.append({"sha": hashlib.sha256(png).hexdigest(), "filename": Path(filename).name})
            objects.append({"id": f"benchmark-{index + 1}", "type": "image",
                            "x": 20 + index * 420, "y": 247, "w": 400, "h": 225,
                            "src": _data_url("image/png", png), "fit": "contain"})
        contact_sha = None
        try:
            from .design_review import render_candidate
            contact, _ = render_candidate(_image_scene(objects, "#F3F3EF"), folder / "contact-render")
            (folder / "contact.png").write_bytes(contact.read_bytes())
            contact_sha = hashlib.sha256((folder / "contact.png").read_bytes()).hexdigest()
        except EngineError as exc:
            if exc.code != "DESIGN_RENDER_UNAVAILABLE":
                raise
            # Without a renderer the first page stands in for the contact sheet.
            shutil.copyfile(folder / "page-1.png", folder / "contact.png")
            contact_sha = hashlib.sha256((folder / "contact.png").read_bytes()).hexdigest()
        name = "对标风格 " + "、".join(Path(f[0]).stem for f in decoded)[:40]
        body = {"pages": pages, "contactSha": contact_sha, "names": [f[0] for f in decoded]}
        with studio.wb.atomic() as db:
            db.execute("INSERT INTO studio_user_templates VALUES (?,?,?,?,?)",
                       (tid, "style", name[:60], _json(body), _now()))
        created.append(tid)
    return {"templates": [t for t in list_templates(studio) if t["id"] in created]}


def rename(studio, template_id, name):
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 60:
        fail("INVALID_REQUEST", "模板名称需要 1–60 字。")
    _get(studio, template_id)
    with studio.wb.atomic() as db:
        db.execute("UPDATE studio_user_templates SET name=? WHERE id=?", (name.strip(), template_id))
    return {"templates": list_templates(studio)}


def delete(studio, template_id):
    _get(studio, template_id)
    shutil.rmtree(_directory(studio, template_id), ignore_errors=True)
    with studio.wb.atomic() as db:
        db.execute("DELETE FROM studio_user_templates WHERE id=?", (template_id,))
        db.execute("DELETE FROM studio_style_preferences WHERE template_id=?", (template_id,))
    return {"templates": list_templates(studio)}


def image(studio, template_id, index=0):
    """Return (png_path, sha256) for an uploaded page or a benchmark page."""
    row = _get(studio, template_id)
    body = json.loads(row["body"])
    pages = body.get("pages") or [{"sha": body["sha256"]}]
    if not 0 <= index < len(pages):
        fail("NOT_FOUND", "没有这张模板图片。")
    page = pages[index]
    name = "page.png" if row["kind"] == "page" else f"page-{index + 1}.png"
    path = _directory(studio, template_id) / name
    if not path.is_file():
        fail("NOT_FOUND", "模板图片文件缺失。")
    return path, page["sha"]


def template_card(studio, template_id):
    row = _get(studio, template_id, "page")
    path, _ = image(studio, template_id, 0)
    return ({"id": "user-" + row["id"], "name": row["name"], "role": "content",
             "use": "用户上传的模板页",
             "fitRule": "只模仿版式与视觉语言，不复制模板页上的文字、数据、Logo 或人物。",
             "userTemplate": True}, path)


def style_reference(name, profile):
    return {"name": name, "profile": profile, "instruction": STYLE_INSTRUCTION}


def style_card(studio, template_id):
    """An analysed benchmark style used as the reference for restyling one page."""
    row = _get(studio, template_id, "style")
    profile = json.loads(row["body"]).get("profile")
    if not profile:
        fail("STYLE_NOT_ANALYZED", "请先解析对标风格。")
    contact = _directory(studio, template_id) / "contact.png"
    return ({"id": "style-" + row["id"], "name": row["name"], "role": "content", "use": "对标风格逐页改版",
             "fitRule": "按对标风格重排本页；只迁移设计，不复制对标页的文字、数据、Logo 或人物。"},
            contact if contact.is_file() else None, style_reference(row["name"], profile))


def _vision_mode(studio):
    from .model_profiles import selected, resolve
    chosen = selected(studio)
    mode = studio.agent_mode
    profile = resolve(chosen) if chosen else None
    visual = mode == "codex" or (mode == "api" and bool(profile and profile.get("vision")))
    return chosen, mode, visual


def analyze_style(studio, template_id):
    row = _get(studio, template_id, "style")
    body = json.loads(row["body"])
    chosen, mode, visual = _vision_mode(studio)
    if not visual:
        fail("TEMPLATE_NEEDS_VISION", "这个模板是图片，需要支持看图的模型；请在右上角切换模型后重试。")
    contact = _directory(studio, template_id) / "contact.png"
    if not contact.is_file():
        fail("STYLE_CONTACT_MISSING", "这套对标稿缺少拼图预览，请重新上传 3 页。")
    workdir = studio.wb.project_dir(studio.project_id)
    staged = workdir / "style-analysis" / template_id / "contact.png"
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(contact, staged)
    from .agent_bridge import run_turn
    context = {"generationTask": {"kind": "style_analysis"},
               "previewPurpose": "三页对标 PPT 拼图（从左到右为第1、2、3页），只用于提炼设计风格。"}
    profile = None
    for attempt in range(2):
        plan = run_turn(mode, ANALYZE_PROMPT, context, timeout=150, workdir=workdir,
                        preview_png=staged, model_binding=chosen)
        profile = parse_profile_reply(plan.get("reply"))
        if profile is not None:
            break
        context["revisionCorrection"] = {
            "instruction": "上次输出不是要求的 JSON 结构。只返回 reply 为该 JSON 对象，字段齐全。"}
    if profile is None:
        fail("STYLE_ANALYSIS_FAILED", "两次尝试都没有得到可用的风格档案，请稍后再试。")
    body["profile"] = profile
    body["analyzedBy"] = (chosen or {}).get("label") or mode
    with studio.wb.atomic() as db:
        db.execute("UPDATE studio_user_templates SET body=? WHERE id=?",
                   (_json(body), template_id))
    return {"template": _row(_get(studio, template_id))}


def update_style(studio, template_id, name=None, profile=None):
    row = _get(studio, template_id, "style")
    body = json.loads(row["body"])
    if name is not None:
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 60:
            fail("INVALID_REQUEST", "模板名称需要 1–60 字。")
        body["name"] = name.strip()
    if profile is not None:
        body["profile"] = validate_profile(profile)
    with studio.wb.atomic() as db:
        db.execute("UPDATE studio_user_templates SET name=?, body=? WHERE id=?",
                   (body.get("name", row["name"]), _json(body), template_id))
    return {"template": _row(_get(studio, template_id))}


def select_style(studio, template_id):
    if template_id is not None:
        _get(studio, template_id, "style")
    with studio.wb.atomic() as db:
        if template_id is None:
            db.execute("DELETE FROM studio_style_preferences WHERE project_id=?", (studio.project_id,))
        else:
            db.execute("INSERT OR REPLACE INTO studio_style_preferences VALUES (?,?)",
                       (studio.project_id, template_id))
        studio._touch(db)
    return studio.state()


def selected_style(studio):
    with studio.wb._connection() as db:
        row = db.execute("""SELECT t.id,t.name,t.body FROM studio_style_preferences s
            JOIN studio_user_templates t ON t.id=s.template_id
            WHERE s.project_id=? AND t.kind='style'""", (studio.project_id,)).fetchone()
    if not row:
        return None
    body = json.loads(row["body"])
    return {"id": row["id"], "name": row["name"], "profile": body.get("profile"),
            "summary": (body.get("profile") or {}).get("summary")}
