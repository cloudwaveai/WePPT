"""One-click brand logo: Chrome-side pixel processing, placement, application.

Processing runs in headless Chrome (no Pillow). Scenes store the logo as an
image object id 'brand-logo' with a data URL; the file copies live under the
project's brand/ directory.
"""
from __future__ import annotations

import base64
import json
import uuid
import colorsys

from pathlib import Path

from .core import EngineError, _json, _now


MAX_BYTES = 5 * 1024 * 1024
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
LOGO_ID = "brand-logo"
POSITIONS = {"auto", "top-right", "top-left", "bottom-right", "bottom-left"}
SIZES = {"small", "medium", "large"}
PAGE_SCOPES = {"all", "cover", "except-cover"}
DEFAULT_SETTINGS = {"position": "auto", "size": "medium", "pages": "all"}

HEIGHTS = {"small": 32, "medium": 44, "large": 60}
CORNERS = ["top-right", "top-left", "bottom-right", "bottom-left"]

PROCESS_SCRIPT = """<script>
(async()=>{
const src=%%SRC%%;
const img=new Image();await new Promise((res,rej)=>{img.onload=res;img.onerror=()=>rej(new Error('bad image'));img.src=src;});
const scale=Math.min(1,1200/Math.max(img.naturalWidth,img.naturalHeight));
const W=Math.max(1,Math.round(img.naturalWidth*scale)),H=Math.max(1,Math.round(img.naturalHeight*scale));
const cv=document.createElement('canvas');cv.width=W;cv.height=H;
const cx=cv.getContext('2d',{willReadFrequently:true});cx.drawImage(img,0,0,W,H);
const data=cx.getImageData(0,0,W,H);const p=data.data;
const alphaAt=i=>p[i*4+3];
let low=0;for(let i=0;i<W*H;i++)if(alphaAt(i)<250)low++;
const hasAlpha=low/(W*H)>=0.01;
// Border colour = per-channel median of the 2-px border.
const border=[];for(let y=0;y<H;y++)for(let x=0;x<W;x++)if(y<2||y>=H-2||x<2||x>=W-2)border.push(y*W+x);
const med=ch=>{const a=border.map(i=>p[i*4+ch]).sort((a,b)=>a-b);return a[a.length>>1];};
const bc=[med(0),med(1),med(2)];
const dist=i=>{const d=Math.max(Math.abs(p[i*4]-bc[0]),Math.abs(p[i*4+1]-bc[1]),Math.abs(p[i*4+2]-bc[2]));return d;};
let near=0;for(const i of border)if(dist(i)<=40)near++;
let removedBackground=false;
if(!hasAlpha&&near/border.length>=0.9){
  // Flood fill from every border pixel, removing connected pixels within 40.
  const q=[];const seen=new Uint8Array(W*H);
  for(const i of border)if(dist(i)<=40&&!seen[i]){seen[i]=1;q.push(i);}
  while(q.length){const i=q.pop();const x=i%W,y=(i-x)/W;
    for(const[dx,dy]of[[1,0],[-1,0],[0,1],[0,-1]]){const nx=x+dx,ny=y+dy;
      if(nx<0||ny<0||nx>=W||ny>=H)continue;const j=ny*W+nx;
      if(!seen[j]&&dist(j)<=40){seen[j]=1;q.push(j);}}}
  for(let i=0;i<W*H;i++)if(seen[i]){const d=dist(i);
    p[i*4+3]=d<=40?0:Math.round(255*Math.min(1,Math.max(0,(d-40)/30)));}
  cx.putImageData(data,0,0);  // Write the cleared background back; the variants are drawn from the canvas.
  removedBackground=true;
}
// Trim to alpha > 16, pad 2% of the larger side.
let x0=W,y0=H,x1=0,y1=0;
for(let y=0;y<H;y++)for(let x=0;x<W;x++){const i=y*W+x;if(p[i*4+3]>16){if(x<x0)x0=x;if(y<y0)y0=y;if(x>x1)x1=x;if(y>y1)y1=y;}}
if(x1<x0){x0=0;y0=0;x1=W-1;y1=H-1;}
const pad=Math.round(Math.max(x1-x0+1,y1-y0+1)*0.02);
x0=Math.max(0,x0-pad);y0=Math.max(0,y0-pad);x1=Math.min(W-1,x1+pad);y1=Math.min(H-1,y1+pad);
const tw=x1-x0+1,th=y1-y0+1;
const out=document.createElement('canvas');out.width=tw;out.height=th;
const ox=out.getContext('2d');ox.drawImage(cv,x0,y0,tw,th,0,0,tw,th);
const op=ox.getImageData(0,0,tw,th).data;
// Tone + mean colour over opaque pixels.
let lum=0,wa=0,rm=0,gm=0,bm=0,am=0;
for(let i=0;i<tw*th;i++){const a=op[i*4+3];if(a>128){const w=a/255;wa+=w;
  const r=op[i*4]/255,g=op[i*4+1]/255,b=op[i*4+2]/255;
  lum+=w*(0.2126*r+0.7152*g+0.0722*b);rm+=w*r*255;gm+=w*g*255;bm+=w*b*255;}}
const tone=wa?(lum/wa<0.45?'dark':lum/wa>0.7?'light':'mid'):'mid';
const hex=n=>Math.round(n/wa).toString(16).padStart(2,'0');
const meanColor=wa?('#'+hex(rm)+hex(gm)+hex(bm)).toUpperCase():'#888888';
const variants={original:out.toDataURL('image/png')};
if(removedBackground||hasAlpha){
  const mk=fill=>{const c=document.createElement('canvas');c.width=tw;c.height=th;
    const g=c.getContext('2d');g.drawImage(out,0,0);const d=g.getImageData(0,0,tw,th);
    for(let i=0;i<tw*th;i++)if(d.data[i*4+3]>0){d.data[i*4]=fill[0];d.data[i*4+1]=fill[1];d.data[i*4+2]=fill[2];}
    g.putImageData(d,0,0);return c.toDataURL('image/png');};
  variants.white=mk([255,255,255]);variants.dark=mk([31,35,41]);
}
const result={width:tw,height:th,hasAlpha,removedBackground,tone,meanColor,variants};
const e=document.createElement('script');e.type='application/json';e.id='design-measurement';
e.textContent=JSON.stringify(result).replaceAll('<','\\\\u003c');document.body.append(e);
})().catch(err=>{const e=document.createElement('script');e.type='application/json';e.id='design-measurement';
e.textContent=JSON.stringify({error:String(err)});document.body.append(e);});
</script>"""


def _fail(code, message):
    raise EngineError(code, message)


def initialize(studio):
    with studio.wb._connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS studio_project_logos (
            project_id TEXT PRIMARY KEY, body TEXT NOT NULL)""")


def _brand(studio):
    folder = studio.wb._inside(studio.wb.project_dir(studio.project_id) / "brand",
                               studio.wb.project_dir(studio.project_id))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _record(row):
    body = json.loads(row["body"])
    return {"preview": body.get("preview"), "tone": body.get("tone"), "hasAlpha": body.get("hasAlpha"),
            "removedBackground": body.get("removedBackground"), "meanColor": body.get("meanColor"),
            "width": body.get("width"), "height": body.get("height"),
            "settings": body.get("settings") or dict(DEFAULT_SETTINGS), "body": body,
            "variants": body.get("variants") or {"original": "logo-original.png"}}


def project_logo(studio):
    with studio.wb._connection() as db:
        row = db.execute("SELECT body FROM studio_project_logos WHERE project_id=?",
                         (studio.project_id,)).fetchone()
    return _record(row) if row else None


def save_logo_record(studio, body, settings):
    with studio.wb.atomic() as db:
        db.execute("INSERT OR REPLACE INTO studio_project_logos VALUES (?,?)",
                   (studio.project_id, _json({**body, "settings": settings})))
        studio._touch(db)


def save_settings(studio, settings):
    logo = project_logo(studio)
    if not logo:
        _fail("LOGO_MISSING", "请先上传 Logo。")
    cleaned = dict(DEFAULT_SETTINGS)
    if isinstance(settings, dict):
        if settings.get("position") in POSITIONS:
            cleaned["position"] = settings["position"]
        if settings.get("size") in SIZES:
            cleaned["size"] = settings["size"]
        if settings.get("pages") in PAGE_SCOPES:
            cleaned["pages"] = settings["pages"]
    body = {k: logo["body"][k] for k in logo["body"] if k != "settings"}
    save_logo_record(studio, body, cleaned)
    return {"logo": project_logo(studio), "state": studio.state()}


def process_logo(studio, filename, mime, encoded):
    if mime not in MAGIC:
        _fail("UNSUPPORTED_UPLOAD", "Logo 只接受 PNG 或 JPEG。")
    try:
        data = base64.b64decode(str(encoded or ""), validate=True)
    except (ValueError, TypeError):
        _fail("INVALID_UPLOAD", "图片编码无效。")
    if not data or len(data) > MAX_BYTES:
        _fail("UPLOAD_TOO_LARGE", "Logo 图片为空或超过 5 MB。")
    if not data.startswith(MAGIC[mime]):
        _fail("INVALID_UPLOAD", "图片内容与声明格式不一致。")
    folder = _brand(studio)
    folder.mkdir(parents=True, exist_ok=True)
    ext = "png" if mime == "image/png" else "jpg"
    (folder / f"logo-upload.{ext}").write_bytes(data)
    src = "data:" + mime + ";base64," + base64.b64encode(data).decode()
    markup = "<!doctype html><html><body>" + PROCESS_SCRIPT.replace("%%SRC%%", json.dumps(src)) + "</body></html>"
    from .design_review import run_json_page
    result = run_json_page(markup, folder / "process")
    if not isinstance(result, dict) or result.get("error") or not result.get("variants"):
        _fail("LOGO_PROCESS_FAILED", "Logo 图片无法处理，请换一张清晰的 PNG。")
    variants = result["variants"]
    (folder / "logo-original.png").write_bytes(base64.b64decode(variants["original"].split(",", 1)[1]))
    for name in ("white", "dark"):
        if variants.get(name):
            (folder / f"logo-{name}.png").write_bytes(base64.b64decode(variants[name].split(",", 1)[1]))
    body = {"filename": filename, "width": result["width"], "height": result["height"],
            "hasAlpha": result["hasAlpha"], "removedBackground": result["removedBackground"],
            "tone": result["tone"], "meanColor": result["meanColor"],
            "preview": variants["original"],
            "variants": {k: f"logo-{k}.png" for k in variants}}
    existing = project_logo(studio)
    settings = existing["settings"] if existing else dict(DEFAULT_SETTINGS)
    save_logo_record(studio, body, settings)
    return {"logo": project_logo(studio), "state": studio.state()}


def _luminance(value):
    if not isinstance(value, str) or len(value) < 7 or not value.startswith("#"):
        return None
    try:
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except ValueError:
        return None
    channel = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a, b):
    la, lb = _luminance(a), _luminance(b)
    if la is None or lb is None:
        return 21
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


def _overlaps(box, obj):
    return (box["x"] < obj["x"] + obj["w"] and obj["x"] < box["x"] + box["w"]
            and box["y"] < obj["y"] + obj["h"] and obj["y"] < box["y"] + box["h"])


def _contains(container, box):
    return (container["x"] <= box["x"] and container["y"] <= box["y"]
            and container["x"] + container["w"] >= box["x"] + box["w"]
            and container["y"] + container["h"] >= box["y"] + box["h"])


def _background_at(scene, box):
    topmost = None
    for obj in scene.get("objects", []):
        if obj.get("type") not in ("rect", "ellipse") or obj.get("rotation"):
            continue
        fill = obj.get("fill")
        if not isinstance(fill, str) or not fill.startswith("#"):
            continue
        if _contains(obj, box):
            topmost = fill
    return topmost or scene.get("background")


def place_logo(scene, logo, settings, page_role):
    """Pure: return {'scene': new_scene} or {'skipped': 'no-space'|'excluded'}."""
    settings = {**DEFAULT_SETTINGS, **(settings or {})}
    if settings["pages"] == "cover" and page_role != "cover":
        return {"scene": _strip_logo(scene), "skipped": "excluded"}
    if settings["pages"] == "except-cover" and page_role == "cover":
        return {"scene": _strip_logo(scene), "skipped": "excluded"}
    scale = 1.4 if page_role == "cover" else 1
    height = HEIGHTS[settings["size"]] * scale
    aspect = (logo.get("width") or 1) / (logo.get("height") or 1)
    width = min(240 * scale, height * aspect)
    height = width / aspect
    margin = 40
    W, H = scene.get("width", 1280), scene.get("height", 720)
    corners = [settings["position"]] if settings["position"] != "auto" else CORNERS

    def box_for(corner, w, h):
        x = W - w - margin if "right" in corner else margin
        y = H - h - margin if "bottom" in corner else margin
        return {"x": round(x, 2), "y": round(y, 2), "w": round(w, 2), "h": round(h, 2)}

    blockers = [o for o in scene.get("objects", [])
                if o.get("type") in ("text", "image") and o.get("id") != LOGO_ID]
    box = None
    for factor in (1, 0.75):
        for corner in corners:
            candidate = box_for(corner, width * factor, height * factor)
            if not any(_overlaps(candidate, o) for o in blockers):
                box = candidate
                break
        if box:
            break
    nudged = []
    if box is None:
        # Last resort: nudge only-text blockers away from a corner by <=24px.
        for corner in corners:
            candidate = box_for(corner, width * 0.75, height * 0.75)
            hits = [o for o in blockers if _overlaps(candidate, o)]
            if hits and all(o["type"] == "text" for o in hits):
                direction = -1 if "bottom" in corner else 1
                moves = []
                for o in hits:
                    if direction > 0:
                        dy = candidate["y"] + candidate["h"] - o["y"]
                        ny = o["y"] + min(24, dy)
                        ok = (ny + o["h"] <= scene.get("height", H) - 24
                              and not _overlaps({"x": o["x"], "y": ny, "w": o["w"], "h": o["h"]}, candidate))
                    else:
                        dy = o["y"] + o["h"] - candidate["y"]
                        ny = o["y"] - min(24, dy)
                        ok = ny >= 24 and not _overlaps({"x": o["x"], "y": ny, "w": o["w"], "h": o["h"]}, candidate)
                    if not ok:
                        break
                    moves.append((o, ny - o["y"]))
                else:
                    others = [o for o in blockers if o not in hits]
                    if all(not _overlaps({"x": o["x"], "y": o["y"] + dy, "w": o["w"], "h": o["h"]}, other)
                           for o, dy in moves for other in others if other is not o):
                        box = candidate
                        nudged = moves
                        break
    if box is None:
        return {"scene": _strip_logo(scene), "skipped": "no-space"}
    variant = "original"
    if logo.get("removedBackground") is False and not logo.get("hasAlpha"):
        variant = "original"
    else:
        background = _background_at(scene, box)
        L = _luminance(background)
        if L is None:
            variant = "original"
        elif logo.get("tone") == "dark" and L < .4:
            variant = "white"
        elif logo.get("tone") == "light" and L > .75:
            variant = "dark"
        elif logo.get("tone") == "mid" and _contrast(logo.get("meanColor", "#888888"), background) < 2:
            variant = "white" if L < .5 else "dark"
        else:
            variant = "original"
    if variant not in (logo.get("variants") or {}):
        variant = "original"
    png = logo.get("dataUrls", {}).get(variant)
    if png is None:
        png = logo.get("preview")
    if not png:
        return {"scene": _strip_logo(scene), "skipped": "no-variant"}
    result = _strip_logo(scene)
    if nudged:
        moved = {o["id"]: dy for o, dy in nudged}
        for o in result["objects"]:
            if o.get("id") in moved:
                o["y"] = round(o["y"] + moved[o["id"]], 2)
    result["objects"] = result["objects"] + [{
        "id": LOGO_ID, "type": "image", **box, "src": png, "fit": "contain", "alt": "Logo"}]
    out = {"scene": result}
    if nudged:
        out["nudged"] = [{"objectId": o["id"], "dy": round(dy, 2)} for o, dy in nudged]
    return out


def _strip_logo(scene):
    result = json.loads(json.dumps(scene))
    result["objects"] = [o for o in result.get("objects", []) if o.get("id") != LOGO_ID]
    return result


def _logo_with_data(studio, logo):
    folder = _brand(studio)
    urls = {}
    for name in (logo.get("variants") or {}):
        path = folder / logo["variants"][name]
        if path.is_file():
            urls[name] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    return {**logo, "dataUrls": urls}


def apply_logo(studio):
    logo = project_logo(studio)
    if not logo:
        _fail("LOGO_MISSING", "请先上传 Logo。")
    logo = _logo_with_data(studio, logo)
    project = studio.wb.get_project(studio.project_id)
    changed, skipped = [], []
    with studio.wb.atomic() as db:
        for item in project["workspace"]["slides"]:
            if item["archived"]:
                continue
            sid = item["id"]
            try:
                current = studio.get_scene(sid)
            except EngineError:
                skipped.append({"slideId": sid, "reason": "missing"})
                continue
            if current["stale"]:
                skipped.append({"slideId": sid, "reason": "stale"})
                continue
            placed = place_logo(current["scene"], logo, logo["settings"],
                                item.get("role", "content"))
            new_scene = placed["scene"]
            reason = placed.get("skipped")
            if new_scene == current["scene"]:
                skipped.append({"slideId": sid, "reason": reason or "unchanged"})
                continue
            from .editor import _history, _save_history
            undo, _ = _history(studio, db, sid, current["sceneRevision"])
            result = studio.put_scene(sid, current["contentRevision"], new_scene, "添加 Logo")
            if result.get("unchanged"):
                skipped.append({"slideId": sid, "reason": reason or "unchanged"})
                continue
            undo.append({"before": current["scene"], "after": result["scene"]})
            _save_history(studio, db, sid, result["sceneRevision"], undo, [])
            changed.append(sid)
        studio._touch(db)
    return {"changedSlides": changed, "skipped": skipped, "logo": project_logo(studio),
            "state": studio.state()}


def place_forced(studio, slide_id, scene_revision):
    """Force-place at top-right regardless of overlap; user drags it after."""
    logo = project_logo(studio)
    if not logo:
        _fail("LOGO_MISSING", "请先上传 Logo。")
    logo = _logo_with_data(studio, logo)
    with studio.wb.atomic() as db:
        current = studio.get_scene(slide_id)
        studio.wb._revision(current["sceneRevision"], scene_revision)
        if current["stale"]:
            _fail("SCENE_STALE", "页面内容已变化，请更新预览后再放 Logo。")
        scene = _strip_logo(current["scene"])
        settings = dict(logo["settings"])
        settings["position"] = "top-right"
        placed = place_logo(scene, logo, settings,
                            next((s.get("role", "content") for s in
                                  studio.wb.get_project(studio.project_id)["workspace"]["slides"]
                                  if s["id"] == slide_id), "content"))
        target = placed["scene"]
        if placed.get("skipped"):
            size_h = HEIGHTS[settings["size"]]
            width = min(240, size_h * (logo.get("width") or 1) / (logo.get("height") or 1))
            box = {"x": round(1280 - width - 40, 2), "y": 40, "w": round(width, 2), "h": size_h}
            target = _strip_logo(scene)
            target["objects"] = target["objects"] + [{"id": LOGO_ID, "type": "image", **box,
                "src": logo["dataUrls"].get("original") or logo["preview"],
                "fit": "contain", "alt": "Logo"}]
        from .editor import _history, _save_history
        undo, _ = _history(studio, db, slide_id, current["sceneRevision"])
        result = studio.put_scene(slide_id, current["contentRevision"], target, "放置 Logo")
        undo.append({"before": current["scene"], "after": result["scene"]})
        _save_history(studio, db, slide_id, result["sceneRevision"], undo, [])
        studio._touch(db)
    return {"slideId": slide_id, "sceneRevision": result["sceneRevision"], "state": studio.state()}


def remove_logo(studio):
    project = studio.wb.get_project(studio.project_id)
    changed, skipped = [], []
    with studio.wb.atomic() as db:
        db.execute("DELETE FROM studio_project_logos WHERE project_id=?", (studio.project_id,))
        for item in project["workspace"]["slides"]:
            if item["archived"]:
                continue
            sid = item["id"]
            try:
                current = studio.get_scene(sid)
            except EngineError:
                continue
            if current["stale"]:
                skipped.append({"slideId": sid, "reason": "stale"})
                continue
            stripped = _strip_logo(current["scene"])
            if stripped == current["scene"]:
                continue
            from .editor import _history, _save_history
            undo, _ = _history(studio, db, sid, current["sceneRevision"])
            result = studio.put_scene(sid, current["contentRevision"], stripped, "移除 Logo")
            if result.get("unchanged"):
                continue
            undo.append({"before": current["scene"], "after": result["scene"]})
            _save_history(studio, db, sid, result["sceneRevision"], undo, [])
            changed.append(sid)
        studio._touch(db)
    return {"changedSlides": changed, "skipped": skipped, "state": studio.state()}


def apply_to_deck(studio, db, deck):
    """Deck-completion hook: place the project logo on the finished pages and
    carry the deck review forward like auto-images do."""
    logo = project_logo(studio)
    if not logo or deck["execution"] != "agent":
        return []
    plan = json.loads(deck["plan"])
    rows = db.execute("SELECT page_index,slide_id FROM studio_deck_pages WHERE deck_id=? "
                      "AND status='complete' AND slide_id IS NOT NULL ORDER BY page_index",
                      (deck["id"],)).fetchall()
    logo = _logo_with_data(studio, logo)
    placed = []
    from .auto_images import acknowledge_review
    for row in rows:
        brief_role = (plan["pages"][row["page_index"]].get("role")
                      if row["page_index"] < len(plan.get("pages", [])) else None)
        current = studio.get_scene(row["slide_id"])
        if current["stale"]:
            continue
        result = place_logo(current["scene"], logo, logo["settings"],
                            brief_role or "content")
        if result["scene"] == current["scene"]:
            continue
        before_rev = current["sceneRevision"]
        saved = studio.put_scene(row["slide_id"], current["contentRevision"],
                                 result["scene"], "添加 Logo")
        if not saved.get("unchanged"):
            acknowledge_review(studio, db, row["slide_id"], before_rev, saved["sceneRevision"])
            placed.append(row["slide_id"])
    return placed
