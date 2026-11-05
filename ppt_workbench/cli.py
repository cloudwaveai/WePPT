"""JSON CLI adapter for the shared PPT workbench engine.

Review records are local operator attestations. Running this CLI does not
authenticate a person; shell-capable agents can run it too.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

from .core import EngineError, Workbench


class InputError(Exception):
    def __init__(self, message, code="INVALID_INPUT", details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError(message, "CLI_ARGUMENT_ERROR", {"hint": "Run pptctl --help."})


def _positive_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _parser():
    parser = Parser(prog="pptctl", description="逐页 PPT 工作流；业务结果与错误输出为 JSON。")
    parser.add_argument("--root", default=os.environ.get("PPT_WORKBENCH_ROOT", "./ppt-workbench-data"),
                        help="状态目录，默认 ./ppt-workbench-data；可用 PPT_WORKBENCH_ROOT 设置。")
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project", help="项目简报与 HTML 工作区 JSON")
    projects = project.add_subparsers(dest="project_command", required=True)
    create = projects.add_parser("create", help="创建新项目，不覆盖已有项目")
    create.add_argument("project_id")
    create.add_argument("--brief", metavar="JSON_FILE", help="项目字段对象；- 从 stdin 读取")
    importing = projects.add_parser("import", help="导入 HTML 工作区，仅创建新项目")
    importing.add_argument("project_id")
    importing.add_argument("--file", required=True, metavar="JSON_FILE", help="工作区 JSON；- 为 stdin")
    show = projects.add_parser("show")
    show.add_argument("project_id")
    update = projects.add_parser("update")
    update.add_argument("project_id")
    update.add_argument("--base-revision", required=True, type=_positive_int)
    update.add_argument("--changes", required=True, metavar="JSON_FILE", help="项目字段对象；- 为 stdin")
    exporting = projects.add_parser("export", help="导出可由 HTML 打开的工作区 JSON")
    exporting.add_argument("project_id")
    exporting.add_argument("--output", metavar="FILE", help="保存到文件；省略或 - 输出到 stdout")
    exporting.add_argument("--for-html", action="store_true",
                           help="兼容旧 HTML：把后续原话连同定位合并到导出副本，保留全部思想文字")

    slide = commands.add_parser("slide", help="逐页创建、读取、字段修改和恢复")
    slides = slide.add_subparsers(dest="slide_command", required=True)
    add = slides.add_parser("add")
    add.add_argument("project_id")
    add.add_argument("--title", required=True)
    add.add_argument("--intent", "--user-intent", dest="user_intent", required=True,
                     help="用户提供的本页原始想法，不应由模型代编")
    add.add_argument("--role", default="content", choices=["cover", "toc", "chapter", "content", "ending", "appendix"])
    for name in ("show", "patch", "restore", "append-input"):
        item = slides.add_parser(name)
        item.add_argument("project_id")
        item.add_argument("slide_id")
        if name != "show":
            item.add_argument("--base-revision", required=True, type=_positive_int)
        if name == "patch":
            item.add_argument("--changes", required=True, metavar="JSON_FILE",
                              help='[{"path":"/takeaway","value":"..."}]；- 为 stdin')
            item.add_argument("--summary", default="")
        if name == "restore":
            item.add_argument("--restore-revision", required=True, type=_positive_int)
        if name == "append-input":
            item.add_argument("--text", required=True, help="追加的用户原话；保留最初原意，不认证说话者身份")
            item.add_argument("--source-note", default="", help="原话来源或定位说明")

    for name in ("next", "gate", "history"):
        item = commands.add_parser(name)
        item.add_argument("project_id")
        item.add_argument("--slide", "--slide-id", dest="slide_id")
    templates = commands.add_parser("template").add_subparsers(dest="template_command", required=True)
    templates.add_parser("list")
    templates.add_parser("get").add_argument("template_id")

    artifacts = commands.add_parser("artifact").add_subparsers(dest="artifact_command", required=True)
    register = artifacts.add_parser("register", help="登记实际源文件、预览和对象映射；相对路径基于项目目录")
    register.add_argument("project_id")
    register.add_argument("slide_id")
    register.add_argument("--base-revision", required=True, type=_positive_int)
    register.add_argument("--artifact", required=True, help="项目目录中的可编辑源文件")
    register.add_argument("--preview", required=True, help="项目目录中的页面预览")
    register.add_argument("--manifest", default="", help="项目目录中的对象 ID 映射 JSON")

    review = commands.add_parser("review", help="记录本地操作者审阅陈述，不认证人类身份")
    review.add_argument("project_id")
    review.add_argument("slide_id")
    review.add_argument("--base-revision", required=True, type=_positive_int)
    review.add_argument("--kind", required=True, choices=["content", "evidence", "visual"])
    review.add_argument("--statement", required=True, help="说明实际审阅了什么及结论，不可空白")
    review.add_argument("--reviewer", default="operator")
    review.add_argument("--evidence-id", help="kind=evidence 时必须填写")

    release = commands.add_parser("release-manifest", help="通过 gate 后生成文件哈希交付清单；不生成 PPT")
    release.add_argument("project_id")
    commands.add_parser("doctor", help="读取运行环境信息，不安装依赖或修改客户端")
    config = commands.add_parser("config", help="打印绝对路径接入配置；不写入客户端设置")
    config.add_argument("--client", required=True, choices=["claude", "codex"])
    studio = commands.add_parser("studio", help="启动聊天与实时预览工作台，仅监听本机")
    studio.add_argument("--project", default="main")
    studio.add_argument("--port", default=8765, type=int)
    studio.add_argument("--agent", default=None, choices=["manual", "claude", "codex", "outline", "api"],
                        help="省略时恢复项目上次的执行方式；可在界面中切换")
    studio.add_argument("--open", action="store_true", help="自动在本机浏览器打开")
    studio.add_argument("--demo", action="store_true", help="空项目中载入明确标注的演示内容")
    scenes = commands.add_parser("scene", help="真实可编辑页面与预览").add_subparsers(dest="scene_command", required=True)
    for name in ("get", "generate", "replace", "patch", "undo"):
        item = scenes.add_parser(name)
        item.add_argument("project_id")
        item.add_argument("slide_id")
        if name in {"generate", "replace"}:
            item.add_argument("--base-revision", type=_positive_int, required=name == "replace")
        if name in {"patch", "undo"}:
            item.add_argument("--base-scene-revision", required=True, type=_positive_int)
        if name == "replace":
            item.add_argument("--file", required=True)
        if name == "patch":
            item.add_argument("--changes", required=True)
    chats = commands.add_parser("chat", help="与网页聊天任务共用队列").add_subparsers(dest="chat_command", required=True)
    for name in ("next", "send", "respond"):
        item = chats.add_parser(name)
        item.add_argument("project_id")
        if name == "send":
            item.add_argument("--message", required=True)
            item.add_argument("--slide")
            item.add_argument("--object")
            item.add_argument("--reply-to-message", help="回答整稿当前页的指定助手提问消息")
            item.add_argument("--reply-to-deck-page", action="store_true", help="将原话作为整稿当前待补充页的材料")
            item.add_argument("--scope", choices=["page", "deck"], default="page", help="整稿反馈可一次分派到多个页面")
            item.add_argument("--auto-resume", action="store_true", help="补充当前页后自动继续，不另消耗输入轮次")
            item.add_argument("--client-message-id", help="同一输入重试使用相同ID，不重复计算轮次")
        if name == "respond":
            item.add_argument("job_id")
            item.add_argument("--plan", required=True)
    decks = commands.add_parser("deck", help="整稿计划、进度、暂停恢复与修改计数").add_subparsers(dest="deck_command", required=True)
    for name in ("start", "from-outline", "status", "control", "step"):
        item = decks.add_parser(name)
        item.add_argument("project_id")
        if name == "start":
            item.add_argument("--plan", required=True, help="整稿计划 JSON 文件")
            item.add_argument("--source-text", required=True, help="用户提供的原始思想或大纲，不由模型伪造")
            item.add_argument("--execution", default="agent", choices=["agent", "outline"])
        if name == "from-outline":
            item.add_argument("--file", required=True, help="以‘按大纲排版’开头的 Markdown 文件；- 为 stdin")
        if name == "control":
            item.add_argument("--action", required=True, choices=["pause", "resume", "retry", "cancel"])
    delivery = commands.add_parser("delivery", help="总交互轮次与整稿反馈状态").add_subparsers(dest="delivery_command", required=True)
    for name in ("status", "control"):
        item = delivery.add_parser(name)
        item.add_argument("project_id")
        if name == "control":
            item.add_argument("--action", choices=["retry", "cancel"], required=True)
            item.add_argument("--round-id")
    quality = commands.add_parser("quality", help="机械检查与真实浏览器测量状态").add_subparsers(dest="quality_command", required=True)
    for name in ("status", "check"):
        item = quality.add_parser(name)
        item.add_argument("project_id")
        if name == "check":
            item.add_argument("--auto-fix", action="store_true", help="只在当前轮授权范围内修正可靠的版式问题")
    export = commands.add_parser("export", help="导出实际 HTML 或可编辑 PPTX")
    export.add_argument("project_id")
    export.add_argument("--format", choices=["html", "pptx"], default="html")
    export.add_argument("--slide")
    export.add_argument("--strict", action="store_true", help="要求正式交付检查通过；默认明确标注为草稿")
    return parser


def _nonfinite(value):
    raise ValueError(f"Non-finite JSON number is not supported: {value}")


def _read_json(filename, expected):
    try:
        content = sys.stdin.read() if filename == "-" else Path(filename).expanduser().read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise InputError("无法读取 JSON 输入文件。", "INPUT_FILE_ERROR", {"path": filename, "reason": str(exc)}) from exc
    try:
        result = json.loads(content, parse_constant=_nonfinite)
    except ValueError as exc:
        raise InputError("输入不是有效 JSON。", "INVALID_JSON", {"path": filename, "reason": str(exc)}) from exc
    if not isinstance(result, expected):
        name = "object" if expected is dict else "array"
        raise InputError(f"JSON 顶层必须是 {name}。", "INVALID_JSON_SHAPE", {"path": filename})
    return result


def _write_json_file(filename, value):
    path = Path(filename).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".ppt-export-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(path)


def _package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _config(client, root):
    # Do not resolve the interpreter symlink: doing so can leave a virtualenv.
    python = os.path.abspath(sys.executable)
    args = ["-m", "ppt_workbench.mcp_server", "--root", str(root)]
    if client == "claude":
        config = {"mcpServers": {"ppt": {"type": "stdio", "command": python, "args": args}}}
        registration = ["claude", "mcp", "add", "--transport", "stdio", "--scope", "project", "ppt", "--", python, *args]
        format_name = "json"
    else:
        config = "[mcp_servers.ppt]\ncommand = " + json.dumps(python, ensure_ascii=False) + "\nargs = " + json.dumps(args, ensure_ascii=False) + "\n"
        registration = ["codex", "mcp", "add", "ppt", "--", python, *args]
        format_name = "toml"
    return {"client": client, "root": str(root), "format": format_name, "config": config,
            "registrationArgv": registration, "writesSettings": False,
            "note": "在上述 Python 环境安装本包及 MCP 依赖后，手动采用配置或运行参数数组对应的命令。"}


def _dispatch(args):
    root = Path(args.root).expanduser().resolve()
    if args.command == "studio":
        from .server import serve
        serve(root, args.project, args.port, args.agent, args.open, args.demo)
        return {"status": "stopped"}, 0
    if args.command in {"scene", "chat", "export", "deck", "delivery", "quality"}:
        from .studio import Studio
        studio = Studio(root, args.project_id, create=False)
        if args.command == "delivery":
            return (studio.delivery_state() if args.delivery_command == "status" else
                    studio.control_delivery(args.action, args.round_id)), 0
        if args.command == "quality":
            if args.quality_command == "status":
                return studio.quality_state(), 0
            return studio.check_current_quality(auto_fix=args.auto_fix), 0
        if args.command == "deck":
            if args.deck_command == "status":
                return studio.deck_state(), 0
            if args.deck_command == "control":
                return studio.control_deck(args.action), 0
            if args.deck_command == "step":
                return {"processed": studio.run_pending(), "deck": studio.deck_state()}, 0
            if args.deck_command == "start":
                return studio.create_deck(_read_json(args.plan, dict), args.source_text, args.execution), 0
            try:
                source = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                raise InputError("无法读取大纲文件。", "INPUT_FILE_ERROR") from exc
            from .outline import parse_outline
            plan = parse_outline(source)
            if plan is None:
                raise InputError("大纲须以‘按大纲排版’开头。", "INVALID_OUTLINE")
            return studio.create_deck(plan, source, "outline"), 0
        if args.command == "export":
            return studio.export(args.format, args.slide, args.strict), 0
        if args.command == "chat":
            if args.chat_command == "next":
                return studio.next_job(), 0
            if args.chat_command == "send":
                return studio.enqueue(args.message, args.slide, args.object, client_message_id=args.client_message_id,
                                      choice_message_id=args.reply_to_message, reply_to_deck_page=args.reply_to_deck_page,
                                      scope=args.scope, auto_resume=args.auto_resume), 0
            return studio.apply_plan(args.job_id, _read_json(args.plan, dict)), 0
        if args.scene_command == "get":
            return studio.get_scene(args.slide_id), 0
        if args.scene_command == "generate":
            return studio.generate_scene(args.slide_id, args.base_revision), 0
        if args.scene_command == "replace":
            return studio.put_scene(args.slide_id, args.base_revision, _read_json(args.file, dict)), 0
        if args.scene_command == "patch":
            return studio.change_scene(args.slide_id, args.base_scene_revision, _read_json(args.changes, list)), 0
        return studio.undo(args.slide_id, args.base_scene_revision), 0
    if args.command == "config":
        return _config(args.client, root), 0
    if args.command == "doctor":
        return {"python": {"executable": os.path.abspath(sys.executable), "version": sys.version.split()[0]},
                "mcp": {"version": _package_version("mcp"), "available": importlib.util.find_spec("mcp") is not None},
                "workbenchVersion": _package_version("ppt-workbench"), "sqliteVersion": sqlite3.sqlite_version,
                "clients": {"claude": shutil.which("claude"), "codex": shutil.which("codex")},
                "root": str(root), "rootExists": root.exists(), "changedSettings": False}, 0

    wb = Workbench(root)
    if args.command == "project":
        action = args.project_command
        if action == "create":
            return wb.create_project(args.project_id, _read_json(args.brief, dict) if args.brief else {}), 0
        if action == "import":
            return wb.import_workspace(args.project_id, _read_json(args.file, dict)), 0
        if action == "show":
            return wb.get_project(args.project_id), 0
        if action == "update":
            return wb.update_project(args.project_id, args.base_revision, _read_json(args.changes, dict)), 0
        result = wb.export_workspace(args.project_id, for_html=args.for_html)
        if args.output and args.output != "-":
            return {"projectId": args.project_id, "outputPath": _write_json_file(args.output, result),
                    "schema": result.get("schema"), "slideCount": len(result.get("slides", []))}, 0
        return result, 0
    if args.command == "slide":
        if args.slide_command == "add":
            return wb.add_slide(args.project_id, args.title, args.user_intent, args.role), 0
        if args.slide_command == "show":
            return wb.get_slide(args.project_id, args.slide_id), 0
        if args.slide_command == "patch":
            return wb.patch_slide(args.project_id, args.slide_id, args.base_revision,
                                  _read_json(args.changes, list), args.summary), 0
        if args.slide_command == "append-input":
            return wb.append_user_input(args.project_id, args.slide_id, args.base_revision,
                                        args.text, args.source_note), 0
        return wb.restore_slide(args.project_id, args.slide_id, args.base_revision, args.restore_revision), 0
    if args.command == "next":
        return wb.next_action(args.project_id, args.slide_id), 0
    if args.command == "template":
        from .curated_designs import public_catalog, public_detail
        return (public_catalog() if args.template_command == "list" else public_detail(args.template_id)), 0
    if args.command == "artifact":
        return wb.register_artifact(args.project_id, args.slide_id, args.base_revision,
                                    args.artifact, args.preview, args.manifest), 0
    if args.command == "review":
        if not args.statement.strip():
            raise InputError("请填写实际审阅陈述。")
        if args.kind == "evidence" and not args.evidence_id:
            raise InputError("证据审阅必须指定 --evidence-id。")
        if args.kind != "evidence" and args.evidence_id:
            raise InputError("--evidence-id 仅用于 kind=evidence。")
        result = wb.record_review(args.project_id, args.slide_id, args.base_revision, args.kind,
                                  args.statement, args.reviewer, args.evidence_id)
        result.update({"reviewNotice": "已记录本地操作者陈述；此命令不认证人类身份，也不自动证明内容、来源或视觉质量。",
                       "humanIdentityAuthenticated": False, "assurance": "local-operator-attestation"})
        return result, 0
    if args.command == "gate":
        result = wb.gate(args.project_id, args.slide_id)
        return result, 0 if result["ready"] else 3
    if args.command == "history":
        return wb.history(args.project_id, args.slide_id), 0
    if args.command == "release-manifest":
        return wb.release_manifest(args.project_id), 0
    raise InputError("未知命令。", "CLI_ARGUMENT_ERROR")


def _emit(value):
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    sys.stdout.write("\n")


def main(argv=None):
    """Return 0 for success, 1 for engine/I/O errors, 2 for input, 3 for gate gaps."""
    try:
        args = _parser().parse_args(argv)
        result, code = _dispatch(args)
        _emit(result)
        return code
    except InputError as exc:
        error = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            error["details"] = exc.details
        _emit({"ok": False, "error": error})
        return 2
    except EngineError as exc:
        _emit({"ok": False, "error": exc.to_dict()})
        return 1
    except (OSError, UnicodeError, sqlite3.Error) as exc:
        _emit({"ok": False, "error": {"code": "IO_ERROR", "message": str(exc)}})
        return 1
    except KeyboardInterrupt:
        _emit({"ok": False, "error": {"code": "INTERRUPTED", "message": "操作已中断。"}})
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
