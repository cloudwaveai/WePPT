"""Chat, durable jobs and editable page scenes shared by the browser, CLI and MCP."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .core import EngineError, Workbench, _now, _json, _hash
from .rendering import validate_scene, render_html, scene_from_slide, patch_scene, edit_scene_objects, export_pptx, export_html_deck, MAX_IMAGE_BYTES
from .deck_flow import DeckFlow, WAITING_CODES
from .delivery import DeliveryFlow
from .quality import QualityFlow
from .templates import apply_template, catalog, recommend_templates, template_for_role
from .local_renderer import scene_from_slide as local_scene_from_slide


def fail(code, message, details=None):
    raise EngineError(code, message, details)


class _ActionRevisionMismatch(EngineError):
    """A model action used the wrong revision after the job baselines passed."""


class _ActionSceneTargetMismatch(EngineError):
    """A replacement scene disagrees with its already authorized action target."""


class Studio(DeliveryFlow, QualityFlow, DeckFlow):
    def __init__(self, root, project_id="main", agent=None, create=True):
        self.wb = Workbench(root)
        self.root = self.wb.root
        self.project_id = self.wb._project_id(project_id)
        from .document_editing import initialize as initialize_document_editing
        initialize_document_editing(self)
        from .background_tasks import initialize as initialize_background_tasks
        initialize_background_tasks(self)
        if agent not in {None, "manual", "claude", "codex", "outline", "api"}:
            fail("INVALID_AGENT", "请选择 manual、claude、codex 或 outline。")
        try:
            self.wb.get_project(project_id)
        except EngineError as exc:
            if not create or exc.code != "PROJECT_NOT_FOUND":
                raise
            self.wb.create_project(project_id, {"title": "新演示文稿"})
        with self.wb._connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS studio_state (
                project_id TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1,
                selected_slide_id TEXT, demo INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS studio_pack_bindings (
                project_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL, sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_pack_preferences (
                project_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_template_preferences (
                project_id TEXT PRIMARY KEY, template_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_image_preferences (
                project_id TEXT PRIMARY KEY, mode TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_palette_preferences (
                project_id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_palette_applied (
                project_id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_user_templates (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
                body TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_style_preferences (
                project_id TEXT PRIMARY KEY, template_id TEXT);
            CREATE TABLE IF NOT EXISTS studio_project_logos (
                project_id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_derived_projects (
                project_id TEXT PRIMARY KEY, source_project_id TEXT NOT NULL,
                mode TEXT NOT NULL, audience TEXT, style_id TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_scenes (
                project_id TEXT NOT NULL, slide_id TEXT NOT NULL, revision INTEGER NOT NULL,
                content_revision INTEGER NOT NULL, body TEXT NOT NULL, paths TEXT NOT NULL,
                changes TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(project_id,slide_id,revision));
            CREATE TABLE IF NOT EXISTS studio_messages (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, role TEXT NOT NULL,
                text TEXT NOT NULL, slide_id TEXT, status TEXT NOT NULL, extras TEXT NOT NULL,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, client_message_id TEXT NOT NULL,
                message_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id,client_message_id));
            CREATE TABLE IF NOT EXISTS studio_assets (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, filename TEXT NOT NULL,
                mime TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL, excerpt TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
        self._init_deck_flow(agent)
        from .model_profiles import initialize as initialize_models
        initialize_models(self)
        self._init_quality()
        self._init_delivery()
        from .editor import initialize
        initialize(self)
        from .template_adaptation import initialize as initialize_template_adaptation
        initialize_template_adaptation(self)
        from .image_generation import ImageJobs
        ImageJobs(self)
        with self.wb.atomic() as db:
            db.execute("INSERT OR IGNORE INTO studio_state(project_id) VALUES (?)", (project_id,))
            if not db.execute("SELECT 1 FROM studio_messages WHERE project_id=?", (project_id,)).fetchone():
                self._message(db, "assistant", "粘贴演示大纲即可开始。连接 Claude Code 或 Codex 后可逐页生成整套初稿，缺少的资料会标为占位；选择本地大纲排版模式时，可输入“按大纲排版”和完整逐页文字。")

    def _touch(self, db, selected=None):
        db.execute("UPDATE studio_state SET version=version+1 WHERE project_id=?", (self.project_id,))
        if selected is not None:
            db.execute("UPDATE studio_state SET selected_slide_id=? WHERE project_id=?", (selected, self.project_id))

    def _message(self, db, role, text, slide_id=None, status="complete", **extras):
        if role == "assistant" and not extras.get("isRoundOutput"):
            op = getattr(self._operation_local, "current", None) or {}
            job_id = extras.get("jobId") or op.get("jobId")
            rid = extras.get("roundId") or op.get("roundId") or (self._round_for_job(db, job_id) if job_id else None)
            if rid:
                extras.setdefault("roundId", rid)
                extras.setdefault("internalProgress", True)
        mid = "M-" + uuid.uuid4().hex
        db.execute("INSERT INTO studio_messages VALUES (?,?,?,?,?,?,?,?)",
                   (mid, self.project_id, role, str(text), slide_id, status, _json(extras), _now()))
        self._touch(db)
        return mid

    def _latest_scene(self, db, slide_id):
        row = db.execute("SELECT * FROM studio_scenes WHERE project_id=? AND slide_id=? ORDER BY revision DESC LIMIT 1",
                         (self.project_id, slide_id)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _scene_integrity_issues(page):
        # A project logo missing at registration is a release issue, but does
        # not make the generated scene stale. All other integrity issues do.
        issues = page.get("integrityIssues", [])
        declared_missing = (page.get("artifact") or {}).get("materialIssues", [])
        return [issue for index, issue in enumerate(issues) if not (
            index < len(declared_missing) and issue.get("code") == "MATERIAL_UNAVAILABLE"
            and (issue.get("kind") == "logo" and issue.get("id") == "project-logo"
                 or issue.get("message", "").startswith("logo project-logo 在产物登记时")))]

    def get_scene(self, slide_id):
        with self.wb.atomic() as db:
            page = self.wb.get_slide(self.project_id, slide_id)
            row = self._latest_scene(db, slide_id)
            if row is None:
                fail("SCENE_MISSING", "本页还没有可编辑预览，请先生成当前页。")
            return {"projectId": self.project_id, "slideId": slide_id, "sceneRevision": row["revision"],
                    "contentRevision": page["revision"], "renderedContentRevision": row["content_revision"],
                    "stale": row["content_revision"] != page["revision"] or page["artifact"] is None or bool(self._scene_integrity_issues(page)),
                    "scene": json.loads(row["body"]), "changes": json.loads(row["changes"]),
                    "paths": json.loads(row["paths"]), "previewUrl": f"/api/preview/{slide_id}?project={self.project_id}&rev={row['revision']}"}

    def state(self):
        from .agent_bridge import diagnose
        from .image_generation import ImageJobs
        from . import background_tasks, document_editing, presentation_import
        ImageJobs(self)
        with self.wb.atomic() as db:
            project = self.wb.get_project(self.project_id)
            meta = db.execute("SELECT * FROM studio_state WHERE project_id=?", (self.project_id,)).fetchone()
            slides = []
            for page in project["workspace"]["slides"]:
                if page["archived"]:
                    continue
                row = self._latest_scene(db, page["id"])
                page_view = self.wb.get_slide(self.project_id, page["id"])
                slides.append({"id": page["id"], "title": page["title"], "role": page.get("role", "content"), "revision": page["revision"],
                    "sceneRevision": row["revision"] if row else 0, "hasPreview": row is not None,
                    "sceneTemplateId": json.loads(row["body"]).get("templateId") if row else None,
                    "hasDiagram": bool(row and json.loads(row["body"]).get("diagram")),
                    "reviewedSceneRevision": row["revision"] if row and page_view["reviews"]["visual"] else None,
                    "stale": bool(row and (row["content_revision"] != page["revision"] or page_view["artifact"] is None or self._scene_integrity_issues(page_view))),
                    "previewContentStale": bool(row and row["content_revision"] != page["revision"]),
                    "previewMaterialUnavailable": bool(row and any(issue.get("code") == "MATERIAL_UNAVAILABLE" for issue in page_view.get("integrityIssues", []))),
                    "previewUrl": f"/api/preview/{page['id']}?project={self.project_id}&rev={row['revision']}" if row else None})
            selected = meta["selected_slide_id"] or project["workspace"].get("selectedSlideId")
            if selected not in {s["id"] for s in slides}:
                selected = slides[0]["id"] if slides else None
            rows = db.execute("SELECT * FROM studio_messages WHERE project_id=? ORDER BY created_at,id", (self.project_id,)).fetchall()
            messages = [{"id": r["id"], "role": r["role"], "text": r["text"], "status": r["status"],
                         "pageId": r["slide_id"], "createdAt": r["created_at"], **json.loads(r["extras"])} for r in rows]
            jobs = db.execute("SELECT id,status,message_id,created_at,payload FROM studio_jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 20", (self.project_id,)).fetchall()
            event = db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE project_id=?", (self.project_id,)).fetchone()[0]
            assets = db.execute("SELECT id AS assetId,filename,mime,bytes FROM studio_assets WHERE project_id=? ORDER BY created_at", (self.project_id,)).fetchall()
            image_batches = db.execute("""SELECT b.id,b.slide_id,b.status,b.created_at,
                (SELECT COUNT(*) FROM image_generation_jobs j WHERE j.project_id=b.project_id
                    AND substr(j.request_id,1,length(b.id)+1)=b.id||':' AND j.asset_id IS NOT NULL) AS generatedCount,
                (SELECT COUNT(*) FROM image_generation_jobs j WHERE j.project_id=b.project_id
                    AND substr(j.request_id,1,length(b.id)+1)=b.id||':') AS totalCount,
                (SELECT e.code FROM image_generation_jobs j JOIN image_generation_errors e ON e.job_id=j.id
                    WHERE j.project_id=b.project_id AND substr(j.request_id,1,length(b.id)+1)=b.id||':' LIMIT 1) AS errorCode
                FROM image_generation_batches b WHERE b.project_id=? ORDER BY b.created_at DESC LIMIT 20""", (self.project_id,)).fetchall()
            # Page lists, completed rounds and their quality must describe one
            # committed state. A worker can otherwise finish more pages between
            # the old list read and a newer delivery_state read below the lock.
            deck_state = self.deck_state()
            delivery_state = self.delivery_state()
            quality_state = self.quality_state()
            document_history = document_editing.history(self)
            background_state = background_tasks.state(self)
            palette_state = self.palette()
        return {"projectId": self.project_id, "projectRevision": project["revision"],
                "importSource": presentation_import.source_info(self),
                "backgroundTasks": background_state,
                "documentHistory": document_history,
                "project": project["workspace"]["project"], "slides": slides,
                "selectedSlideId": selected, "messages": messages, "jobs": [{k:j[k] for k in ('id','status','message_id','created_at')} | {"slideId": json.loads(j['payload']).get('slideId')} for j in jobs],
                "assets": [dict(a) for a in assets], "imageBatches": [dict(b) for b in image_batches], "agent": diagnose(self.agent_mode), "demo": bool(meta["demo"]),
                "version": int(meta["version"]) + int(event), "deck": deck_state,
                "delivery": delivery_state, "quality": quality_state,
                "selectedTemplateId": self.selected_template(), "imageMode": self.image_mode(), "imageModeLocked": self.image_mode_locked(),
                "palette": palette_state, "palettePresets": self.palette_presets(),
                "styleReference": self._style_reference_public(),
                "logo": self._logo_public(), "derivedFrom": self._derived_from(),
                **self.model_state()}

    def model_state(self):
        from .model_profiles import public_state
        return public_state(self)

    def selected_template(self):
        with self.wb._connection() as db:
            row = db.execute("SELECT template_id FROM studio_template_preferences WHERE project_id=?",
                             (self.project_id,)).fetchone()
            return row["template_id"] if row else None

    @staticmethod
    def image_mode_locked():
        """WEPPT_AUTO_IMAGES=off is a server-wide hard switch over every project setting."""
        return os.environ.get("WEPPT_AUTO_IMAGES", "auto").strip().lower() in {"off", "0", "false", "no"}

    def image_mode(self):
        """Auto illustration for finished decks: on unless the server or the project turns it off."""
        if self.image_mode_locked():
            return "off"
        with self.wb._connection() as db:
            row = db.execute("SELECT mode FROM studio_image_preferences WHERE project_id=?", (self.project_id,)).fetchone()
        return row["mode"] if row else "auto"

    def set_image_mode(self, mode):
        if mode not in {"auto", "off"}:
            fail("INVALID_IMAGE_MODE", "自动配图只能设为 auto 或 off。")
        if mode == "auto" and self.image_mode_locked():
            fail("IMAGE_MODE_LOCKED", "服务器已关闭自动配图，项目内不能单独开启。")
        with self.wb.atomic() as db:
            db.execute("INSERT OR REPLACE INTO studio_image_preferences VALUES (?,?)", (self.project_id, mode))
            self._touch(db)
        return self.state()

    def palette(self):
        from .palette import palette
        return palette(self)

    @staticmethod
    def palette_presets():
        from .palette import PALETTE_PRESETS
        return PALETTE_PRESETS

    def set_palette(self, value):
        from .palette import set_palette
        set_palette(self, value)
        return self.state()

    def apply_palette(self, scope="page", slide_id=None, scene_revision=None, palette_value=None, project_revision=None):
        from .palette import apply_palette
        return apply_palette(self, scope, slide_id, scene_revision, palette_value, project_revision)

    def select_template(self, template_id, slide_id=None, scene_revision=None):
        if not isinstance(template_id, str) or template_id not in {t["id"] for t in catalog()}:
            fail("UNKNOWN_TEMPLATE", "未找到视觉模板。")
        with self.wb.atomic() as db:
            result = {"projectId": self.project_id}
            if slide_id is not None:
                current = self.get_scene(slide_id)
                self.wb._revision(current["sceneRevision"], scene_revision)
                if current["stale"]:
                    fail("SCENE_STALE", "内容或预览完整性已变化，请先重新生成预览。")
                selected = db.execute("SELECT selected_slide_id FROM studio_state WHERE project_id=?", (self.project_id,)).fetchone()[0]
                from .editor import _history, _save_history
                undo, _ = _history(self, db, slide_id, current["sceneRevision"])
                result = self.put_scene(slide_id, current["contentRevision"],
                                        apply_template(current["scene"], template_id), "手动应用视觉模板：" + template_id)
                undo.append({"before": current["scene"], "after": result["scene"]})
                _save_history(self, db, slide_id, result["sceneRevision"], undo, [])
                db.execute("UPDATE studio_state SET selected_slide_id=? WHERE project_id=?", (selected, self.project_id))
            db.execute("INSERT INTO studio_template_preferences VALUES (?,?) "
                       "ON CONFLICT(project_id) DO UPDATE SET template_id=excluded.template_id",
                       (self.project_id, template_id))
            self._touch(db)
            return result | {"selectedTemplateId": template_id}

    def preview_template(self, template_id, slide_id=None, scene_revision=None):
        """Render a candidate against a captured revision without changing the project."""
        from .templates import sample_scene
        if slide_id is None:
            return {"scene": sample_scene(template_id), "slideId": None, "sceneRevision": None}
        with self.wb.atomic():
            current = self.get_scene(slide_id)
            self.wb._revision(current["sceneRevision"], scene_revision)
            if current["stale"]:
                fail("SCENE_STALE", "内容已变化，请先重新生成预览。")
            return {"scene": apply_template(current["scene"], template_id),
                    "slideId": slide_id, "sceneRevision": current["sceneRevision"]}

    def edit_scene(self, slide_id, scene_revision, changes):
        from .editor import edit
        return edit(self, slide_id, scene_revision, changes)

    def select(self, slide_id):
        with self.wb.atomic() as db:
            self.wb.get_slide(self.project_id, slide_id)
            self._touch(db, slide_id)
        return {"selectedSlideId": slide_id}

    @staticmethod
    def scene_diff(before, after):
        old = {o["id"]: o for o in (before or {}).get("objects", [])}
        new = {o["id"]: o for o in after["objects"]}
        changes = []
        if before:
            old_order = [o["id"] for o in before.get("objects", [])]
            new_order = [o["id"] for o in after["objects"]]
            if old_order != new_order:
                changes.append({"objectId": "page", "label": "objectOrder", "before": old_order, "after": new_order})
        for field in ("background", "templateId"):
            if before and before.get(field) != after.get(field):
                changes.append({"objectId": "page", "label": field, "before": before.get(field), "after": after.get(field)})
        for oid in sorted(old.keys() | new.keys()):
            a, b = old.get(oid), new.get(oid)
            if a == b:
                continue
            fields = sorted(k for k in (a or {}).keys() | (b or {}).keys() if (a or {}).get(k) != (b or {}).get(k))
            changes.append({"objectId": oid, "label": oid, "fields": fields,
                            "before": {k: a.get(k) for k in fields} if a else None,
                            "after": {k: b.get(k) for k in fields} if b else None})
        return changes

    def _resolve_images(self, scene):
        if not isinstance(scene, dict):
            fail("INVALID_SCENE", "页面场景必须是 JSON 对象。")
        result = copy.deepcopy(scene)
        for obj in result.get("objects", []):
            if obj.get("type") == "image" and str(obj.get("src", "")).startswith("scene-image:"):
                ref = obj["src"][12:]
                parts = ref.split("/", 1)
                if len(parts) != 2:
                    fail("INVALID_IMAGE_REFERENCE", "页面图片引用无效。")
                with self.wb._connection() as db:
                    existing = self._latest_scene(db, parts[0])
                if existing is None:
                    fail("INVALID_IMAGE_REFERENCE", "引用的页面图片不存在。")
                found = next((o for o in json.loads(existing["body"])["objects"] if o["id"] == parts[1] and o["type"] == "image"), None)
                if found is None:
                    fail("INVALID_IMAGE_REFERENCE", "引用的图片对象不存在。")
                obj["src"] = found["src"]
            if obj.get("type") == "image" and str(obj.get("src", "")).startswith("asset:"):
                asset = self.asset(obj["src"][6:])
                if asset["mime"] not in {"image/png", "image/jpeg"}:
                    fail("INVALID_IMAGE", "页面图片只接受 PNG 或 JPEG。")
                data = (self.wb.project_dir(self.project_id) / asset["path"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                    fail("ASSET_CHANGED", "上传素材已改变，请重新上传。")
                obj["src"] = "data:" + asset["mime"] + ";base64," + base64.b64encode(data).decode()
        return result

    def put_scene(self, slide_id, base_revision, scene, summary="更新当前页预览", *, preserve_layout=False):
        normalized = validate_scene(self._resolve_images(scene))
        if normalized["slideId"] != slide_id:
            fail("SCOPE_VIOLATION", "场景 slideId 必须与目标页一致。")
        with self.wb.atomic() as db:
            page = self.wb.get_slide(self.project_id, slide_id)
            self.wb._revision(page["revision"], base_revision)
            previous = self._latest_scene(db, slide_id)
            if previous is None and not preserve_layout and not normalized.get("diagram") and self.selected_template() and normalized.get("templateId") != self.selected_template():
                chosen = template_for_role(self.selected_template(), self.wb.get_slide(self.project_id, slide_id)["slide"].get("role", "content"))
                if normalized.get("templateId") != chosen:
                    normalized = apply_template(normalized, chosen)
            before = json.loads(previous["body"]) if previous else None
            diff = self.scene_diff(before, normalized)
            if previous and not diff and previous["content_revision"] == page["revision"] and page["artifact"] is not None and not page.get("integrityIssues"):
                return self.get_scene(slide_id) | {"changes": [], "unchanged": True}
            revision = (previous["revision"] if previous else 0) + 1
            content_changes = [{"path": "/changeRequest", "value": {
                "baseRevision": base_revision, "targetType": "whole-slide", "targetId": slide_id,
                "operation": "layout", "change": summary, "keep": "其他页面保持原样", "acceptance": "查看当前场景与预览"}}]
            bound_points = {}
            for obj in normalized["objects"]:
                if obj["type"] != "text":
                    continue
                binding = obj.get("binding", obj["id"] if obj["id"] in {"title", "takeaway"} else "")
                if binding in {"title", "takeaway"} and obj["text"] != page["slide"].get(binding):
                    content_changes.append({"path": "/" + binding, "value": obj["text"]})
                elif binding.startswith("keyPoints:"):
                    bound_points[int(binding.split(":", 1)[1])] = obj["text"]
            if bound_points:
                points = normalized.get("bindingSeparator", "\n").join(bound_points[i] for i in sorted(bound_points))
                if points != page["slide"]["keyPoints"]:
                    content_changes.append({"path": "/keyPoints", "value": points})
            page = self.wb.patch_slide(self.project_id, slide_id, base_revision, content_changes, summary)
            directory = self.wb.project_dir(self.project_id) / "studio" / slide_id / (f"r{revision:04d}-" + uuid.uuid4().hex[:10])
            directory = self.wb._inside(directory, self.wb.project_dir(self.project_id))
            directory.mkdir(parents=True)
            source = directory / "scene.json"
            preview = directory / "preview.html"
            objects = directory / "objects.json"
            source.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            preview.write_text(render_html(normalized, interactive=True), encoding="utf-8")
            objects.write_text(json.dumps({"slideId": slide_id, "renderer": "ppt-workbench-scene-v1", "objects": [
                {"id": o["id"], "type": o["type"], "selector": "[data-object-id=\"" + o["id"] + "\"]"} for o in normalized["objects"]]}, ensure_ascii=False), encoding="utf-8")
            paths = {"source": str(source), "preview": str(preview), "objects": str(objects)}
            db.execute("INSERT INTO studio_scenes VALUES (?,?,?,?,?,?,?,?)", (
                self.project_id, slide_id, revision, page["revision"], _json(normalized), _json(paths), _json(diff), _now()))
            self.wb.register_artifact(self.project_id, slide_id, page["revision"], str(source), str(preview), str(objects))
            if diff:
                self._record_deck_revision(db, slide_id, previous["revision"] if previous else None, revision, summary)
                self._round_changed(db, slide_id)
            self._touch(db, slide_id)
            return self.get_scene(slide_id)

    def generate_scene(self, slide_id, base_revision=None):
        with self.wb.atomic():
            project = self.wb.get_project(self.project_id)
            page = self.wb.get_slide(self.project_id, slide_id)
            if base_revision is not None:
                self.wb._revision(page["revision"], base_revision)
            with self.wb._connection() as db:
                previous = self._latest_scene(db, slide_id)
            chosen = json.loads(previous["body"]).get("templateId") if previous else self.selected_template()
            tid = page["slide"].get("templateId")
            entries = {t["id"]: t for t in catalog()}
            if chosen in entries:
                chosen = template_for_role(chosen, page["slide"].get("role", "content"))
            opening_defaults = {"cover": "opening-02-01-cover", "toc": "opening-04-02-toc", "chapter": "opening-05-02-chapter"}
            layout_id = chosen or tid or opening_defaults.get(page["slide"].get("role")) or "claim-proof"
            template = {"id": layout_id} if layout_id else None
            numeric_shells = {"kpi-hero", "case-scorecard", "landscape-path", "table-rising-bars", "market-path"}
            if layout_id in entries and (entries[layout_id].get("opening") or entries[layout_id].get("sourceLabel") == "设计地图 · 原版布局"):
                content_layout = layout_id if layout_id in {"process", "timeline", "roadmap", "user-journey", "compare", "parallel"} else "toc"
                scene = scene_from_slide(page["slide"], project["workspace"]["project"], {"id": content_layout})
                scene = apply_template(scene, layout_id)
            elif layout_id in numeric_shells:
                scene = scene_from_slide(page["slide"], project["workspace"]["project"], {"id": "content"})
                scene = apply_template(scene, layout_id)
            else:
                scene = local_scene_from_slide(page["slide"], project["workspace"]["project"], template)
                if any(obj.get("type") == "text" and obj.get("opacity", 1) < 0.5 for obj in scene["objects"]):
                    scene = scene_from_slide(page["slide"], project["workspace"]["project"], {"id": "content"})
                    if layout_id in entries:
                        scene = apply_template(scene, layout_id)
            if chosen in entries and (entries[chosen].get("legacy") or entries[chosen].get("variantOf") or chosen in {"kpi-hero", "case-scorecard", "landscape-path", "table-rising-bars", "market-path"}):
                scene = apply_template(scene, chosen)
            return self.put_scene(slide_id, page["revision"], scene, "按本页内容生成可编辑预览")

    def change_scene(self, slide_id, base_scene_revision, changes, allowed_object_id=None):
        with self.wb.atomic():
            current = self.get_scene(slide_id)
            self.wb._revision(current["sceneRevision"], base_scene_revision)
            if current["stale"]:
                fail("SCENE_STALE", "内容已变化，请先重新生成对应内容的预览。")
            if allowed_object_id and any(c.get("objectId") != allowed_object_id for c in changes):
                fail("SCOPE_VIOLATION", "本次只允许修改选中的对象。")
            resolved_changes = copy.deepcopy(changes)
            for change in resolved_changes:
                properties = change.get("properties", {})
                if isinstance(properties, dict) and str(properties.get("src", "")).startswith(("asset:", "scene-image:")):
                    properties["src"] = self._resolve_images({"objects": [{"type": "image", "src": properties["src"]}]})["objects"][0]["src"]
            candidate = patch_scene(current["scene"], resolved_changes)
            return self.put_scene(slide_id, current["contentRevision"], candidate, "仅调整指定对象：" + ", ".join(c["objectId"] for c in changes))

    def change_scene_objects(self, slide_id, base_scene_revision, operations):
        with self.wb.atomic():
            current = self.get_scene(slide_id)
            self.wb._revision(current["sceneRevision"], base_scene_revision)
            if current["stale"]:
                fail("SCENE_STALE", "内容已变化，请先重新生成对应内容的预览。")
            resolved = copy.deepcopy(operations)
            for operation in resolved:
                if operation.get("op") == "add" and isinstance(operation.get("object"), dict):
                    operation["object"] = self._resolve_images({"objects": [operation["object"]]})["objects"][0]
            candidate = edit_scene_objects(current["scene"], resolved)
            return self.put_scene(slide_id, current["contentRevision"], candidate, "调整页面对象结构")

    def undo(self, slide_id, scene_revision, allowed_object_id=None):
        with self.wb.atomic() as db:
            current = self.get_scene(slide_id)
            self.wb._revision(current["sceneRevision"], scene_revision)
            prior = db.execute("SELECT body FROM studio_scenes WHERE project_id=? AND slide_id=? AND revision<? ORDER BY revision DESC LIMIT 1",
                               (self.project_id, slide_id, scene_revision)).fetchone()
            if prior is None:
                fail("NO_PREVIOUS_SCENE", "本页还没有可恢复的上一版预览。")
            previous_scene = json.loads(prior["body"])
            if allowed_object_id and any(c["objectId"] != allowed_object_id for c in self.scene_diff(current["scene"], previous_scene)):
                fail("SCOPE_VIOLATION", "上一版涉及其他对象；请先清除对象选择，再明确撤销整页。")
            result = self.put_scene(slide_id, current["contentRevision"], previous_scene, "恢复上一版页面，保留全部历史")
            self._message(db, "assistant", "已恢复这页的上一版预览，历史记录仍保留。", slide_id, changes=result["changes"])
            return result

    def review(self, slide_id, scene_revision, statement="已查看当前页面并认可这一版表达与版式"):
        with self.wb.atomic() as db:
            current = self.get_scene(slide_id)
            self.wb._revision(current["sceneRevision"], scene_revision)
            if current["stale"]:
                fail("SCENE_STALE", "当前预览对应旧内容，请更新后再认可。")
            self.wb.record_review(self.project_id, slide_id, current["contentRevision"], "content", statement, reviewer="local-browser-operator")
            result = self.wb.record_review(self.project_id, slide_id, current["contentRevision"], "visual", statement, reviewer="local-browser-operator")
            self._message(db, "assistant", "已记录你对当前页的认可。资料真实性仍按各条来源的核验记录处理。", slide_id)
            return result

    def asset(self, asset_id):
        with self.wb._connection() as db:
            row = db.execute("SELECT * FROM studio_assets WHERE project_id=? AND id=?", (self.project_id, asset_id)).fetchone()
        if not row:
            fail("ASSET_NOT_FOUND", "未找到该素材。")
        return dict(row)

    def upload(self, filename, mime, encoded):
        if not isinstance(filename, str) or not filename.strip() or len(filename) > 250:
            fail("INVALID_UPLOAD", "请提供有效文件名。")
        types = {"image/png": ".png", "image/jpeg": ".jpg", "text/plain": ".txt", "text/markdown": ".md", "application/pdf": ".pdf"}
        if mime not in types:
            # Browser File.type is often empty for Markdown.
            if filename.lower().endswith((".md", ".txt")):
                mime = "text/markdown" if filename.lower().endswith(".md") else "text/plain"
            else:
                fail("UNSUPPORTED_UPLOAD", "支持 PNG、JPEG、TXT、Markdown 和 PDF。")
        if not isinstance(encoded, str) or len(encoded) > 28_000_000:
            fail("UPLOAD_TOO_LARGE", "单个文件上限为 20 MB。")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            fail("INVALID_UPLOAD", "附件编码无效。")
        if not data or len(data) > 20 * 1024 * 1024:
            fail("UPLOAD_TOO_LARGE", "文件为空或超过 20 MB。")
        if mime.startswith("image/") and len(data) > MAX_IMAGE_BYTES:
            fail("UPLOAD_TOO_LARGE", "图片上限为 8 MB，请先压缩图片；其他附件上限为 20 MB。")
        magic = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff", "application/pdf": b"%PDF-"}
        if mime in magic and not data.startswith(magic[mime]):
            fail("INVALID_UPLOAD", "文件内容与声明格式不一致。")
        excerpt = ""
        if mime.startswith("text/"):
            try:
                excerpt = data.decode("utf-8-sig")
            except UnicodeError:
                fail("INVALID_UPLOAD", "文本附件需要 UTF-8 编码。")
            if len(excerpt) > 50_000:
                fail("UPLOAD_TOO_LARGE", "文本附件上限为 50,000 字，请拆分材料。")
        aid = "A-" + uuid.uuid4().hex
        target = self.wb._inside(self.wb.project_dir(self.project_id) / "uploads" / (aid + types[mime]), self.wb.project_dir(self.project_id))
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        relative = str(target.relative_to(self.wb.project_dir(self.project_id)))
        with self.wb.atomic() as db:
            db.execute("INSERT INTO studio_assets VALUES (?,?,?,?,?,?,?,?,?)", (aid, self.project_id, Path(filename).name, mime, relative,
                len(data), hashlib.sha256(data).hexdigest(), excerpt, _now()))
            self._touch(db)
        return {"assetId": aid, "filename": Path(filename).name, "mime": mime, "bytes": len(data), "reference": relative,
                "readStatus": "text-available" if excerpt else "file-registered", "note": "PDF 已登记；生成任务上下文时会尝试提取内容。" if mime == "application/pdf" else ""}

    def enqueue(self, message, slide_id=None, object_id=None, client_message_id=None, attachments=None,
                choice_message_id=None, reply_to_deck_page=False, scope="page", auto_resume=False):
        if not isinstance(message, str) or not message.strip() or len(message) > 30_000:
            fail("INVALID_MESSAGE", "请输入 1 到 30,000 字的消息。")
        attachments = attachments or []
        if not isinstance(attachments, list) or len(attachments) > 10:
            fail("INVALID_ATTACHMENTS", "每次最多附 10 个文件。")
        assets = [self.asset(a) for a in attachments]
        request_id = client_message_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or len(request_id) > 160:
            fail("INVALID_MESSAGE_ID", "消息标识无效。")
        if choice_message_id is not None and (not isinstance(choice_message_id, str) or not choice_message_id or len(choice_message_id) > 160):
            fail("INVALID_MESSAGE_ID", "问题消息标识无效。")
        if type(reply_to_deck_page) is not bool:
            fail("INVALID_REQUEST", "replyToDeckPage 必须为布尔值。")
        if scope not in {"page", "deck"} or type(auto_resume) is not bool:
            fail("INVALID_REQUEST", "scope 必须为 page/deck，autoResume 必须为布尔值。")
        if scope == "deck" and object_id:
            fail("QUESTION_SCOPE_MISMATCH", "整稿输入不能同时绑定一个页面对象，请先明确本次范围。")
        with self.wb.atomic() as db:
            existing = db.execute("SELECT id,status FROM studio_jobs WHERE project_id=? AND client_message_id=?", (self.project_id, request_id)).fetchone()
            if existing:
                return {"jobId": existing["id"], "status": existing["status"], "deduplicated": True,
                        "roundId": self._round_for_job(db, existing["id"])}
            if choice_message_id is not None or reply_to_deck_page:
                return self._capture_deck_answer(db, message, request_id, attachments, assets, choice_message_id, slide_id, object_id, auto_resume)
            selected = db.execute("SELECT * FROM studio_state WHERE project_id=?", (self.project_id,)).fetchone()
            slide_id = None if scope == "deck" else (slide_id or selected["selected_slide_id"])
            page = self.wb.get_slide(self.project_id, slide_id) if slide_id else None
            scene = self._latest_scene(db, slide_id) if slide_id else None
            if object_id:
                if not scene or object_id not in {o["id"] for o in json.loads(scene["body"])["objects"]}:
                    fail("OBJECT_NOT_FOUND", "选中的对象已不存在，请重新选择。")
            jid = "J-" + uuid.uuid4().hex
            mid = self._message(db, "user", message, slide_id, "queued", jobId=jid, objectId=object_id,
                                attachments=[{"assetId": a["id"], "filename": a["filename"], "mime": a["mime"]} for a in assets])
            project = self.wb.get_project(self.project_id)
            deck_baselines = {}
            for item in project["workspace"]["slides"]:
                if not item["archived"]:
                    saved_scene = self._latest_scene(db, item["id"])
                    deck_baselines[item["id"]] = {"contentRevision": item["revision"], "sceneRevision": saved_scene["revision"] if saved_scene else None}
            payload = {"message": message, "slideId": slide_id, "objectId": object_id,
                       "baseRevision": page["revision"] if page else None,
                       "baseSceneRevision": scene["revision"] if scene else None,
                       "projectRevision": project["revision"], "attachments": attachments,
                       "scope": scope, "deckBaselines": deck_baselines}
            from .model_profiles import selected as selected_model, resolve
            chosen = selected_model(self)
            if chosen:
                resolve(chosen)
                payload["modelBinding"] = chosen
            db.execute("INSERT INTO studio_jobs VALUES (?,?,?,?,?,?,?,?,?)", (jid, self.project_id, request_id, mid, "queued", _json(payload), None, _now(), _now()))
            round_id = self._begin_round(db, mid, message, jid)
            self._touch(db)
        if message.strip() in {"继续", "继续。", "继续！"} and not attachments and not object_id:
            with self.wb._connection() as db:
                candidates = db.execute("""SELECT DISTINCT r.id FROM studio_delivery_rounds r
                    JOIN studio_delivery_jobs b ON b.round_id=r.id
                    JOIN studio_feedback_pages f ON f.job_id=b.job_id
                    JOIN studio_jobs j ON j.id=f.job_id
                    WHERE r.project_id=? AND r.status='failed' AND (j.status='failed' OR EXISTS
                        (SELECT 1 FROM image_generation_batches ib WHERE ib.id=f.job_id AND ib.status IN ('failed','conflict','interrupted')
                         AND EXISTS (SELECT 1 FROM studio_feedback_pages later JOIN studio_jobs lj ON lj.id=later.job_id
                                     WHERE later.parent_job_id=f.parent_job_id AND later.position>f.position AND lj.status='queued')))""", (self.project_id,)).fetchall()
                deck = self._deck_row(db)
                competing_deck = bool(deck and deck["status"] in {"paused", "blocked", "running"})
                other_work = db.execute("""SELECT 1 FROM studio_jobs j WHERE j.project_id=?
                    AND j.id<>? AND j.status IN ('queued','running') AND NOT EXISTS
                    (SELECT 1 FROM studio_feedback_pages f WHERE f.job_id=j.id) LIMIT 1""", (self.project_id, jid)).fetchone()
            if len(candidates) == 1 and not competing_deck and not other_work:
                with self.wb._connection() as db:
                    failed_jobs = any(j['status'] == 'failed' for j in self._round_jobs(db, candidates[0]['id']))
                if failed_jobs:
                    self.control_delivery("retry", candidates[0]["id"])
                    reply = "已继续之前中断的整稿反馈，已完成的页面会保留。"
                else:
                    self.control_delivery("continue_without_images", candidates[0]["id"])
                    reply = "已跳过失败的图片任务并继续后续页面；原有图片保留，图片失败仍需单独处理。"
                self.apply_plan(jid, {"reply": reply, "actions": []})
                return {"jobId": jid, "status": self.job(jid)["status"], "roundId": round_id}
            if candidates:
                self.apply_plan(jid, {"reply": "有多个可能需要继续的任务，请先指定。", "actions": [],
                                      "questions": [{"question": "要继续哪一轮反馈或整稿任务？", "choices": []}]})
                return {"jobId": jid, "status": self.job(jid)["status"], "roundId": round_id}
        from .outline import parse_outline
        try:
            outline = parse_outline(message) if self.agent_mode in {"manual", "outline"} else None
            if outline:
                if object_id:
                    fail("SCOPE_VIOLATION", "已选中对象时只能调整该对象，请先清除对象选择再创建整稿。")
                with self.wb._connection() as db:
                    intake = self._intake_from_round(db, mid, len(outline["pages"]))
                actions = ([{"type": "project_update", "changes": intake["projectChanges"]}] if intake["projectChanges"] else []) + [{"type": "deck_start", **outline}]
                reply = "已收到你提供的完整大纲，接下来按页生成真实预览。"
                if intake["warnings"]:
                    reply += "\n" + "\n".join(intake["warnings"])
                self.apply_plan(jid, {"reply": reply, "actions": actions})
                return {"jobId": jid, "status": self.job(jid)["status"], "deck": self.deck_state(), "roundId": round_id}
            from .intake import is_intake_metadata_message, parse_intake_metadata
            from .feedback import parse_feedback_with_intake
            if scope == "deck":
                current_pages = self.wb.get_project(self.project_id)["workspace"]["slides"]
                combined = parse_feedback_with_intake(message, [{"id": p["id"], "title": p["title"]} for p in current_pages if not p["archived"]])
                if combined:
                    self._apply_intake_submission(jid, combined["intake"], combined["feedback"])
                    return {"jobId": jid, "status": self.job(jid)["status"], "roundId": round_id}
            if is_intake_metadata_message(message):
                with self.wb._connection() as db:
                    count = len(self._intake_page_map(db))
                intake = parse_intake_metadata(message, page_count=count)
                self._apply_intake_submission(jid, intake)
                return {"jobId": jid, "status": self.job(jid)["status"], "roundId": round_id}
            from .feedback import parse_feedback
            pages = self.wb.get_project(self.project_id)["workspace"]["slides"]
            feedback = parse_feedback(message, [{"id": p["id"], "title": p["title"]} for p in pages if not p["archived"]])
            if feedback:
                if object_id:
                    fail("SCOPE_VIOLATION", "已选中对象时不能执行整稿反馈。请先清除对象选择。")
                with self.wb.atomic() as db:
                    payload = self.job(jid)["payload"]
                    payload.update(slideId=None, objectId=None, baseRevision=None, baseSceneRevision=None, scope="deck")
                    db.execute("UPDATE studio_jobs SET payload=? WHERE id=?", (_json(payload), jid))
                self.apply_plan(jid, {"reply": "已将本轮反馈分派到指定页面，正在逐页执行。", "actions": [feedback]})
                return {"jobId": jid, "status": self.job(jid)["status"], "roundId": round_id}
        except EngineError as exc:
            self.fail_job(jid, exc)
            return {"jobId": jid, "status": "failed", "roundId": round_id}
        if message.strip() in {"检查整稿", "检查当前稿", "查看整稿结果", "导出当前稿"} and scope == "deck":
            self.apply_plan(jid, {"reply": "已重新检查当前整套页面。可以通过导出入口下载当前稿件；自动检查不代表资料真实性或人工审美已通过。", "actions": []})
        local_deck = self.deck_state()
        if self.agent_mode in {"manual", "outline"} and (selected["demo"] or (local_deck and local_deck["execution"] == "outline")):
            self._demo_command(jid, payload)
        if self.agent_mode == "outline" and self.job(jid)["status"] == "queued":
            self.apply_plan(jid, {"reply": "当前为本地大纲排版，不调用模型。可以输入“按大纲排版”及完整逐页内容，或选中文字后输入“文字改为：…”；这条要求尚未执行，其他自然语言要求请切换已安装的 Claude Code / Codex。", "actions": [],
                                 "questions": [{"question": "这条要求需要怎样继续？", "choices": ["切换已登录的 Claude Code 或 Codex", "改用明确的本地修改指令"]}]})
        return {"jobId": jid, "status": self.job(jid)["status"], "roundId": round_id}

    def job(self, job_id):
        with self.wb._connection() as db:
            row = db.execute("SELECT * FROM studio_jobs WHERE project_id=? AND id=?", (self.project_id, job_id)).fetchone()
        if not row:
            fail("JOB_NOT_FOUND", "没有找到这个对话任务。")
        return {**dict(row), "payload": json.loads(row["payload"]), "result": json.loads(row["result"]) if row["result"] else None}

    def next_job(self):
        with self.wb.atomic() as db:
            rows = db.execute("SELECT id FROM studio_jobs WHERE project_id=? AND status IN ('queued','running') ORDER BY created_at", (self.project_id,)).fetchall()
            job = next((j for row in rows if self._job_available(db, j := self.job(row["id"]), external=True)), None)
        if job is None:
            return {"pending": False, "projectId": self.project_id}
        return {"pending": True, "job": job, "context": self.context(job["payload"])}

    def template_recommendations(self, slide_id):
        page = self.wb.get_slide(self.project_id, slide_id)["slide"] if slide_id else {"role": "cover"}
        role = page.get("role", "content")
        from .semantic_planning import plan_page_expression
        from .jev_recommendations import configured
        from .taste import taste_profile
        taste = taste_profile(self)
        return {"slideId": slide_id, "role": role, "expressionPlan": plan_page_expression(page),
                "smartAvailable": configured(), "tasteSummary": taste["summary"] if taste["signals"] >= 3 else None,
                "recommendations": recommend_templates(role, page=page, taste=taste)}

    def context(self, payload=None):
        payload = payload or {}
        project = self.wb.get_project(self.project_id)
        sid = None if payload.get("kind") == "deck_page" or payload.get("scope") == "deck" else (payload.get("slideId") or self.state()["selectedSlideId"])
        page = self.wb.get_slide(self.project_id, sid) if sid else None
        scene = None
        if sid:
            try:
                scene = self.get_scene(sid)
            except EngineError as exc:
                if exc.code != "SCENE_MISSING":
                    raise
        if scene:
            scene = copy.deepcopy(scene)
            for obj in scene["scene"]["objects"]:
                if obj["type"] == "image":
                    obj["src"] = "scene-image:" + sid + "/" + obj["id"]
            for change in scene.get("changes", []):
                for side in ("before", "after"):
                    if isinstance(change.get(side), dict) and "src" in change[side]:
                        change[side]["src"] = "[图片引用已省略；读取当前对象 src]"
        assets = []
        for aid in payload.get("attachments", []):
            a = self.asset(aid)
            inspected = {"text": a["excerpt"], "readStatus": "text-available" if a["excerpt"] else "not-inspected"}
            if a["mime"] == "application/pdf":
                from .reference_inspection import inspect_reference
                asset_path = self.wb._inside(self.wb.project_dir(self.project_id) / a["path"], self.wb.project_dir(self.project_id))
                data = asset_path.read_bytes()
                if hashlib.sha256(data).hexdigest() != a["sha256"]:
                    fail("ASSET_INTEGRITY", "素材文件已变化，请重新上传。")
                inspected = inspect_reference(data, a["mime"])
            assets.append({"assetId": aid, "filename": a["filename"], "mime": a["mime"], "reference": a["path"],
                           "imageSrc": "asset:" + aid if a["mime"].startswith("image/") else None, **inspected})
        with self.wb._connection() as db:
            history = db.execute("SELECT role,text FROM studio_messages WHERE project_id=? ORDER BY created_at DESC LIMIT 12", (self.project_id,)).fetchall()
            intent = self._conversation_intent(db, payload)
        generation = {}
        if payload.get("kind") == "deck_page":
            with self.wb._connection() as db:
                deck, item = self._deck_page(db, payload)
            generation = {"deckDesign": json.loads(deck["plan"]).get("design"), "currentDeckPage": json.loads(item["plan"]) | {"index": item["page_index"] + 1},
                "generationTask": {"kind": "deck_page", "deckId": deck["id"], "pageIndex": item["page_index"],
                                   "sourceMessage": deck["source_message"]},
                "plannedOutline": [{"index": index + 1, "title": p["title"], "role": p["role"]} for index, p in enumerate(json.loads(deck["plan"])["pages"])]}
            from .deck_design import generation_context
            generation.update(generation_context(self, deck, item["page_index"]))
            with self.wb._connection() as db:
                answers = self._deck_answers(db, deck["id"], item["page_index"])
                generation["intakeInputs"] = self._deck_intake_inputs(db, deck)
            if answers:
                generation["currentDeckPage"]["supplementalAnswers"] = answers
        elif payload.get("kind") == "feedback_page":
            generation = {"generationTask": {"kind": "feedback_page", "roundId": payload.get("roundId"),
                           "sourceMessage": payload.get("sourceMessage"), "parentJobId": payload.get("parentJobId")},
                          "currentFeedback": {"slideId": payload["slideId"], "objectId": payload.get("objectId"),
                                              "instruction": payload["message"]}}
        recommendation_page = page["slide"] if page else generation.get("currentDeckPage")
        if recommendation_page and assets:
            recommendation_page = copy.deepcopy(recommendation_page)
            recommendation_page["assets"] = list(recommendation_page.get("assets") or []) + assets
        recommended = []
        # Built-in historical layouts are only for rendering saved documents.
        from .semantic_planning import plan_page_expression
        expression = plan_page_expression(recommendation_page) if recommendation_page else None
        from .reference_templates import visual_guidance
        guidance = {"selectedReference": None, "principles": ["使用精选设计案例，按本页文案重新排版。"]}
        from .deck_design import MAX_AUTO_IMAGES
        from . import curated_designs
        return {"creationContract": "content-led-v1" if not project["workspace"]["slides"] else None,
                "templateContract": curated_designs.template_contract(self, payload),
                "curatedDesignLibrary": curated_designs.planning_context() if payload.get("kind") != "deck_page" else None,
                "imageMode": self.image_mode(), "autoImageLimit": MAX_AUTO_IMAGES,
                "projectId": self.project_id, "projectRevision": project["revision"], "project": project["workspace"]["project"],
                "pageExpression": expression, "visualGuidance": guidance,
                "diagramDesign": __import__('ppt_workbench.diagram_design', fromlist=['guidance_for_page']).guidance_for_page(recommendation_page, expression),
                "designExperiences": __import__('ppt_workbench.design_loop', fromlist=['experiences']).experiences(self, (expression or {}).get('relationship','general')),
                "selectedTemplateId": None,
                "designDirection": __import__('ppt_workbench.design_direction', fromlist=['context']).context(),
                "userPalette": self._user_palette_context(),
                "styleReference": self._style_reference_context(),
                "userTasteProfile": self._user_taste_context(),
                "currentSceneTemplateId": scene["scene"].get("templateId") if scene else None,
                "recommendedTemplates": [{"id": t["id"], "title": t["title"], "roles": t["roles"], "use": t.get("use", ""), "referenceId": t.get("referenceId"), "capacityLabel": t.get("capacityLabel"), "fitRule": t.get("fitRule"), "adaptation": t.get("adaptation")} for t in recommended],
                "deck": self.deck_state(), "delivery": self.delivery_state(), **generation,
                "deliveryTask": {"kind": "feedback_plan" if payload.get("scope") == "deck" and project["workspace"]["slides"] else "intake",
                                 "roundId": payload.get("roundId"), "scope": payload.get("scope", "page")},
                "currentPage": page, "scene": scene, "selectedObjectId": payload.get("objectId"),
                "outline": [{"id": s["id"], "title": s["title"]} for s in project["workspace"]["slides"] if not s["archived"]],
                "pageRoles": ["cover", "toc", "chapter", "content", "ending", "appendix"],
                "templates": [],
                "conversation": list(reversed([dict(m) for m in history])), "userIntentHistory": intent, "attachments": assets,
                "rules": ["用户原话与附件是内容依据，不能捏造业务数据或用户认可。", "每轮最多修改或新增一页。选中对象时只允许scene_patch该对象。",
                          "初稿缺少可选事实或素材时使用明确占位并继续生成；仅在无法确定任务或目标范围时询问，最多三个问题。", "新建页的user_intent会由服务端绑定本次用户原话。",
                          "项目更新需明确用户选择。素材src使用附件的asset:ID或原有scene-image:页ID/对象ID引用；图片尚未检查时不能描述其内容为事实。",
                          "currentDeckPage.supplementalAnswers 是用户对当前待生成页问题的补充原话；只用于当前页，不能据此修改已完成的其他页。"],
                "sceneSpec": {"schema": "ppt-scene", "schemaVersion": 1, "width": 1280, "height": 720,
                              "types": ["text", "rect", "ellipse", "line", "image"], "requiredObjectFields": ["id", "type", "x", "y", "w", "h"],
                              "binding": "text对象可绑定title/takeaway/keyPoints:N，N从0连续；正文按scene.bindingSeparator合并回内容卡",
                              "textProperties": ["text", "fontSize", "color", "bold", "italic", "align", "valign", "fontFamily", "lineHeight", "binding", "textSource",
                                                 "letterSpacing", "emphasis", "emphasisColor"],
                              "textStyleRules": "letterSpacing为-5到40的像素字距，适合短标签与大标题微调；emphasis为本对象文字中原样出现的1–8个关键词，按emphasisColor加粗着色（不写颜色时只加粗），不改变文字本身。",
                              "newPageTextReferences": "仅新建整稿页面的scene文本对象可用textRef代替text：title或block.ID.heading/body/kicker/metric。服务器填入原文，不得同时使用text与textRef。heading/body可用textRange:[start,end]拆分完整正文（Unicode字符、右端不含），所有范围必须恰好覆盖原文。textSource由服务器记录，修正时保持。已有对象修改使用text。",
                              "rectProperties": ["fill", "stroke", "strokeWidth", "radius", "rotation", "shadow"],
                              "ellipseProperties": ["fill", "stroke", "strokeWidth", "rotation", "shadow"],
                              "shapeRules": "rotation为-180到180度，仅用于装饰性色块与椭圆，不旋转承载正文的底板；shadow取none、soft或lift，用于卡片层次。椭圆可做节点、大圆底和焦点背景。",
                              "defaults": "省略等于默认值的属性：opacity 1、bold false、italic false、align left、valign top、lineHeight 1.35、radius 0、stroke none。",
                              "lineProperties": ["stroke", "strokeWidth", "startArrow", "endArrow"], "imageProperties": ["src", "fit", "alt"],
                              "lineArrowRules": "startArrow/endArrow为可选布尔值，箭头与线条一体。起点(x,y)，终点(x+w,y+h)。向左/向上用startArrow:true；向右/向下用endArrow:true。折线仅在抵达目标节点的末段设箭头，不使用漂浮文字箭头。",
                              "geometryRules": "x/y为画布内的起点；w/h为非负宽高，不是终点坐标。非线对象w/h至少1。线段w或h可为0，但不能同时为0。所有终点必须在画布内。用水平/垂直分段连接，不使用负数宽高。",
                              "titleExample": {"id":"title","type":"text","text":"与计划标题完全一致","binding":"title","x":64,"y":44,"w":1152,"h":100,"fontSize":44,"color":"#142D50","bold":True}}}

    def _logo_public(self):
        from .logo import project_logo
        logo = project_logo(self)
        if not logo:
            return None
        return {k: logo[k] for k in ("preview", "tone", "hasAlpha", "removedBackground", "meanColor", "settings")}

    def _derived_from(self):
        from .derived import provenance
        return provenance(self)

    def _style_reference_public(self):
        from .user_templates import selected_style
        chosen = selected_style(self)
        if not chosen:
            return None
        return {"id": chosen["id"], "name": chosen["name"], "summary": chosen["summary"]}

    def _user_palette_context(self):
        chosen = self.palette()
        if not chosen:
            return None
        from .palette import PALETTE_INSTRUCTION
        return {"primary": chosen["primary"], "secondary": list(chosen["secondary"]),
                "instruction": PALETTE_INSTRUCTION}

    def _style_reference_context(self):
        from .user_templates import selected_style, STYLE_INSTRUCTION
        chosen = selected_style(self)
        if not chosen or not chosen.get("profile"):
            return None
        return {"name": chosen["name"], "profile": chosen["profile"], "instruction": STYLE_INSTRUCTION}

    def _user_taste_context(self):
        from .taste import taste_profile
        profile = taste_profile(self)
        if profile["signals"] < 3:
            return None
        return {"summary": profile["summary"],
                "instruction": "这是用户过往作品中反复采用的设计方向，仅作审美参考：与本次内容和受众相符时优先采用相近的视觉语言；不得因此改变内容。"}

    def apply_plan(self, job_id, plan):
        from .agent_bridge import validate_plan
        plan = validate_plan(plan)
        if not isinstance(plan, dict) or not isinstance(plan.get("reply"), str) or not plan["reply"].strip():
            fail("INVALID_PLAN", "代理回复必须包含非空 reply。")
        actions = plan.get("actions", [])
        if not isinstance(actions, list) or len(actions) > 8:
            fail("INVALID_PLAN", "单轮最多 8 个操作。")
        allowed = {"project_update", "slide_add", "slide_patch", "scene_replace", "scene_patch", "scene_objects", "deck_start", "deck_feedback", "image_generate", "diagram_image"}
        if any(not isinstance(a, dict) or a.get("type") not in allowed for a in actions):
            fail("INVALID_PLAN", "包含不支持的操作，审核与任意命令不在代理操作范围内。")
        with self.wb.atomic() as db:
            job = self.job(job_id)
            if job["status"] == "complete":
                return {"jobId": job_id, "deduplicated": True, **(job["result"] or {})}
            if job["status"] not in {"queued", "running"}:
                fail("JOB_CLOSED", "此任务已结束，请重新发起消息。")
            payload = job["payload"]
            sid = payload["slideId"]
            self._validate_deck_submission(db, job, actions)
            self._validate_feedback_submission(db, job, actions)
            batches = [a for a in actions if a["type"] == "deck_feedback"]
            if batches and (len(actions) != 1 or payload.get("objectId")):
                fail("SCOPE_VIOLATION", "整稿反馈必须单独分派，不能伴随单页修改或对象选择。")
            starts = [a for a in actions if a["type"] == "deck_start"]
            if starts and (len(starts) > 1 or any(a["type"] not in {"deck_start", "project_update"} for a in actions)):
                fail("SCOPE_VIOLATION", "整稿计划只能伴随项目简报更新，不能同时修改页面。")
            if starts and starts[0].get("execution") == "outline":
                if self.agent_mode in {"claude", "codex", "api"}:
                    fail("OUTLINE_MODE_REQUIRED", "本地大纲排版需要选择大纲模式；当前代理模式请使用 agent 执行。")
                from .outline import parse_outline, validate_deck_plan
                supplied = parse_outline(payload["message"])
                proposed = validate_deck_plan({k: v for k, v in starts[0].items() if k != "type"})
                if supplied is None or supplied != proposed:
                    fail("OUTLINE_SOURCE_MISMATCH", "本地大纲排版只能使用本条显式大纲的原文；模型拟写的整稿计划请使用 agent 执行模式。")
            if actions and sid:
                self.wb._revision(self.wb.get_slide(self.project_id, sid)["revision"], payload["baseRevision"])
            if any(a["type"] == "project_update" for a in actions):
                self.wb._revision(self.wb.get_project(self.project_id)["revision"], payload["projectRevision"])
            additions = [a for a in actions if a["type"] == "slide_add"]
            if additions and self._deck_row(db) and payload.get("kind") != "deck_page":
                fail("SCOPE_VIOLATION", "整稿页计划已经保存，本次不能在计划外新增页；可调整指定的已生成页面，另一套整稿请使用新项目。")
            image_actions = [a for a in actions if a['type'] in {'image_generate','diagram_image'}]
            if image_actions and (len(actions) != 1 or not sid or payload.get('objectId') or payload.get('kind') == 'deck_page'):
                fail('SCOPE_VIOLATION', '图片生成需要单独针对当前页面提交。')
            targeted = {a.get("slide_id") for a in actions if a["type"] in {"slide_patch", "scene_replace", "scene_patch", "scene_objects", "image_generate", "diagram_image"}}
            if len(additions) > 1 or len(targeted) > 1 or (additions and targeted):
                fail("SCOPE_VIOLATION", "每轮仅处理一页；不能同时修改其他页。")
            if targeted and (None in targeted or (sid and targeted != {sid})):
                fail("SCOPE_VIOLATION", "操作目标与本次对话选中的页面不一致。")
            if payload.get("objectId") and any(a["type"] != "scene_patch" for a in actions):
                fail("SCOPE_VIOLATION", "已经选中对象，本次只能调整该对象。")
            # Verify every declared baseline before applying any mutation.
            for action in actions:
                field = "base_revision" if action["type"] in {"slide_patch", "scene_replace"} else "base_scene_revision" if action["type"] in {"scene_patch", "scene_objects", "image_generate", "diagram_image"} else None
                if field:
                    actual = (self.wb.get_slide(self.project_id, action["slide_id"])["revision"] if field == "base_revision"
                              else self.get_scene(action["slide_id"])["sceneRevision"])
                    try:
                        self.wb._revision(actual, action.get(field))
                    except EngineError as exc:
                        if payload.get("kind") != "feedback_page" or exc.code != "STALE_REVISION":
                            raise
                        raise _ActionRevisionMismatch(exc.code, exc.message, exc.details | {
                            "slideId": action["slide_id"], "field": field}) from exc
            # Validate nested scene targets before any mutation. The action's
            # scope and original baselines have already passed above.
            for action in actions:
                if action['type'] == 'scene_replace' and action['scene'].get('slideId') != action['slide_id']:
                    raise _ActionSceneTargetMismatch('SCOPE_VIOLATION', '场景 slideId 必须与目标页一致。',
                        {'slideId':action['slide_id'],'field':'scene.slideId','current':action['slide_id']})
            changed_page, scene_result = None, None
            with self._operation(job_id, payload.get("kind") == "deck_page", payload["message"], round_id=payload.get("roundId")):
                for action in actions:
                    kind = action["type"]
                    if kind == "project_update":
                        p = self.wb.get_project(self.project_id)
                        updated = self.wb.update_project(self.project_id, p["revision"], action.get("changes", {}))
                        if p["workspace"]["slides"] and updated["workspace"]["project"] != p["workspace"]["project"]:
                            self._record_deck_revision(db, sid, p["revision"], updated["revision"], "更新整稿项目简报")
                    elif kind == "deck_start":
                        self.create_deck({k: v for k, v in action.items() if k != "type"}, payload["message"], action.get("execution", "agent"))
                    elif kind == "deck_feedback":
                        self._create_feedback_jobs(db, job, action)
                    elif kind == "slide_add":
                        page = self.wb.add_slide(self.project_id, action.get("title", ""), payload["message"], action.get("role", "content"))
                        changed_page = page["slideId"]
                        changes = []
                        for source, field in (("takeaway", "takeaway"), ("key_points", "keyPoints"), ("template_id", "templateId")):
                            if source in action:
                                value = action[source]
                                if source == "template_id":
                                    from .templates import recover_generated_template
                                    value = recover_generated_template(value, action.get("role", "content"), page=action,
                                                                       known_ids=self.wb._templates())
                                changes.append({"path": "/" + field, "value": value})
                        if payload.get("kind") == "deck_page":
                            declared = self._deck_intake(db, payload["deckId"])["pageEvidence"].get(str(payload["pageIndex"] + 1))
                            if declared in {"yes", "no"}:
                                changes.append({"path": "/evidenceRequired", "value": declared})
                        if changes:
                            self.wb.patch_slide(self.project_id, changed_page, page["revision"], changes, "采用当前候选内容")
                        if payload.get("kind") == "deck_page":
                            deck = self._deck_row(db)
                            for intake in self._deck_intake_inputs(db, deck):
                                if intake["messageId"] == deck["source_message_id"]:
                                    continue
                                current_page = self.wb.get_slide(self.project_id, changed_page)
                                self.wb.append_user_input(self.project_id, changed_page, current_page["revision"], intake["text"],
                                    f"整稿建立前第 {intake['roundNumber']} 轮原始输入；消息 {intake['messageId']}")
                            for answer in self._deck_answers(db, payload["deckId"], payload["pageIndex"]):
                                current_page = self.wb.get_slide(self.project_id, changed_page)
                                self.wb.append_user_input(self.project_id, changed_page, current_page["revision"], answer["text"],
                                    f"整稿第 {payload['pageIndex'] + 1} 页网页补充；消息 {answer['sourceMessageId']}；问题 {answer['questionMessageId']}")
                        if action.get('scene') or action.get('diagram'):
                            from .page_design import prepare_scene
                            page = self.wb.get_slide(self.project_id, changed_page)
                            scene_result = self.put_scene(changed_page, page['revision'],
                                prepare_scene(action, changed_page, self._resolve_images), '按页面方案生成原生设计', preserve_layout=True)
                    elif kind == "slide_patch":
                        changed_page = action["slide_id"]
                        page = self.wb.get_slide(self.project_id, changed_page)
                        self.wb.patch_slide(self.project_id, changed_page, page["revision"], action.get("changes", []), action.get("summary", "按本次对话更新当前页"))
                    elif kind == "scene_replace":
                        changed_page = action["slide_id"]
                        page = self.wb.get_slide(self.project_id, changed_page)
                        scene_result = self.put_scene(changed_page, page["revision"], action.get("scene"), "按本次对话生成当前页")
                    elif kind == "scene_patch":
                        changed_page = action["slide_id"]
                        scene_result = self.change_scene(changed_page, self.get_scene(changed_page)["sceneRevision"],
                                                         action.get("changes", []), payload.get("objectId"))
                    elif kind == "diagram_image":
                        from .diagram_design import fallback
                        fallback(self, action['slide_id'], action['base_scene_revision'], job_id,
                                 payload['message'])
                    elif kind == "image_generate":
                        from .image_generation import ImageJobs
                        ImageJobs(self).enqueue_batch(job_id, action['slide_id'], action['images'])
                    elif kind == "scene_objects":
                        changed_page = action["slide_id"]
                        scene_result = self.change_scene_objects(changed_page, self.get_scene(changed_page)["sceneRevision"], action["operations"])
                if changed_page and scene_result is None:
                    scene_result = self.generate_scene(changed_page)
            choices = []
            question_lines = []
            for question in plan.get("questions", [])[:3]:
                if not isinstance(question, dict) or not isinstance(question.get("question"), str):
                    fail("INVALID_PLAN", "问题格式不正确。")
                question_lines.append(question["question"])
                for choice in question.get("choices", []):
                    if isinstance(choice, str):
                        choices.append({"label": choice, "value": question["question"] + "：" + choice})
            reply = plan["reply"] + ("\n\n" + "\n".join(question_lines) if question_lines else "")
            result = {"reply": reply, "slideId": changed_page or sid, "sceneRevision": scene_result["sceneRevision"] if scene_result else None,
                      "changes": scene_result["changes"] if scene_result else [],
                      "needsInput": bool(plan.get("questions") and not actions),
                      "preciseEdit": bool(actions and all(a["type"] == "scene_patch" for a in actions))}
            if payload.get("modelBinding"):
                result["modelBinding"] = payload["modelBinding"]
            deck_extras = {"deckId": payload["deckId"], "deckPageIndex": payload["pageIndex"] + 1,
                           "isDeckQuestion": changed_page is None} if payload.get("kind") == "deck_page" else {}
            assistant_mid = self._message(db, "assistant", reply, result["slideId"], choices=choices, changes=result["changes"], jobId=job_id, modelBinding=payload.get("modelBinding"), **deck_extras)
            db.execute("UPDATE studio_jobs SET status='complete',result=?,updated_at=? WHERE id=?", (_json(result), _now(), job_id))
            db.execute("UPDATE studio_messages SET status='complete' WHERE id=?", (job["message_id"],))
            self._finish_deck_page(db, job, changed_page, assistant_mid)
            self._touch(db, result["slideId"])
            self._finish_round(self._round_for_job(db, job_id))
            return {"jobId": job_id, **result}

    def fail_job(self, job_id, error):
        with self.wb.atomic() as db:
            job = self.job(job_id)
            if job["status"] in {"complete", "cancelled", "failed"}:
                return
            detail = error.to_dict() if isinstance(error, EngineError) else {"code": "AGENT_FAILED", "message": str(error)}
            db.execute("UPDATE studio_jobs SET status='failed',result=?,updated_at=? WHERE id=?", (_json({"error": detail}), _now(), job_id))
            db.execute("UPDATE studio_messages SET status='failed' WHERE id=?", (job["message_id"],))
            self._message(db, "assistant", "这次修改未完成：" + detail["message"], job["payload"].get("slideId"), "failed", error=detail, jobId=job_id)
            if job["payload"].get("kind") == "deck_page":
                self._block_deck(db, job["payload"], detail)
            if job["payload"].get("kind") == "deck_review":
                db.execute("UPDATE studio_decks SET status='blocked',last_error=?,updated_at=? WHERE id=? AND status='running'",
                           (_json(detail), _now(), job["payload"]["deckId"]))
            self._finish_round(self._round_for_job(db, job_id), error=detail)

    def recover_interrupted_jobs(self):
        """Only the server holding ProjectServerLock may call this startup recovery."""
        from .background_tasks import recover
        recover(self)
        with self.wb.atomic() as db:
            rows = db.execute("SELECT id,message_id FROM studio_jobs WHERE project_id=? AND status='running'", (self.project_id,)).fetchall()
            for row in rows:
                db.execute("UPDATE studio_jobs SET status='queued',updated_at=? WHERE id=?", (_now(), row["id"]))
                db.execute("UPDATE studio_messages SET status='queued' WHERE id=?", (row["message_id"],))
                db.execute("UPDATE studio_deck_pages SET status='queued' WHERE job_id=? AND status='running'", (row["id"],))
            if rows:
                self._message(db, "assistant", f"工作台已重新启动，{len(rows)} 个未完成请求已恢复排队。原始想法和已完成页面均已保留。")
            return len(rows)

    def run_pending(self):
        from .agent_bridge import run_turn, diagnose
        with self.wb.atomic() as db:
            rows = db.execute("SELECT id FROM studio_jobs WHERE project_id=? AND status='queued' ORDER BY created_at", (self.project_id,)).fetchall()
            mode = self.agent_mode
            available = mode in {"claude", "codex", "api"} and diagnose(mode)["available"]
            job = None
            for row in rows:
                candidate = self.job(row["id"])
                if not self._job_available(db, candidate):
                    continue
                payload = candidate["payload"]
                from .template_packs import is_local_job
                local = (payload.get("kind") in {"deck_page", "feedback_page"} and payload.get("execution") == "outline") or is_local_job(self, payload)
                if local or payload.get("modelBinding") or available:
                    job = candidate
                    break
                if payload.get("kind") == "deck_page":
                    code = "WAITING_FOR_AGENT" if mode == "manual" else "AGENT_REQUIRED" if mode == "outline" else "AGENT_NOT_INSTALLED"
                    message = "整稿等待已连接的 Coding Agent 通过 MCP 继续，或在界面选择本机执行器。" if mode == "manual" else "此整稿计划需要真实模型执行器；请连接 Claude Code 或 Codex 后继续。"
                    self._block_deck(db, payload, {"code": code, "message": message}, page_failed=False)
                    self._finish_round(self._round_for_job(db, candidate["id"]))
                elif payload.get("kind") == "feedback_page":
                    rid = self._round_for_job(db, candidate["id"])
                    db.execute("UPDATE studio_delivery_rounds SET status='waiting_agent',updated_at=? WHERE id=?", (_now(), rid))
            if job is None:
                return False
            job_id = job["id"]
            rid = self._round_for_job(db, job_id)
            db.execute("UPDATE studio_delivery_rounds SET status='processing',updated_at=? WHERE id=?", (_now(), rid))
            db.execute("UPDATE studio_jobs SET status='running',updated_at=? WHERE id=?", (_now(), job_id))
            if job["payload"].get("kind") == "deck_page":
                db.execute("UPDATE studio_deck_pages SET status='running' WHERE job_id=?", (job_id,))
            db.execute("UPDATE studio_messages SET status='running' WHERE id=?", (job["message_id"],))
            self._touch(db)
        # Jobs run in the owner scope of their project: history-derived
        # features (taste, recommendations, template lists) must not read
        # another space's data just because the worker has no visitor context.
        from . import owners
        owner_scope = owners.set_scoped(owners.project_owner(self.wb, self.project_id))
        try:
            from functools import partial
            from .model_profiles import resolve
            chosen = job["payload"].get("modelBinding")
            if chosen:
                mode = resolve(chosen)["mode"]
            runner = partial(run_turn, model_binding=chosen) if chosen else run_turn
            if job["payload"].get("kind") == "deck_review":
                from .deck_review import run_review
                run_review(self, job, mode, runner)
                return True
            if job["payload"].get("kind") == "feedback_page" and job["payload"].get("execution") == "outline":
                self._demo_command(job_id, job["payload"])
                if self.job(job_id)["status"] in {"queued", "running"}:
                    self.fail_job(job_id, EngineError("LOCAL_FEEDBACK_UNSUPPORTED", "本地排版只支持明确的标题、文字、字号或背景修改；这条要求需要真实模型执行器。"))
                return True
            if is_local_job(self, job["payload"]):
                from .template_packs import page_job
                plan = page_job(self, job["payload"])
            elif job["payload"].get("kind") == "deck_page" and job["payload"].get("execution") == "outline":
                plan = self._local_deck_plan(job["payload"])
            else:
                correction = None
                for attempt in range(3):
                    context = self.context(job["payload"])
                    if correction:
                        context["revisionCorrection"] = correction
                    selected_ids = job["payload"].get("attachments", [])
                    records = [self.asset(aid) for aid in selected_ids] if mode == "codex" else []
                    try:
                        plan = runner(mode, job["payload"]["message"], context,
                                        timeout=120, workdir=self.wb.project_dir(self.project_id),
                                        selected_ids=selected_ids, asset_records=records)
                        if context.get('creationContract') and job['payload'].get('kind') != 'deck_page':
                            from .deck_design import review_plan
                            if not correction or correction.get("code") != "TEMPLATE_CAPACITY":
                                plan = review_plan(self, job, plan, context, mode, runner)
                            from .template_packs import default_plan
                            plan = default_plan(plan, context)
                        if job['payload'].get('kind') == 'deck_page' and len(plan.get('actions', [])) == 1:
                            from .design_review import review_new_page
                            plan = review_new_page(self, job, plan, context, mode, runner)
                        self.apply_plan(job_id, plan)
                        break
                    except EngineError as exc:
                        if exc.code == 'TEMPLATE_CAPACITY' and context.get('creationContract'):
                            if attempt == 2:
                                raise
                            correction = {'code':exc.code, 'message':exc.message, 'draft':plan,
                                          'instruction':'保持页数、标题、全部原文和限定词，仅重新分组或选择同套可读容量更大的版式。不能删字、缩写、合并限定对象或擅自拆页。确实装不下时保留内容并说明冲突。'}
                            continue
                        if exc.code in {'INVALID_AGENT_OUTPUT', 'INVALID_DESIGN_BRIEF', 'INVALID_PROJECT_FIELDS', 'INVALID_COMPOSITION'}:
                            if attempt == 2:
                                raise
                            from .core import PATCH_FIELDS
                            correction = {'code':exc.code, 'message':exc.message, 'details':exc.details,
                                'allowedSlidePatchPaths':['/' + field for field in sorted(PATCH_FIELDS)],
                                'instruction':'仅纠正输出协议，重新返回完整计划。arguments_json 是不含 type 的 JSON 字符串。slide_patch 只能使用列出的顶层路径；精确修改可见文字时用 scene_patch，使用当前对象 ID、properties.text 和 scene.sceneRevision。保留原修改范围、所有未要求修改的内容及视觉属性。不得把受保护字段换个路径提交。'}
                            continue
                        if exc.code == 'INVALID_AGENT_QUESTION':
                            if attempt == 2:
                                raise
                            correction = {'code':exc.code, 'field':'questions', 'instruction':
                                '只纠正提问格式并重新返回完整计划：questions 最多三个；每项含 question 非空文本、choices 数组。choices 可为空，最多六个非空文本；上传 Logo 或自由回答用 []。不编造答案，不丢失原问题，不扩大修改范围。'}
                            continue
                        if exc.code == 'MODEL_OUTPUT_TRUNCATED' and (job['payload'].get('kind') == 'deck_page' or context.get('creationContract')):
                            # Nothing was applied. One compact re-authoring is
                            # cheaper than blocking the whole deck for a manual retry.
                            if attempt == 2 or (correction or {}).get('code') == exc.code:
                                raise
                            correction = {'code': exc.code, 'instruction': (
                                '上次输出超过长度上限被截断，没有应用。重新返回完整计划，但输出更紧凑：省略等于默认值的属性'
                                '（opacity 1、italic false、bold false、align left、valign top、lineHeight 1.35、radius 0、stroke none）；'
                                '对象 ID 保持简短；合并重复的装饰色块与线条；计划文字一律用 textRef 引用，不重复书写原文。'
                                '页面标题、全部计划文字、视觉焦点和设计方向保持不变。'
                                if job['payload'].get('kind') == 'deck_page' else
                                '上次输出超过长度上限被截断，没有应用。重新返回完整计划，但输出更紧凑：strategy 与每页 designBrief '
                                '的每个说明字段只写一句短句；不重复复述用户原文以外的说明；页数、用户事实、原文与限定条件保持不变。')}
                            continue
                        if isinstance(exc, _ActionSceneTargetMismatch) and job['payload'].get('kind') == 'feedback_page':
                            if attempt == 2:
                                raise
                            correction = {**exc.details, 'code':exc.code, 'instruction':
                                'scene_replace 的 scene.slideId 必须与 action.slide_id 和当前目标页一致。S001 仅是新建页占位。保留当前页完整内容，不修改其他页面。'}
                            continue
                        if not isinstance(exc, _ActionRevisionMismatch):
                            page_retry = job['payload'].get('kind') == 'deck_page' and exc.code in {
                                'INVALID_AGENT_OUTPUT','INVALID_SCENE','SCENE_OUT_OF_BOUNDS','INVALID_DIAGRAM','DESIGN_CONTENT_MISMATCH',
                                'DESIGN_REPEATED_FOOTER','DESIGN_LAYOUT_REQUIRED','DESIGN_OVERFLOW'}
                            # This is preflight only: no image job or paid generation
                            # has started. Provider failures are never retried here.
                            image_retry = job['payload'].get('kind') == 'feedback_page' and exc.code == 'IMAGE_INVALID_TARGET'
                            layout_retry = job['payload'].get('kind') == 'feedback_page' and exc.code in {'INVALID_SCENE','SCENE_OUT_OF_BOUNDS'}
                            if attempt == 2 or not (page_retry or image_retry or layout_retry):
                                raise
                            correction = {'instruction':('修正图片对象 ID 或位置；参考当前 scene，背景矩形可原位替换，新增背景使用 placement=background。保留所有文字，不重建其他页面。' if image_retry else '修正版式参数后重新提交完整计划。矩形 radius 必须在 0 到 min(w,h)/2 之间；所有对象必须在画布内。保留当前页全部原文、图片与未要求改动的内容，不修改其他页面。' if layout_retry else '严格按输出协议返回可解析的完整 JSON；修正生成的整页场景后重新提交，保留计划的全部文字和图解关系。'),
                                          'code':exc.code,'message':exc.message,'details':exc.details}
                            continue
                        if attempt == 2:
                            raise
                        correction = {**exc.details, "instruction": (
                            "上次操作的版本号错误。请重新生成完整计划，并将指定字段设为 current；"
                            "base_revision 是内容版本，base_scene_revision 是场景版本，不能互换。"
                            "不要更改目标或绕过并发保护。")}
                return True
            self.apply_plan(job_id, plan)
        except Exception as exc:
            self.fail_job(job_id, exc)
        finally:
            owners.reset(owner_scope)
        return True

    def demo(self):
        with self.wb.atomic() as db:
            project = self.wb.get_project(self.project_id)
            if project["workspace"]["slides"]:
                fail("PROJECT_NOT_EMPTY", "示例只在空项目中创建，避免覆盖你的页面。")
            self.wb.update_project(self.project_id, project["revision"], {"title": "逐页工作台 · 演示项目", "purpose": "other",
                "purposeOther": "产品交互示例", "audience": "体验工作台的人", "outcome": "体验聊天、预览与局部修改",
                "delivery": "both", "logoPolicy": "none", "dataPolicy": "none"})
            examples = [
                ("让想法成为看得见的页面", "cover", "这是一份产品交互演示。体验先说清想法，再生成单页，最后针对预览调整。", "先写下想法，再逐页打磨", "当前是示例内容，不代表真实业务案例", "cover"),
                ("内容与版式分开调整", "content", "演示怎样区分用户思想和版面修改。", "原始思想保留，表达与版式按反馈修改", "内容：要让读者理解什么\n版式：怎样让信息更清楚", "compare-2"),
                ("每一次修改，都能看见结果", "content", "演示工作台的制作步骤，不使用虚构成效数据。", "先完成当前页，再继续下一页", "写下这一页的想法\n查看生成的页面\n点中对象提出修改\n认可后继续下一页", "process")]
            ids = []
            known = {t["id"] for t in self.wb.list_templates()["templates"]}
            for title, role, original, takeaway, points, template in examples:
                page = self.wb.add_slide(self.project_id, title, original, role)
                sid = page["slideId"]; ids.append(sid)
                self.wb.patch_slide(self.project_id, sid, page["revision"], [{"path": "/takeaway", "value": takeaway},
                    {"path": "/keyPoints", "value": points}, {"path": "/evidenceRequired", "value": "no"},
                    {"path": "/templateId", "value": template if template in known else "custom"}])
                self.generate_scene(sid)
            db.execute("UPDATE studio_state SET demo=1 WHERE project_id=?", (self.project_id,))
            self._touch(db, ids[0])
            self._message(db, "assistant", "已载入明确标注的演示项目。未接模型时，可试“标题放大一点”“标题改为：你的新标题”或“背景换成深蓝色”。这些演示指令由本地规则处理。", ids[0], choices=[
                {"label": "标题放大一点", "value": "标题放大一点"}, {"label": "背景换成深蓝色", "value": "背景换成深蓝色"}])
        return self.state()

    def _demo_command(self, job_id, payload):
        sid, message = payload.get("slideId"), payload["message"].strip()
        if not sid:
            return
        try:
            current = self.get_scene(sid)
            self.wb._revision(current["contentRevision"], payload["baseRevision"])
            self.wb._revision(current["sceneRevision"], payload["baseSceneRevision"])
            title_id = payload.get("objectId") or "title"
            obj = next((o for o in current["scene"]["objects"] if o["id"] == title_id), None)
            changes = None
            match = re.fullmatch(r"(?:标题|文字)改为[：:]\s*(.+)", message, re.S)
            if match and obj and obj["type"] == "text":
                changes = [{"objectId": title_id, "properties": {"text": match.group(1)}}]
            elif message == "标题放大一点" and obj and obj["type"] == "text":
                changes = [{"objectId": title_id, "properties": {"fontSize": min(88, obj.get("fontSize", 40) + 4)}}]
            if changes:
                self.apply_plan(job_id, {"reply": "本地规则修改已完成，右侧显示实际更新后的页面；本次未调用模型。", "actions": [{"type": "scene_patch", "slide_id": sid,
                    "base_scene_revision": current["sceneRevision"], "changes": changes}]})
            elif message in {"背景换成深蓝色", "背景换成白色"} and not payload.get("objectId"):
                scene = copy.deepcopy(current["scene"])
                dark = "深蓝" in message
                scene["background"] = "#14254B" if dark else "#FFFFFF"
                for obj in scene["objects"]:
                    if obj["type"] == "text":
                        obj["color"] = "#FFFFFF" if dark else "#172541"
                self.apply_plan(job_id, {"reply": "本地配色已更新。这是本地规则操作，内容保持原样。", "actions": [{"type": "scene_replace", "slide_id": sid,
                    "base_revision": current["contentRevision"], "scene": scene}]})
            elif message == "撤销上一步":
                if payload.get("kind") == "feedback_page":
                    fail("LOCAL_FEEDBACK_UNSUPPORTED", "批量反馈中的撤销需要真实执行器，请选择目标页后单独撤销。")
                with self._operation(job_id, False, message):
                    self.undo(sid, current["sceneRevision"], payload.get("objectId"))
                self.apply_plan(job_id, {"reply": "已通过本地操作恢复上一版预览。", "actions": []})
        except EngineError as exc:
            self.fail_job(job_id, exc)

    def export(self, format_name="html", slide_id=None, strict=False):
        if format_name not in {"html", "pptx"}:
            fail("INVALID_EXPORT", "支持 HTML 与 PPTX 导出。")
        with self.wb.atomic():
            project = self.wb.get_project(self.project_id)
            deck = self.deck_state()
            if not slide_id and deck and deck["completedPages"] < deck["totalPages"]:
                fail("DECK_INCOMPLETE", "整稿尚未全部生成，不能把部分页面作为完整演示稿导出。可继续任务或明确导出指定单页。", {"completedPages": deck["completedPages"], "totalPages": deck["totalPages"]})
            ids = [slide_id] if slide_id else [s["id"] for s in project["workspace"]["slides"] if not s["archived"]]
            if strict and slide_id and slide_id not in {s["id"] for s in project["workspace"]["slides"] if not s["archived"]}:
                fail("RELEASE_GATE_FAILED", "正式导出不能选择已归档或不存在的页面；请审阅当前可见页面。", {"slideId": slide_id})
            if not ids:
                fail("NO_PAGES", "还没有可导出的页面。")
            scenes = []
            for sid in ids:
                current = self.get_scene(sid)
                if current["stale"]:
                    fail("SCENE_STALE", "部分页面内容已更新，先刷新预览再导出。", {"slideId": sid})
                scenes.append(current["scene"])
            if strict:
                quality = self.quality_state()
                if not quality.get("readyToReview") or not quality.get("humanAccepted"):
                    fail("RELEASE_GATE_FAILED", "正式导出需要当前版本的实际浏览器检查与明确的内容、视觉认可；可以先导出草稿。",
                         {"qualityStatus": quality.get("status"), "readyToReview": bool(quality.get("readyToReview")),
                          "humanAccepted": bool(quality.get("humanAccepted"))})
            if strict and not self.wb.gate(self.project_id)["ready"]:
                fail("RELEASE_GATE_FAILED", "正式交付条件未满足；可以先导出明确标注的草稿。", self.wb.gate(self.project_id))
            folder = self.wb.project_dir(self.project_id) / "exports"
            folder.mkdir(exist_ok=True)
            path = folder / (("release-" if strict else "draft-") + uuid.uuid4().hex[:12] + "." + format_name)
            title = project["workspace"]["project"]["title"]
            if format_name == "html":
                path.write_text(export_html_deck(scenes, title=title), encoding="utf-8")
            else:
                export_pptx(scenes, path, title=title)
            return {"path": str(path), "format": format_name, "slideCount": len(scenes), "draft": not strict,
                    "note": "草稿导出不表示内容、资料或视觉已经通过审核。" if not strict else "已通过当前流程条件检查。"}
