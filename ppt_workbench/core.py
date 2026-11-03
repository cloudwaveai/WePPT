"""Durable, versioned PPT preparation records. No model or slide renderer lives here.

Reviews are operator attestations, not authenticated proof of a human identity.
The engine constrains calls made through it; an agent with shell/filesystem access
can bypass this local service and must be confined separately for stronger policy.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import copy
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid

SCHEMA = "ppt-slide-workspace"
PROJECT_DEFAULT = {
    "title": "", "purpose": "", "purposeOther": "", "audience": "",
    "outcome": "", "delivery": "", "duration": "", "logoPolicy": "undecided",
    "logoReference": "", "brandReference": "", "dataPolicy": "undecided", "scopeNote": "",
}
PATCH_FIELDS = {"title", "takeaway", "keyPoints", "candidateText", "candidateState",
                "role", "templateId", "evidenceRequired", "evidence", "assets", "changeRequest"}
ROLES = {"", "cover", "toc", "chapter", "content", "ending", "appendix"}
REVIEW_KINDS = {"content", "evidence", "visual"}
MAX_FILE_BYTES = 100 * 1024 * 1024
# Legacy workflow.js cleanText uses String.slice(0, 16000), i.e. UTF-16 units.
HTML_TEXT_LIMIT = 16000


class EngineError(Exception):
    def __init__(self, code: str, message: str, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def to_dict(self):
        result = {"code": self.code, "message": self.message}
        if self.details is not None:
            result["details"] = self.details
        return result


def _fail(code, message, details=None):
    raise EngineError(code, message, details)


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value, name, *, required=False):
    if not isinstance(value, str):
        _fail("INVALID_INPUT", f"{name} 必须为文本。")
    if len(value) > 100_000:
        _fail("INVALID_INPUT", f"{name} 超过长度限制。")
    if required and not value.strip():
        _fail("INVALID_INPUT", f"缺少 {name}。")
    return value


def _blank_slide(sid, title="", user_intent="", role="content"):
    return {
        "id": sid, "revision": 1, "title": title, "userIntent": user_intent,
        "userInputs": [],
        "takeaway": "", "keyPoints": "", "candidateText": "", "candidateState": "empty",
        "role": role, "templateId": "", "contentStatus": "draft",
        "evidenceRequired": "undecided", "evidence": [], "assets": [],
        "changeRequest": {"baseRevision": 1, "targetType": "region", "targetId": "",
                          "operation": "copy", "change": "", "keep": "", "acceptance": ""},
        "render": {"status": "not-rendered", "artifactPath": "", "previewPath": "",
                   "manifestPath": "", "renderedRevision": None},
        "history": [], "archived": False, "dirty": False, "updatedAt": _now(),
    }


class Workbench:
    """One SQLite state store shared by CLI and MCP adapters."""

    def __init__(self, root, templates_path=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self._inside(self.root / "workbench.sqlite")
        self.templates_path = Path(templates_path) if templates_path else Path(__file__).parent / "data" / "template-rules.json"
        self._templates_cache = None
        self._transaction_local = threading.local()
        with self._connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, revision INTEGER NOT NULL, workspace TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS slide_revisions (
                project_id TEXT NOT NULL, slide_id TEXT NOT NULL, revision INTEGER NOT NULL,
                body TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, slide_id, revision));
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, slide_id TEXT NOT NULL,
                revision INTEGER NOT NULL, kind TEXT NOT NULL, evidence_id TEXT NOT NULL,
                subject_hash TEXT NOT NULL, reviewer TEXT NOT NULL, statement TEXT NOT NULL,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts (
                project_id TEXT NOT NULL, slide_id TEXT NOT NULL, revision INTEGER NOT NULL,
                binding_hash TEXT NOT NULL, record TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, slide_id, revision));
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                slide_id TEXT, action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    def _inside(self, path, boundary=None):
        boundary = (boundary or self.root).resolve()
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(boundary):
            _fail("PATH_OUTSIDE_WORKSPACE", "路径超出指定工作目录。")
        return resolved

    @contextmanager
    def _connection(self):
        active = getattr(self._transaction_local, "connection", None)
        if active is not None:
            yield active
            return
        self._inside(self.db_path)
        db = sqlite3.connect(str(self.db_path), timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            nested = db.in_transaction
            marker = "nested_" + uuid.uuid4().hex
            db.execute("SAVEPOINT " + marker if nested else "BEGIN IMMEDIATE")
            try:
                yield db
                if nested:
                    db.execute("RELEASE SAVEPOINT " + marker)
                else:
                    db.commit()
            except Exception:
                if nested:
                    db.execute("ROLLBACK TO SAVEPOINT " + marker)
                    db.execute("RELEASE SAVEPOINT " + marker)
                else:
                    db.rollback()
                raise

    @contextmanager
    def atomic(self):
        """Group multiple engine calls into one transaction in the current thread."""
        if getattr(self._transaction_local, "connection", None) is not None:
            with self._transaction() as db:
                yield db
            return
        with self._connection() as db:
            self._transaction_local.connection = db
            try:
                with self._transaction():
                    yield db
            finally:
                del self._transaction_local.connection

    def _project_id(self, pid):
        if not isinstance(pid, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", pid):
            _fail("INVALID_PROJECT_ID", "项目 ID 只能含字母、数字、下划线或连字符，长度不超过 64。")
        return pid

    def project_dir(self, project_id):
        pid = self._project_id(project_id)
        folder = self._inside(self.root / "projects" / pid)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _read(self, db, pid):
        self._project_id(pid)
        row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if row is None:
            _fail("PROJECT_NOT_FOUND", "未找到项目。", {"projectId": pid})
        return row, json.loads(row["workspace"])

    @staticmethod
    def _slide(state, sid):
        for slide in state["slides"]:
            if slide["id"] == sid:
                return slide
        _fail("SLIDE_NOT_FOUND", "未找到指定页面。", {"slideId": sid})

    @staticmethod
    def _revision(actual, expected):
        if type(expected) is not int or expected != actual:
            _fail("STALE_REVISION", "基准版本过期；请读取当前版本并比较差异。", {"expected": expected, "current": actual})

    def _save(self, db, pid, state, revision, *, slide=None, action, details=None):
        state["updatedAt"] = _now()
        db.execute("UPDATE projects SET workspace=?, revision=?, updated_at=? WHERE id=?",
                   (_json(state), revision + 1, state["updatedAt"], pid))
        if slide is not None:
            db.execute("INSERT INTO slide_revisions VALUES (?,?,?,?,?)",
                       (pid, slide["id"], slide["revision"], _json(slide), state["updatedAt"]))
        self._event(db, pid, slide["id"] if slide else None, action, details or {})

    @staticmethod
    def _event(db, pid, sid, action, details):
        db.execute("INSERT INTO events (project_id,slide_id,action,details,created_at) VALUES (?,?,?,?,?)",
                   (pid, sid, action, _json(details), _now()))

    @staticmethod
    def _content_hash(state, slide):
        project = {k: state["project"].get(k, "") for k in ("title", "purpose", "purposeOther", "audience", "outcome", "scopeNote", "dataPolicy")}
        fields = ("id", "userIntent", "userInputs", "title", "takeaway", "keyPoints", "role", "evidenceRequired")
        return _hash({"project": project, "slide": {k: slide.get(k) for k in fields}})

    @staticmethod
    def _has_user_input(slide):
        return bool(slide["userIntent"].strip() or any(i["text"].strip() for i in slide.get("userInputs", [])))

    @staticmethod
    def _render_binding(state, slide):
        return _hash({"contentHash": Workbench._content_hash(state, slide), "revision": slide["revision"],
                      "design": {k: state["project"].get(k, "") for k in ("logoPolicy", "logoReference", "brandReference", "delivery", "duration")},
                      "templateId": slide["templateId"], "assets": slide["assets"], "evidence": slide["evidence"]})

    @staticmethod
    def _evidence_hash(state, slide, evidence):
        return _hash({"contentHash": Workbench._content_hash(state, slide), "evidence": {
            k: evidence.get(k, "") for k in ("id", "claim", "source", "locator", "scope")}})

    def _validate_project(self, brief):
        if not isinstance(brief, dict) or set(brief) - set(PROJECT_DEFAULT):
            _fail("INVALID_PROJECT_FIELDS", "项目包含未知字段。", {"allowed": sorted(PROJECT_DEFAULT)})
        for key, value in brief.items():
            _text(value, key)
        enums = {"purpose": {"", "proposal", "report", "pitch", "teaching", "other"},
                 "delivery": {"", "live", "read", "both"}, "logoPolicy": {"undecided", "none", "company", "joint"},
                 "dataPolicy": {"undecided", "user", "research", "mixed", "none"}}
        for key, choices in enums.items():
            if key in brief and brief[key] not in choices:
                _fail("INVALID_PROJECT_FIELDS", f"{key} 取值不支持。")

    def _validate_slide(self, slide):
        for key in ("role", "candidateState", "evidenceRequired"):
            _text(slide[key], key)
        if slide["role"] not in ROLES:
            _fail("INVALID_SLIDE", "页面角色不支持。")
        for key in ("title", "userIntent", "takeaway", "keyPoints", "candidateText", "templateId"):
            _text(slide[key], key)
        if slide["candidateState"] not in {"empty", "proposed", "adopted"} or slide["evidenceRequired"] not in {"undecided", "yes", "no"}:
            _fail("INVALID_SLIDE", "页面内容状态不支持。")
        if slide["templateId"] not in {"", "custom"} and slide["templateId"] not in self._templates():
            _fail("UNKNOWN_TEMPLATE", "模板不存在；沿用原稿或自定义版式请使用 custom。")
        inputs = slide.setdefault("userInputs", [])
        if not isinstance(inputs, list) or len(inputs) > 1000:
            _fail("INVALID_SLIDE", "用户补充输入必须为不超过 1000 项的数组。")
        input_ids = set()
        for entry in inputs:
            if not isinstance(entry, dict) or set(entry) != {"id", "text", "sourceNote", "recordedAt", "provenance"}:
                _fail("INVALID_SLIDE", "用户补充输入记录格式不正确。")
            for key in ("id", "text", "sourceNote", "recordedAt", "provenance"):
                _text(entry[key], "userInputs." + key, required=key in {"id", "text"})
            if entry["id"] in input_ids or entry["provenance"] != "client-transcribed-unverified":
                _fail("INVALID_SLIDE", "用户输入 ID 重复或来源声明不支持。")
            input_ids.add(entry["id"])
        for collection in ("evidence", "assets"):
            if not isinstance(slide[collection], list) or len(slide[collection]) > 100:
                _fail("INVALID_SLIDE", f"{collection} 必须为不超过 100 项的数组。")
            seen = set()
            for item in slide[collection]:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", item["id"]) or item["id"] in seen:
                    _fail("INVALID_SLIDE", f"{collection} 条目 ID 非法或重复。")
                seen.add(item["id"])
                if collection == "evidence":
                    if set(item) - {"id", "claim", "source", "locator", "scope", "status", "verifiedBy"}:
                        _fail("INVALID_SLIDE", "证据条目包含未知字段。")
                    for key in ("claim", "source", "locator", "scope", "verifiedBy"):
                        _text(item.setdefault(key, ""), key)
                    _text(item.setdefault("status", "unverified" if item["source"] else "missing"), "status")
                    if item["status"] not in {"missing", "unverified"} or item["verifiedBy"]:
                        _fail("REVIEW_REQUIRED", "不能通过字段写入核验状态；请由审阅通道记录依据与核验陈述。")
                else:
                    if set(item) - {"id", "description", "kind", "owner", "status", "reference", "required"}:
                        _fail("INVALID_SLIDE", "素材条目包含未知字段。")
                    for key in ("description", "reference"):
                        _text(item.setdefault(key, ""), key)
                    for key in ("kind", "owner", "status"):
                        _text(item.get(key), key)
                    if item.get("kind") not in {"screenshot", "photo", "logo", "data", "other"} or item.get("owner") not in {"user", "team", "ai-research", "designer"}:
                        _fail("INVALID_SLIDE", "素材类型或提供方不支持。")
                    if item.get("status") not in {"missing", "requested", "provided", "not-needed"} or type(item.get("required")) is not bool:
                        _fail("INVALID_SLIDE", "素材状态或 required 类型不正确。")
        cr = slide.get("changeRequest", {})
        if not isinstance(cr, dict) or set(cr) - {"baseRevision", "targetType", "targetId", "operation", "change", "keep", "acceptance"}:
            _fail("INVALID_SLIDE", "修改请求包含未知字段。")
        _text(cr.get("targetType", "region"), "targetType")
        _text(cr.get("operation", "copy"), "operation")
        if cr.get("targetType", "region") not in {"region", "object", "whole-slide"}:
            _fail("INVALID_SLIDE", "目标类型不支持。")
        if cr.get("operation", "copy") not in {"copy", "layout", "style", "asset", "chart", "other"}:
            _fail("INVALID_SLIDE", "修改类型不支持。")
        for key in ("targetId", "change", "keep", "acceptance"):
            _text(cr.get(key, ""), key)
        if "baseRevision" in cr and (type(cr["baseRevision"]) is not int or cr["baseRevision"] < 1):
            _fail("INVALID_SLIDE", "修改请求的基准版本必须为正整数。")

    def list_projects(self):
        with self._connection() as db:
            rows = db.execute("SELECT id, workspace, created_at, updated_at FROM projects ORDER BY updated_at DESC, id").fetchall()
        result = []
        for row in rows:
            workspace = json.loads(row["workspace"])
            result.append({"projectId": row["id"], "title": workspace["project"]["title"],
                           "slideCount": sum(not slide.get("archived", False) for slide in workspace["slides"]),
                           "createdAt": row["created_at"], "updatedAt": row["updated_at"]})
        return result

    def create_project(self, project_id, brief=None):
        self._project_id(project_id)
        brief = {} if brief is None else brief
        self._validate_project(brief)
        now = _now()
        state = {"schema": SCHEMA, "schemaVersion": 1, "project": PROJECT_DEFAULT | brief,
                 "slides": [], "nextSlideNumber": 1, "selectedSlideId": None, "updatedAt": now}
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                _fail("PROJECT_EXISTS", "项目已存在，不会覆盖。")
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (project_id, 1, _json(state), now, now))
            self._event(db, project_id, None, "project-created", {})
        self.project_dir(project_id)
        return self.get_project(project_id)

    def import_workspace(self, project_id, workspace):
        self._project_id(project_id)
        if not isinstance(workspace, dict) or workspace.get("schema") != SCHEMA or workspace.get("schemaVersion") != 1:
            _fail("UNSUPPORTED_SCHEMA", "需要 HTML 导出的 ppt-slide-workspace v1。")
        if not isinstance(workspace.get("slides"), list) or len(workspace["slides"]) > 200:
            _fail("INVALID_IMPORT", "页面数组缺失或超过 200 页。")
        brief = workspace.get("project", {})
        self._validate_project(brief)
        state = {"schema": SCHEMA, "schemaVersion": 1, "project": PROJECT_DEFAULT | copy.deepcopy(brief),
                 "slides": [], "nextSlideNumber": 1, "selectedSlideId": None, "updatedAt": _now()}
        seen, declarations = set(), []
        for source in workspace["slides"]:
            if not isinstance(source, dict):
                _fail("INVALID_IMPORT", "页面必须为对象。")
            sid = source.get("id", "")
            if not isinstance(sid, str) or not re.fullmatch(r"S\d{3,}", sid) or sid in seen:
                _fail("INVALID_IMPORT", "页面 ID 非法或重复。")
            seen.add(sid)
            revision = source.get("revision", 1)
            if type(revision) is not int or revision < 1:
                _fail("INVALID_IMPORT", "页面版本必须为正整数。")
            slide = _blank_slide(sid)
            for field in PATCH_FIELDS | {"userIntent", "userInputs", "archived"}:
                if field in source:
                    slide[field] = copy.deepcopy(source[field])
            if type(slide["archived"]) is not bool:
                _fail("INVALID_IMPORT", "archived 必须为布尔值。")
            slide["revision"] = revision
            declarations.append({"slideId": sid, "declaredContentStatus": source.get("contentStatus"),
                                 "declaredRender": source.get("render"), "declaredEvidence": source.get("evidence"),
                                 "hadUncommittedInput": bool(source.get("dirty"))})
            if not isinstance(slide["evidence"], list):
                _fail("INVALID_IMPORT", "证据必须为数组。")
            for evidence in slide["evidence"]:
                if not isinstance(evidence, dict):
                    _fail("INVALID_IMPORT", "证据条目必须为对象。")
                evidence["status"] = "unverified" if evidence.get("source") else "missing"
                evidence["verifiedBy"] = ""
            self._validate_slide(slide)
            state["slides"].append(slide)
            state["nextSlideNumber"] = max(state["nextSlideNumber"], int(sid[1:]) + 1)
        state["selectedSlideId"] = state["slides"][0]["id"] if state["slides"] else None
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                _fail("PROJECT_EXISTS", "导入只创建新项目；不会覆盖已有项目。")
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (project_id, 1, _json(state), _now(), _now()))
            for slide in state["slides"]:
                db.execute("INSERT INTO slide_revisions VALUES (?,?,?,?,?)", (project_id, slide["id"], slide["revision"], _json(slide), _now()))
            self._event(db, project_id, None, "workspace-imported", {"priorDeclarations": declarations,
                         "trust": "Import claims retained only as history; no review or artifact records accepted."})
        self.project_dir(project_id)
        result = self.get_project(project_id)
        result["importNotice"] = "导入文本作为新的已保存基线；原 dirty 声明仅保留在日志。原确认、核验与渲染声明也是历史信息，不是当前引擎的审阅凭据。"
        return result

    def get_project(self, project_id):
        with self._connection() as db:
            row, state = self._read(db, project_id)
        return {"projectId": project_id, "revision": row["revision"], "workspace": state,
                "projectDir": str(self.project_dir(project_id)), "trustBoundary": "local-operator-attestation"}

    def update_project(self, project_id, base_revision, changes):
        self._validate_project(changes)
        if not changes:
            _fail("EMPTY_PATCH", "没有项目修改。")
        with self._transaction() as db:
            row, state = self._read(db, project_id)
            self._revision(row["revision"], base_revision)
            state["project"].update(copy.deepcopy(changes))
            self._save(db, project_id, state, row["revision"], action="project-updated", details={"fields": sorted(changes)})
        return self.get_project(project_id)

    def add_slide(self, project_id, title, user_intent, role="content"):
        _text(title, "title"); _text(user_intent, "user_intent")
        with self._transaction() as db:
            row, state = self._read(db, project_id)
            if len(state["slides"]) >= 200:
                _fail("CAPACITY", "每个项目最多 200 页。")
            sid = "S" + str(state["nextSlideNumber"]).zfill(3)
            state["nextSlideNumber"] += 1
            slide = _blank_slide(sid, title, user_intent, role)
            self._validate_slide(slide)
            state["slides"].append(slide); state["selectedSlideId"] = sid
            self._save(db, project_id, state, row["revision"], slide=slide, action="slide-added")
        return self.get_slide(project_id, sid)

    def append_user_input(self, project_id, slide_id, base_revision, text, source_note=""):
        """Append a transcript without replacing original intent or authenticating its sender."""
        _text(text, "用户补充原话", required=True)
        _text(source_note, "source_note")
        with self._transaction() as db:
            row, state = self._read(db, project_id)
            slide = self._slide(state, slide_id)
            self._revision(slide["revision"], base_revision)
            entry = {"id": "U-" + uuid.uuid4().hex, "text": text, "sourceNote": source_note,
                     "recordedAt": _now(), "provenance": "client-transcribed-unverified"}
            slide.setdefault("userInputs", []).append(entry)
            self._validate_slide(slide)
            slide["revision"] += 1
            slide["updatedAt"] = _now()
            slide["history"].append({"revision": slide["revision"], "at": slide["updatedAt"],
                                     "action": "append-user-input", "summary": "追加用户补充原话；保留已有原话"})
            self._save(db, project_id, state, row["revision"], slide=slide, action="user-input-appended",
                       details={"inputId": entry["id"], "sourceNote": source_note,
                                "provenance": entry["provenance"], "humanIdentityAuthenticated": False})
        return self.get_slide(project_id, slide_id)

    def _artifact(self, db, pid, slide, state):
        row = db.execute("SELECT * FROM artifacts WHERE project_id=? AND slide_id=? AND revision=?",
                         (pid, slide["id"], slide["revision"])).fetchone()
        if row is None or row["binding_hash"] != self._render_binding(state, slide):
            return None
        return json.loads(row["record"])

    def _review(self, db, pid, slide, kind, subject_hash, evidence_id=""):
        row = db.execute("""SELECT * FROM reviews WHERE project_id=? AND slide_id=? AND revision=?
            AND kind=? AND evidence_id=? AND subject_hash=? ORDER BY created_at DESC LIMIT 1""",
            (pid, slide["id"], slide["revision"], kind, evidence_id, subject_hash)).fetchone()
        return dict(row) | {"assurance": "local-operator-attestation", "humanIdentityAuthenticated": False} if row else None

    def _view_slide(self, db, pid, state, slide):
        result = copy.deepcopy(slide)
        content_hash = self._content_hash(state, slide)
        content = self._review(db, pid, slide, "content", content_hash)
        result["contentStatus"] = "confirmed" if content else "draft"
        evidence_reviews = []
        for evidence in result["evidence"]:
            review = self._review(db, pid, slide, "evidence", self._evidence_hash(state, slide, evidence), evidence["id"])
            if review:
                evidence["status"], evidence["verifiedBy"] = "verified", review["reviewer"]
                evidence_reviews.append(review)
        artifact = self._artifact(db, pid, slide, state)
        visual = None
        integrity_issues = []
        if artifact:
            integrity_issues = self._file_issues(pid, artifact)
            if not integrity_issues:
                visual = self._review(db, pid, slide, "visual", _hash(artifact))
            result["render"] = {"status": "approved" if visual else "draft", "artifactPath": artifact["source"]["path"],
                                "previewPath": artifact["preview"]["path"], "manifestPath": artifact.get("objects", {}).get("path", ""),
                                "renderedRevision": None if integrity_issues else slide["revision"]}
        return {"projectId": pid, "slideId": slide["id"], "revision": slide["revision"], "slide": result,
                "contentHash": content_hash, "reviews": {"content": content, "evidence": evidence_reviews, "visual": visual},
                "artifact": artifact, "integrityIssues": integrity_issues}

    def get_slide(self, project_id, slide_id):
        with self._connection() as db:
            _, state = self._read(db, project_id)
            slide = self._slide(state, slide_id)
            return self._view_slide(db, project_id, state, slide)

    @staticmethod
    def _pointer_set(slide, path, value):
        if not isinstance(path, str) or not path.startswith("/"):
            _fail("INVALID_PATCH", "使用单页内 JSON Pointer 路径，例如 /title。")
        parts = [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]
        if not parts or parts[0] not in PATCH_FIELDS:
            _fail("PROTECTED_FIELD", "不能修改原始思想、其他页面或系统维护字段。", {"path": path})
        if any(p in {"__proto__", "prototype", "constructor", ".."} for p in parts):
            _fail("INVALID_PATCH", "路径包含不支持的片段。")
        target = slide
        for part in parts[:-1]:
            if isinstance(target, dict) and part in target:
                target = target[part]
            elif isinstance(target, list) and part.isdecimal() and int(part) < len(target):
                target = target[int(part)]
            else:
                _fail("INVALID_PATCH", "路径不存在，不自动创建嵌套结构。")
        final = parts[-1]
        if isinstance(target, dict) and (final in target or len(parts) == 1):
            target[final] = copy.deepcopy(value)
        elif isinstance(target, list) and final.isdecimal() and int(final) < len(target):
            target[int(final)] = copy.deepcopy(value)
        else:
            _fail("INVALID_PATCH", "目标字段不存在。")

    def patch_slide(self, project_id, slide_id, base_revision, changes, summary=""):
        if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
            _fail("INVALID_PATCH", "changes 需要 1—100 项字段改动。")
        _text(summary, "summary")
        with self._transaction() as db:
            row, state = self._read(db, project_id)
            slide = self._slide(state, slide_id)
            self._revision(slide["revision"], base_revision)
            other_before = _hash([s for s in state["slides"] if s["id"] != slide_id])
            before = copy.deepcopy(slide)
            for change in changes:
                if not isinstance(change, dict) or set(change) != {"path", "value"}:
                    _fail("INVALID_PATCH", "每项改动只接受 path 与 value。")
                self._pointer_set(slide, change["path"], change["value"])
            self._validate_slide(slide)
            if slide == before:
                _fail("EMPTY_PATCH", "本次补丁没有改变内容。")
            slide["revision"] += 1; slide["updatedAt"] = _now(); slide["contentStatus"] = "draft"
            slide["history"].append({"revision": slide["revision"], "at": slide["updatedAt"], "action": "patch", "summary": summary or "更新指定字段"})
            if _hash([s for s in state["slides"] if s["id"] != slide_id]) != other_before:
                _fail("SCOPE_VIOLATION", "检测到其他页面改变，已取消。")
            self._save(db, project_id, state, row["revision"], slide=slide, action="slide-patched",
                       details={"paths": [c["path"] for c in changes], "summary": summary,
                                "otherSlidesUnchanged": True, "renderedSlideScopeValidated": False})
        return self.get_slide(project_id, slide_id) | {"otherSlideRecordsUnchanged": True}

    def restore_slide(self, project_id, slide_id, base_revision, restore_revision):
        with self._transaction() as db:
            row, state = self._read(db, project_id)
            current = self._slide(state, slide_id)
            self._revision(current["revision"], base_revision)
            old = db.execute("SELECT body FROM slide_revisions WHERE project_id=? AND slide_id=? AND revision=?",
                             (project_id, slide_id, restore_revision)).fetchone()
            if old is None:
                _fail("REVISION_NOT_FOUND", "找不到要恢复的页面版本。")
            restored = json.loads(old["body"])
            # Restoring presentation content must not erase any original transcript.
            restored["userIntent"] = current["userIntent"]
            restored["userInputs"] = copy.deepcopy(current.get("userInputs", []))
            restored["revision"] = current["revision"] + 1
            restored["updatedAt"] = _now(); restored["contentStatus"] = "draft"
            restored["history"] = current["history"] + [{"revision": restored["revision"], "at": restored["updatedAt"],
                "action": "restore", "summary": f"恢复版本 {restore_revision} 的内容；作为新版本保存"}]
            for index, slide in enumerate(state["slides"]):
                if slide["id"] == slide_id:
                    state["slides"][index] = restored
            self._save(db, project_id, state, row["revision"], slide=restored, action="slide-restored",
                       details={"restoredFrom": restore_revision})
        return self.get_slide(project_id, slide_id)

    def _file_record(self, pid, filename):
        _text(filename, "file path", required=True)
        folder = self.project_dir(pid)
        path = Path(filename)
        path = self._inside(path if path.is_absolute() else folder / path, folder)
        if not path.is_file():
            _fail("FILE_NOT_FOUND", "所登记的文件不存在或不是普通文件。", {"path": str(path)})
        if path.stat().st_size == 0 or path.stat().st_size > MAX_FILE_BYTES:
            _fail("FILE_SIZE", "文件为空或超过 100 MiB。")
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        return {"path": str(path.relative_to(folder)), "sha256": sha.hexdigest(), "bytes": path.stat().st_size}

    def register_artifact(self, project_id, slide_id, base_revision, artifact_path, preview_path, manifest_path=""):
        with self._transaction() as db:
            _, state = self._read(db, project_id)
            slide = self._slide(state, slide_id)
            self._revision(slide["revision"], base_revision)
            source = self._file_record(project_id, artifact_path)
            preview = self._file_record(project_id, preview_path)
            record = {"source": source, "preview": preview, "recordedAt": _now(),
                      "scopeValidation": "not_verified", "semanticValidation": "operator_review_required"}
            materials, material_issues = [], []
            declared = []
            if state["project"]["logoPolicy"] in {"company", "joint"}:
                declared.append(("logo", "project-logo", state["project"]["logoReference"]))
            declared.extend(("asset", a["id"], a["reference"]) for a in slide["assets"]
                            if a["status"] == "provided" or a["required"])
            for kind, material_id, filename in declared:
                try:
                    materials.append({"kind": kind, "id": material_id, "reference": filename,
                                      "file": self._file_record(project_id, filename)})
                except EngineError as exc:
                    material_issues.append({"code": "MATERIAL_UNAVAILABLE", "kind": kind, "id": material_id, "message": f"{kind} {material_id} 在产物登记时缺少可读取素材：{exc.message}"})
            record["materials"], record["materialIssues"] = materials, material_issues
            if manifest_path:
                obj_record = self._file_record(project_id, manifest_path)
                try:
                    objects = json.loads((self.project_dir(project_id) / obj_record["path"]).read_text())
                except (ValueError, UnicodeError) as exc:
                    _fail("INVALID_OBJECT_MANIFEST", "对象映射必须为有效 JSON。", str(exc))
                if not isinstance(objects, dict) or objects.get("slideId") != slide_id or not isinstance(objects.get("objects"), list):
                    _fail("INVALID_OBJECT_MANIFEST", "对象映射需包含匹配的 slideId 与 objects 数组。")
                ids = [x.get("id") if isinstance(x, dict) else None for x in objects["objects"]]
                if not ids or any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
                    _fail("INVALID_OBJECT_MANIFEST", "对象 ID 不能为空或重复。")
                record["objects"] = obj_record
            binding = self._render_binding(state, slide)
            db.execute("INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?)", (project_id, slide_id, slide["revision"], binding, _json(record), _now()))
            self._event(db, project_id, slide_id, "artifact-registered", {"revision": slide["revision"], "record": record})
        return self.get_slide(project_id, slide_id)

    def _file_issues(self, project_id, artifact):
        issues = copy.deepcopy(artifact.get("materialIssues", []))
        if "materials" not in artifact:
            issues.append({"code": "MATERIAL_SNAPSHOT_MISSING", "message": "缺少素材哈希快照，需重新登记。"})
        for kind in ("source", "preview", "objects"):
            record = artifact.get(kind)
            if not record:
                if kind == "objects":
                    issues.append({"code": "OBJECT_MAP_MISSING", "message": "补充本页对象 ID 到可编辑源对象的映射。"})
                continue
            try:
                current = self._file_record(project_id, record["path"])
                if current["sha256"] != record["sha256"] or current["bytes"] != record["bytes"]:
                    issues.append({"code": "ARTIFACT_CHANGED", "message": f"{kind} 文件已改变，需重新登记并审阅。"})
            except EngineError as exc:
                issues.append({"code": exc.code, "message": f"{kind}: {exc.message}"})
        for material in artifact.get("materials", []):
            record = material["file"]
            label = material["kind"] + " " + material["id"]
            try:
                current = self._file_record(project_id, material.get("reference", record["path"]))
                if current["sha256"] != record["sha256"] or current["bytes"] != record["bytes"] or current["path"] != record["path"]:
                    issues.append({"code": "MATERIAL_CHANGED", "message": f"素材 {label} 已改变，需重新生成/登记产物并审阅。"})
            except EngineError as exc:
                issues.append({"code": "MATERIAL_UNAVAILABLE", "message": f"素材 {label}: {exc.message}"})
        return issues

    def record_review(self, project_id, slide_id, base_revision, kind, statement, reviewer="operator", evidence_id=None):
        """Local operator attestation. Adapters must not expose this as an MCP tool."""
        _text(kind, "kind")
        if kind not in REVIEW_KINDS:
            _fail("INVALID_REVIEW", "审阅类型必须为 content、evidence 或 visual。")
        _text(statement, "实际审阅陈述", required=True); _text(reviewer, "审阅者", required=True)
        with self._transaction() as db:
            _, state = self._read(db, project_id)
            slide = self._slide(state, slide_id)
            self._revision(slide["revision"], base_revision)
            eid = ""
            if kind == "content":
                if not self._has_user_input(slide) or not (slide["takeaway"].strip() or slide["keyPoints"].strip()):
                    _fail("CONTENT_INCOMPLETE", "保留用户原意，并填写当前页拟用表达后再审阅。")
                subject = self._content_hash(state, slide)
            elif kind == "evidence":
                item = next((e for e in slide["evidence"] if e["id"] == evidence_id), None)
                if not item or not all(item.get(k, "").strip() for k in ("claim", "source", "locator", "scope")):
                    _fail("EVIDENCE_INCOMPLETE", "核验记录需要主张、真实出处、定位与口径。")
                eid = item["id"]; subject = self._evidence_hash(state, slide, item)
            else:
                artifact = self._artifact(db, project_id, slide, state)
                if not artifact:
                    _fail("ARTIFACT_MISSING", "没有与当前页面版本绑定的实际文件。")
                issues = self._file_issues(project_id, artifact)
                if issues:
                    _fail("ARTIFACT_INVALID", "实际文件登记需要更新。", issues)
                subject = _hash(artifact)
            review_id = "R-" + uuid.uuid4().hex
            db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (review_id, project_id, slide_id, slide["revision"], kind, eid, subject, reviewer, statement, _now()))
            self._event(db, project_id, slide_id, "operator-review-recorded", {"reviewId": review_id, "kind": kind,
                "revision": slide["revision"], "subjectHash": subject, "assurance": "local-operator-attestation"})
        return self.get_slide(project_id, slide_id)

    def _gate_slide(self, db, pid, state, slide):
        view = self._view_slide(db, pid, state, slide)
        issues = []
        def add(code, message): issues.append({"code": code, "message": message})
        project = state["project"]
        if not project.get("purpose") or not project.get("audience", "").strip() or not project.get("outcome", "").strip() or not project.get("delivery"):
            add("PROJECT_BRIEF_INCOMPLETE", "明确用途、主要听众、预期结果与展示方式。")
        if project.get("purpose") == "other" and not project.get("purposeOther", "").strip():
            add("PROJECT_BRIEF_INCOMPLETE", "说明其他用途的具体内容。")
        if project.get("dataPolicy", "undecided") == "undecided":
            add("DATA_POLICY_UNDECIDED", "明确资料由用户提供、需要研究、混合，或无需外部资料。")
        if not slide["role"] or not self._has_user_input(slide) or not (slide["takeaway"].strip() or slide["keyPoints"].strip()):
            add("CONTENT_INCOMPLETE", "明确页面类型、用户原意与拟用表达。")
        if not slide["templateId"]:
            add("LAYOUT_UNDECIDED", "选择内置模板或 custom，并提供实际版式。")
        if not view["reviews"]["content"]:
            add("CONTENT_REVIEW_MISSING", "当前内容版本没有对应的操作者确认记录。")
        logo = state["project"].get("logoPolicy", "undecided")
        if logo == "undecided":
            add("LOGO_UNDECIDED", "明确是否使用 Logo。")
        elif logo in {"company", "joint"}:
            try:
                self._file_record(pid, state["project"].get("logoReference", ""))
            except EngineError:
                add("LOGO_FILE_MISSING", "将准确 Logo 文件放入项目目录，并填写相对路径。")
        if slide["evidenceRequired"] == "undecided":
            add("EVIDENCE_REQUIREMENT_UNDECIDED", "明确本页是否包含需要依据的事实。")
        if slide["evidenceRequired"] == "yes" and not slide["evidence"]:
            add("EVIDENCE_MISSING", "登记支撑本页主张的来源。")
        if slide["evidenceRequired"] == "no" and slide["evidence"]:
            add("EVIDENCE_POLICY_CONFLICT", "本页已有事实依据条目，不能同时标记为无需依据。")
        for e in view["slide"]["evidence"]:
            if e["status"] != "verified":
                add("EVIDENCE_REVIEW_MISSING", "依据 " + e["id"] + " 尚无与当前内容绑定的核验记录。")
        for asset in slide["assets"]:
            if not asset.get("required"):
                continue
            if asset.get("status") != "provided":
                add("ASSET_MISSING", "必需素材 " + asset["id"] + " 尚未提供。")
                continue
            try:
                self._file_record(pid, asset.get("reference", ""))
            except EngineError:
                add("ASSET_FILE_MISSING", "必需素材 " + asset["id"] + " 没有项目目录中的实际文件。")
        artifact = view["artifact"]
        if not artifact:
            add("ARTIFACT_MISSING", "当前版本没有已读取、计算哈希的页面源文件和预览。")
        else:
            issues.extend(view["integrityIssues"])
            if not view["reviews"]["visual"]:
                add("VISUAL_REVIEW_MISSING", "登记后尚无对应文件哈希的视觉审阅记录。")
        return {"slideId": slide["id"], "revision": slide["revision"], "ready": not issues, "issues": issues,
                "contentHash": view["contentHash"], "artifact": artifact, "assurance": "operator-attestation-and-file-integrity"}

    def gate(self, project_id, slide_id=None):
        with self._connection() as db:
            row, state = self._read(db, project_id)
            selected = [self._slide(state, slide_id)] if slide_id else [s for s in state["slides"] if not s["archived"]]
            checks = [self._gate_slide(db, project_id, state, s) for s in selected]
        return {"projectId": project_id, "projectRevision": row["revision"], "ready": bool(checks) and all(s["ready"] for s in checks),
                "slides": checks, "limitations": ["不认证操作者的人类身份", "不自动证明来源真实或支撑语义", "不自动证明视觉质量", "不验证实际 PPT 文件中其他页未变化", "不能约束绕过本引擎的文件修改"]}

    def next_action(self, project_id, slide_id=None):
        data = self.get_project(project_id); state = data["workspace"]
        slides = [s for s in state["slides"] if not s["archived"]]
        if not slides:
            return {"action": "collect_outline", "questions": [{"id": "outline", "question": "请提供每页的想法，或先提供当前页原话。", "options": ["已有逐页大纲", "从零散想法整理", "沿用已有演示稿"]}], "project": state["project"]}
        slide = self._slide(state, slide_id or state.get("selectedSlideId") or slides[0]["id"])
        check = self.gate(project_id, slide["id"])["slides"][0]
        questions = []
        p = state["project"]
        if not p["purpose"]:
            questions.append({"id": "purpose", "question": "这份材料主要用于什么？", "options": ["汇报情况", "说明方案并促成决定", "讲解知识"], "allowFreeText": True})
        if not p["audience"].strip():
            questions.append({"id": "audience", "question": "主要听众是谁，他们已经了解什么？", "options": [], "allowFreeText": True})
        if not self._has_user_input(slide):
            questions.append({"id": "user_intent", "question": "你希望这一页表达什么？请提供原话或原稿位置。", "options": [], "allowFreeText": True})
        if not p["outcome"].strip():
            questions.append({"id": "outcome", "question": "希望听众看完后理解什么或采取什么行动？", "options": ["了解现状", "对齐方案", "作出决定或行动"], "allowFreeText": True})
        if not p["delivery"]:
            questions.append({"id": "delivery", "question": "这份材料将怎样被使用？", "options": ["现场讲解", "独立阅读", "两者兼用"], "allowFreeText": True})
        if p["dataPolicy"] == "undecided":
            questions.append({"id": "data_policy", "question": "所需事实资料由谁提供？", "options": ["用户提供真实资料", "协助查找并提交核验", "无需外部事实资料"], "allowFreeText": True})
        if p["purpose"] == "other" and not p["purposeOther"].strip():
            questions.append({"id": "purpose_other", "question": "请说明这份材料的具体用途。", "options": [], "allowFreeText": True})
        if not (slide["takeaway"].strip() or slide["keyPoints"].strip()):
            questions.append({"id": "message", "question": "这一页主要帮助读者做哪件事？", "options": ["认识对象", "理解过程或原因", "比较并作出选择"], "allowFreeText": True})
        if slide["evidenceRequired"] == "undecided":
            questions.append({"id": "evidence", "question": "本页是否使用需要证明的事实或数据？", "options": ["需要，已有资料", "需要，仍需查找", "只表达明确的计划或观点"], "allowFreeText": True})
        if p["logoPolicy"] == "undecided":
            questions.append({"id": "logo", "question": "本次怎样处理 Logo？", "options": ["使用准确的公司 Logo", "不使用 Logo", "联合品牌 Logo"], "allowFreeText": True})
        codes = {i["code"] for i in check["issues"]}
        if questions:
            action = "clarify_current_page"
        elif codes & {"ASSET_MISSING", "ASSET_FILE_MISSING", "LOGO_FILE_MISSING", "EVIDENCE_MISSING", "EVIDENCE_POLICY_CONFLICT"}:
            action = "collect_required_materials"
        elif "EVIDENCE_REVIEW_MISSING" in codes:
            action = "request_evidence_review"
        elif codes & {"CONTENT_INCOMPLETE", "PROJECT_BRIEF_INCOMPLETE", "LAYOUT_UNDECIDED", "DATA_POLICY_UNDECIDED"}:
            action = "resolve_page_gaps"
        elif "CONTENT_REVIEW_MISSING" in codes:
            action = "request_content_review"
        elif "ARTIFACT_MISSING" in codes:
            action = "render_current_page_with_external_tool"
        elif codes & {"ARTIFACT_CHANGED", "FILE_NOT_FOUND", "OBJECT_MAP_MISSING", "PATH_OUTSIDE_WORKSPACE",
                      "MATERIAL_CHANGED", "MATERIAL_UNAVAILABLE", "MATERIAL_SNAPSHOT_MISSING"}:
            action = "repair_artifact_registration"
        elif "VISUAL_REVIEW_MISSING" in codes:
            action = "request_visual_review"
        elif codes:
            action = "resolve_page_gaps"
        else:
            action = "ready_for_release_manifest"
        template = self.get_template(slide["templateId"]) if slide["templateId"] not in {"", "custom"} else None
        return {"action": action, "projectId": project_id, "slideId": slide["id"], "revision": slide["revision"],
                "questions": questions[:3], "pendingQuestionCount": max(0, len(questions) - 3),
                "context": {"project": p, "currentPage": self.get_slide(project_id, slide["id"])["slide"],
                            "template": template, "otherPageTitles": [{"id": s["id"], "title": s["title"]} for s in slides if s["id"] != slide["id"]]},
                "issues": check["issues"], "draftAllowed": self._has_user_input(slide),
                "draftRule": "缺资料可做明确标注的结构草稿；当前问题只影响依赖它的工作。正式清单需通过 gate。"}

    def _templates(self):
        if self._templates_cache is None:
            try:
                payload = json.loads(self.templates_path.read_text(encoding="utf-8"))
                entries = payload["templates"] if isinstance(payload, dict) else payload
                self._templates_cache = {t["id"]: t for t in entries}
                # Studio exposes additional local, opening and variant templates.
                # Keep explicitly supplied rule files isolated from that catalog.
                if self.templates_path == Path(__file__).parent / "data" / "template-rules.json":
                    from .templates import catalog
                    for entry in catalog():
                        self._templates_cache.setdefault(entry["id"], entry)
                self._template_structure = payload.get("structure", {}) if isinstance(payload, dict) else {}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                _fail("TEMPLATE_DATA_MISSING", "缺少有效的内置模板数据。", str(exc))
        return self._templates_cache

    def list_templates(self):
        return {"templates": [{"id": t["id"], "title": t["title"], "family": t["family"], "use": t["use"]} for t in self._templates().values()],
                "customAllowed": True}

    def get_template(self, template_id):
        _text(template_id, "template_id", required=True)
        value = self._templates().get(template_id)
        if value is None:
            _fail("UNKNOWN_TEMPLATE", "未找到模板。", {"templateId": template_id})
        return {"template": copy.deepcopy(value), "conditions": copy.deepcopy(self._template_structure.get("variants", {}).get(template_id, []))}

    def export_workspace(self, project_id, for_html=False):
        if type(for_html) is not bool:
            _fail("INVALID_INPUT", "for_html 必须为布尔值。")
        with self._connection() as db:
            _, state = self._read(db, project_id)
            output = copy.deepcopy(state)
            output["slides"] = [self._view_slide(db, project_id, state, s)["slide"] for s in state["slides"]]
            if for_html:
                for slide in output["slides"]:
                    parts = [slide["userIntent"]] if slide["userIntent"] else []
                    for entry in slide.pop("userInputs", []):
                        parts.append("【追加原话｜客户端转录，未认证身份】\n"
                                     + "记录 ID：" + entry["id"] + "\n"
                                     + "来源定位：" + (entry["sourceNote"] or "未填写") + "\n"
                                     + "记录时间：" + entry["recordedAt"] + "\n"
                                     + "原话：\n" + entry["text"])
                    combined = "\n\n---\n\n".join(parts)
                    units = len(combined.encode("utf-16-le", "surrogatepass")) // 2
                    if units > HTML_TEXT_LIMIT:
                        _fail("HTML_EXPORT_TOO_LARGE", "合并原话超过旧 HTML 的文本上限；为避免静默丢失，请使用默认完整导出。",
                              {"slideId": slide["id"], "utf16Units": units, "limit": HTML_TEXT_LIMIT})
                    slide["userIntent"] = combined
                output["htmlExportNotice"] = (
                    "供旧 HTML v1 使用的兼容副本：追加原话、记录 ID、来源定位和时间已合并进 userIntent；"
                    "结构化来源记录被简化为文字，userInputs 不重复输出。数据库中的原始思想与追加记录未改变。"
                    "来源仍为客户端转录，未认证操作者身份。"
                )
            return output

    def history(self, project_id, slide_id=None):
        with self._connection() as db:
            self._read(db, project_id)
            if slide_id:
                rows = db.execute("SELECT * FROM events WHERE project_id=? AND slide_id=? ORDER BY seq", (project_id, slide_id)).fetchall()
                versions = db.execute("SELECT revision,created_at FROM slide_revisions WHERE project_id=? AND slide_id=? ORDER BY revision", (project_id, slide_id)).fetchall()
            else:
                rows = db.execute("SELECT * FROM events WHERE project_id=? ORDER BY seq", (project_id,)).fetchall()
                versions = []
        return {"projectId": project_id, "slideId": slide_id, "revisions": [dict(x) for x in versions],
                "events": [{**dict(row), "details": json.loads(row["details"])} for row in rows]}

    def release_manifest(self, project_id):
        # The gate and state snapshot share one DB transaction. Files are rehashed
        # immediately here; no promise is made about arbitrary later mutations.
        with self._transaction() as db:
            row, state = self._read(db, project_id)
            slides = [s for s in state["slides"] if not s["archived"]]
            checks = [self._gate_slide(db, project_id, state, s) for s in slides]
            if not checks or any(not c["ready"] for c in checks):
                _fail("RELEASE_GATE_FAILED", "交付清单尚未满足记录与文件完整性条件。", checks)
            manifest = {"type": "ppt-workbench-release-manifest", "schemaVersion": 1,
                        "projectId": project_id, "projectRevision": row["revision"], "createdAt": _now(),
                        "slides": checks, "assurance": "local-operator-attestation-and-file-integrity",
                        "limitations": ["这是记录与文件哈希清单，不是已生成的 PPT", "本地审阅记录不认证人类身份", "语义真实性、视觉质量和实际跨页改动范围依赖外部检查"]}
            directory = self._inside(self.project_dir(project_id) / "releases", self.project_dir(project_id))
            directory.mkdir(exist_ok=True)
            path = directory / ("release-" + uuid.uuid4().hex + ".json")
            payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            with path.open("xb") as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            self._event(db, project_id, None, "release-manifest-created", {"path": str(path.relative_to(self.project_dir(project_id))), "sha256": hashlib.sha256(payload).hexdigest()})
        return {"manifestPath": str(path), "manifest": manifest}
