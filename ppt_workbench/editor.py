"""Direct editing history and model proposals which require explicit application."""
import json
import threading
import uuid

from .core import EngineError
from .rendering import patch_scene, render_html

EDIT_FIELDS = {"text", "fontSize", "fontFamily", "color", "bold", "italic", "align",
               "valign", "x", "y", "w", "h", "opacity", "fill", "stroke", "strokeWidth", "startArrow", "endArrow",
               "letterSpacing", "emphasis", "emphasisColor", "rotation", "shadow"}
QUICK_ACTIONS = {
    "concise": "精简所选文字，保留核心含义、事实、数字和限定条件。仅修改 text。",
    "headline": "把所选文字改为清楚的结论式标题，不增加未经提供的事实。仅修改 text。",
    "polish": "改善所选文字的表达，保留原意、事实、数字和限定条件。仅修改 text。",
    "layout": "改善当前页的对齐、间距和信息层级，保留全部原文、图片、对象与字号，不裁切图片。",
    "hierarchy": "改善当前页视觉层级，使用颜色、加粗和对齐突出重点，保留全部原文、图片、对象与字号。",
    "custom": "执行用户补充的修改要求，保留没有要求修改的内容。",
}


def initialize(studio):
    studio.suggestion_lock = threading.Lock()
    with studio.wb._connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS studio_editor_history (
            project_id TEXT NOT NULL, slide_id TEXT NOT NULL,
            scene_revision INTEGER NOT NULL, undo_stack TEXT NOT NULL, redo_stack TEXT NOT NULL,
            PRIMARY KEY(project_id,slide_id));
        CREATE TABLE IF NOT EXISTS studio_editor_proposals (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, slide_id TEXT NOT NULL,
            scene_revision INTEGER NOT NULL, changes TEXT NOT NULL);
        """)


def _history(studio, db, sid, revision):
    row = db.execute("SELECT * FROM studio_editor_history WHERE project_id=? AND slide_id=?",
                     (studio.project_id, sid)).fetchone()
    if not row or row["scene_revision"] != revision:
        return [], []
    return json.loads(row["undo_stack"]), json.loads(row["redo_stack"])


def _save_history(studio, db, sid, revision, undo, redo):
    db.execute("INSERT OR REPLACE INTO studio_editor_history VALUES (?,?,?,?,?)",
               (studio.project_id, sid, revision, json.dumps(undo), json.dumps(redo)))


def history_status(studio, sid):
    with studio.wb.atomic() as db:
        current = studio.get_scene(sid)
        undo, redo = _history(studio, db, sid, current["sceneRevision"])
        return {"sceneRevision": current["sceneRevision"], "canUndo": bool(undo), "canRedo": bool(redo)}


def edit(studio, sid, revision, changes):
    if not isinstance(changes, list) or not changes or any(
        not isinstance(c, dict) or set(c) != {"objectId", "properties"}
        or not isinstance(c["properties"], dict) or not c["properties"]
        or set(c["properties"]) - EDIT_FIELDS for c in changes
    ):
        raise EngineError("INVALID_SCENE_PATCH", "请选择支持的文字、格式或位置属性。")
    with studio.wb.atomic() as db:
        before = studio.get_scene(sid)
        candidate = patch_scene(before["scene"], changes)
        studio.wb._revision(before["sceneRevision"], revision)
        if candidate == before["scene"]:
            return before
        undo, _ = _history(studio, db, sid, revision)
        result = studio.change_scene(sid, revision, changes)
        undo.append({"before": before["scene"], "after": result["scene"]})
        _save_history(studio, db, sid, result["sceneRevision"], undo, [])
        return result


def travel(studio, sid, revision, direction):
    if direction not in {"undo", "redo"}:
        raise EngineError("INVALID_REQUEST", "请选择撤销或重做。")
    with studio.wb.atomic() as db:
        current = studio.get_scene(sid)
        studio.wb._revision(current["sceneRevision"], revision)
        if current["stale"]:
            raise EngineError("SCENE_STALE", "页面内容已变化，请先更新预览。")
        undo, redo = _history(studio, db, sid, revision)
        source, destination = (undo, redo) if direction == "undo" else (redo, undo)
        if not source:
            raise EngineError("NO_EDITOR_HISTORY", "没有可撤销或重做的编辑；其他操作更新页面后，编辑历史会重新开始。")
        entry = source.pop()
        result = studio.put_scene(sid, current["contentRevision"],
                                 entry["before" if direction == "undo" else "after"],
                                 "撤销编辑" if direction == "undo" else "重做编辑")
        destination.append(entry)
        _save_history(studio, db, sid, result["sceneRevision"], undo, redo)
        return result


def replace_scene(studio, sid, revision, scene, reason):
    """Apply a whole-scene replacement as one undoable editor operation."""
    with studio.wb.atomic() as db:
        before = studio.get_scene(sid)
        studio.wb._revision(before['sceneRevision'], revision)
        if before['stale']:
            raise EngineError('SCENE_STALE', '页面内容已变化，请先更新预览。')
        undo, _ = _history(studio, db, sid, revision)
        result = studio.put_scene(sid, before['contentRevision'], scene, reason)
        undo.append({'before': before['scene'], 'after': result['scene']})
        _save_history(studio, db, sid, result['sceneRevision'], undo, [])
        return result


def suggest(studio, sid, revision, action, object_id=None, instruction=""):
    from .agent_bridge import run_turn, validate_plan
    if not isinstance(action, str) or action not in QUICK_ACTIONS:
        raise EngineError("INVALID_REQUEST", "请选择支持的推荐操作。")
    if not isinstance(instruction, str) or len(instruction) > 4000:
        raise EngineError("INVALID_REQUEST", "修改要求最多 4000 字。")
    if action == "custom" and not instruction.strip():
        raise EngineError("INVALID_REQUEST", "请填写修改要求。")
    if studio.agent_mode not in {"codex", "claude", "api"}:
        raise EngineError("AGENT_REQUIRED", "AI 快捷推荐需要连接 Codex 或 Claude Code。请在顶部选择执行方式。")
    if not studio.suggestion_lock.acquire(blocking=False):
        raise EngineError("SUGGESTION_BUSY", "正在生成建议，请稍后再试。")
    try:
        with studio.wb.atomic():
            from .model_profiles import selected
            chosen = selected(studio)
            mode = studio.agent_mode
            current = studio.get_scene(sid)
            studio.wb._revision(current["sceneRevision"], revision)
            if current["stale"]:
                raise EngineError("SCENE_STALE", "请先更新当前页面预览。")
            selected = next((o for o in current["scene"]["objects"] if o["id"] == object_id), None)
            if object_id is not None and selected is None:
                raise EngineError("SCENE_OBJECT_NOT_FOUND", "未找到所选对象。")
            if action in {"concise", "headline", "polish"} and (not selected or selected["type"] != "text"):
                raise EngineError("INVALID_REQUEST", "请先选择一段文字。")
            full_context = studio.context({"slideId": sid, "objectId": object_id, "scope": "page"})
            # Quick edits need the current page and user intent, not the entire
            # template library or deck execution state. Source data stays intact.
            context = {key: full_context[key] for key in (
                "projectId", "project", "currentPage", "scene", "selectedObjectId",
                "sceneSpec", "userIntentHistory", "rules", "visualGuidance")}
        context["proposalOnly"] = True
        context["rules"].append("本次只生成待用户预览的建议。仅允许一项 scene_patch，不修改项目、页面结构或其他页面。")
        message = ("生成待用户预览的编辑建议。仅返回一项 scene_patch，使用当前 sceneRevision。"
                   "不能增加、删除对象或修改图片来源。\n" + QUICK_ACTIONS[action]
                   + ("\n用户补充要求：" + instruction if instruction else ""))
        plan = validate_plan(run_turn(mode, message, context, timeout=75,
                                      workdir=studio.wb.project_dir(studio.project_id),
                                      **({"model_binding":chosen} if chosen else {})))
        actions = plan["actions"]
        if len(actions) != 1 or actions[0]["type"] != "scene_patch":
            raise EngineError("INVALID_SUGGESTION", "模型没有返回可预览的局部修改，请调整要求后重试。")
        proposal = actions[0]
        if proposal["slide_id"] != sid or proposal["base_scene_revision"] != revision:
            raise EngineError("SCOPE_VIOLATION", "建议的页面或版本不匹配，请重新生成。")
        changes = proposal["changes"]
        allowed = ({"text"} if action in {"concise", "headline", "polish"} else
                   EDIT_FIELDS - {"text", "fontSize"} if action in {"layout", "hierarchy"} else EDIT_FIELDS)
        for change in changes:
            if object_id is not None and change["objectId"] != object_id:
                raise EngineError("SCOPE_VIOLATION", "建议超出了选中对象范围，未应用。")
            if set(change["properties"]) - allowed:
                raise EngineError("SCOPE_VIOLATION", "建议包含本操作不允许修改的属性，未应用。")
        candidate = patch_scene(current["scene"], changes)
        if candidate == current["scene"]:
            raise EngineError("INVALID_SUGGESTION", "模型没有提出实际修改，当前页面保持不变。")
        proposal_id = uuid.uuid4().hex
        with studio.wb.atomic() as db:
            studio.wb._revision(studio.get_scene(sid)["sceneRevision"], revision)
            db.execute("INSERT INTO studio_editor_proposals VALUES (?,?,?,?,?)",
                       (proposal_id, studio.project_id, sid, revision, json.dumps(changes)))
        return {"proposalId": proposal_id, "slideId": sid, "sceneRevision": revision,
                "reply": plan["reply"], "changes": studio.scene_diff(current["scene"], candidate),
                "beforeHtml": render_html(current["scene"], interactive=False),
                "afterHtml": render_html(candidate, interactive=False)}
    finally:
        studio.suggestion_lock.release()


def apply_suggestion(studio, proposal_id):
    if not isinstance(proposal_id, str):
        raise EngineError("INVALID_REQUEST", "请选择要应用的建议。")
    with studio.wb.atomic() as db:
        row = db.execute("SELECT * FROM studio_editor_proposals WHERE id=? AND project_id=?",
                         (proposal_id, studio.project_id)).fetchone()
        if not row:
            raise EngineError("PROPOSAL_NOT_FOUND", "建议不存在或已经应用，请重新生成。")
        result = edit(studio, row["slide_id"], row["scene_revision"], json.loads(row["changes"]))
        db.execute("DELETE FROM studio_editor_proposals WHERE id=?", (proposal_id,))
        return result
