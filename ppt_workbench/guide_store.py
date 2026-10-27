"""Independent, project-scoped content guidance and reusable experience storage."""
from __future__ import annotations

import json
from .core import EngineError


def _init(studio):
    with studio.wb._connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS studio_guide_documents (
            project_id TEXT NOT NULL, kind TEXT NOT NULL, revision INTEGER NOT NULL,
            body TEXT NOT NULL, PRIMARY KEY(project_id,kind))""")


def load(studio, kind):
    if kind not in {"draft", "experience"}:
        raise EngineError("INVALID_REQUEST", "未知的引导文档类型。")
    _init(studio)
    with studio.wb._connection() as db:
        row = db.execute("SELECT revision,body FROM studio_guide_documents WHERE project_id=? AND kind=?",
                         (studio.project_id, kind)).fetchone()
    return {"projectId": studio.project_id, "revision": row["revision"] if row else 0,
            "document": json.loads(row["body"]) if row else {}}


def save(studio, kind, revision, document):
    if kind not in {"draft", "experience"} or type(revision) is not int or revision < 0 or not isinstance(document, dict):
        raise EngineError("INVALID_REQUEST", "引导文档及版本无效。")
    body = json.dumps(document, ensure_ascii=False)
    if len(body.encode("utf-8")) > 500_000:
        raise EngineError("REQUEST_TOO_LARGE", "引导内容超过容量，请拆分保存。")
    _init(studio)
    with studio.wb.atomic() as db:
        row = db.execute("SELECT revision FROM studio_guide_documents WHERE project_id=? AND kind=?",
                         (studio.project_id, kind)).fetchone()
        actual = row["revision"] if row else 0
        if actual != revision:
            raise EngineError("STALE_REVISION", "另一窗口已更新引导内容，请重新加载后合并。")
        db.execute("INSERT INTO studio_guide_documents VALUES (?,?,?,?) ON CONFLICT(project_id,kind) DO UPDATE SET revision=excluded.revision,body=excluded.body",
                   (studio.project_id, kind, actual + 1, body))
    return {"projectId": studio.project_id, "revision": actual + 1, "document": document}
