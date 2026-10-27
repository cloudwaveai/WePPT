"""Bounded mechanical layout checks with version-bound browser measurements.

This module does not judge facts, taste, or whether a human has reviewed a deck.
Browser reports are client-reported geometry, never approval statements. Safe
repairs only enlarge text boxes into demonstrably empty space; words, fonts,
images, positions, and unrelated objects are retained.
"""
from __future__ import annotations

import copy
import json
import math
import re
import uuid

from .core import EngineError, _hash, _json, _now
from .rendering import validate_scene, patch_scene


MAX_REPAIR_PASSES = 2
MAX_REPAIRS_PER_PAGE_ROUND = 3
MEASUREMENT_SCHEMA = "ppt-browser-measurement"


def _issue(code, message, slide_id, object_ids=(), *, severity="warning", basis="scene"):
    return {"code": code, "severity": severity, "slideId": slide_id,
            "objectIds": list(object_ids), "message": message, "basis": basis}


def _luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def _contrast(a, b):
    x, y = sorted((_luminance(a), _luminance(b)))
    return (y + .05) / (x + .05)


def _contains(outer, inner):
    return (outer["x"] <= inner["x"] and outer["y"] <= inner["y"]
            and outer["x"] + outer["w"] >= inner["x"] + inner["w"]
            and outer["y"] + outer["h"] >= inner["y"] + inner["h"])


def _intersection(a, b):
    return (max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])),
            max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])))


def _text_background(scene, obj):
    background = scene["background"]
    for prior in scene["objects"]:
        if prior["id"] == obj["id"]:
            break
        if prior["type"] == "rect" and prior["fill"] != "none" and prior["opacity"] >= .99 and _contains(prior, obj):
            background = prior["fill"]
        elif prior["type"] == "image" and _contains(prior, obj):
            return None  # A bitmap background cannot be inferred from geometry.
    return background


def _estimated_height(obj):
    """Conservative character-width estimate; never called a browser result."""
    size, width = obj["fontSize"], max(1, obj["w"])
    lines = 0
    for paragraph in obj["text"].split("\n"):
        units = sum(1 if ord(c) >= 0x2e80 else .35 if c.isspace() or c in ".,:;!|'`" else .65 if c.isupper() else .56 for c in paragraph)
        lines += max(1, math.ceil(units * size / width))
    return lines * size * obj["lineHeight"]


def _content_text(obj):
    return obj["type"] == "text" and bool(obj["text"].strip()) and (
        obj.get("binding") or obj["id"] in {"title", "takeaway"} or obj["id"].startswith("body-"))


def audit_scene(scene, measurement=None):
    """Return precise mechanical findings, retaining their evidence type."""
    scene = validate_scene(scene)
    sid, issues = scene["slideId"], []
    metrics = {r["objectId"]: r for r in (measurement or {}).get("objects", [])}
    measured = bool(measurement and measurement["fontsReady"] and measurement["imagesLoaded"])
    content = [o for o in scene["objects"] if _content_text(o)]
    if not any(o.get("binding") == "title" or o["id"] == "title" for o in content):
        issues.append(_issue("TITLE_MISSING", "本页缺少可识别的标题对象。", sid, severity="error"))
    for obj in scene["objects"]:
        if obj["type"] != "text" or not obj["text"].strip():
            continue
        oid = obj["id"]
        important = _content_text(obj)
        minimum = 18 if important else 14
        if obj["fontSize"] < minimum:
            issues.append(_issue("TEXT_TOO_SMALL", f"文字字号为 {obj['fontSize']:g}px，低于本工作台的 {minimum}px 可读性检查线。", sid, [oid], severity="error" if important else "warning"))
        if oid == "title" and obj["fontSize"] < 28:
            issues.append(_issue("TITLE_HIERARCHY", "标题字号较小，请确认是否能体现页面层级。", sid, [oid]))
        if important and re.search(r"\[(?:待补|补充|替换|你的|请填写|未提供|TODO|TBD)[^\]\n]*\]|【(?:待补|补充|替换|未提供)[^】\n]*】", obj["text"], re.I):
            issues.append(_issue("CONTENT_PLACEHOLDER", "页面仍有明确标记的待补内容。", sid, [oid], severity="error", basis="content-marker"))
        if important and obj["opacity"] < .3:
            issues.append(_issue("TEXT_LOW_OPACITY", "主要文字透明度较低。", sid, [oid], severity="error"))
        background = _text_background(scene, obj)
        if important and background and obj["opacity"] >= .99:
            ratio = _contrast(obj["color"], background)
            threshold = 3 if obj["fontSize"] >= 24 or obj["bold"] and obj["fontSize"] >= 19 else 4.5
            if ratio < threshold:
                issues.append(_issue("TEXT_CONTRAST", f"文字与已知底色的对比度约 {ratio:.2f}，低于本工作台检查线 {threshold:g}；未自动更改配色。", sid, [oid], severity="error"))
        metric = metrics.get(oid)
        if measured and metric:
            if metric["scrollHeight"] > metric["clientHeight"] + 2 or metric["scrollWidth"] > metric["clientWidth"] + 2:
                issues.append(_issue("TEXT_OVERFLOW", "浏览器实测文字超过文字框。", sid, [oid], severity="error", basis="browser-reported"))
        elif _estimated_height(obj) > obj["h"] + 2:
            issues.append(_issue("ESTIMATED_OVERFLOW", "文字容量估算偏紧，需要真实浏览器测量确认。", sid, [oid], basis="estimate"))
    for index, a in enumerate(content):
        for b in content[index + 1:]:
            iw, ih = _intersection(a, b)
            # Text-box edges may touch without their painted glyphs colliding.
            if iw > 8 and ih > max(8, min(a["h"], b["h"]) * .12):
                issues.append(_issue("TEXT_BOX_OVERLAP", "主要文字框存在明显重叠，请检查实际文字是否相互遮挡。", sid, [a["id"], b["id"]], severity="error", basis="geometry"))
    for index, obj in enumerate(scene["objects"]):
        if not _content_text(obj):
            continue
        for later in scene["objects"][index + 1:]:
            if later["type"] not in {"image", "rect"} or later["opacity"] < .99 or later.get("fill") == "none":
                continue
            iw, ih = _intersection(obj, later)
            if iw * ih > obj["w"] * obj["h"] * .9:
                issues.append(_issue("TEXT_OCCLUDED", "主要文字框被后绘制的图片或实色块覆盖，请检查图层顺序。", sid, [obj["id"], later["id"]], severity="error", basis="geometry"))
    if measurement and not measured:
        issues.append(_issue("BROWSER_NOT_READY", "已收到浏览器报告，但字体或图片尚未加载完成，暂不能视为实测通过。", sid, basis="browser-reported"))
    return issues


def _safe_height(scene, obj):
    limit = scene["height"] - 12
    for other in scene["objects"]:
        if other["id"] == obj["id"]:
            continue
        if other["type"] == "rect" and _contains(other, obj):
            limit = min(limit, other["y"] + other["h"] - 4)
            continue
        horizontal = min(obj["x"] + obj["w"], other["x"] + other["w"]) - max(obj["x"], other["x"])
        if horizontal > 2 and other["y"] >= obj["y"] + obj["h"] - 2:
            limit = min(limit, other["y"] - 8)
    return max(obj["h"], limit - obj["y"])


def propose_safe_repairs(scene, measurement=None, protected_objects=()):
    """Only enlarge overflowing text vertically, without moving any object."""
    scene = validate_scene(scene)
    protected = set(protected_objects)
    metrics = {r["objectId"]: r for r in (measurement or {}).get("objects", [])}
    measured = bool(measurement and measurement["fontsReady"] and measurement["imagesLoaded"])
    changes = []
    for obj in scene["objects"]:
        if obj["type"] != "text" or obj["id"] in protected or not obj["text"].strip():
            continue
        metric = metrics.get(obj["id"])
        if measured and metric:
            if metric["scrollWidth"] > metric["clientWidth"] + 2:
                continue  # Width/font/content changes require an explicit choice.
            needed = metric["scrollHeight"] + 4
            overflowing = metric["scrollHeight"] > metric["clientHeight"] + 2
        else:
            needed = math.ceil(_estimated_height(obj)) + 4
            overflowing = needed > obj["h"] + 6
        available = _safe_height(scene, obj)
        if overflowing and needed <= available and needed > obj["h"] + 2:
            changes.append({"objectId": obj["id"], "properties": {"h": needed}})
    if not changes:
        return []
    candidate = patch_scene(scene, changes)
    # A repair never introduces a new intersecting content pair.
    old_pairs = {tuple(i["objectIds"]) for i in audit_scene(scene) if i["code"] == "TEXT_BOX_OVERLAP"}
    new_pairs = {tuple(i["objectIds"]) for i in audit_scene(candidate) if i["code"] == "TEXT_BOX_OVERLAP"}
    return changes if new_pairs <= old_pairs else []


def validate_browser_report(scene, report):
    scene = validate_scene(scene)
    fields = {"schema", "schemaVersion", "slideId", "width", "height", "fontsReady", "imagesLoaded", "objects", "overflowIds"}
    if not isinstance(report, dict) or set(report) != fields:
        raise EngineError("INVALID_QUALITY_REPORT", "测量报告字段不完整或包含不支持的字段；报告不能包含审核结论。")
    if report["schema"] != MEASUREMENT_SCHEMA or type(report["schemaVersion"]) is not int or report["schemaVersion"] != 1 or report["slideId"] != scene["slideId"]:
        raise EngineError("INVALID_QUALITY_REPORT", "测量报告的页面或格式不匹配。")
    for field in ("width", "height"):
        if type(report[field]) not in {int, float} or not math.isfinite(report[field]) or abs(report[field] - scene[field]) > .1:
            raise EngineError("INVALID_QUALITY_REPORT", "测量画布尺寸与当前页面不匹配。")
    if type(report["fontsReady"]) is not bool or type(report["imagesLoaded"]) is not bool:
        raise EngineError("INVALID_QUALITY_REPORT", "字体与图片状态必须为布尔值。")
    rows = report["objects"]
    if not isinstance(rows, list) or len(rows) != len(scene["objects"]):
        raise EngineError("INVALID_QUALITY_REPORT", "测量报告必须包含当前页面的全部对象。")
    expected = {o["id"]: o for o in scene["objects"]}
    seen, overflows, image_results = set(), set(), []
    for row in rows:
        fields = {"objectId", "type", "clientWidth", "clientHeight", "scrollWidth", "scrollHeight"}
        if not isinstance(row, dict) or not isinstance(row.get("objectId"), str) or row["objectId"] not in expected or row["objectId"] in seen:
            raise EngineError("INVALID_QUALITY_REPORT", "测量报告中有未知或重复的对象。")
        obj = expected[row["objectId"]]
        if obj["type"] == "image":
            fields.add("imageLoaded")
        if set(row) != fields or row["type"] != obj["type"]:
            raise EngineError("INVALID_QUALITY_REPORT", "测量对象属性或类型不匹配。")
        seen.add(row["objectId"])
        for field in ("clientWidth", "clientHeight", "scrollWidth", "scrollHeight"):
            if type(row[field]) not in {int, float} or not math.isfinite(row[field]) or not 0 <= row[field] <= 2_000_000:
                raise EngineError("INVALID_QUALITY_REPORT", "测量尺寸必须是有限的非负数值。")
        border = 2 * obj["strokeWidth"] if obj["type"] == "rect" else 0
        expected_w, expected_h = max(0, obj["w"] - border), max(0, obj["h"] - border)
        if obj["type"] != "line" and (abs(row["clientWidth"] - expected_w) > 2 or abs(row["clientHeight"] - expected_h) > 2):
            raise EngineError("INVALID_QUALITY_REPORT", "对象测量尺寸与当前场景不符，可能来自旧版页面。")
        if row["scrollWidth"] < row["clientWidth"] - 2 or row["scrollHeight"] < row["clientHeight"] - 2:
            raise EngineError("INVALID_QUALITY_REPORT", "内容尺寸不能小于容器尺寸。")
        if obj["type"] == "text" and (row["scrollWidth"] > row["clientWidth"] + 2 or row["scrollHeight"] > row["clientHeight"] + 2):
            overflows.add(obj["id"])
        if obj["type"] == "image":
            if type(row["imageLoaded"]) is not bool:
                raise EngineError("INVALID_QUALITY_REPORT", "图片状态必须为布尔值。")
            image_results.append(row["imageLoaded"])
    if not isinstance(report["overflowIds"], list) or any(not isinstance(v, str) for v in report["overflowIds"]) or len(set(report["overflowIds"])) != len(report["overflowIds"]) or set(report["overflowIds"]) != overflows:
        raise EngineError("INVALID_QUALITY_REPORT", "溢出对象清单与实际测量值不一致。")
    if report["imagesLoaded"] != all(image_results):
        raise EngineError("INVALID_QUALITY_REPORT", "图片总体状态与逐对象状态不一致。")
    return copy.deepcopy(report)


class QualityFlow:
    def _init_quality(self):
        with self.wb._connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS studio_quality_runs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, round_id TEXT,
                snapshot_key TEXT NOT NULL, snapshot TEXT NOT NULL,
                report TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_quality_measurements (
                project_id TEXT NOT NULL, slide_id TEXT NOT NULL, scene_revision INTEGER NOT NULL,
                scene_hash TEXT NOT NULL, report TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(project_id,slide_id,scene_revision));
            CREATE TABLE IF NOT EXISTS studio_quality_fixes (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, round_id TEXT NOT NULL,
                slide_id TEXT NOT NULL, before_revision INTEGER NOT NULL, after_revision INTEGER NOT NULL,
                changes TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    def _quality_current(self):
        project = self.wb.get_project(self.project_id)
        scenes, missing = [], []
        for page in project["workspace"]["slides"]:
            if page["archived"]:
                continue
            try:
                current = self.get_scene(page["id"])
            except EngineError as exc:
                if exc.code != "SCENE_MISSING":
                    raise
                missing.append({"slideId": page["id"], "sceneRevision": None, "contentRevision": page["revision"], "stale": True})
                continue
            scenes.append(current)
        pages = [{"slideId": s["slideId"], "sceneRevision": s["sceneRevision"], "contentRevision": s["contentRevision"], "stale": s["stale"]} for s in scenes] + missing
        order = {p["id"]: i for i, p in enumerate(project["workspace"]["slides"])}
        pages.sort(key=lambda p: order[p["slideId"]])
        return {"projectRevision": project["revision"], "pages": pages}, scenes, missing

    def _quality_measurement(self, db, current):
        row = db.execute("SELECT scene_hash,report FROM studio_quality_measurements WHERE project_id=? AND slide_id=? AND scene_revision=?", (self.project_id, current["slideId"], current["sceneRevision"])).fetchone()
        if current["stale"] or row is None or row["scene_hash"] != _hash(current["scene"]):
            return None
        return json.loads(row["report"])

    def _quality_human_accepted(self, snapshots):
        if not snapshots:
            return False
        for item in snapshots:
            if item["stale"]:
                return False
            page = self.wb.get_slide(self.project_id, item["slideId"])
            if not page["reviews"]["content"] or not page["reviews"]["visual"]:
                return False
        return True

    def quality_state(self):
        with self.wb.atomic() as db:
            snapshot, scenes, missing = self._quality_current()
            row = db.execute("SELECT * FROM studio_quality_runs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (self.project_id,)).fetchone()
            pending = [p["slideId"] for p in snapshot["pages"]]
            if row is None:
                return {"status": "not_checked", "readyToReview": False, "humanAccepted": False,
                        "semanticStatus": "operator_review_required", "checkedAt": None, "roundId": None,
                        "snapshot": snapshot, "snapshotKey": _hash(snapshot), "pages": [], "issues": [], "fixes": [],
                        "browser": {"measured": 0, "total": len(pending), "pendingSlideIds": pending},
                        "note": "尚未执行版式检查；程序不能自动确认事实或审美合格。"}
            state = json.loads(row["report"])
            state["humanAccepted"] = self._quality_human_accepted(snapshot["pages"])
            if _hash(snapshot) != row["snapshot_key"]:
                state = {**state, "status": "stale", "readyToReview": False, "humanAccepted": False,
                         "previousSnapshot": state["snapshot"], "snapshot": snapshot, "snapshotKey": _hash(snapshot),
                         "browser": {"measured": 0, "total": len(pending), "pendingSlideIds": pending},
                         "note": "内容或页面版本已变化，之前的质量检查不适用于当前稿件。"}
            return state

    def _quality_protected(self, current, supplied):
        protected = set((supplied or {}).get(current["slideId"], []))
        page = self.wb.get_slide(self.project_id, current["slideId"])["slide"]
        request = page.get("changeRequest") or {}
        summary = request.get("change", "") if isinstance(request, dict) else ""
        with self.wb._connection() as db:
            automatic = db.execute("SELECT 1 FROM studio_quality_fixes WHERE project_id=? AND slide_id=? AND after_revision=?", (self.project_id, current["slideId"], current["sceneRevision"])).fetchone()
        if not automatic and summary.startswith(("仅调整指定对象", "恢复上一版页面")):
            protected.update(c["objectId"] for c in current["changes"] if c.get("objectId") != "page")
        return protected

    def _quality_repair_authority(self, db, round_id, scope):
        """Revalidate repair scope after acquiring the same write transaction.

        A caller may have read its policy before another user submission. That
        policy cannot authorize edits to the newer round, even when the scene
        itself has not changed yet. Standalone repairs remain available only
        before a delivery ledger exists.
        """
        latest = db.execute("SELECT id,status,snapshot FROM studio_delivery_rounds WHERE project_id=? ORDER BY number DESC LIMIT 1", (self.project_id,)).fetchone()
        if latest is None:
            return (True, scope) if round_id is None else (False, set())
        if round_id != latest["id"] or latest["status"] in {"failed", "cancelled", "legacy"}:
            return False, set()
        operation = getattr(self._operation_local, "current", None) or {}
        finishing_current = operation.get("roundId") == round_id and operation.get("generation") is True and operation.get("automatic") is True
        if latest["snapshot"] and json.loads(latest["snapshot"]) != self._delivery_snapshot() and not finishing_current:
            return False, set()
        delivery_scope = getattr(self, "delivery_auto_fix_scope", None)
        policy = delivery_scope(round_id) if callable(delivery_scope) else {}
        if not policy.get("autoFix"):
            return False, set()
        return True, scope & set(policy.get("slideIds", []))

    def check_current_quality(self, auto_fix=False):
        """Check the latest round atomically, using its current repair mandate."""
        if type(auto_fix) is not bool:
            raise EngineError("INVALID_QUALITY_REQUEST", "自动修正开关必须为布尔值。")
        with self.wb.atomic() as db:
            current = db.execute("SELECT id,snapshot FROM studio_delivery_rounds WHERE project_id=? ORDER BY number DESC LIMIT 1", (self.project_id,)).fetchone()
            round_id = current["id"] if current else None
            scope = self.delivery_auto_fix_scope(round_id)
            stale = bool(current and current["snapshot"] and json.loads(current["snapshot"]) != self._delivery_snapshot())
            result = self.run_quality(auto_fix=bool(auto_fix and scope.get("autoFix") and not stale),
                                      round_id=round_id, scope_slide_ids=scope.get("slideIds", []))
            self.refresh_delivery_quality()
            return result

    def run_quality(self, auto_fix=True, round_id=None, scope_slide_ids=None, protected_objects=None):
        if type(auto_fix) is not bool or (round_id is not None and (not isinstance(round_id, str) or not round_id or len(round_id) > 160)):
            raise EngineError("INVALID_QUALITY_REQUEST", "质量检查参数无效。")
        if scope_slide_ids is not None and (not isinstance(scope_slide_ids, (list, tuple, set)) or any(not isinstance(x, str) for x in scope_slide_ids)):
            raise EngineError("INVALID_QUALITY_REQUEST", "检查范围必须为页面 ID 列表。")
        if protected_objects is not None and (not isinstance(protected_objects, dict) or any(not isinstance(v, (list, tuple, set)) or any(not isinstance(x, str) for x in v) for v in protected_objects.values())):
            raise EngineError("INVALID_QUALITY_REQUEST", "保护对象必须按页面提供对象 ID 列表。")
        with self.wb.atomic() as db:
            _, current, _ = self._quality_current()
            existing_ids = {s["slideId"] for s in current}
            scope = existing_ids if scope_slide_ids is None else set(scope_slide_ids)
            if scope - existing_ids:
                raise EngineError("QUALITY_PAGE_NOT_FOUND", "质量修正范围包含没有实际页面的 ID。")
            if auto_fix:
                auto_fix, scope = self._quality_repair_authority(db, round_id, scope)
            protection = {item["slideId"]: sorted(self._quality_protected(item, protected_objects)) for item in current}
            for _ in range(MAX_REPAIR_PASSES if auto_fix else 0):
                did_fix = False
                for before in current:
                    sid = before["slideId"]
                    if sid not in scope or before["stale"]:
                        continue
                    count = db.execute("SELECT COUNT(*) FROM studio_quality_fixes WHERE project_id=? AND slide_id=? AND round_id=?", (self.project_id, sid, round_id or "standalone")).fetchone()[0]
                    if count >= MAX_REPAIRS_PER_PAGE_ROUND:
                        continue
                    measurement = self._quality_measurement(db, before)
                    changes = propose_safe_repairs(before["scene"], measurement, protection.get(sid, ()))
                    if not changes:
                        continue
                    with self._operation(generation=True, description="自动版式修正：扩展文字框可用高度", round_id=round_id, automatic=True):
                        after = self.change_scene(sid, before["sceneRevision"], changes)
                    db.execute("INSERT INTO studio_quality_fixes VALUES (?,?,?,?,?,?,?,?)", ("QF-" + uuid.uuid4().hex, self.project_id, round_id or "standalone", sid,
                               before["sceneRevision"], after["sceneRevision"], _json(changes), _now()))
                    did_fix = True
                _, current, _ = self._quality_current()
                if not did_fix:
                    break
            snapshot, current, missing = self._quality_current()
            issues, pages, pending, measured_count = [], [], [], 0
            for item in current:
                sid = item["slideId"]
                measurement = self._quality_measurement(db, item)
                measured = bool(measurement and measurement["fontsReady"] and measurement["imagesLoaded"])
                found = audit_scene(item["scene"], measurement)
                if item["stale"]:
                    found.append(_issue("STALE_PAGE", "页面预览未对应最新内容，不能完成当前版式检查。", sid, severity="error"))
                if measured:
                    measured_count += 1
                else:
                    pending.append(sid)
                issues.extend(found)
                pages.append({"slideId": sid, "sceneRevision": item["sceneRevision"], "status": "needs_attention" if any(i["severity"] == "error" for i in found) else "measured" if measured else "awaiting_browser",
                              "measured": measured, "issues": found})
            for item in missing:
                found = _issue("PAGE_NOT_RENDERED", "这一页尚未生成实际预览。", item["slideId"], severity="error")
                issues.append(found)
                pending.append(item["slideId"])
                pages.append({"slideId": item["slideId"], "sceneRevision": None, "status": "needs_attention", "measured": False, "issues": [found]})
            deck = self._deck_row(db)
            unfinished = db.execute("SELECT COUNT(*) FROM studio_deck_pages WHERE deck_id=? AND status!='complete'", (deck["id"],)).fetchone()[0] if deck else 0
            if unfinished:
                issues.append(_issue("DECK_INCOMPLETE", "整稿计划尚未全部生成。", None, severity="error"))
            if not current:
                issues.append(_issue("NO_RENDERED_PAGES", "还没有可检查的页面。", None, severity="error"))
            groups = {}
            for item in current:
                scene = item["scene"]
                title = next((o for o in scene["objects"] if o["id"] == "title" and o["type"] == "text"), None)
                if title:
                    groups.setdefault(scene.get("templateId", "custom"), []).append((scene["slideId"], title))
            for template, group in groups.items():
                if len(group) < 2 or template == "custom":
                    continue
                sizes = {g[1]["fontSize"] for g in group}
                if max(sizes) - min(sizes) > 4:
                    issues.append(_issue("TITLE_STYLE_VARIATION", "同类页面的标题字号存在差异，请确认这是有意设计。", None, [sid + "/title" for sid, _ in group], basis="deck-comparison"))
            blockers = [i for i in issues if i["severity"] == "error"]
            status = "needs_attention" if blockers else "awaiting_browser" if pending else "ready_to_review"
            fixes = db.execute("SELECT * FROM studio_quality_fixes WHERE project_id=? ORDER BY created_at,rowid", (self.project_id,)).fetchall()
            state = {"status": status, "readyToReview": status == "ready_to_review", "humanAccepted": self._quality_human_accepted(snapshot["pages"]),
                     "semanticStatus": "operator_review_required", "checkedAt": _now(), "roundId": round_id,
                     "repairPolicy": {"autoFix": auto_fix, "slideIds": sorted(scope), "protectedObjects": protection},
                     "snapshot": snapshot, "snapshotKey": _hash(snapshot), "pages": pages, "issues": issues,
                     "blockerCount": len(blockers), "warningCount": len(issues) - len(blockers),
                     "browser": {"measured": measured_count, "total": len(snapshot["pages"]), "pendingSlideIds": pending},
                     "fixes": [{"slideId": r["slide_id"], "roundId": None if r["round_id"] == "standalone" else r["round_id"],
                                "beforeRevision": r["before_revision"], "afterRevision": r["after_revision"], "changes": json.loads(r["changes"]), "createdAt": r["created_at"]} for r in fixes],
                     "note": "这里只检查可计算的版式问题和浏览器上报的布局；内容事实、表达与审美仍需查看实际页面判断。"}
            db.execute("INSERT INTO studio_quality_runs VALUES (?,?,?,?,?,?,?)", ("Q-" + uuid.uuid4().hex, self.project_id, round_id, _hash(snapshot), _json(snapshot), _json(state), _now()))
            self._touch(db)
            return state

    def record_browser_measurements(self, slide_id, scene_revision, report):
        if type(scene_revision) is not int or scene_revision < 1:
            raise EngineError("INVALID_QUALITY_REPORT", "测量必须绑定明确的页面版本。")
        with self.wb.atomic() as db:
            current = self.get_scene(slide_id)
            if current["sceneRevision"] != scene_revision or current["stale"]:
                raise EngineError("QUALITY_STALE_REPORT", "测量来自旧页面或旧内容，未用于当前版本。")
            normalized = validate_browser_report(current["scene"], report)
            row = db.execute("SELECT report FROM studio_quality_measurements WHERE project_id=? AND slide_id=? AND scene_revision=?", (self.project_id, slide_id, scene_revision)).fetchone()
            unchanged = row is not None and json.loads(row["report"]) == normalized
            if not unchanged:
                db.execute("INSERT OR REPLACE INTO studio_quality_measurements VALUES (?,?,?,?,?,?)", (self.project_id, slide_id, scene_revision, _hash(current["scene"]), _json(normalized), _now()))
            latest = db.execute("SELECT round_id,snapshot_key,report FROM studio_quality_runs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (self.project_id,)).fetchone()
            round_id = latest["round_id"] if latest else None
            current_round = db.execute("SELECT id FROM studio_delivery_rounds WHERE project_id=? ORDER BY number DESC LIMIT 1", (self.project_id,)).fetchone()
            policy_is_current = round_id == (current_round["id"] if current_round else None)
            # Identical repeats do not make an unbounded run/fix history.
            state = self.quality_state()
            if not unchanged or state["status"] in {"stale", "not_checked"} or not policy_is_current:
                policy = json.loads(latest["report"]).get("repairPolicy", {}) if latest else {}
                allowed = set(policy.get("slideIds", []))
                auto_fix = policy.get("autoFix") is True
                if state["status"] == "stale" or not policy_is_current:
                    # A newer external/user change has not been checked under
                    # this policy. Even a submission with unchanged geometry
                    # supersedes the old mandate and its baseline must survive.
                    auto_fix, allowed = False, set()
                round_id = current_round["id"] if current_round else None
                delivery_scope = getattr(self, "delivery_auto_fix_scope", None)
                if callable(delivery_scope) and round_id is not None:
                    delivery = delivery_scope(round_id) or {}
                    auto_fix = auto_fix and delivery.get("autoFix") is True
                    allowed &= set(delivery.get("slideIds", []))
                state = self.run_quality(auto_fix=auto_fix, round_id=round_id, scope_slide_ids=sorted(allowed),
                                         protected_objects=policy.get("protectedObjects"))
            refresh = getattr(self, "refresh_delivery_quality", None)
            if callable(refresh):
                refresh()
            return {"accepted": True, "deduplicated": unchanged, "slideId": slide_id, "sceneRevision": scene_revision, "quality": state}
