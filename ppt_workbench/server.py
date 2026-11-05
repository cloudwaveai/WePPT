"""Loopback-only chat/preview HTTP companion; no cloud deployment or arbitrary shell API."""
from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
import base64
import hashlib
import copy
import html
import mimetypes
import os
from pathlib import Path
import secrets
import stat
import sys
import threading
from urllib.parse import parse_qs, urlparse, urlencode
import webbrowser

from .core import EngineError
from .studio import Studio
from .templates import catalog, sample_scene
from .rendering import render_html
from . import guide_store
from . import editor
from . import owners


# Exact bundled paths only; no user-controlled filesystem path or local POTX access.
REFERENCE_ASSETS = frozenset({"/reference-library/catalog.json"} | {
    f"/reference-library/previews/{group:02}-{page:02}.png"
    for group, count in ((1, 10), (2, 2), (3, 14), (4, 18))
    for page in range(1, count + 1)
})


class ProjectServerLock:
    """An OS-owned lock survives stale files, but not a terminated server process."""

    def __init__(self, path):
        self.file = open(path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0, 2)
                if self.file.tell() == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise EngineError("STUDIO_ALREADY_RUNNING", "这个项目已有工作台在运行，请打开已有窗口或先关闭旧服务。") from exc

    def close(self):
        if self.file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, studio, token=None):
        self.studio = studio
        self.public_origin = os.environ.get("WEPPT_PUBLIC_ORIGIN", "").rstrip("/")
        public = urlparse(self.public_origin)
        if self.public_origin and (public.scheme != "https" or not public.hostname
                or public.username or public.password or public.path or public.query or public.fragment):
            raise EngineError("INVALID_PUBLIC_ORIGIN", "公网入口必须是无路径的 HTTPS origin。")
        self.public_host = public.netloc if self.public_origin else None
        self.open_access = os.environ.get("WEPPT_PUBLIC_ACCESS") == "open"
        if self.open_access and not self.public_origin:
            raise EngineError("INVALID_PUBLIC_ORIGIN", "开放开发访问需要明确的 HTTPS origin。")
        token_path = os.environ.get("WEPPT_TOKEN_FILE")
        if token is None and token_path:
            path = Path(token_path)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise EngineError("INVALID_TOKEN_FILE", "访问凭据必须是仅当前所有者可读写的普通文件。")
            token = path.read_text().strip()
            if len(token) < 32 or not all(c.isalnum() or c in "-_" for c in token) or not token.isascii():
                raise EngineError("INVALID_TOKEN_FILE", "访问凭据必须是至少 32 字符的安全随机文本。")
        if self.public_origin and not token and not self.open_access:
            raise EngineError("PUBLIC_AUTH_REQUIRED", "公网部署需要持久化访问凭据。")
        self.token = token or secrets.token_urlsafe(32)
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.project_lock = ProjectServerLock(studio.wb.project_dir(studio.project_id) / "studio-server.lock")
        self.projects_lock = threading.RLock()
        self.studios = {studio.project_id: studio}
        self.project_locks = {studio.project_id: self.project_lock}
        try:
            super().__init__(address, StudioHandler)
            studio.recover_interrupted_jobs()
            from .image_generation import ImageJobs
            ImageJobs(studio).recover_interrupted()
        except BaseException:
            self.project_lock.close()
            raise

    def server_close(self):
        self.stop_event.set()
        try:
            super().server_close()
        finally:
            for lock in self.project_locks.values():
                lock.close()

    def open_project(self, project_id):
        with self.projects_lock:
            if project_id in self.studios:
                return self.studios[project_id]
            self.studio.wb.get_project(project_id)
            lock = ProjectServerLock(self.studio.wb.project_dir(project_id) / "studio-server.lock")
            try:
                studio = Studio(self.studio.root, project_id, create=False)
                studio.recover_interrupted_jobs()
                from .image_generation import ImageJobs
                ImageJobs(studio).recover_interrupted()
            except BaseException:
                lock.close()
                raise
            self.studios[project_id] = studio
            self.project_locks[project_id] = lock
            return studio

    def start_worker(self):
        """Keep a worker available for UI mode changes and local outline jobs."""
        if self.worker_thread and self.worker_thread.is_alive():
            return

        # Reopen durable work even when its browser never returns after restart.
        with self.studio.wb._connection() as db:
            pending = db.execute("""SELECT project_id FROM studio_background_tasks WHERE status IN ('queued','running')
                UNION SELECT project_id FROM studio_jobs WHERE status IN ('queued','running')""").fetchall()
        for row in pending:
            self.open_project(row['project_id'])

        def work():
            while not self.stop_event.is_set():
                try:
                    with self.projects_lock:
                        studios = list(self.studios.values())
                    processed = False
                    for studio in studios:
                        if self.stop_event.is_set():
                            break
                        from .background_tasks import run_pending as run_background
                        background_result = run_background(studio)
                        if background_result is not None:
                            processed = True
                            if background_result.get("projectId"):
                                self.open_project(background_result["projectId"])
                        processed = studio.run_pending() or processed
                        if not getattr(studio, '_image_worker', None) or not studio._image_worker.is_alive():
                            from .image_generation import ImageJobs
                            image_jobs = ImageJobs(studio)
                            with studio.wb._connection() as db:
                                batch = db.execute("SELECT id FROM image_generation_batches WHERE project_id=? AND status='pending' ORDER BY created_at LIMIT 1", (studio.project_id,)).fetchone()
                            if batch:
                                def run_images(jobs=image_jobs, batch_id=batch['id'], wb=studio.wb, pid=studio.project_id):
                                    from .codex_image_provider import CodexImageProvider
                                    from . import owners
                                    scope = owners.set_scoped(owners.project_owner(wb, pid))
                                    try:
                                        jobs.run_batch(batch_id, CodexImageProvider())
                                    finally:
                                        owners.reset(scope)
                                studio._image_worker = threading.Thread(target=run_images, daemon=True, name='ppt-image-worker')
                                studio._image_worker.start()
                                processed = True
                except Exception as exc:
                    print(f"PPT Studio worker: {type(exc).__name__}", file=sys.stderr)
                    processed = False
                if not processed:
                    self.stop_event.wait(0.5)

        self.worker_thread = threading.Thread(target=work, daemon=True, name="ppt-agent-worker")
        self.worker_thread.start()


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "PPTStudio/0.4"

    def log_message(self, *args):
        # Access URLs can carry the one-time browser bootstrap token.
        pass

    def _host_ok(self):
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.server.public_host:
            hosts.add(self.server.public_host)
        return self.headers.get("Host") in hosts

    def _authorized(self):
        if self.server.open_access:
            return True
        given = self.headers.get("X-Studio-Token", "")
        if given and secrets.compare_digest(given, self.server.token):
            return True
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return "ppt_studio" in cookies and secrets.compare_digest(cookies["ppt_studio"].value, self.server.token)
        except Exception:
            return False

    def _json(self, value, status=200):
        self._send(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def _send(self, data, mime, status=200, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", (headers or {}).get("Cache-Control", "no-store"))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
        for key, value in (headers or {}).items():
            if key != "Cache-Control":
                self.send_header(key, value)
        if getattr(self, "_owner_cookie", None):
            self.send_header("Set-Cookie", f"{owners.COOKIE}={self._owner_cookie}; HttpOnly; SameSite=Lax; Path=/; Max-Age=63072000"
                             + ("; Secure" if self.server.public_origin else ""))
            self._owner_cookie = None
        self.end_headers()
        self.wfile.write(data)

    def _scene_html(self, studio, scene, *, interactive=True, saved_scene=None):
        """Share original image bytes between browser views; exports stay self-contained."""
        rendered = render_html(scene, interactive=interactive)
        # Sandboxed frames omit Strict cookies on image subrequests. Keep private
        # deployments self-contained; do not loosen authentication or sandboxing.
        if not self.server.open_access:
            return rendered
        for obj in (saved_scene or scene)["objects"]:
            if obj["type"] != "image":
                continue
            raw = base64.b64decode(obj["src"].split(",", 1)[1])
            url = "/api/scene-image?" + urlencode({"project": studio.project_id,
                "slideId": scene["slideId"], "objectId": obj["id"], "sha": hashlib.sha256(raw).hexdigest()})
            rendered = rendered.replace(obj["src"], html.escape(url, quote=True))
        return rendered

    def _error(self, exc):
        if isinstance(exc, EngineError):
            status = (409 if exc.code in {"STALE_REVISION", "SCENE_STALE", "PROJECT_NOT_EMPTY", "JOB_CLOSED"}
                      else 404 if exc.code in {"PROJECT_NOT_FOUND", "TEMPLATE_NOT_FOUND"} else 400)
            self._json({"error": exc.to_dict()}, status)
        else:
            self._json({"error": {"code": "INTERNAL_ERROR", "message": "操作未完成，请检查本地服务输出。"}}, 500)
            print(f"PPT Studio error: {exc!r}", file=sys.stderr)

    def _with_owner(self, handler):
        """Open-access deployments scope projects to an anonymous owner cookie."""
        self._owner_cookie = None
        token = None
        if self.server.open_access:
            try:
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                token = cookies[owners.COOKIE].value if owners.COOKIE in cookies else None
            except Exception:
                token = None
            if not owners.valid(token):
                token = self._owner_cookie = owners.new_token()
        self._owner_token = token
        marker = owners.set_current(token)
        try:
            handler()
        finally:
            owners.reset(marker)

    def _project_studio(self, project_id, path=""):
        if project_id and path != "/api/scene-image" and not owners.project_visible(self.server.studio.wb, project_id):
            raise EngineError("PROJECT_NOT_FOUND", "没有找到这个项目，或它属于其他人的空间。")
        return self.server.open_project(project_id) if project_id else self.server.studio

    def do_GET(self):
        self._with_owner(self._do_get)

    def do_POST(self):
        self._with_owner(self._do_post)

    def _do_get(self):
        if not self._host_ok():
            self._json({"error": {"code": "HOST_REJECTED", "message": "只接受本机工作台地址。"}}, 403)
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path
        if path == "/" and "token" in query and secrets.compare_digest(query["token"][0], self.server.token):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "ppt_studio=" + self.server.token + "; HttpOnly; SameSite=Strict; Path=/"
                             + ("; Secure" if self.server.public_origin else ""))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._authorized():
            message = "WePPT 开发环境需要授权访问，请使用管理员提供的专用登录链接。" if self.server.public_origin else "请使用启动命令输出的完整链接打开工作台。"
            self._send(message.encode(), "text/plain; charset=utf-8", 401)
            return
        try:
            project_id = self.headers.get("X-WePPT-Project") or query.get("project", [None])[0]
            studio = self._project_studio(project_id, path)
            if path == "/api/projects":
                from .background_tasks import project_activity
                projects = [{**p, "activity": project_activity(studio.wb, p["projectId"])} for p in owners.list_projects(studio.wb)]
                self._json({"projects": projects, "activeProjectId": studio.project_id,
                            "personalSpace": owners.current() is not None})
            elif path == "/api/source":
                source = studio.wb.project_dir(studio.project_id) / "import/source.pptx"
                if not source.is_file():
                    raise EngineError("NOT_FOUND", "当前项目没有导入的原稿。")
                self._send(source.read_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation", headers={"Content-Disposition": 'attachment; filename="original.pptx"'})
            elif path == "/api/me":
                self._json({"personalSpace": owners.current() is not None, "code": self._owner_token})
            elif path == "/api/state":
                state = studio.state()
                if (query.get("sinceProject", [None])[0] == studio.project_id
                        and query.get("since", [None])[0] == str(state["version"])):
                    self._json({"unchanged": True, "projectId": studio.project_id, "version": state["version"]})
                else:
                    self._json(state)
            elif path == "/api/scene":
                current = studio.get_scene(query.get("slide", [None])[0])
                if query.get("metadata", [None])[0] == "1":
                    current = copy.deepcopy(current)
                    for obj in current["scene"]["objects"]:
                        if obj["type"] == "image":
                            obj["src"] = "scene-image:" + obj["id"]
                    for change in current.get("changes", []):
                        for side in ("before", "after"):
                            if isinstance(change.get(side), dict) and "src" in change[side]:
                                change[side]["src"] = "scene-image:" + change.get("objectId", "")
                self._json(current)
            elif path == "/api/scene-image":
                current = studio.get_scene(query.get("slideId", [None])[0])
                obj = next((o for o in current["scene"]["objects"]
                            if o["id"] == query.get("objectId", [None])[0] and o["type"] == "image"), None)
                raw = base64.b64decode(obj["src"].split(",", 1)[1]) if obj else b""
                if not obj or hashlib.sha256(raw).hexdigest() != query.get("sha", [None])[0]:
                    self._json({"error": {"code": "IMAGE_CHANGED", "message": "图片已变化，请刷新页面。"}}, 404)
                else:
                    self._send(raw, obj["src"].split(";", 1)[0][5:],
                               headers={"Cache-Control": "private, max-age=3600, immutable"})
            elif path == "/api/editor/history":
                self._json(editor.history_status(studio, query.get("slide", [None])[0]))
            elif path in {"/api/guide/draft", "/api/guide/experience"}:
                self._json(guide_store.load(studio, path.rsplit("/", 1)[-1]))
            elif path == "/api/derive/mapping":
                from .derived import mapping
                self._json(mapping(studio))
            elif path == "/api/template-packs":
                from .template_packs import cards
                self._json(cards(studio))
            elif path == "/api/template-packs/preview":
                from .template_packs import preview
                scene = preview(query.get('pack', [None])[0], query.get('role', ['content'])[0])
                self._send(render_html(scene, interactive=False).encode(), 'text/html; charset=utf-8')
            elif path == "/api/user-templates":
                from .user_templates import list_templates
                self._json({"templates": list_templates(studio)})
            elif path == "/api/user-templates/image":
                from .user_templates import image
                file, sha = image(studio, query.get("id", [None])[0], int(query.get("index", ["0"])[0] or 0))
                if sha != query.get("sha", [None])[0]:
                    self._json({"error": {"code": "ASSET_CHANGED", "message": "图片已更新，请刷新列表。"}}, 404)
                else:
                    self._send(file.read_bytes(), "image/png",
                               headers={"Cache-Control": "private, max-age=31536000, immutable"})
            elif path == "/api/templates":
                self._json({"templates": catalog()})
            elif path == "/api/templates/recommendations":
                self._json(studio.template_recommendations(query.get("slideId", [None])[0]))
            elif path == "/api/templates/preview":
                revision = query.get("sceneRevision", [None])[0]
                if revision is not None and not revision.isdecimal():
                    raise EngineError("INVALID_REQUEST", "页面版本无效。")
                preview = studio.preview_template(query.get("template", [None])[0],
                    query.get("slideId", [None])[0], int(revision) if revision is not None else None)
                saved = studio.get_scene(preview["slideId"])["scene"] if preview["slideId"] else None
                preview_html = (self._scene_html(studio, preview["scene"], interactive=False, saved_scene=saved)
                                if saved else render_html(preview["scene"], interactive=False))
                if query.get("format", [None])[0] == "json":
                    self._json({"html": preview_html, "slideId": preview["slideId"], "sceneRevision": preview["sceneRevision"]})
                else:
                    self._send(preview_html.encode(), "text/html; charset=utf-8")
            elif path.startswith("/api/preview/"):
                sid = path.rsplit("/", 1)[-1]
                current = studio.get_scene(sid)
                # Render the saved scene with current editor interactions. Older
                # projects gain editing gestures without rewriting their artifacts.
                self._send(self._scene_html(studio, current["scene"]).encode(), "text/html; charset=utf-8")
            elif path == "/api/export":
                result = studio.export(query.get("format", ["html"])[0], query.get("slide", [None])[0], query.get("strict", ["false"])[0].lower() in {"true", "1"})
                file = Path(result["path"])
                self._send(file.read_bytes(), "text/html; charset=utf-8" if result["format"] == "html" else "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                           headers={"Content-Disposition": 'attachment; filename="' + file.name + '"'})
            elif path in REFERENCE_ASSETS:
                root = (Path(__file__).parent / "web" / "reference-library").resolve()
                file = Path(__file__).parent / "web" / path[1:]
                # Also reject a replaced bundled asset that resolves through a symlink.
                if not file.resolve().is_relative_to(root) or not file.is_file():
                    self._json({"error": {"code": "NOT_FOUND", "message": "没有这个参考资源。"}}, 404)
                else:
                    raw = file.read_bytes()
                    digest = hashlib.sha256(raw).hexdigest()
                    version = query.get('v', [None])[0]
                    if version is not None and version != digest:
                        self._json({"error": {"code": "ASSET_CHANGED", "message": "参考图片已更新，请刷新样式列表。"}}, 404)
                        return
                    headers = {"ETag": '"' + digest + '"', "Cache-Control":
                               "private, max-age=31536000, immutable" if version else "private, no-cache"}
                    mime = "image/png" if file.suffix == ".png" else "application/json; charset=utf-8"
                    if self.headers.get('If-None-Match') == headers['ETag']:
                        self._send(b'', mime, 304, headers)
                    else:
                        self._send(raw, mime, headers=headers)
            elif path in {"/", "/index.html", "/app.js", "/preview-loader.js", "/style.css", "/editor.css", "/guide.html", "/guide.js", "/guide.css", "/guide-experience.json", "/reference-library.html", "/reference-library.js", "/reference-library.css"}:
                file = Path(__file__).parent / "web" / ("index.html" if path in {"/", "/index.html"} else path[1:])
                self._send(file.read_bytes(), {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}[file.suffix])
            elif path == "/favicon.ico":
                self._send(b"", "image/x-icon", 204)
            else:
                self._json({"error": {"code": "NOT_FOUND", "message": "没有这个地址。"}}, 404)
        except Exception as exc:
            self._error(exc)

    def _do_post(self):
        origin = self.headers.get("Origin")
        origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if self.server.public_origin:
            origins.add(self.server.public_origin)
        if not self._host_ok() or not self._authorized() or (origin and origin not in origins):
            self._json({"error": {"code": "REQUEST_REJECTED", "message": "请求不属于当前本机工作台。"}}, 403)
            return
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise EngineError("INVALID_CONTENT_TYPE", "需要 JSON 请求。")
            length = int(self.headers.get("Content-Length", 0))
            if length < 1 or length > 30_000_000:
                raise EngineError("REQUEST_TOO_LARGE", "请求为空或过大。")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise EngineError("INVALID_REQUEST", "请求体必须为 JSON 对象。")
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            project_id = self.headers.get("X-WePPT-Project") or query.get("project", [None])[0]
            studio = self._project_studio(project_id)
            path = parsed.path
            if path == "/api/projects":
                title = body.get("title")
                if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
                    raise EngineError("INVALID_REQUEST", "请输入 1–120 字的项目名称。")
                project_id = "project-" + secrets.token_hex(8)
                studio.wb.create_project(project_id, {"title": title.strip()})
                owners.claim_project(studio.wb, project_id)
                opened = self.server.open_project(project_id)
                from .model_profiles import selected, select
                chosen = selected(studio)
                if chosen and chosen.get("model") != "unavailable":
                    select(opened, chosen["id"])
                else:
                    opened.set_agent_mode(studio.agent_mode)
                result = {"projectId": project_id}
            elif path == "/api/projects/import":
                from .presentation_import import import_presentation
                result = import_presentation(studio, body.get("filename"), body.get("base64"))
                self.server.open_project(result["projectId"])
            elif path == "/api/me/adopt":
                code = body.get("code")
                if not owners.current() or not owners.valid(code):
                    raise EngineError("INVALID_SPACE_CODE", "空间码无效。")
                self._owner_cookie = code
                result = {"adopted": True}
            elif path == "/api/chat":
                result = studio.enqueue(body.get("message"), body.get("slideId"), body.get("objectId"), body.get("clientMessageId"),
                                        body.get("attachments"), body.get("choiceMessageId"), body.get("replyToDeckPage", False),
                                        scope=body.get("scope", "page"), auto_resume=body.get("autoResume", False))
            elif path in {"/api/guide/draft", "/api/guide/experience"}:
                result = guide_store.save(studio, path.rsplit("/", 1)[-1], body.get("revision"), body.get("document"))
            elif path == "/api/template-packs/select":
                from .template_packs import select
                result = select(studio, body.get('packId'), body.get('projectRevision'))
            elif path == "/api/template-packs/apply":
                from .derived import derive
                result = derive(studio, 'template', style_id=body.get('packId'), source_revision=body.get('projectRevision'))
                self.server.open_project(result['projectId'])
            elif path == "/api/templates/match":
                from .template_matching import match
                result = match(studio, body.get("slideId"), body.get("sceneRevision"), body.get("instruction", ""))
            elif path == "/api/templates/adapt":
                from .template_adaptation import propose
                result = propose(studio,body.get("templateId"),body.get("slideId"),body.get("sceneRevision"),body.get("approach","creative"))
                saved=studio.get_scene(result["slideId"])["scene"]
                result["html"]=self._scene_html(studio,result.pop("scene"),interactive=False,saved_scene=saved)
            elif path == "/api/templates/apply":
                from .template_adaptation import apply
                result = apply(studio,body.get("proposalId"))
            elif path == "/api/template":
                result = studio.select_template(body.get("templateId"), body.get("slideId"), body.get("sceneRevision"))
            elif path == "/api/templates/recommendations":
                from .jev_recommendations import recommend
                result = recommend(studio, body.get("slideId"), body.get("sceneRevision"))
            elif path == "/api/diagram/image":
                from .diagram_design import submit_fallback
                result = submit_fallback(studio, body.get('slideId'), body.get('sceneRevision'), body.get('requestId'))
            elif path == "/api/document":
                from .document_editing import operate
                result = operate(studio, body.get("action"), body.get("projectRevision"), body.get("slideId"), body.get("afterId"))
            elif path == "/api/edit":
                result = studio.edit_scene(body.get("slideId"), body.get("sceneRevision"), body.get("changes"))
            elif path == "/api/editor/history":
                result = editor.travel(studio, body.get("slideId"), body.get("sceneRevision"), body.get("action"))
            elif path == "/api/editor/suggest":
                result = editor.suggest(studio, body.get("slideId"), body.get("sceneRevision"),
                    body.get("action"), body.get("objectId"), body.get("instruction", ""))
            elif path == "/api/editor/apply":
                result = editor.apply_suggestion(studio, body.get("proposalId"))
            elif path == "/api/select":
                result = studio.select(body.get("slideId"))
            elif path == "/api/demo":
                result = studio.demo()
            elif path == "/api/review":
                result = studio.review_submission(body.get("slideId"), body.get("sceneRevision"),
                    body.get("statement") or "已查看当前页面并认可这一版表达与版式", body.get("clientMessageId"))
            elif path == "/api/review/deck":
                studio.review_deck(body.get("sceneRevisions"), body.get("statement"), body.get("clientMessageId"))
                result = studio.state()
            elif path == "/api/undo":
                result = studio.undo_submission(body.get("slideId"), body.get("sceneRevision"), body.get("clientMessageId"))
            elif path == "/api/assets":
                result = studio.upload(body.get("filename"), body.get("mime", ""), body.get("base64"))
            elif path == "/api/model":
                from .model_profiles import select
                result = select(studio, body.get("profileId"))
            elif path == "/api/agent":
                studio.set_agent_mode(body.get("mode"))
                result = studio.state()
            elif path == "/api/image-mode":
                result = studio.set_image_mode(body.get("mode"))
            elif path == "/api/palette":
                result = studio.set_palette(None if body.get("clear") is True else {"primary": body.get("primary"), "secondary": body.get("secondary")})
            elif path == "/api/palette/apply":
                result = studio.apply_palette(body.get("scope", "page"), body.get("slideId"), body.get("sceneRevision"), body.get("palette"), body.get("projectRevision"))
            elif path == "/api/user-templates":
                from .user_templates import upload
                result = upload(studio, body.get("kind"), body.get("files"))
            elif path == "/api/user-templates/rename":
                from .user_templates import rename
                result = rename(studio, body.get("id"), body.get("name"))
            elif path == "/api/user-templates/delete":
                from .user_templates import delete
                result = delete(studio, body.get("id"))
            elif path == "/api/style-templates/start":
                from .background_tasks import submit_style
                result = submit_style(studio, body.get("id"), body.get("projectRevision"))
            elif path == "/api/style-templates/analyze":
                from .user_templates import analyze_style
                result = analyze_style(studio, body.get("id"))
            elif path == "/api/style-templates/update":
                from .user_templates import update_style
                result = update_style(studio, body.get("id"), body.get("name"), body.get("profile"))
            elif path == "/api/style-templates/select":
                from .user_templates import select_style
                result = select_style(studio, body.get("id"))
            elif path == "/api/derive":
                from .derived import derive
                result = derive(studio, body.get("mode"), body.get("audience"),
                                body.get("note"), body.get("styleId"))
                owners.claim_project(studio.wb, result["projectId"])
                self.server.open_project(result["projectId"])
            elif path == "/api/logo":
                from .logo import process_logo
                result = process_logo(studio, body.get("filename", "logo"), body.get("mime"), body.get("base64"))
            elif path == "/api/logo/settings":
                from .logo import save_settings
                result = save_settings(studio, body)
            elif path == "/api/logo/place":
                from .logo import place_forced
                result = place_forced(studio, body.get("slideId"), body.get("sceneRevision"))
            elif path == "/api/logo/apply":
                from .logo import apply_logo
                result = apply_logo(studio)
            elif path == "/api/logo/remove":
                from .logo import remove_logo
                result = remove_logo(studio)
            elif path == "/api/deck/control":
                studio.control_deck(body.get("action"))
                result = studio.state()
            elif path == "/api/delivery/control":
                studio.control_delivery(body.get("action"), body.get("roundId"))
                result = studio.state()
            elif path == "/api/quality/check":
                auto_fix = body.get("autoFix", True)
                if type(auto_fix) is not bool:
                    raise EngineError("INVALID_REQUEST", "autoFix 必须为布尔值。")
                studio.check_current_quality(auto_fix=auto_fix)
                result = studio.state()
            elif path == "/api/quality/report":
                result = studio.record_browser_measurements(body.get("slideId"), body.get("sceneRevision"), body.get("report"))
            else:
                self._json({"error": {"code": "NOT_FOUND", "message": "没有这个操作。"}}, 404)
                return
            self._json(result)
        except (ValueError, TypeError) as exc:
            self._error(EngineError("INVALID_REQUEST", "请求内容无效。"))
        except Exception as exc:
            self._error(exc)


def create_http_server(root, project_id="main", port=8765, agent=None, token=None):
    studio = Studio(root, project_id)
    bind = os.environ.get("WEPPT_BIND_HOST", "127.0.0.1")
    if bind not in {"127.0.0.1", "0.0.0.0"}:
        raise EngineError("INVALID_BIND_HOST", "监听地址只支持 loopback 或显式容器地址。")
    if bind == "0.0.0.0" and not os.environ.get("WEPPT_PUBLIC_ORIGIN"):
        raise EngineError("PUBLIC_AUTH_REQUIRED", "容器对外监听需要明确的 HTTPS 入口与访问凭据。")
    server = StudioHTTPServer((bind, port), studio, token)
    try:
        if agent is not None and not studio.model_state()["selectedModelProfile"]:
            studio.set_agent_mode(agent)
    except BaseException:
        server.server_close()
        raise
    return server


def serve(root, project_id="main", port=8765, agent=None, open_browser=False, demo=False):
    from .agent_bridge import diagnose
    server = create_http_server(root, project_id, port, agent)
    if demo and not server.studio.wb.get_project(project_id)["workspace"]["slides"]:
        server.studio.demo()
    info = diagnose(server.studio.agent_mode)
    server.start_worker()
    url = (server.public_origin + "/" if server.public_origin else
           f"http://127.0.0.1:{server.server_port}/?token={server.token}")
    print(json.dumps({"url": url, "projectId": project_id, "agent": info, "root": str(server.studio.root)}, ensure_ascii=False), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_event.set()
        server.server_close()
    return 0
