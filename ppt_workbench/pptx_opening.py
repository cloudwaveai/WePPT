"""Focused OOXML opening-page importer; no Office execution or slide screenshots.

Only explicitly reviewed pages 1–3 can be bundled. Scenes retain source text;
placeholder roles and provenance live in the manifest, outside the scene schema.
Pillow is needed only when source pictures require cropping/alpha/flip conversion.
"""
from __future__ import annotations

import argparse
import base64
import colorsys
import hashlib
import io
import json
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .rendering import validate_scene

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
DATA_DIR = Path(__file__).parent / "data" / "opening-templates"
# Reviewed from text + OOXML + actual embedded images, not positional heuristics.
REVIEWED = {
    "0710网梯分享.pptx": ("cover", "body", "body"),
    "0828云涌世纪公司介绍.pptx": ("cover", "body", "body"),
    "420云涌世纪公司介绍.pptx": ("cover", "body", "body"),
    "v3FDE宣讲世纪互联.pptx": ("cover", "toc", "body"),
    "【FESCO】云涌世纪公司介绍.pptx": ("cover", "chapter", "body"),
}


def _find(node, path):
    return node.find(path, NS) if node is not None else None


def _text(shape):
    body = _find(shape, "p:txBody")
    if body is None:
        return ""
    return "\n".join("".join((n.text or "") if n.tag.endswith("}t") else "\n"
                              for n in p.iter() if n.tag in {f"{{{NS['a']}}}t", f"{{{NS['a']}}}br"})
                     for p in body.findall("a:p", NS))


class OpeningImporter:
    def __init__(self, source):
        self.source = Path(source)
        self.zip = zipfile.ZipFile(self.source)
        self.assets = {}
        self.warnings = []

    def close(self):
        self.zip.close()

    def xml(self, part):
        return ET.fromstring(self.zip.read(part))

    def rels(self, part):
        name = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        if name not in self.zip.namelist():
            return {}
        return {r.get("Id"): (r.get("Type", "").rsplit("/", 1)[-1],
                posixpath.normpath(posixpath.join(posixpath.dirname(part), r.get("Target", ""))))
                for r in self.xml(name) if r.get("TargetMode") != "External"}

    def related(self, part, kind):
        return next((target for typ, target in self.rels(part).values() if typ == kind), None)

    def color(self, node, default="#000000"):
        if node is None:
            return default
        c = next((n for n in node if n.tag.rsplit("}", 1)[-1] in {"srgbClr", "schemeClr", "sysClr"}), None)
        if c is None:
            return default
        kind = c.tag.rsplit("}", 1)[-1]
        value = c.get("val", "000000")
        if kind == "schemeClr":
            value = self.palette.get(self.clrmap.get(value, value), "000000")
        elif kind == "sysClr":
            value = c.get("lastClr", "000000")
        rgb = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
        for mod in c:
            tag, v = mod.tag.rsplit("}", 1)[-1], int(mod.get("val", 0)) / 100000
            if tag in {"lumMod", "lumOff", "satMod"}:
                h, l, s = colorsys.rgb_to_hls(*rgb)
                if tag == "lumMod": l *= v
                elif tag == "lumOff": l += v
                else: s *= v
                rgb = list(colorsys.hls_to_rgb(h, min(1, max(0, l)), min(1, max(0, s))))
            elif tag == "shade": rgb = [x * v for x in rgb]
            elif tag == "tint": rgb = [x + (1 - x) * v for x in rgb]
        return "#" + "".join(f"{min(255,max(0,round(x*255))):02X}" for x in rgb)

    def warn(self, code, object_id, detail):
        entry = {"code": code, "objectId": object_id, "detail": detail}
        if entry not in self.warnings:
            self.warnings.append(entry)

    def picture(self, shape, part, oid, clip=None, aspect=None):
        blip = _find(shape, "p:blipFill/a:blip")
        if blip is None:
            return None
        rel = self.rels(part).get(blip.get(f"{{{NS['r']}}}embed"))
        if rel is None:
            self.warn("unsupported-image", oid, "External or missing image relationship")
            return None
        target = rel[1]
        raw = self.zip.read(target)
        suffix = Path(target).suffix.lower().replace(".jpg", ".jpeg")
        digest = hashlib.sha256(raw).hexdigest()
        asset = digest[:20] + suffix
        self.assets[asset] = raw
        source_asset = asset
        crop = _find(shape, "p:blipFill/a:srcRect")
        alpha = _find(blip, "a:alphaModFix")
        xf = _find(shape, "p:spPr/a:xfrm")
        flip_h = xf is not None and xf.get("flipH") == "1"
        flip_v = xf is not None and xf.get("flipV") == "1"
        # OOXML stretch may intentionally distort a source image. Scene fit only
        # supports contain/cover, so bake the stretch into the extracted picture.
        if crop is not None or alpha is not None or clip or flip_h or flip_v or aspect or suffix not in {".png", ".jpeg"}:
            from PIL import Image, ImageOps
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
            if crop is not None:
                l, t, r, b = [int(crop.get(k, 0)) / 100000 for k in ("l", "t", "r", "b")]
                im = im.crop((round(l*im.width), round(t*im.height), round((1-r)*im.width), round((1-b)*im.height)))
            if flip_h: im = ImageOps.mirror(im)
            if flip_v: im = ImageOps.flip(im)
            if clip:
                l, t, r, b = clip
                im = im.crop((round(l*im.width), round(t*im.height), round(r*im.width), round(b*im.height)))
            if aspect and abs(im.width/im.height-aspect) > .0001:
                im = im.resize((max(1,round(im.height*aspect)),im.height),Image.Resampling.LANCZOS)
            if alpha is not None:
                amount = int(alpha.get("amt", 100000)) / 100000
                im.putalpha(im.getchannel("A").point(lambda v: round(v*amount)))
            buf = io.BytesIO(); im.save(buf, format="PNG"); raw = buf.getvalue(); suffix = ".png"
            asset = hashlib.sha256(raw).hexdigest()[:20] + suffix
            self.assets[asset] = raw
        return {"src": f"data:image/{'png' if suffix == '.png' else 'jpeg'};base64," + base64.b64encode(raw).decode(),
                "fit": "contain", "alt": Path(target).name}, {"sourcePart": target, "sourceAsset": "assets/" + source_asset,
                "sceneAsset": "assets/" + asset, "sourceSha256": digest}

    def extract(self, page, role):
        if page not in (1, 2, 3) or role not in {"cover", "toc", "chapter"}:
            raise ValueError("Only reviewed opening roles on the first three slides are supported")
        self.warnings = []
        presentation = self.xml("ppt/presentation.xml")
        slides = presentation.findall("p:sldIdLst/p:sldId", NS)
        rid = slides[page-1].get(f"{{{NS['r']}}}id")
        part = self.rels("ppt/presentation.xml")[rid][1]
        root = self.xml(part)
        layout = self.related(part, "slideLayout")
        master = self.related(layout, "slideMaster") if layout else None
        theme = self.related(master, "theme") if master else None
        tr = self.xml(theme) if theme else None
        self.palette = {}
        if tr is not None:
            for c in tr.findall("a:themeElements/a:clrScheme/*", NS):
                self.palette[c.tag.rsplit("}", 1)[-1]] = next(iter(c)).get("lastClr", next(iter(c)).get("val"))
        self.clrmap = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
        if master:
            cm = _find(self.xml(master), "p:clrMap")
            if cm is not None: self.clrmap.update(cm.attrib)
        for inherited in (layout, part):
            cm = _find(self.xml(inherited), "p:clrMapOvr/a:overrideClrMapping") if inherited else None
            if cm is not None: self.clrmap.update(cm.attrib)
        self.fonts = {}
        if tr is not None:
            for family in ("major", "minor"):
                for script in ("latin", "ea", "cs"):
                    f = _find(tr, f"a:themeElements/a:fontScheme/a:{family}Font/a:{script}")
                    self.fonts[(family, script)] = f.get("typeface") if f is not None else ""
                hans = _find(tr, f"a:themeElements/a:fontScheme/a:{family}Font/a:font[@script='Hans']")
                if hans is not None and not self.fonts[(family, "ea")]: self.fonts[(family, "ea")] = hans.get("typeface")
        size = _find(presentation, "p:sldSz")
        cx, cy = int(size.get("cx")), int(size.get("cy"))
        if abs(cx/cy - 16/9) > .001: raise ValueError("Source is not 16:9")
        scale = 1280 / cx
        background = "#FFFFFF"
        for candidate in (part, layout, master):
            bg = _find(self.xml(candidate), "p:cSld/p:bg") if candidate else None
            if bg is not None:
                fill = _find(bg, "p:bgPr/a:solidFill")
                if fill is not None: background = self.color(fill)
                else:
                    ref = _find(bg, "p:bgRef")
                    background = self.color(ref, background)
                    idx = int(ref.get("idx", "0")) - 1001 if ref is not None else -1
                    styles = tr.findall("a:themeElements/a:fmtScheme/a:bgFillStyleLst/*", NS) if tr is not None else []
                    if 0 <= idx < len(styles) and styles[idx].tag.endswith("}solidFill"):
                        old_ph = self.palette.get("phClr")
                        self.palette["phClr"] = background.lstrip("#")
                        background = self.color(styles[idx], background)
                        if old_ph is None: self.palette.pop("phClr", None)
                        else: self.palette["phClr"] = old_ph
                    else:
                        self.warn("unsupported-background", "background", "Non-solid theme background style approximated by its reference color")
                break
        scene = {"schema": "ppt-scene", "schemaVersion": 1, "slideId": f"S{page:03}", "width": 1280,
                 "height": 720, "background": background, "objects": []}
        provenance = []
        point = 0
        title_assigned = False

        def visit(tree, owner, matrix=(scale, scale, 0, 0), prefix=""):
            nonlocal point, title_assigned
            sx, sy, tx, ty = matrix
            for index, shape in enumerate(tree):
                kind = shape.tag.rsplit("}", 1)[-1]
                if kind not in {"sp", "pic", "grpSp", "cxnSp", "graphicFrame"}: continue
                nv = shape.find(".//p:cNvPr", NS)
                oid = prefix + "o" + (nv.get("id") if nv is not None else str(index))
                xf = _find(shape, "p:grpSpPr/a:xfrm" if kind == "grpSp" else "p:spPr/a:xfrm")
                if xf is None:
                    self.warn("unsupported-inherited-transform", oid, "No local transform; placeholder geometry is not guessed")
                    continue
                if xf.get("rot", "0") != "0":
                    self.warn("unsupported-rotation", oid, "Scene schema cannot encode rotated geometry")
                off, ext = _find(xf, "a:off"), _find(xf, "a:ext")
                if off is None or ext is None: continue
                ox, oy, ew, eh = int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))
                if kind == "grpSp":
                    co, ce = _find(xf, "a:chOff"), _find(xf, "a:chExt")
                    if co is None or ce is None or not int(ce.get("cx")) or not int(ce.get("cy")):
                        self.warn("unsupported-group", oid, "Degenerate group coordinate system"); continue
                    gx, gy = sx*ew/int(ce.get("cx")), sy*eh/int(ce.get("cy"))
                    visit(shape, owner, (gx, gy, tx+sx*ox-gx*int(co.get("x")), ty+sy*oy-gy*int(co.get("y"))), oid+"-")
                    continue
                x, y, w, h = sx*ox+tx, sy*oy+ty, sx*ew, sy*eh
                original = [x, y, w, h]
                x2, y2 = min(1280, x+w), min(720, y+h)
                xx, yy = max(0, x), max(0, y)
                if x2 <= xx or y2 < yy: continue
                clip = None
                if any(abs(a-b) > .00001 for a,b in zip([xx, yy, x2-xx, y2-yy], original)):
                    clip = ((xx-x)/w, (yy-y)/h if h else 0, (x2-x)/w, (y2-y)/h if h else 1)
                    self.warn("canvas-clipped", oid, "Source geometry extends beyond slide; clipped to scene bounds")
                box = {"x": round(xx, 5), "y": round(yy, 5), "w": round(x2-xx, 5), "h": round(y2-yy, 5)}
                meta = {"objectId": oid, "sourcePart": owner, "sourceShapeId": nv.get("id") if nv is not None else None,
                        "sourceBox": original}
                if shape.findall(".//a:reflection", NS): self.warn("unsupported-reflection", oid, "Source reflection effect is not represented")
                if kind == "pic":
                    result = self.picture(shape, owner, oid, clip, box["w"]/box["h"] if box["h"] else None)
                    if result:
                        props, asset_meta = result
                        scene["objects"].append(dict(id=oid, type="image", **box, **props))
                        provenance.append(dict(meta, **asset_meta))
                    continue
                if kind == "graphicFrame":
                    self.warn("unsupported-object", oid, "Chart/table/SmartArt not imported"); continue
                sp = _find(shape, "p:spPr")
                geom = _find(sp, "a:prstGeom")
                preset = geom.get("prst", "rect") if geom is not None else "rect"
                fill = _find(sp, "a:solidFill")
                ln = _find(sp, "a:ln")
                stroke = self.color(_find(ln, "a:solidFill"), "none")
                stroke_w = int(ln.get("w", 12700))*scale if ln is not None else 0
                if preset == "line":
                    scene["objects"].append(dict(id=oid, type="line", **box, stroke=stroke if stroke != "none" else "#000000", strokeWidth=max(.1,stroke_w)))
                    provenance.append(meta)
                elif fill is not None or stroke != "none":
                    if preset not in {"rect", "roundRect"}: self.warn("unsupported-geometry", oid, f"{preset} approximated as rectangle")
                    scene["objects"].append(dict(id=oid+"-shape", type="rect", **box, fill=self.color(fill,"none"), stroke=stroke,
                        strokeWidth=min(24,stroke_w), radius=min(box["w"],box["h"])*.16 if preset == "roundRect" else 0))
                    alpha = _find(fill, "a:srgbClr/a:alpha")
                    if alpha is None: alpha = _find(fill, "a:schemeClr/a:alpha")
                    if alpha is not None: scene["objects"][-1]["opacity"] = int(alpha.get("val"))/100000
                    provenance.append(dict(meta, objectId=oid+"-shape"))
                text = _text(shape).rstrip("\n")
                if not text.strip(): continue
                body = _find(shape, "p:txBody")
                props = body.findall(".//a:rPr", NS)
                rp = props[0] if props else _find(body, "a:p/a:endParaRPr")
                pp = _find(body, "a:p/a:pPr")
                bp = _find(body, "a:bodyPr")
                default = _find(body, "a:lstStyle/a:lvl1pPr/a:defRPr")
                def attr(name, fallback):
                    for node in (rp, default):
                        if node is not None and name in node.attrib: return node.get(name)
                    return fallback
                font = _find(rp,"a:ea")
                if font is None or not font.get("typeface"): font = _find(rp,"a:latin")
                family = font.get("typeface") if font is not None else self.fonts.get(("minor", "latin"), "Calibri")
                if family.startswith("+"):
                    family = self.fonts.get(("major" if family.startswith("+mj") else "minor", {"lt":"latin", "ea":"ea", "cs":"cs"}.get(family[-2:], "latin")), "Calibri")
                if not re.fullmatch(r"[\w \-㐀-鿿]{1,80}", family or ""):
                    self.warn("unsupported-font-name", oid, f"Font {family!r} cannot pass scene validator"); family = "Calibri"
                if any(p.get("spc", "0") != "0" for p in props): self.warn("unsupported-tracking", oid, "OOXML character spacing is not supported by scene text")
                sizes = {p.get("sz", attr("sz","1800")) for p in props}
                colors = {self.color(_find(p,"a:solidFill")) for p in props}
                if len(sizes)>1 or len(colors)>1: self.warn("unsupported-mixed-runs", oid, "Scene uses first run style for this text box")
                fs = int(attr("sz", "1800"))/100 * 12700*scale
                if not 10 <= fs <= 160: self.warn("font-size-clamped", oid, f"Original scaled size {fs}")
                left, top, right, bottom = [int(bp.get(k,str(v))) * (sx if k in {"lIns","rIns"} else sy) for k,v in (("lIns",91440),("tIns",45720),("rIns",91440),("bIns",45720))]
                text_box = dict(x=box["x"]+left,y=box["y"]+top,w=max(1,box["w"]-left-right),h=max(1,box["h"]-top-bottom))
                # Insets are represented by the actual editable text content box.
                text_box["w"] = min(text_box["w"],1280-text_box["x"])
                text_box["h"] = min(text_box["h"],720-text_box["y"])
                spacing = _find(pp,"a:lnSpc/a:spcPct")
                obj = dict(id=oid,type="text",**text_box,text=text,fontSize=min(160,max(10,fs)),fontFamily=family,
                    color=self.color(_find(rp,"a:solidFill")),bold=attr("b","0")=="1",italic=attr("i","0")=="1",
                    align={"ctr":"center","r":"right"}.get(pp.get("algn") if pp is not None else None,"left"),
                    valign={"ctr":"middle","b":"bottom"}.get(bp.get("anchor"),"top"),
                    lineHeight=min(2.5,max(1,int(spacing.get("val"))/100000 if spacing is not None else 1)))
                # PowerPoint can overflow its fixed box; browser text is clipped.
                # Keep the original content box and fit explicit lines into it.
                lines = len(text.rstrip("\n").split("\n"))
                if lines > 1 and obj["fontSize"]*obj["lineHeight"]*lines > obj["h"]:
                    original_size = obj["fontSize"]
                    obj["lineHeight"] = max(1, min(obj["lineHeight"], obj["h"]/(obj["fontSize"]*lines)))
                    obj["fontSize"] = max(10, min(obj["fontSize"], obj["h"]/(obj["lineHeight"]*lines)))
                    self.warn("text-fit-adjusted", oid, f"Browser clipping avoided within original text box; source fontSize={original_size}, scene fontSize={obj['fontSize']}, lineHeight={obj['lineHeight']}")
                if text.strip() == "cloudwaveai.com":
                    # Source footer extends past the slide edge; keep the URL
                    # readable in the clipped browser content box.
                    fitted = min(obj["fontSize"], obj["w"]/(len(text.strip())*.6))
                    if fitted < obj["fontSize"]:
                        self.warn("text-fit-adjusted", oid, f"Source footer extends beyond canvas; fontSize {obj['fontSize']} fitted to {fitted}")
                        obj["fontSize"] = max(10,fitted)
                # Match semantic text, including TOC title after the decorative kicker.
                semantic = "decorative"
                if (role == "toc" and text.strip()=="目录") or (role != "toc" and not title_assigned):
                    obj["binding"]="title"; title_assigned=True;semantic="title"
                elif role == "toc" and ("行业现状" in text or "人才画像" in text or "筛选" in text or "FDE之道" in text or "潜能测试" in text):
                    obj["binding"]=f"keyPoints:{point}";point+=1;semantic="toc-item"
                elif role != "toc" and not any(o.get("binding")=="takeaway" for o in scene["objects"]):
                    obj["binding"]="takeaway";semantic="subtitle"
                scene["objects"].append(obj)
                provenance.append(dict(meta,role=semantic,binding=obj.get("binding"),placeholder="{{"+obj["binding"]+"}}" if "binding" in obj else None))
        # Master/layout decorative shapes render behind local slide content.
        if root.get("showMasterSp", "1") != "0":
            for inherited, prefix in ((master,"master-"),(layout,"layout-")):
                if inherited:
                    tree = _find(self.xml(inherited), "p:cSld/p:spTree")
                    if tree is not None:
                        filtered = ET.Element("tree")
                        for s in tree:
                            if s.find(".//p:ph",NS) is None: filtered.append(s)
                        visit(filtered,inherited,prefix=prefix)
        visit(_find(root,"p:cSld/p:spTree"),part)
        return validate_scene(scene), {"objects":provenance,"limitations":self.warnings.copy()}


def extract_bundle(source_dir, output_dir=DATA_DIR):
    """Regenerate reviewed assets and scenes. Original presentations are read only."""
    output_dir = Path(output_dir)
    (output_dir/"assets").mkdir(parents=True,exist_ok=True)
    manifest = {"schema":"ppt-opening-templates","schemaVersion":1,"inspectionScope":"first three slides only",
                "fidelityNotes":["Editable text, rectangles, lines and source pictures; no slide screenshots", "Source font names retained; fonts are not bundled and host substitution can change glyph metrics", "Picture crops, source stretch and alpha baked into individual image assets; untouched originals retained", "Explicit multiline text fits its original content box where browser clipping would occur; adjustments listed per object", "Reflections and character tracking unsupported; see per-template limitations"],
                "templates":[],"inspectedPages":[],"excludedFiles":[{"file":"*.pdf","reason":"PDF excluded; exact PPTX sources authoritative"}]}
    for source_index, (name, roles) in enumerate(REVIEWED.items(),1):
        source = Path(source_dir)/name
        importer = OpeningImporter(source)
        try:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            for page,role in enumerate(roles,1):
                manifest["inspectedPages"].append({"sourceFile":name,"sourcePage":page,"role":role,
                    "included":role!="body","reason":"Reviewed opening page" if role!="body" else "Body content; screenshot/product evidence or explanatory content"})
                if role=="body": continue
                tid=f"opening-{source_index:02}-{page:02}-{role}"
                scene, metadata=importer.extract(page,role)
                scene["templateId"]=tid
                (output_dir/(tid+".json")).write_text(json.dumps(scene,ensure_ascii=False,indent=2)+"\n")
                manifest["templates"].append(dict(id=tid,role=role,sourceFile=name,sourcePage=page,sourceSha256=digest,
                    scene=tid+".json",fidelity="editable-source-geometry-with-listed-limitations",**metadata))
            for asset,data in importer.assets.items(): (output_dir/"assets"/asset).write_bytes(data)
        finally: importer.close()
    (output_dir/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir",type=Path)
    parser.add_argument("--output-dir",type=Path,default=DATA_DIR)
    args=parser.parse_args()
    result=extract_bundle(args.source_dir,args.output_dir)
    print(f"Extracted {len(result['templates'])} editable opening templates")
