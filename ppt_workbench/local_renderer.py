"""Page layouts from the newer local workbench template library."""
import re
import math
from .rendering import SCENE_SCHEMA, COLORS, _fail, validate_scene

def _text_obj(oid, text, x, y, w, h, size=30, color=None, bold=False, **extra):
    return {"id": oid, "type": "text", "x": x, "y": y, "w": w, "h": h,
            "text": text, "fontSize": size, "color": color or COLORS["ink"], "bold": bold, **extra}


def _rect(oid, x, y, w, h, fill, **extra):
    return {"id": oid, "type": "rect", "x": x, "y": y, "w": w, "h": h, "fill": fill, **extra}


def _image_slot(prefix, x, y, w, h, label="图片占位 · 上传替换"):
    """Dashed empty frame + label; ids end with .slot / .slot.label for UI replace."""
    return [
        _rect(f"{prefix}.slot", x, y, w, h, "#F7F9FC", stroke=COLORS["blue"], strokeWidth=2, radius=14),
        _text_obj(
            f"{prefix}.slot.label", label, x + 16, y + max(12, h / 2 - 18), w - 32, 40,
            16, COLORS["muted"], align="center", lineHeight=1.25,
        ),
    ]


def _line(oid, x, y, w, h=0, color=None, stroke=2):
    return {"id": oid, "type": "line", "x": x, "y": y, "w": w, "h": h,
            "stroke": color or COLORS["line"], "strokeWidth": stroke}


def _split_pipe_cells(line):
    """Split a lane/row line on fullwidth or halfwidth pipes."""
    parts = re.split(r"[｜|]", line)
    return [p.strip() for p in parts if p.strip()]


def _parse_swimlane_lanes(entries):
    """Parse swimlane keyPoints into (label, cells[]) per lane.

    Convention (pick one; both are accepted):
    1) Paragraph / multi-line entry: first line = role/label; following lines =
       stage actions left→right. Blank-line separated paragraphs = lanes when
       bindingSeparator is \\n\\n.
    2) Single line with pipes: `角色｜动作1｜动作2｜动作3` (｜ or |).

    Returns a list of {"label": str, "cells": [str, ...], "raw": str}. Stage
    count is max(len(cells)) across lanes (clamped 2..5); shorter lanes pad "".
    """
    lanes = []
    for entry in entries:
        lines = [ln.strip() for ln in entry.split("\n") if ln.strip()]
        if not lines:
            continue
        if len(lines) == 1 and re.search(r"[｜|]", lines[0]):
            parts = _split_pipe_cells(lines[0])
            label, cells = parts[0], parts[1:]
        else:
            label, cells = lines[0], lines[1:]
        lanes.append({"label": label, "cells": cells, "raw": entry})
    if not lanes:
        return []
    stage_n = max((len(L["cells"]) for L in lanes), default=0)
    stage_n = max(2, min(5, stage_n if stage_n else 2))
    for L in lanes:
        cells = list(L["cells"])[:stage_n]
        while len(cells) < stage_n:
            cells.append("")
        L["cells"] = cells
    return lanes


def _parse_kpi_entries(entries):
    """KPI: each entry first line = big value; optional second line = label."""
    cards = []
    for entry in entries:
        lines = [ln.strip() for ln in entry.split("\n") if ln.strip()]
        if not lines:
            continue
        value = lines[0]
        label = lines[1] if len(lines) > 1 else ""
        cards.append({"value": value, "label": label, "raw": entry})
    return cards


def _parse_stage_entry(entry):
    """Funnel/process stage: first line or `名称｜说明` → name + subtitle."""
    lines = [ln.strip() for ln in entry.split("\n") if ln.strip()]
    if not lines:
        return {"name": "", "sub": "", "raw": entry}
    head = lines[0]
    if re.search(r"[｜|]", head):
        parts = _split_pipe_cells(head)
        name = parts[0] if parts else head
        sub = parts[1] if len(parts) > 1 else ("\n".join(lines[1:]) if len(lines) > 1 else "")
    else:
        name = head
        sub = "\n".join(lines[1:]) if len(lines) > 1 else ""
    return {"name": name, "sub": sub, "raw": entry}


def _parse_grid_cell(entry):
    """Portfolio/status grid cell.

    Placeholder when the entry is `+` / `＋` / `待` / `待挖` or starts with `+`.
    Optional `色调:标签` (蓝/青/橙 or blue/teal/orange) sets accent; else cycle.
    """
    raw = entry.strip()
    placeholder_tokens = {"+", "＋", "待", "待挖", "待点亮", "..."}
    if raw in placeholder_tokens or raw.startswith("+") or raw.startswith("＋"):
        label = raw.lstrip("+＋").strip() or "+"
        return {"placeholder": True, "label": label, "accent": None, "raw": entry}
    accent_map = {
        "蓝": "blue", "蓝调": "blue", "blue": "blue",
        "青": "teal", "青绿": "teal", "teal": "teal",
        "橙": "orange", "橙调": "orange", "orange": "orange",
    }
    accent = None
    label = raw
    if ":" in raw or "：" in raw:
        left, right = re.split(r"[:：]", raw, maxsplit=1)
        key = left.strip().lower()
        if key in accent_map:
            accent = accent_map[key]
            label = right.strip() or left.strip()
    return {"placeholder": False, "label": label, "accent": accent, "raw": entry}


def scene_from_slide(slide, project, template=None):
    """Create a starter layout from supplied content without inventing claims.

    Built-in geometry covers golden pages, comparisons, parallel items, steps,
    swimlanes, decision matrices, KPI walls, funnels, portfolio grids, VS cards,
    claim-proof splits, dark KPI heroes, sidebar TOCs, pillar cards, guide
    splits, feature heroes, case scorecards, before/after dual-screen cases and landscape path (table + rising bars).
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
    if tid in {"compare", "change", "tradeoff", "before-after", "team-two", "case-compare", "parallel",
               "swimlane", "decision-matrix", "kpi", "funnel", "portfolio-grid", "status-grid",
               "vs-cards", "claim-proof", "evidence-split", "kpi-hero",
               "pillar-cards", "guide-split", "feature-hero", "case-scorecard",
               "before-after-case", "landscape-path", "table-rising-bars",
               "market-path"} and len(paragraphs) >= 2:
        entries = paragraphs
        separator = "\n\n"
    s = {"schema": SCENE_SCHEMA, "schemaVersion": 1, "slideId": sid,
         "width": 1280, "height": 720, "background": COLORS["paper"],
         "title": title, "templateId": tid, "objects": [], "bindingSeparator": separator,
         "notes": "基础排版保留所提供文案；请在实际预览中确认表达与溢出。" + (" 本页暂用用户原话作为草稿。" if used_intent else "")}
    objects = s["objects"]
    footer = str(project.get("title") or "")
    page_number = str(int(sid[1:])).zfill(2) if re.fullmatch(r"S\d+", sid) else sid
    if role == "cover" or tid.startswith("cover"):
        # Centered classic cover: eyebrow + diamond divider + title + subtitle + bottom credit.
        # No Logo. keyPoints first line → eyebrow; remaining lines → bottom credit; takeaway → subtitle.
        s["background"] = "#102544"
        # Thin inner frame (paper-white matting feel without logo).
        objects.append(_rect(
            "cover.frame", 36, 28, 1208, 664, "none",
            stroke="#FFFFFF", strokeWidth=1, radius=0, opacity=0.22,
        ))
        eyebrow = ""
        credit = ""
        if entries:
            eyebrow = entries[0]
            credit = "\n".join(entries[1:]) if len(entries) > 1 else ""
        if eyebrow:
            objects.append(_text_obj(
                "cover.eyebrow", eyebrow, 140, 96, 1000, 36,
                18, "#8DA8CC", align="center", lineHeight=1.2,
            ))
        # Diamond ornament: two lines + center diamond rect rotated look via small square.
        objects.append(_line("cover.ornament.l", 420, 168, 200, 0, "#42D6B2", 2))
        objects.append(_line("cover.ornament.r", 660, 168, 200, 0, "#42D6B2", 2))
        objects.append(_rect("cover.ornament.diamond", 632, 160, 16, 16, "#42D6B2", radius=2))
        objects.append(_text_obj(
            "title", title, 100, 210, 1080, 160, 56, "#FFFFFF", True,
            align="center", lineHeight=1.18,
        ))
        if takeaway:
            objects.append(_text_obj(
                "takeaway", takeaway, 160, 400, 960, 80 if (credit or footer) else 160,
                26, "#BCCBE2", align="center", lineHeight=1.4,
            ))
        if raw:
            # Keep full keyPoints on body-1 for binding continuity (near-invisible under credit).
            objects.append(_text_obj(
                "body-1", raw, 160, 540, 960, 80, 18, "#8DA8CC",
                align="center", lineHeight=1.35, opacity=0.02,
            ))
        credit_text = credit or (footer if footer and footer != title else "")
        if credit_text:
            objects.append(_text_obj(
                "cover.credit", credit_text, 160, 560 if takeaway else 500, 960, 90,
                16, "#8DA8CC", align="center", lineHeight=1.45,
            ))
        elif footer and footer != title:
            objects.append(_text_obj("footer.project", footer, 160, 654, 960, 28, 16, "#8DA8CC", align="center"))
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
    elif tid == "kpi-hero" and 2 <= len(entries) <= 4:
        # Dark KPI hero: left narrative + staggered hanging value pillars (engine palette).
        # Each entry: first line = value; optional second = label. takeaway = left body.
        s["background"] = "#102544"
        cards = _parse_kpi_entries(entries)
        count = len(cards)
        objects.extend([
            _text_obj("title", title, 64, 90, 520, 140, 40, "#FFFFFF", True, lineHeight=1.15),
        ])
        if takeaway:
            objects.append(_text_obj("takeaway", takeaway, 64, 250, 480, 160, 22, "#BCCBE2", lineHeight=1.4))
        # Hanging pillars from top; heights stagger by index (taller toward the right).
        gap = 28
        pillar_area_x = 620
        pillar_area_w = 1280 - pillar_area_x - 48
        w = (pillar_area_w - gap * (count - 1)) / count
        fills = [COLORS["teal"], COLORS["orange"], COLORS["blue"], "#42D6B2"]
        base_h = 280
        for i, card in enumerate(cards):
            x = pillar_area_x + i * (w + gap)
            h = base_h + i * 70
            y = 0
            fill = fills[i % len(fills)]
            objects.append(_rect(f"kpi.{i+1}.bg", x, y, w, h, fill, radius=0))
            objects.append(_text_obj(
                f"kpi.{i+1}.value", card["value"], x + 10, max(24, h - 120), w - 20, 70,
                36 if count <= 3 else 30, "#102544", True, align="center", lineHeight=1.1,
            ))
            if card["label"]:
                objects.append(_text_obj(
                    f"kpi.{i+1}.label", card["label"], x + 8, h + 16, w - 16, 56,
                    18, "#FFFFFF", align="center", lineHeight=1.25,
                ))
            objects.append(_text_obj(
                f"body-{i+1}", card["raw"], x + 10, max(24, h - 120), w - 20, 90,
                28, "#102544", True, align="center", lineHeight=1.15, opacity=0.02,
            ))
        # Bottom-left evidence inset: empty image slot for manual upload.
        inset_y = 480
        objects.extend(_image_slot("kpi.inset", 64, inset_y, 480, 170, "图片占位 · 上传替换"))
        if footer and footer != title:
            objects.append(_text_obj("footer.project", footer, 64, 670, 500, 24, 16, "#8DA8CC"))
        objects.append(_text_obj("footer.number", page_number, 1130, 679, 76, 24, 17, "#8DA8CC", align="right"))
    elif tid in {"toc-sidebar", "toc-side"} or (tid == "toc" and slide.get("layout") == "sidebar"):
        # Dark left sidebar TOC + right numbered chapter list (engine palette, no Logo).
        # keyPoints: one chapter title per line (4–8). takeaway unused.
        s["background"] = "#F7F4EF"
        sidebar_w = 300
        objects.append(_rect("toc.sidebar.bg", 0, 0, sidebar_w, 720, "#102544", radius=0))
        objects.append(_text_obj(
            "toc.sidebar.title", "目录", 36, 200, sidebar_w - 72, 70,
            48, "#FFFFFF", True, align="center", lineHeight=1.1,
        ))
        objects.append(_text_obj(
            "toc.sidebar.en", "CONTENT", 36, 270, sidebar_w - 72, 36,
            16, "#8DA8CC", align="center", lineHeight=1.2,
        ))
        objects.append(_rect("toc.sidebar.rule", 90, 320, 120, 3, COLORS["teal"], radius=1))
        # Right list
        list_x = sidebar_w + 72
        list_w = 1280 - list_x - 64
        items = entries[:8] if entries else []
        if not items:
            objects.append(_text_obj(
                "body-1", "[补充本次材料的章节名称]", list_x, 250, list_w, 120,
                28, COLORS["muted"], lineHeight=1.3,
            ))
        else:
            n = len(items)
            top = 120
            avail = 520
            row_h = min(78, avail / n)
            for i, text in enumerate(items):
                y = top + i * row_h
                objects.append(_text_obj(
                    f"item.{i+1}.number", str(i + 1).zfill(2), list_x, y + 8, 70, row_h - 16,
                    min(32, row_h * 0.45), COLORS["teal"], True, lineHeight=1.1,
                ))
                objects.append(_text_obj(
                    f"body-{i+1}", text, list_x + 90, y + 10, list_w - 100, row_h - 20,
                    max(18, min(28, row_h * 0.38)), COLORS["ink"], True, lineHeight=1.25,
                ))
                if i < n - 1:
                    objects.append(_line(
                        f"item.{i+1}.rule", list_x + 90, y + row_h - 4, list_w - 100, 0, "#E5E0D8", 1,
                    ))
        objects.append(_text_obj(
            "footer.number", f"{page_number} / 30", 1280 - 140, 679, 100, 24,
            16, COLORS["muted"], align="right",
        ))
        if footer and footer != title:
            objects.append(_text_obj("footer.project", footer, list_x, 679, 700, 24, 15, COLORS["muted"]))
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
        elif tid in {"compare", "change", "tradeoff", "before-after", "team-two"} and len(entries) == 2:
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
        elif tid in {"parallel", "case-compare"} and 2 <= len(entries) <= 4:
            # One entry per column: first line = column title; optional following
            # lines = body. Bound body-* always keeps the full entry for keyPoints:i.
            gap, count = 36, len(entries)
            w = (1128 - gap * (count - 1)) / count
            accents = [COLORS["blue"], COLORS["teal"], COLORS["orange"], "#8959B3"]
            title_size = 28 if count <= 2 else 24
            body_size = 24 if count <= 2 else 21
            title_h = 52
            for i, entry in enumerate(entries):
                x = 76 + i * (w + gap)
                parts = entry.split("\n", 1)
                col_title = parts[0].strip()
                col_body = parts[1].strip() if len(parts) > 1 else ""
                objects.append(_rect(f"item.{i+1}.accent", x, start_y, 54, 6, accents[i]))
                objects.append(_text_obj(
                    f"item.{i+1}.title", col_title, x, start_y + 22, w, title_h,
                    title_size, bold=True, lineHeight=1.2,
                ))
                if col_body:
                    body_y = start_y + 22 + title_h + 8
                    objects.append(_text_obj(
                        f"body-{i+1}", entry, x, body_y, w, max(40, 600 - body_y),
                        body_size, COLORS["muted"], lineHeight=1.4,
                    ))
                else:
                    # Single-line column: title is the visual; body-* sits on the same
                    # slot so keyPoints:i binding stays continuous (paints over title).
                    objects.append(_text_obj(
                        f"body-{i+1}", entry, x, start_y + 22, w, title_h,
                        title_size, bold=True, lineHeight=1.2,
                    ))
                if i < count - 1:
                    objects.append(_line(f"item.{i+1}.divider", x + w + gap / 2, start_y + 2, 0, 600 - start_y, "#DCE4ED", 1))
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
        elif tid == "swimlane" and 2 <= len(entries) <= 4:
            # Swimlane: rect+text+line approximation (no Office table).
            # Parsing: see _parse_swimlane_lanes — paragraph (role + stage lines)
            # or `角色｜动作…` pipes. Stable IDs: lane.{i}.label / lane.{i}.cell.{j}.
            lanes = _parse_swimlane_lanes(entries)
            if len(lanes) >= 2:
                stage_n = len(lanes[0]["cells"])
                lane_n = len(lanes)
                label_w = 150
                gap_x, gap_y = 16, 18
                grid_x = 76 + label_w + 16
                grid_w = 1128 - label_w - 16
                cell_w = (grid_w - gap_x * (stage_n - 1)) / stage_n
                header_h = 36
                avail_h = 600 - start_y - header_h
                row_h = (avail_h - gap_y * (lane_n - 1)) / lane_n
                cell_h = row_h
                accents = [COLORS["blue"], COLORS["ink"], COLORS["teal"], COLORS["orange"]]
                for j in range(stage_n):
                    sx = grid_x + j * (cell_w + gap_x)
                    objects.append(_text_obj(
                        f"lane.stage.{j+1}", f"阶段 {j+1}", sx, start_y, cell_w, header_h,
                        16, COLORS["muted"], align="center", lineHeight=1.2,
                    ))
                for i, lane in enumerate(lanes):
                    ly = start_y + header_h + i * (row_h + gap_y)
                    fill = "#EEF1F8" if i == 0 else COLORS["ink"]
                    label_color = COLORS["ink"] if i == 0 else "#FFFFFF"
                    objects.append(_rect(f"lane.{i+1}.label.bg", 76, ly, label_w, cell_h, fill, radius=10))
                    objects.append(_text_obj(
                        f"lane.{i+1}.label", lane["label"], 84, ly + 12, label_w - 16, cell_h - 24,
                        20, label_color, True, align="center", valign="middle", lineHeight=1.25,
                    ))
                    for j, cell in enumerate(lane["cells"]):
                        cx = grid_x + j * (cell_w + gap_x)
                        objects.append(_rect(
                            f"lane.{i+1}.cell.{j+1}", cx, ly, cell_w, cell_h, "#FFFFFF",
                            stroke="#E3E9F1", strokeWidth=1, radius=10,
                        ))
                        if i > 0:
                            objects.append(_rect(
                                f"lane.{i+1}.cell.{j+1}.accent", cx, ly, cell_w, 6, accents[i % len(accents)], radius=2,
                            ))
                        objects.append(_text_obj(
                            f"lane.{i+1}.cell.{j+1}.text", cell or " ", cx + 14, ly + 18,
                            cell_w - 28, cell_h - 32, 20, COLORS["ink"], lineHeight=1.35,
                        ))
                        if j < stage_n - 1:
                            objects.append(_line(
                                f"lane.{i+1}.link.{j+1}", cx + cell_w, ly + cell_h / 2,
                                gap_x, 0, "#DCE4ED", 2,
                            ))
                    # body-* keeps full entry for keyPoints binding (clipped label slot).
                    objects.append(_text_obj(
                        f"body-{i+1}", lane["raw"], 76, ly, label_w, cell_h,
                        20, label_color, True, align="center", valign="middle",
                        lineHeight=1.25, opacity=0.02,
                    ))
            else:
                objects.append(_text_obj("body-1", raw, 80, start_y + 12, 1110, 622 - start_y, 28, lineHeight=1.45))
        elif tid == "decision-matrix" and len(entries) == 4:
            # 2×2 quadrants. Each entry: first line = quadrant title; rest = body.
            gap = 24
            grid_x, grid_y = 76, start_y
            grid_w, grid_h = 1128, 600 - start_y
            qw = (grid_w - gap) / 2
            qh = (grid_h - gap) / 2
            accents = [COLORS["blue"], COLORS["teal"], COLORS["orange"], "#8959B3"]
            fills = ["#FFFFFF", "#F7F9FC", "#F7F9FC", "#FFFFFF"]
            positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
            objects.append(_line("matrix.axis.h", grid_x, grid_y + qh + gap / 2, grid_w, 0, "#E3E9F1", 2))
            objects.append(_line("matrix.axis.v", grid_x + qw + gap / 2, grid_y, 0, grid_h, "#E3E9F1", 2))
            for i, entry in enumerate(entries):
                col, row = positions[i]
                x = grid_x + col * (qw + gap)
                y = grid_y + row * (qh + gap)
                parts = entry.split("\n", 1)
                qtitle = parts[0].strip()
                qbody = parts[1].strip() if len(parts) > 1 else ""
                objects.append(_rect(f"matrix.{i+1}.bg", x, y, qw, qh, fills[i], stroke="#E3E9F1", strokeWidth=1, radius=12))
                objects.append(_rect(f"matrix.{i+1}.accent", x, y, qw, 8, accents[i], radius=2))
                objects.append(_text_obj(
                    f"matrix.{i+1}.title", qtitle, x + 20, y + 24, qw - 40, 44,
                    24, COLORS["ink"], True, lineHeight=1.2,
                ))
                if qbody:
                    objects.append(_text_obj(
                        f"matrix.{i+1}.body", qbody, x + 20, y + 76, qw - 40, qh - 100,
                        20, COLORS["muted"], lineHeight=1.4,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", entry, x + 20, y + 24, qw - 40, qh - 48,
                    22, COLORS["ink"], lineHeight=1.35, opacity=0.02,
                ))
        elif tid == "kpi" and 2 <= len(entries) <= 4:
            # KPI wall: 2–4 cards. First line = value; optional next line = label.
            cards = _parse_kpi_entries(entries)
            count = len(cards)
            gap = 28
            w = (1128 - gap * (count - 1)) / count
            for i, card in enumerate(cards):
                x = 76 + i * (w + gap)
                alt = i % 2 == 0
                fill = COLORS["ink"] if alt else "#FFFFFF"
                value_color = "#FFFFFF" if alt else COLORS["blue"]
                label_color = "#FFFFFF" if alt else COLORS["ink"]
                objects.append(_rect(
                    f"kpi.{i+1}.bg", x, start_y, w, 600 - start_y, fill,
                    stroke="#E3E9F1" if not alt else "none", strokeWidth=1, radius=14,
                ))
                if not alt:
                    objects.append(_rect(f"kpi.{i+1}.accent", x, start_y, w, 8, COLORS["blue"], radius=2))
                objects.append(_text_obj(
                    f"kpi.{i+1}.value", card["value"], x + 16, start_y + 80, w - 32, 100,
                    52 if count <= 3 else 44, value_color, True, align="center", lineHeight=1.1,
                ))
                if card["label"]:
                    objects.append(_text_obj(
                        f"kpi.{i+1}.label", card["label"], x + 16, start_y + 200, w - 32, 80,
                        22, label_color, align="center", lineHeight=1.3,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", card["raw"], x + 16, start_y + 80, w - 32, 200,
                    28, value_color, True, align="center", lineHeight=1.2, opacity=0.02,
                ))
        elif tid == "funnel" and 3 <= len(entries) <= 5:
            # Funnel: 3–5 centered decreasing bars; last stage orange (收口).
            # Entry: `阶段名｜说明` or first line name + following lines subtitle.
            n = len(entries)
            stages = [_parse_stage_entry(e) for e in entries]
            max_w, min_w = 980, 360
            avail_h = 600 - start_y
            gap = 14
            bar_h = min(88, (avail_h - gap * (n - 1)) / n)
            for i, stage in enumerate(stages):
                t = i / max(1, n - 1)
                w = max_w - t * (max_w - min_w)
                x = 76 + (1128 - w) / 2
                y = start_y + i * (bar_h + gap)
                fill = COLORS["orange"] if i == n - 1 else (
                    COLORS["blue"] if i == 0 else ("#5B7EF0" if i == 1 else ("#7AA0F5" if i == 2 else COLORS["teal"]))
                )
                objects.append(_rect(f"funnel.{i+1}.bg", x, y, w, bar_h, fill, radius=10))
                objects.append(_text_obj(
                    f"funnel.{i+1}.name", stage["name"], x + 24, y + 12, w - 48, 32,
                    24 if n <= 4 else 21, "#FFFFFF", True, align="center", lineHeight=1.15,
                ))
                if stage["sub"]:
                    objects.append(_text_obj(
                        f"funnel.{i+1}.sub", stage["sub"], x + 24, y + 44, w - 48, 28,
                        16, "#FFFFFF", align="center", lineHeight=1.2, opacity=0.92,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", stage["raw"], x + 24, y + 12, w - 48, bar_h - 20,
                    22, "#FFFFFF", True, align="center", lineHeight=1.2, opacity=0.02,
                ))
        elif tid in {"portfolio-grid", "status-grid"} and 4 <= len(entries) <= 16:
            # N×N-ish status grid: filled cells vs outline placeholders (`+` / 待挖).
            # Optional `蓝:标签` / `橙:标签` / `青:标签` sets accent; else cycle.
            n = len(entries)
            cols = 4 if n >= 10 else (3 if n >= 5 else 2)
            rows = math.ceil(n / cols)
            gap = 14
            grid_x, grid_y = 76, start_y
            grid_w, grid_h = 1128, 600 - start_y
            cell_w = (grid_w - gap * (cols - 1)) / cols
            cell_h = (grid_h - gap * (rows - 1)) / rows
            accent_cycle = [COLORS["blue"], COLORS["teal"], COLORS["orange"]]
            accent_key = {"blue": COLORS["blue"], "teal": COLORS["teal"], "orange": COLORS["orange"]}
            filled_i = 0
            for i, entry in enumerate(entries):
                cell = _parse_grid_cell(entry)
                col, row = i % cols, i // cols
                x = grid_x + col * (cell_w + gap)
                y = grid_y + row * (cell_h + gap)
                if cell["placeholder"]:
                    objects.append(_rect(
                        f"grid.{i+1}.bg", x, y, cell_w, cell_h, "#FFFFFF",
                        stroke="#C5D0DE", strokeWidth=2, radius=12,
                    ))
                    objects.append(_text_obj(
                        f"grid.{i+1}.label", cell["label"] if cell["label"] != "+" else "+",
                        x + 10, y + cell_h / 2 - 18, cell_w - 20, 36,
                        28, "#A8B4C4", True, align="center", lineHeight=1.1,
                    ))
                else:
                    if cell["accent"] and cell["accent"] in accent_key:
                        accent = accent_key[cell["accent"]]
                    else:
                        accent = accent_cycle[filled_i % len(accent_cycle)]
                        filled_i += 1
                    objects.append(_rect(
                        f"grid.{i+1}.bg", x, y, cell_w, cell_h, "#F7F9FC",
                        stroke="#E3E9F1", strokeWidth=1, radius=12,
                    ))
                    objects.append(_rect(f"grid.{i+1}.dot", x + 16, y + 16, 12, 12, accent, radius=6))
                    objects.append(_text_obj(
                        f"grid.{i+1}.label", cell["label"], x + 14, y + cell_h / 2 - 20,
                        cell_w - 28, 48, 20, COLORS["ink"], True, align="center", lineHeight=1.25,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", cell["raw"], x + 14, y + 20, cell_w - 28, cell_h - 40,
                    18, COLORS["ink"], align="center", lineHeight=1.25, opacity=0.02,
                ))
        elif tid == "vs-cards" and len(entries) == 2:
            # Dual theme cards (orange vs teal) with center VS badge.
            # Each entry: first line = card title; rest = body. takeaway → bottom bar.
            gap = 48
            card_w = (1128 - gap) / 2
            card_h = (560 if takeaway else 600) - start_y
            if takeaway:
                # reclaim vertical space: bottom bar uses takeaway; hide duplicate top takeaway look
                # (top takeaway object already exists; bottom bar restates conclusion)
                pass
            accents = [COLORS["orange"], COLORS["teal"]]
            washes = ["#FFF8F1", "#F0F8F6"]
            for i, entry in enumerate(entries):
                x = 76 + i * (card_w + gap)
                parts = entry.split("\n", 1)
                ctitle = parts[0].strip()
                cbody = parts[1].strip() if len(parts) > 1 else ""
                objects.append(_rect(
                    f"vs.{i+1}.bg", x, start_y, card_w, card_h, washes[i],
                    stroke=accents[i], strokeWidth=3, radius=16,
                ))
                objects.append(_rect(f"vs.{i+1}.accent", x, start_y, card_w, 10, accents[i], radius=2))
                objects.append(_text_obj(
                    f"vs.{i+1}.title", ctitle, x + 28, start_y + 28, card_w - 56, 56,
                    28, accents[i], True, lineHeight=1.2,
                ))
                if cbody:
                    objects.append(_text_obj(
                        f"vs.{i+1}.body", cbody, x + 28, start_y + 96, card_w - 56, card_h - 120,
                        22, COLORS["ink"], lineHeight=1.4,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", entry, x + 28, start_y + 28, card_w - 56, card_h - 56,
                    24, COLORS["ink"], lineHeight=1.35, opacity=0.02,
                ))
            # Center VS badge
            vs_size = 56
            vs_x = 76 + card_w + (gap - vs_size) / 2
            vs_y = start_y + card_h / 2 - vs_size / 2
            objects.append(_rect("vs.badge", vs_x, vs_y, vs_size, vs_size, COLORS["ink"], radius=28))
            objects.append(_text_obj(
                "vs.badge.label", "VS", vs_x, vs_y + 14, vs_size, 30,
                20, "#FFFFFF", True, align="center", lineHeight=1.1,
            ))
            if takeaway:
                bar_y = 620
                objects.append(_rect("vs.conclusion.bg", 76, bar_y, 1128, 44, COLORS["ink"], radius=10))
                objects.append(_text_obj(
                    "vs.conclusion", takeaway, 96, bar_y + 8, 1088, 28,
                    18, "#FFFFFF", align="center", lineHeight=1.2,
                ))
        elif tid in {"claim-proof", "evidence-split"} and len(entries) >= 2:
            # Left evidence shell + right claim rows + optional bottom conclusion (takeaway).
            # Entry 0 = evidence label/body; remaining = right-side claim lines/rows.
            bar_h = 52 if takeaway else 0
            content_bottom = 600 - bar_h
            left_w = 420
            right_x = 76 + left_w + 28
            right_w = 1128 - left_w - 28
            left_h = content_bottom - start_y
            objects.extend(_image_slot("proof.evidence", 76, start_y, left_w, left_h, "图片占位 · 上传替换"))
            objects.append(_rect("proof.evidence.accent", 76, start_y, 8, left_h, COLORS["blue"], radius=2))
            # Keep first entry on body-1 for keyPoints binding (near-invisible under the slot label).
            objects.append(_text_obj(
                "body-1", entries[0], 100, start_y + 52, left_w - 48, left_h - 72,
                22, COLORS["ink"], lineHeight=1.4, opacity=0.02,
            ))
            right_entries = entries[1:]
            # First right entry as large claim if single-line-ish; rest as rows
            claim = right_entries[0]
            claim_parts = claim.split("\n", 1)
            objects.append(_text_obj(
                "proof.claim", claim_parts[0].strip(), right_x, start_y, right_w, 56,
                32, COLORS["ink"], True, lineHeight=1.15,
            ))
            objects.append(_rect("proof.claim.rule", right_x, start_y + 58, 120, 4, COLORS["orange"], radius=2))
            objects.append(_text_obj(
                "body-2", claim, right_x, start_y, right_w, 56,
                32, COLORS["ink"], True, lineHeight=1.15, opacity=0.02,
            ))
            rows = right_entries[1:]
            if claim_parts[1:] and claim_parts[1].strip() and not rows:
                # body under claim title when only one right paragraph with multiple lines
                objects.append(_text_obj(
                    "proof.claim.body", claim_parts[1].strip(), right_x, start_y + 76, right_w, 80,
                    20, COLORS["muted"], lineHeight=1.35,
                ))
            row_top = start_y + 100
            avail = content_bottom - row_top - 8
            if rows:
                row_h = min(72, avail / max(1, len(rows)))
                for j, row in enumerate(rows):
                    y = row_top + j * row_h
                    objects.append(_rect(
                        f"proof.row.{j+1}.bg", right_x, y, right_w, row_h - 10, "#FFFFFF",
                        stroke="#E3E9F1", strokeWidth=1, radius=10,
                    ))
                    objects.append(_text_obj(
                        f"body-{j+3}", row, right_x + 18, y + 10, right_w - 36, row_h - 26,
                        20, COLORS["ink"], lineHeight=1.3,
                    ))
            if takeaway:
                bar_y = 610
                objects.append(_rect("proof.conclusion.bg", 76, bar_y, 1128, bar_h - 8, COLORS["ink"], radius=10))
                objects.append(_text_obj(
                    "proof.conclusion", takeaway, 96, bar_y + 10, 1088, 28,
                    18, "#FFFFFF", lineHeight=1.2,
                ))
        elif tid == "pillar-cards" and 2 <= len(entries) <= 4:
            # Multi-pillar domain cards: number + title + bullets + bottom summary bar.
            # Each blank-separated entry: first line = title; middle = bullets; last line
            # after `总结：` (or the final line) = pointed summary bar text.
            accents = [COLORS["blue"], COLORS["orange"], COLORS["teal"], "#5B7EF0"]
            washes = ["#EEF2FC", "#FFF6ED", "#EAF6F4", "#F0F3FA"]
            count = len(entries)
            gap = 28
            w = (1128 - gap * (count - 1)) / count
            pillars = []
            for entry in entries:
                lines = [ln.strip() for ln in entry.split("\n") if ln.strip()]
                title_l = lines[0] if lines else ""
                summary = ""
                bullets = []
                for ln in lines[1:]:
                    if ln.startswith("总结：") or ln.startswith("总结:"):
                        summary = ln.split("：", 1)[-1].split(":", 1)[-1].strip()
                    else:
                        bullets.append(ln.lstrip("·•-— ").strip())
                if not summary and bullets:
                    summary = bullets.pop()
                pillars.append({"title": title_l, "bullets": bullets[:4], "summary": summary or title_l, "raw": entry})
            for i, p in enumerate(pillars):
                x = 76 + i * (w + gap)
                y0 = start_y
                h = 600 - start_y
                objects.append(_rect(
                    f"pillar.{i+1}.bg", x, y0, w, h, "#FFFFFF",
                    stroke="#E3E9F1", strokeWidth=1, radius=14,
                ))
                # Number badge (rounded square standing in for hexagon)
                badge = 44
                objects.append(_rect(
                    f"pillar.{i+1}.badge", x + (w - badge) / 2, y0 + 18, badge, badge,
                    accents[i % len(accents)], radius=10,
                ))
                objects.append(_text_obj(
                    f"pillar.{i+1}.num", str(i + 1).zfill(2), x + (w - badge) / 2, y0 + 26, badge, 30,
                    18, "#FFFFFF", True, align="center", lineHeight=1.1,
                ))
                objects.append(_text_obj(
                    f"pillar.{i+1}.title", p["title"], x + 16, y0 + 78, w - 32, 52,
                    22 if count <= 3 else 18, COLORS["ink"], True, align="center", lineHeight=1.2,
                ))
                by = y0 + 140
                for j, b in enumerate(p["bullets"]):
                    objects.append(_rect(
                        f"pillar.{i+1}.dot.{j+1}", x + 22, by + 8, 8, 8,
                        accents[i % len(accents)], radius=4,
                    ))
                    objects.append(_text_obj(
                        f"pillar.{i+1}.bullet.{j+1}", b, x + 38, by, w - 56, 36,
                        16, COLORS["muted"], lineHeight=1.3,
                    ))
                    by += 40
                # Bottom summary bar (rectangle with chevron-ish right tip via overlapping)
                bar_h = 44
                bar_y = y0 + h - bar_h - 16
                objects.append(_rect(
                    f"pillar.{i+1}.summary.bg", x + 12, bar_y, w - 24, bar_h,
                    accents[i % len(accents)], radius=8,
                ))
                objects.append(_text_obj(
                    f"pillar.{i+1}.summary", p["summary"], x + 24, bar_y + 10, w - 48, 28,
                    15, "#FFFFFF", True, align="center", lineHeight=1.15,
                ))
                objects.append(_text_obj(
                    f"body-{i+1}", p["raw"], x + 16, y0 + 78, w - 32, 80,
                    18, COLORS["ink"], lineHeight=1.2, opacity=0.02,
                ))
        elif tid == "guide-split" and len(entries) >= 2:
            # Left vertical steps + right categorized tool/item grid.
            # Steps: entries without `分组名：项｜项` pattern.
            # Groups: `电脑：A｜B｜C` (fullwidth/halfwidth colon + pipes).
            steps, groups = [], []
            for entry in entries:
                head = entry.split("\n", 1)[0].strip()
                if re.search(r"[：:]", head) and re.search(r"[｜|]", head):
                    groups.append(entry)
                elif re.match(r"^.+[：:].+", head) and ("｜" in entry or "|" in entry):
                    groups.append(entry)
                else:
                    steps.append(entry)
            if not steps:
                steps, groups = entries[: max(1, len(entries) // 2)], entries[max(1, len(entries) // 2):]
            if not groups:
                # Single right placeholder group from remaining empty
                groups = ["工具组：项甲｜项乙｜项丙"]
            left_w = 420
            right_x = 76 + left_w + 32
            right_w = 1128 - left_w - 32
            content_h = 600 - start_y
            # Left steps
            n = min(5, max(1, len(steps)))
            step_items = steps[:n]
            gap_y = 16
            row_h = (content_h - gap_y * (n - 1)) / n if n else content_h
            for i, entry in enumerate(step_items):
                stage = _parse_stage_entry(entry)
                y = start_y + i * (row_h + gap_y)
                fill = COLORS["teal"] if i == n - 1 else COLORS["blue"]
                objects.append(_rect(f"guide.step.{i+1}.dot", 76, y + 8, 44, 44, fill, radius=22))
                objects.append(_text_obj(
                    f"guide.step.{i+1}.num", str(i + 1), 76, y + 16, 44, 28,
                    18, "#FFFFFF", True, align="center", lineHeight=1.1,
                ))
                if i < n - 1:
                    objects.append(_line(
                        f"guide.step.{i+1}.link", 97, y + 56, 0, row_h + gap_y - 56, "#C5D0DE", 2,
                    ))
                objects.append(_text_obj(
                    f"guide.step.{i+1}.title", stage["name"], 136, y + 4, left_w - 70, 28,
                    20, COLORS["ink"], True, lineHeight=1.2,
                ))
                if stage["sub"]:
                    objects.append(_text_obj(
                        f"guide.step.{i+1}.sub", stage["sub"], 136, y + 34, left_w - 70, max(28, row_h - 44),
                        15, COLORS["muted"], lineHeight=1.3,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", stage["raw"], 136, y + 4, left_w - 70, 40,
                    18, COLORS["ink"], lineHeight=1.2, opacity=0.02,
                ))
            # Right groups
            g_n = min(4, len(groups))
            g_h = (content_h - 12 * (g_n - 1)) / g_n
            for gi, gentry in enumerate(groups[:g_n]):
                gy = start_y + gi * (g_h + 12)
                lines = [ln.strip() for ln in gentry.split("\n") if ln.strip()]
                head = lines[0]
                if re.search(r"[：:]", head):
                    gname, rest = re.split(r"[：:]", head, maxsplit=1)
                else:
                    gname, rest = head, ""
                items = _split_pipe_cells(rest) if rest else []
                for extra in lines[1:]:
                    items.extend(_split_pipe_cells(extra) if re.search(r"[｜|]", extra) else [extra])
                objects.append(_rect(
                    f"guide.group.{gi+1}.bg", right_x, gy, right_w, g_h, "#F7F9FC",
                    stroke="#E3E9F1", strokeWidth=1, radius=12,
                ))
                objects.append(_text_obj(
                    f"guide.group.{gi+1}.name", gname.strip(), right_x + 16, gy + 12, 100, 28,
                    16, COLORS["ink"], True, lineHeight=1.2,
                ))
                chip_x = right_x + 120
                chip_w = 88
                for ti, item in enumerate(items[:6]):
                    cx = chip_x + ti * (chip_w + 10)
                    if cx + chip_w > right_x + right_w - 12:
                        break
                    objects.append(_rect(
                        f"guide.group.{gi+1}.chip.{ti+1}", cx, gy + (g_h - 56) / 2, chip_w, 56,
                        "#FFFFFF", stroke="#DCE4ED", strokeWidth=1, radius=10,
                    ))
                    objects.append(_rect(
                        f"guide.group.{gi+1}.icon.{ti+1}", cx + (chip_w - 28) / 2, gy + (g_h - 56) / 2 + 8, 28, 28,
                        [COLORS["blue"], COLORS["teal"], COLORS["orange"]][ti % 3], radius=14,
                    ))
                    objects.append(_text_obj(
                        f"guide.group.{gi+1}.item.{ti+1}", item[:8], cx + 4, gy + (g_h - 56) / 2 + 36, chip_w - 8, 18,
                        11, COLORS["muted"], align="center", lineHeight=1.1,
                    ))
                body_i = n + gi + 1
                objects.append(_text_obj(
                    f"body-{body_i}", gentry, right_x + 16, gy + 12, right_w - 32, 40,
                    14, COLORS["ink"], lineHeight=1.2, opacity=0.02,
                ))
            if takeaway:
                objects.append(_rect("guide.tip.bg", 76, 610, 1128, 40, "#FFF6ED", radius=8))
                objects.append(_text_obj(
                    "guide.tip", takeaway, 96, 618, 1088, 26, 15, COLORS["orange"], lineHeight=1.2,
                ))
        elif tid == "feature-hero" and len(entries) >= 1:
            # Left narrative bullets + right large rounded hero placeholder + optional bottom badges.
            # Covers guide-showcase / product-hero refs. takeaway or a `提示：` line → tip bar.
            # Short final paragraph of `A｜B｜C` (no colon) → bottom badge strip.
            tip = takeaway
            bullets, badges = [], []
            for entry in entries:
                head = entry.strip()
                if head.startswith("提示：") or head.startswith("提示:"):
                    tip = head.split("：", 1)[-1].split(":", 1)[-1].strip()
                    continue
                lines = [ln.strip() for ln in entry.split("\n") if ln.strip()]
                if len(lines) == 1 and re.search(r"[｜|]", lines[0]) and not re.search(r"[：:]", lines[0]):
                    badges = _split_pipe_cells(lines[0])
                    continue
                bullets.append(entry)
            if not bullets:
                bullets = entries[:1]
            left_w = 520
            right_x = 76 + left_w + 28
            right_w = 1128 - left_w - 28
            tip_h = 44 if tip else 0
            badge_h = 70 if badges else 0
            content_bottom = 600 - tip_h - badge_h
            # Left bullets
            bn = min(5, len(bullets))
            row_h = max(56, (content_bottom - start_y) / bn) if bn else 60
            for i, entry in enumerate(bullets[:bn]):
                stage = _parse_stage_entry(entry)
                y = start_y + i * row_h
                objects.append(_rect(
                    f"feature.bullet.{i+1}.dot", 76, y + 10, 12, 12, COLORS["teal"], radius=6,
                ))
                objects.append(_text_obj(
                    f"feature.bullet.{i+1}.title", stage["name"], 100, y, left_w - 40, 28,
                    20, COLORS["ink"], True, lineHeight=1.2,
                ))
                if stage["sub"]:
                    objects.append(_text_obj(
                        f"feature.bullet.{i+1}.sub", stage["sub"], 100, y + 30, left_w - 40, max(24, row_h - 36),
                        15, COLORS["muted"], lineHeight=1.3,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", stage["raw"], 100, y, left_w - 40, 40,
                    18, COLORS["ink"], lineHeight=1.2, opacity=0.02,
                ))
            # Right hero: empty image slot for product / screenshot upload.
            hero_h = content_bottom - start_y - 8
            objects.append(_rect(
                "feature.hero.bg", right_x, start_y, right_w, hero_h, COLORS["teal"], radius=18,
            ))
            objects.extend(_image_slot(
                "feature.hero", right_x + 28, start_y + 28, right_w - 56, hero_h - 56,
                "图片占位 · 上传替换",
            ))
            # Bottom badges
            if badges:
                by = content_bottom + 4
                bw = min(160, (1128 - 12 * (len(badges[:4]) - 1)) / max(1, len(badges[:4])))
                for bi, lab in enumerate(badges[:4]):
                    bx = 76 + bi * (bw + 12)
                    objects.append(_rect(
                        f"feature.badge.{bi+1}.icon", bx, by + 8, 36, 36,
                        [COLORS["teal"], COLORS["blue"], COLORS["orange"], "#5B7EF0"][bi % 4], radius=18,
                    ))
                    objects.append(_text_obj(
                        f"feature.badge.{bi+1}.label", lab, bx + 44, by + 14, bw - 44, 28,
                        15, COLORS["ink"], True, lineHeight=1.2,
                    ))
            if tip:
                ty = 610
                objects.append(_rect("feature.tip.bg", 76, ty, 1128, 40, "#FFF6ED", radius=8))
                objects.append(_text_obj(
                    "feature.tip", tip, 96, ty + 8, 1088, 26, 15, COLORS["orange"], lineHeight=1.2,
                ))
        elif tid == "case-scorecard" and len(entries) >= 2:
            # Three-column case scorecard: numbered list | comparison table | chart + conclusion.
            # Paragraphs: 0 = list lines (`要点｜副标`); 1 = table rows (`指标｜甲｜乙｜结果`);
            # optional 2 = chart labels / notes. takeaway → right conclusion box.
            cols = entries[:3]
            while len(cols) < 3:
                cols.append("")
            list_lines = [ln.strip() for ln in cols[0].split("\n") if ln.strip()]
            table_lines = [ln.strip() for ln in cols[1].split("\n") if ln.strip()]
            chart_lines = [ln.strip() for ln in cols[2].split("\n") if ln.strip()] if cols[2] else []
            gap = 20
            col_w = (1128 - gap * 2) / 3
            y0 = start_y
            h = 600 - start_y
            # --- Col 1: numbered list ---
            x1 = 76
            objects.append(_text_obj(
                "score.col1.caption", "01 要点", x1, y0, col_w, 28,
                14, COLORS["muted"], True, lineHeight=1.2,
            ))
            items = list_lines[:8] or ["要点一｜说明", "要点二｜说明"]
            lh = min(48, (h - 40) / max(1, len(items)))
            for i, line in enumerate(items):
                stage = _parse_stage_entry(line)
                y = y0 + 36 + i * lh
                objects.append(_rect(
                    f"score.list.{i+1}.badge", x1, y + 4, 28, 28, COLORS["blue"], radius=6,
                ))
                objects.append(_text_obj(
                    f"score.list.{i+1}.num", str(i + 1), x1, y + 8, 28, 22,
                    13, "#FFFFFF", True, align="center", lineHeight=1.1,
                ))
                objects.append(_text_obj(
                    f"score.list.{i+1}.title", stage["name"], x1 + 36, y, col_w - 40, 22,
                    14, COLORS["ink"], True, lineHeight=1.15,
                ))
                if stage["sub"]:
                    objects.append(_text_obj(
                        f"score.list.{i+1}.sub", stage["sub"], x1 + 36, y + 20, col_w - 40, 18,
                        11, COLORS["muted"], lineHeight=1.15,
                    ))
            objects.append(_text_obj(
                "body-1", cols[0] or "\n".join(items), x1, y0 + 36, col_w, 40,
                12, COLORS["ink"], opacity=0.02,
            ))
            # --- Col 2: table ---
            x2 = 76 + col_w + gap
            objects.append(_text_obj(
                "score.col2.caption", "02 对比表", x2, y0, col_w, 28,
                14, COLORS["muted"], True, lineHeight=1.2,
            ))
            rows = []
            for line in (table_lines or ["指标｜对照｜本品｜结果", "指标A｜—｜—｜↑", "指标B｜—｜—｜↑"]):
                rows.append(_split_pipe_cells(line) if re.search(r"[｜|]", line) else [line])
            max_c = min(4, max(len(r) for r in rows))
            for r in rows:
                while len(r) < max_c:
                    r.append("")
                del r[max_c:]
            th = min(36, (h - 40) / max(1, len(rows)))
            cell_w = col_w / max_c
            for ri, row in enumerate(rows[:10]):
                ry = y0 + 36 + ri * th
                bg = "#EEF2FC" if ri == 0 else ("#F7F9FC" if ri % 2 == 0 else "#FFFFFF")
                objects.append(_rect(
                    f"score.table.row.{ri+1}", x2, ry, col_w, th - 2, bg, radius=4,
                ))
                for ci, cell in enumerate(row):
                    objects.append(_text_obj(
                        f"score.table.{ri+1}.{ci+1}", cell[:18], x2 + ci * cell_w + 4, ry + 6,
                        cell_w - 8, th - 10, 11 if ri else 12,
                        COLORS["ink"] if ri else COLORS["blue"], True if ri == 0 else False,
                        align="center", lineHeight=1.1,
                    ))
            objects.append(_text_obj(
                "body-2", cols[1] or "\n".join(table_lines), x2, y0 + 36, col_w, 40,
                12, COLORS["ink"], opacity=0.02,
            ))
            # --- Col 3: mini chart placeholder + conclusion ---
            x3 = 76 + 2 * (col_w + gap)
            objects.append(_text_obj(
                "score.col3.caption", "03 趋势与结论", x3, y0, col_w, 28,
                14, COLORS["muted"], True, lineHeight=1.2,
            ))
            chart_h = h * 0.42
            objects.append(_rect(
                "score.chart.bg", x3, y0 + 36, col_w, chart_h, "#FFFFFF",
                stroke="#E3E9F1", strokeWidth=1, radius=10,
            ))
            # Simplified two-series polyline via short line segments (placeholder geometry)
            pad = 20
            pts_a = [(0.0, 0.85), (0.25, 0.55), (0.5, 0.4), (0.75, 0.28), (1.0, 0.18)]
            pts_b = [(0.0, 0.75), (0.25, 0.7), (0.5, 0.62), (0.75, 0.5), (1.0, 0.45)]
            def _seg(oid, pts, color):
                # Scene lines only allow non-negative w/h; always start at the
                # left-or-top endpoint so deltas stay in-bounds.
                for si in range(len(pts) - 1):
                    x0p, y0p = pts[si]
                    x1p, y1p = pts[si + 1]
                    ax = x3 + pad + x0p * (col_w - 2 * pad)
                    ay = y0 + 36 + pad + y0p * (chart_h - 2 * pad)
                    bx = x3 + pad + x1p * (col_w - 2 * pad)
                    by = y0 + 36 + pad + y1p * (chart_h - 2 * pad)
                    if ax <= bx:
                        lx, ly, lw, lh = ax, ay, bx - ax, by - ay
                    else:
                        lx, ly, lw, lh = bx, by, ax - bx, ay - by
                    if lh < 0:
                        ly, lh = ly + lh, -lh
                    objects.append(_line(f"{oid}.{si+1}", lx, ly, max(lw, 0.1), max(lh, 0), color, 2))
            _seg("score.chart.a", pts_a, COLORS["teal"])
            _seg("score.chart.b", pts_b, COLORS["orange"])
            if chart_lines:
                objects.append(_text_obj(
                    "score.chart.note", chart_lines[0][:40], x3 + 10, y0 + 36 + chart_h - 28, col_w - 20, 22,
                    11, COLORS["muted"], align="center", lineHeight=1.1,
                ))
            conc_y = y0 + 36 + chart_h + 12
            conc_h = h - (conc_y - y0) - 8
            objects.append(_rect(
                "score.conclusion.bg", x3, conc_y, col_w, max(60, conc_h), "#EAF6F4", radius=10,
            ))
            conc = takeaway or (chart_lines[1] if len(chart_lines) > 1 else "结论占位：补一句收束")
            objects.append(_text_obj(
                "score.conclusion", conc, x3 + 14, conc_y + 14, col_w - 28, max(40, conc_h - 28),
                14, COLORS["ink"], lineHeight=1.35,
            ))
            objects.append(_text_obj(
                "body-3", cols[2] or conc, x3, conc_y, col_w, 40,
                12, COLORS["ink"], opacity=0.02,
            ))
        elif tid == "before-after-case" and len(entries) >= 1:
            # Left steps (+ optional code placeholder) | mid "原版" screen | right "重构" screen | bottom bar.
            # Entries: step paragraphs; optional final `原版｜重构` labels. takeaway → bottom conclusion.
            labels = ["原版", "重构"]
            steps = []
            for entry in entries:
                head = entry.strip()
                if re.search(r"[｜|]", head) and not re.search(r"\n", head) and len(_split_pipe_cells(head)) == 2:
                    maybe = _split_pipe_cells(head)
                    if all(len(m) <= 12 for m in maybe):
                        labels = maybe
                        continue
                steps.append(entry)
            if not steps:
                steps = ["步骤一｜说明", "步骤二｜说明", "步骤三｜说明"]
            tip_h = 48 if takeaway else 0
            y0 = start_y
            h = 600 - start_y - tip_h
            left_w = 400
            gap = 20
            screen_w = (1128 - left_w - gap * 2) / 2
            # Left: steps + code shell
            sn = min(4, len(steps))
            step_block = h * 0.48
            sh = step_block / sn
            for i, entry in enumerate(steps[:sn]):
                stage = _parse_stage_entry(entry)
                y = y0 + i * sh
                objects.append(_rect(
                    f"bac.step.{i+1}.dot", 76, y + 6, 28, 28, COLORS["blue"] if i < sn - 1 else COLORS["teal"],
                    radius=14,
                ))
                objects.append(_text_obj(
                    f"bac.step.{i+1}.num", str(i + 1), 76, y + 10, 28, 22,
                    13, "#FFFFFF", True, align="center", lineHeight=1.1,
                ))
                objects.append(_text_obj(
                    f"bac.step.{i+1}.title", stage["name"], 114, y + 2, left_w - 50, 24,
                    15, COLORS["ink"], True, lineHeight=1.15,
                ))
                if stage["sub"]:
                    objects.append(_text_obj(
                        f"bac.step.{i+1}.sub", stage["sub"], 114, y + 26, left_w - 50, max(20, sh - 30),
                        12, COLORS["muted"], lineHeight=1.25,
                    ))
                objects.append(_text_obj(
                    f"body-{i+1}", stage["raw"], 114, y + 2, left_w - 50, 30,
                    12, COLORS["ink"], opacity=0.02,
                ))
            code_y = y0 + step_block + 8
            code_h = h - step_block - 16
            objects.append(_rect(
                "bac.code.bg", 76, code_y, left_w, max(60, code_h), "#102544", radius=10,
            ))
            objects.append(_text_obj(
                "bac.code.label", "代码 / 日志占位", 92, code_y + max(20, code_h / 2 - 12), left_w - 32, 28,
                14, "#8DA8CC", align="center", lineHeight=1.2,
            ))
            # Dual screens: empty image slots for before/after screenshots.
            for si, lab in enumerate(labels[:2]):
                sx = 76 + left_w + gap + si * (screen_w + gap)
                objects.append(_text_obj(
                    f"bac.screen.{si+1}.caption", f"0{si+2} {lab}", sx, y0, screen_w, 28,
                    14, COLORS["muted"], True, lineHeight=1.2,
                ))
                objects.append(_rect(
                    f"bac.screen.{si+1}.bg", sx, y0 + 32, screen_w, h - 40, "#FFFFFF",
                    stroke=COLORS["blue"] if si == 0 else COLORS["teal"], strokeWidth=2, radius=16,
                ))
                objects.extend(_image_slot(
                    f"bac.screen.{si+1}", sx + 16, y0 + 48, screen_w - 32, h - 72,
                    f"图片占位 · {lab}",
                ))
            if takeaway:
                objects.append(_rect("bac.conclusion.bg", 76, 610, 1128, 40, "#EEF2FC", radius=10))
                objects.append(_text_obj(
                    "bac.conclusion", takeaway, 96, 618, 1088, 26,
                    15, COLORS["ink"], True, lineHeight=1.2,
                ))
        elif tid in {"landscape-path", "table-rising-bars", "market-path"} and len(entries) >= 1:
            # Left comparison table (品类｜左列｜右列) + right rising path bars + takeaway bar.
            # Paragraphs: 0 = table rows (optional final non-pipe line = table caption);
            # 1 = 2–4 path stages `标题｜说明`. takeaway → bottom conclusion.
            table_raw = entries[0] if entries else ""
            path_raw = entries[1] if len(entries) > 1 else ""
            table_lines = [ln.strip() for ln in table_raw.split("\n") if ln.strip()]
            caption = ""
            rows = []
            for ln in table_lines:
                if re.search(r"[｜|]", ln):
                    rows.append(_split_pipe_cells(ln))
                else:
                    caption = ln
            if not rows:
                rows = [
                    ["品类", "海外产品", "国内产品"],
                    ["类别 A", "产品甲", "产品乙"],
                    ["类别 B", "产品丙", "产品丁"],
                    ["类别 C", "产品戊", "产品己"],
                    ["类别 D", "产品庚", "产品辛"],
                    ["类别 E", "产品壬", "产品癸"],
                ]
            max_c = min(4, max(len(r) for r in rows))
            for r in rows:
                while len(r) < max_c:
                    r.append("")
                del r[max_c:]
            path_lines = []
            if path_raw:
                path_lines = [ln.strip() for ln in path_raw.split("\n") if ln.strip()]
            if not path_lines and len(entries) > 2:
                path_lines = [e.strip() for e in entries[1:] if e.strip()]
            if not path_lines:
                path_lines = ["解析｜拆开看懂", "重构｜用 AI 重做", "突破｜走出困境", "先发｜抢占主动"]
            stages = [_parse_stage_entry(ln) for ln in path_lines[:4]]
            tip_h = 44 if takeaway else 0
            y0 = start_y
            h = 600 - start_y - tip_h
            gap = 28
            left_w = 640
            right_w = 1128 - left_w - gap
            left_x = 76
            right_x = 76 + left_w + gap
            # --- Left: table ---
            objects.append(_text_obj(
                "land.table.caption", "对照表", left_x, y0, left_w, 26,
                14, COLORS["muted"], True, lineHeight=1.2,
            ))
            table_top = y0 + 30
            usable_h = h - 30 - (36 if caption else 0)
            row_h = min(42, usable_h / max(1, len(rows)))
            col_w = left_w / max_c
            for ri, row in enumerate(rows[:12]):
                ry = table_top + ri * row_h
                if ri == 0:
                    bg = "#EEF2FC"
                else:
                    bg = "#FFFFFF" if ri % 2 else "#F7F9FC"
                objects.append(_rect(
                    f"land.table.row.{ri+1}", left_x, ry, left_w, row_h - 2, bg, radius=4,
                ))
                for ci, cell in enumerate(row):
                    if ri == 0:
                        if ci == max_c - 1 and max_c >= 3:
                            color = COLORS["teal"]
                        elif ci == 1:
                            color = COLORS["blue"]
                        else:
                            color = COLORS["ink"]
                        bold = True
                        size = 13
                    else:
                        color = COLORS["ink"]
                        bold = ci == 0
                        size = 12
                    objects.append(_text_obj(
                        f"land.table.{ri+1}.{ci+1}", cell[:22], left_x + ci * col_w + 8, ry + 8,
                        col_w - 14, row_h - 14, size, color, bold, align="left", lineHeight=1.15,
                    ))
            objects.append(_text_obj(
                "body-1", table_raw or "\n".join("|".join(r) for r in rows), left_x, table_top, left_w, 40,
                12, COLORS["ink"], opacity=0.02,
            ))
            if caption:
                objects.append(_text_obj(
                    "land.table.note", caption[:80], left_x, table_top + len(rows[:12]) * row_h + 4,
                    left_w, 28, 13, COLORS["muted"], lineHeight=1.25,
                ))
            # --- Right: rising bars ---
            objects.append(_text_obj(
                "land.path.caption", "路径", right_x, y0, right_w, 26,
                14, COLORS["muted"], True, lineHeight=1.2,
            ))
            n = len(stages)
            bar_gap = 14
            bar_w = (right_w - bar_gap * (n - 1)) / n
            bar_area_top = y0 + 36
            bar_area_h = h - 70
            if n == 2:
                heights = [0.55, 0.9]
            elif n == 3:
                heights = [0.48, 0.68, 0.9]
            else:
                heights = [0.42, 0.58, 0.74, 0.92][:n]
            fills = [COLORS["blue"], "#5B7EF0", COLORS["teal"], COLORS["orange"]]
            for i, stage in enumerate(stages):
                bh = bar_area_h * heights[i]
                bx = right_x + i * (bar_w + bar_gap)
                by = bar_area_top + (bar_area_h - bh)
                fill = fills[i % len(fills)]
                objects.append(_rect(
                    f"land.bar.{i+1}.bg", bx, by, bar_w, bh, fill, radius=10,
                ))
                objects.append(_text_obj(
                    f"land.bar.{i+1}.title", stage["name"][:8], bx + 6, by + 14, bar_w - 12, 28,
                    16, "#FFFFFF", True, align="center", lineHeight=1.15,
                ))
                if stage["sub"]:
                    objects.append(_text_obj(
                        f"land.bar.{i+1}.sub", stage["sub"][:16], bx + 6, by + 44, bar_w - 12, 48,
                        12, "#FFFFFF", align="center", lineHeight=1.25,
                    ))
                objects.append(_text_obj(
                    f"body-{i+2}", stage["raw"], bx, by, bar_w, 30,
                    12, COLORS["ink"], opacity=0.02,
                ))
            if takeaway:
                objects.append(_rect("land.conclusion.bg", 76, 610, 1128, 40, COLORS["ink"], radius=10))
                objects.append(_text_obj(
                    "land.conclusion", takeaway, 96, 618, 1088, 26,
                    15, "#FFFFFF", True, lineHeight=1.2,
                ))

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

