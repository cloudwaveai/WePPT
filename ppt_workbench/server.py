"""Loopback-only chat/preview HTTP companion; no cloud deployment or arbitrary shell API."""
from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser

from .core import EngineError
from .studio import Studio
from .templates import catalog, sample_scene
from .rendering import render_html
from . import guide_store


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

        def work():
            while not self.stop_event.is_set():
                try:
                    with self.projects_lock:
                        studios = list(self.studios.values())
                    processed = False
                    for studio in studios:
                        if self.stop_event.is_set():
                            break
                        processed = studio.run_pending() or processed
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
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _authorized(self):
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
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, exc):
        if isinstance(exc, EngineError):
            status = 409 if exc.code in {"STALE_REVISION", "SCENE_STALE", "PROJECT_NOT_EMPTY", "JOB_CLOSED"} else 400
            self._json({"error": exc.to_dict()}, status)
        else:
            self._json({"error": {"code": "INTERNAL_ERROR", "message": "操作未完成，请检查本地服务输出。"}}, 500)
            print(f"PPT Studio error: {exc!r}", file=sys.stderr)

    def do_GET(self):
        if not self._host_ok():
            self._json({"error": {"code": "HOST_REJECTED", "message": "只接受本机工作台地址。"}}, 403)
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path
        if path == "/" and "token" in query and secrets.compare_digest(query["token"][0], self.server.token):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "ppt_studio=" + self.server.token + "; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._authorized():
            self._send("请使用启动命令输出的完整链接打开工作台。".encode(), "text/plain; charset=utf-8", 401)
            return
        try:
            project_id = self.headers.get("X-WePPT-Project") or query.get("project", [None])[0]
            studio = self.server.open_project(project_id) if project_id else self.server.studio
            if path == "/api/projects":
                self._json({"projects": studio.wb.list_projects(), "activeProjectId": studio.project_id})
            elif path == "/api/state":
                self._json(studio.state())
            elif path == "/api/scene":
                self._json(studio.get_scene(query.get("slide", [None])[0]))
            elif path in {"/api/guide/draft", "/api/guide/experience"}:
                self._json(guide_store.load(studio, path.rsplit("/", 1)[-1]))
            elif path == "/api/templates":
                self._json({"templates": catalog()})
            elif path == "/api/templates/preview":
                self._send(render_html(sample_scene(query.get("template", [None])[0]), interactive=False).encode(),
                           "text/html; charset=utf-8")
            elif path.startswith("/api/preview/"):
                sid = path.rsplit("/", 1)[-1]
                current = studio.get_scene(sid)
                # Serve the engine-registered file only after checking containment.
                preview = studio.wb._inside(Path(current["paths"]["preview"]), studio.wb.project_dir(studio.project_id))
                self._send(preview.read_bytes(), "text/html; charset=utf-8")
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
                    self._send(file.read_bytes(), "image/png" if file.suffix == ".png" else "application/json; charset=utf-8")
            elif path in {"/", "/index.html", "/app.js", "/style.css", "/guide.html", "/guide.js", "/guide.css", "/guide-experience.json", "/reference-library.html", "/reference-library.js", "/reference-library.css"}:
                file = Path(__file__).parent / "web" / ("index.html" if path in {"/", "/index.html"} else path[1:])
                self._send(file.read_bytes(), {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}[file.suffix])
            elif path == "/favicon.ico":
                self._send(b"", "image/x-icon", 204)
            else:
                self._json({"error": {"code": "NOT_FOUND", "message": "没有这个地址。"}}, 404)
        except Exception as exc:
            self._error(exc)

    def do_POST(self):
        origin = self.headers.get("Origin")
        origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
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
            studio = self.server.open_project(project_id) if project_id else self.server.studio
            path = parsed.path
            if path == "/api/projects":
                title = body.get("title")
                if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
                    raise EngineError("INVALID_REQUEST", "请输入 1–120 字的项目名称。")
                project_id = "project-" + secrets.token_hex(8)
                studio.wb.create_project(project_id, {"title": title.strip()})
                opened = self.server.open_project(project_id)
                opened.set_agent_mode(studio.agent_mode)
                result = {"projectId": project_id}
            elif path == "/api/chat":
                result = studio.enqueue(body.get("message"), body.get("slideId"), body.get("objectId"), body.get("clientMessageId"),
                                        body.get("attachments"), body.get("choiceMessageId"), body.get("replyToDeckPage", False),
                                        scope=body.get("scope", "page"), auto_resume=body.get("autoResume", False))
            elif path in {"/api/guide/draft", "/api/guide/experience"}:
                result = guide_store.save(studio, path.rsplit("/", 1)[-1], body.get("revision"), body.get("document"))
            elif path == "/api/template":
                result = studio.select_template(body.get("templateId"), body.get("slideId"), body.get("sceneRevision"))
            elif path == "/api/edit":
                result = studio.edit_scene(body.get("slideId"), body.get("sceneRevision"), body.get("changes"))
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
            elif path == "/api/agent":
                studio.set_agent_mode(body.get("mode"))
                result = studio.state()
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
    server = StudioHTTPServer(("127.0.0.1", port), studio, token)
    try:
        if agent is not None:
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
    url = f"http://127.0.0.1:{server.server_port}/?token={server.token}"
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
