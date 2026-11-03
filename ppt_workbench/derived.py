"""Derived projects: audience variants and benchmark-style restyle copies.

The source project is never modified. A new project is created with copied
preferences, provenance recorded, and a deck-scope job enqueued.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import secrets
import uuid

from .core import EngineError, _json, _now


AUDIENCES = {
    "employee": ("员工版",
        "面向公司员工的内部同步：保留真实的产品信息、当前进展、存在的问题与风险以及下一步分工；不做营销包装，问题和不足如实呈现；删去融资金额、估值和面向投资人的愿景表述；财务内容只保留与员工工作相关的部分。"),
    "customer": ("客户版",
        "面向有付费意愿的客户：突出客户痛点、产品能力与优势、案例与价值、服务与交付方式，并单独给出报价页；删去融资金额、估值、财务模型、投资回报、股权结构以及公司内部的愿景和问题；表达可以适度包装，但不夸大，不编造案例和数字。报价只使用源稿中的价格信息；源稿没有报价时保留一页“报价方案”，写明“报价待补充”，不自行定价。"),
    "leader": ("领导同行版",
        "面向领导或同行的交流：保留业务进展、产品亮点、关键成果和方法，适度做产品包装；减少财务内容，不展示融资金额、估值和详细财务模型；内部问题只保留需要领导决策或适合同行交流的部分。"),
    "investor": ("投资人版",
        "面向投资人：完整保留市场机会、产品与竞争优势、商业模式、关键数据与进展、团队、未来规划、财务规划和融资计划；做必要的产品包装，突出增长逻辑；源稿缺少的财务或融资信息用明确的“待补充”占位，不编造。"),
}

AUDIENCE_MESSAGE = """【受众版本】基于源稿《{title}》生成面向「{target}」的新版本整稿。
受众规则：{rule}
{note}制作要求：
1. 只使用下面“源稿内容”中的事实、数字和表述；可以删减、合并、重排页面并改写措辞以适合受众，但不得新增源稿没有的事实、数字、客户名称或承诺。
2. 按受众规则删去不应出现的页面或段落；受众需要但源稿缺少的内容，用一页或一段明确标注“待补充”。
3. 页数按内容需要决定，一般不超过源稿页数加 2 页。
4. reply 先用几行说明：保留了源稿哪些页、删去或合并了哪些页及原因、新增了哪些待补充内容。
{images}源稿内容（按页）：
{pages}"""

RESTYLE_MESSAGE = """【对标风格重排】按本项目选定的对标风格「{style_name}」重新设计源稿《{title}》的整套页面。
制作要求：
1. 保持源稿的页数、页序、每页标题和全部正文文字不变，不删减、不改写、不新增事实。
2. 只改变版式、构图、配色、字体层级和装饰元素，让整套页面符合对标风格的 UI、元素和设计风格。
3. 相邻页面保持节奏变化，不把每页都套成同一种骨架。
{images}源稿内容（按页）：
{pages}"""

IMAGE_NOTE = "源稿图片已作为附件提供，文件名标明了来源页，可在对应页面使用。\n"


def initialize(studio):
    with studio.wb._connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS studio_derived_projects (
            project_id TEXT PRIMARY KEY, source_project_id TEXT NOT NULL,
            mode TEXT NOT NULL, audience TEXT, style_id TEXT, created_at TEXT NOT NULL)""")


def _source_pages(studio):
    from .design_loop import connector_glyph
    project = studio.wb.get_project(studio.project_id)
    pages = []
    for index, item in enumerate(project["workspace"]["slides"], start=1):
        if item["archived"]:
            continue
        try:
            current = studio.get_scene(item["id"])
        except EngineError:
            continue
        if not current or not current.get("scene"):
            continue
        texts, seen = [], set()
        objects = sorted((o for o in current["scene"].get("objects", [])
                          if o["type"] == "text" and o["id"] != "brand-logo"
                          and not connector_glyph(o)),
                         key=lambda o: (o.get("y", 0), o.get("x", 0)))
        for obj in objects:
            text = (obj.get("text") or "").strip()
            if text and text not in seen:
                texts.append(text)
                seen.add(text)
        pages.append({"index": index, "id": item["id"], "role": item.get("role", "content"),
                      "title": item.get("title", ""), "texts": texts,
                      "scene": current["scene"]})
    return pages


def _image_bytes(studio, scene, oid):
    """Decode an image object's source, resolving scene-image/asset references."""
    for obj in scene.get("objects", []):
        if obj.get("type") != "image" or obj["id"] != oid:
            continue
        src = str(obj.get("src") or "")
        if src.startswith("data:image/"):
            raw = base64.b64decode(src.split(",", 1)[1])
            return ("image/png" if src.split(";", 1)[0].endswith("png") else "image/jpeg"), raw
        if src.startswith("asset:"):
            asset = studio.asset(src[6:])
            if asset["mime"] in {"image/png", "image/jpeg"}:
                return asset["mime"], (studio.wb.project_dir(studio.project_id) / asset["path"]).read_bytes()
    return None


def _copy_images(studio, target, pages):
    """Copy up to 10 distinct PNG/JPEG scene images; returns attachment ids."""
    seen, assets = set(), []
    for page in pages:
        for obj in page["scene"].get("objects", []):
            if len(assets) >= 10:
                return assets
            if obj.get("type") != "image" or obj["id"] in {"brand-logo"} or obj["id"].startswith("image-slot"):
                continue
            found = _image_bytes(studio, page["scene"], obj["id"])
            if not found:
                continue
            mime, data = found
            sha = hashlib.sha256(data).hexdigest()
            if sha in seen or len(data) > 8 * 1024 * 1024:
                continue
            seen.add(sha)
            ext = "png" if mime == "image/png" else "jpg"
            uploaded = target.upload(f"源稿第{page['index']}页-{obj['id']}.{ext}", mime,
                                     base64.b64encode(data).decode())
            assets.append(uploaded["assetId"])
    return assets


def derive(studio, mode, audience=None, note=None, style_id=None):
    """Create a derived project and enqueue its regeneration job."""
    from .model_profiles import selected, resolve
    if mode not in {"audience", "restyle"}:
        raise EngineError("INVALID_REQUEST", "生成方式只能是受众版本或对标风格。")
    project = studio.wb.get_project(studio.project_id)
    pages = _source_pages(studio)
    if not pages:
        raise EngineError("DERIVE_EMPTY", "原稿还没有可读取的页面。")
    with studio.wb._connection() as db:
        if db.execute("SELECT 1 FROM studio_jobs WHERE project_id=? AND status IN ('queued','running') LIMIT 1",
                      (studio.project_id,)).fetchone():
            raise EngineError("DERIVE_BUSY", "原稿还有任务在进行，请完成后再生成新版本。")
    chosen = selected(studio)
    mode_name = studio.agent_mode
    if mode_name not in {"codex", "claude", "api"} or (chosen and resolve(chosen)["mode"] != mode_name):
        raise EngineError("AGENT_REQUIRED", "请先在右上角选择可生成整稿的模型，再生成新版本。")
    title = project["workspace"]["project"].get("title") or studio.project_id
    if mode == "audience":
        if audience not in AUDIENCES:
            raise EngineError("INVALID_REQUEST", "请选择受众版本。")
        label, rule = AUDIENCES[audience]
        target_label = label[:-1] if label.endswith("版") else label
        note = str(note or "").strip()[:500]
        note_block = f"用户补充要求：{note}\n" if note else ""
        style_row = None
    else:
        from .user_templates import selected_style as _sel, _get as _tget
        row = _tget(studio, style_id, "style")
        body = json.loads(row["body"])
        if not body.get("profile"):
            raise EngineError("STYLE_NOT_ANALYZED", "请先解析对标风格。")
        label, rule = "对标风格", ""
        target_label = body.get("profile", {}).get("summary") or row["name"]
        note_block = ""
        style_row = row
    pages_block = "\n\n".join(
        f"第{p['index']}页｜{p['role']}｜{p['title']}\n" + "\n".join(p["texts"])
        for p in pages)
    def build(has_images):
        if mode == "audience":
            return AUDIENCE_MESSAGE.format(title=title, target=target_label, rule=rule,
                                           note=note_block,
                                           images=IMAGE_NOTE if has_images else "", pages=pages_block)
        return RESTYLE_MESSAGE.format(title=title, style_name=style_row["name"],
                                      images=IMAGE_NOTE if has_images else "", pages=pages_block)
    if len(build(True)) > 30_000:
        raise EngineError("DERIVE_TOO_LONG", "原稿内容超过单次整稿上限（30,000 字），请先精简后再生成。")
    new_id = "project-" + secrets.token_hex(8)
    new_title = f"{title} · {label}"[:120]
    studio.wb.create_project(new_id, {"title": new_title})
    from .studio import Studio as _Studio
    opened = _Studio(studio.wb.root, new_id)
    try:
        from .model_profiles import select
        if chosen and chosen.get("model") != "unavailable":
            select(opened, chosen["id"])
        else:
            opened.set_agent_mode(mode_name)
    except EngineError:
        opened.set_agent_mode(mode_name)
    opened.set_image_mode(studio.image_mode())
    palette = studio.palette()
    if palette:
        opened.set_palette(palette)
    from .user_templates import selected_style
    style = selected_style(studio)
    if style and mode == "restyle":
        from .user_templates import select_style
        select_style(opened, style_id)
    elif style:
        from .user_templates import select_style
        select_style(opened, style["id"])
    from .logo import project_logo
    logo = project_logo(studio)
    if logo:
        from .logo import save_logo_record
        brand = studio.wb.project_dir(studio.project_id) / "brand"
        target_brand = opened.wb.project_dir(opened.project_id) / "brand"
        target_brand.mkdir(parents=True, exist_ok=True)
        import shutil
        for png in brand.glob("logo-*.png"):
            shutil.copyfile(png, target_brand / png.name)
        save_logo_record(opened, logo["body"], logo["settings"])
    assets = _copy_images(studio, opened, pages)
    job = opened.enqueue(build(bool(assets)), scope="deck", attachments=assets,
                         client_message_id="derive-" + uuid.uuid4().hex[:16])
    with opened.wb.atomic() as db:
        db.execute("INSERT INTO studio_derived_projects VALUES (?,?,?,?,?,?)",
                   (new_id, studio.project_id, mode, audience, style_id, _now()))
    return {"projectId": new_id, "jobId": job["jobId"], "audienceLabel": label, "title": new_title}


def provenance(studio):
    with studio.wb._connection() as db:
        row = db.execute("SELECT * FROM studio_derived_projects WHERE project_id=?",
                         (studio.project_id,)).fetchone()
    if not row:
        return None
    label = AUDIENCES.get(row["audience"], (None,))[0] if row["mode"] == "audience" else "对标风格"
    try:
        source_title = studio.wb.get_project(row["source_project_id"]).get("title", row["source_project_id"])
    except EngineError:
        source_title = row["source_project_id"]
    return {"projectId": row["source_project_id"], "title": source_title,
            "mode": row["mode"], "audienceLabel": label}
