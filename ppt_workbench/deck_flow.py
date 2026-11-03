"""Durable whole-deck scheduling above single-page operations.

The scheduler never marks reviews or quality as passed. Every page is committed
through Studio's existing atomic scene pipeline. Outline execution is a visibly
labelled local renderer, not a mock model.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import threading
import uuid

from .core import EngineError, _now, _json, _hash


WAITING_CODES = {"WAITING_FOR_AGENT", "AGENT_NOT_INSTALLED", "AGENT_REQUIRED"}


class DeckFlow:
    def _init_deck_flow(self, agent):
        self._operation_local = threading.local()
        with self.wb._connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS studio_runtime (
                project_id TEXT PRIMARY KEY, agent_mode TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_decks (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL, status TEXT NOT NULL, execution TEXT NOT NULL,
                source_message TEXT NOT NULL, source_message_id TEXT NOT NULL,
                plan TEXT NOT NULL, fingerprint TEXT NOT NULL,
                initial_completed_at TEXT, last_error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_deck_pages (
                deck_id TEXT NOT NULL, page_index INTEGER NOT NULL, plan TEXT NOT NULL,
                status TEXT NOT NULL, slide_id TEXT, job_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT, PRIMARY KEY(deck_id,page_index));
            CREATE TABLE IF NOT EXISTS studio_deck_revisions (
                id TEXT PRIMARY KEY, deck_id TEXT NOT NULL, project_id TEXT NOT NULL,
                event_key TEXT NOT NULL, source TEXT NOT NULL, description TEXT NOT NULL,
                slide_id TEXT, before_revision INTEGER, after_revision INTEGER,
                stage TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(deck_id,event_key));
            CREATE TABLE IF NOT EXISTS studio_deck_answers (
                id TEXT PRIMARY KEY, deck_id TEXT NOT NULL, page_index INTEGER NOT NULL,
                message_id TEXT NOT NULL UNIQUE, question_message_id TEXT,
                text TEXT NOT NULL, attachments TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
        with self.wb.atomic() as db:
            db.execute("INSERT OR IGNORE INTO studio_runtime VALUES (?,?)", (self.project_id, agent or "manual"))
            if agent is not None:
                db.execute("UPDATE studio_runtime SET agent_mode=? WHERE project_id=?", (agent, self.project_id))

    @property
    def agent_mode(self):
        with self.wb._connection() as db:
            row = db.execute("SELECT agent_mode FROM studio_runtime WHERE project_id=?", (self.project_id,)).fetchone()
        return row[0] if row else "manual"

    def set_agent_mode(self, mode):
        from .agent_bridge import diagnose
        if mode not in {"manual", "claude", "codex", "outline", "api"}:
            raise EngineError("INVALID_AGENT", "请选择 manual、claude、codex 或 outline。")
        with self.wb.atomic() as db:
            db.execute("UPDATE studio_model_selection SET profile_id=NULL WHERE project_id=?", (self.project_id,))
            db.execute("UPDATE studio_runtime SET agent_mode=? WHERE project_id=?", (mode, self.project_id))
            deck = self._deck_row(db)
            if deck and deck["status"] == "blocked" and self._deck_error(deck).get("code") in WAITING_CODES:
                db.execute("UPDATE studio_decks SET status='running',last_error=NULL,updated_at=? WHERE id=?", (_now(), deck["id"]))
                self._queue_next_deck_page(db, deck["id"])
            self._touch(db)
        return {"mode": mode, "agent": diagnose(mode)}

    def _deck_row(self, db):
        row = db.execute("SELECT * FROM studio_decks WHERE project_id=?", (self.project_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _deck_error(deck):
        return json.loads(deck["last_error"]) if deck and deck["last_error"] else {}

    @contextmanager
    def _operation(self, job_id=None, generation=False, description="", round_id=None, automatic=False):
        prior = getattr(self._operation_local, "current", None)
        self._operation_local.current = {"jobId": job_id, "generation": generation, "description": description,
                                         "roundId": round_id or (prior or {}).get("roundId"),
                                         "automatic": automatic or (prior or {}).get("automatic", False)}
        try:
            # Serialise each actual mutation scope. Binding the event range
            # outside this transaction could accidentally absorb a concurrent
            # CLI change into an internal page task's round.
            with self.wb.atomic() as db:
                auditing = getattr(self, "_delivery_audit_ready", False)
                start_event = self._last_core_event(db) if auditing else None
                yield
                if auditing:
                    self._bind_operation_events(db, start_event, self._operation_local.current)
        finally:
            self._operation_local.current = prior

    def _record_deck_revision(self, db, slide_id, before_revision, after_revision, description):
        deck = self._deck_row(db)
        op = getattr(self._operation_local, "current", None) or {}
        if not deck or op.get("generation") or op.get("automatic") or (before_revision is None and not deck["initial_completed_at"]):
            return
        job_id = op.get("jobId")
        rid = op.get("roundId") or (self._round_for_job(db, job_id) if job_id else None)
        key = "round:" + rid if rid else ("job:" + job_id if job_id else f"scene:{slide_id}:{after_revision}")
        db.execute("""INSERT OR IGNORE INTO studio_deck_revisions
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", ("R-" + uuid.uuid4().hex, deck["id"], self.project_id, key,
                "chat" if job_id else "local-or-external", op.get("description") or description,
                slide_id, before_revision, after_revision,
                "after-initial-draft" if deck["initial_completed_at"] else "during-initial-draft", _now()))
        recorded = db.execute("SELECT slide_id FROM studio_deck_revisions WHERE deck_id=? AND event_key=?", (deck["id"], key)).fetchone()
        if recorded and recorded["slide_id"] != slide_id:
            db.execute("UPDATE studio_deck_revisions SET slide_id=NULL,before_revision=NULL,after_revision=NULL WHERE deck_id=? AND event_key=?", (deck["id"], key))
        else:
            db.execute("UPDATE studio_deck_revisions SET after_revision=? WHERE deck_id=? AND event_key=?", (after_revision, deck["id"], key))

    def deck_state(self):
        with self.wb.atomic() as db:
            deck = self._deck_row(db)
            if not deck:
                return None
            rows = db.execute("SELECT * FROM studio_deck_pages WHERE deck_id=? ORDER BY page_index", (deck["id"],)).fetchall()
            revisions = db.execute("SELECT * FROM studio_deck_revisions WHERE deck_id=? ORDER BY created_at,id", (deck["id"],)).fetchall()
            completed = sum(r["status"] == "complete" for r in rows)
            pending = next((r for r in rows if r["status"] not in {"complete", "cancelled"}), None)
            pending_question = self._pending_deck_question(db, deck, pending)
            from .deck_review import review_state
            return {"designReview": review_state(self, db, deck), "id": deck["id"], "title": deck["title"], "status": deck["status"], "execution": deck["execution"],
                "totalPages": len(rows), "completedPages": completed,
                "currentPage": pending["page_index"] + 1 if pending else None,
                "pendingQuestionMessageId": pending_question,
                "pendingAnswerCount": len(self._deck_answers(db, deck["id"], pending["page_index"])) if pending else 0,
                "initialCompletedAt": deck["initial_completed_at"], "revisionCount": len(revisions), "revisionTarget": 3,
                "withinRevisionTarget": len(revisions) <= 3, "qualityAccepted": False,
                "revisionNote": "仅记录实际修改次数；次数达标不代表整稿质量已经验收。",
                "pages": [{"index": r["page_index"] + 1, "title": json.loads(r["plan"])["title"],
                           "slideId": r["slide_id"], "status": r["status"], "attempts": r["attempts"],
                           "error": json.loads(r["error"]) if r["error"] else None} for r in rows],
                "revisions": [{"number": i + 1, "source": r["source"], "description": r["description"],
                               "slideId": r["slide_id"], "beforeRevision": r["before_revision"], "afterRevision": r["after_revision"],
                               "stage": r["stage"], "createdAt": r["created_at"]} for i, r in enumerate(revisions)],
                "lastError": self._deck_error(deck) or None}

    def _deck_answers(self, db, deck_id, page_index):
        rows = db.execute("SELECT * FROM studio_deck_answers WHERE deck_id=? AND page_index=? ORDER BY created_at,id", (deck_id, page_index)).fetchall()
        return [{"text": r["text"], "sourceMessageId": r["message_id"], "questionMessageId": r["question_message_id"],
                 "attachmentIds": json.loads(r["attachments"]), "recordedAt": r["created_at"],
                 "provenance": "client-transcribed-unverified"} for r in rows]

    def _pending_deck_question(self, db, deck, pending):
        if not pending or deck["status"] != "blocked" or self._deck_error(deck).get("code") != "PAGE_NEEDS_INPUT":
            return None
        known = self._deck_error(deck).get("questionMessageId")
        if known:
            return known
        # Compatibility for persisted questions produced before explicit IDs.
        rows = db.execute("SELECT id,extras FROM studio_messages WHERE project_id=? AND role='assistant' ORDER BY created_at DESC,id DESC", (self.project_id,)).fetchall()
        return next((r["id"] for r in rows if json.loads(r["extras"]).get("jobId") == pending["job_id"]), None)

    def _capture_deck_answer(self, db, message, request_id, attachments, assets, choice_message_id, slide_id, object_id, auto_resume=False):
        if slide_id is not None or object_id is not None:
            raise EngineError("QUESTION_SCOPE_MISMATCH", "这条回答属于待生成页，请清除旧页或对象的编辑目标后回答。")
        deck = self._deck_row(db)
        pending = db.execute("SELECT * FROM studio_deck_pages WHERE deck_id=? AND status!='complete' ORDER BY page_index LIMIT 1", (deck["id"],)).fetchone() if deck else None
        if not deck or not pending or deck["status"] != "blocked" or self._deck_error(deck).get("code") != "PAGE_NEEDS_INPUT":
            raise EngineError("STALE_QUESTION", "这个待生成页的问题已经结束或任务状态已变化，请重新查看当前问题。")
        current_question = self._pending_deck_question(db, deck, pending)
        if choice_message_id is not None:
            row = db.execute("SELECT * FROM studio_messages WHERE project_id=? AND id=? AND role='assistant'", (self.project_id, choice_message_id)).fetchone()
            extras = json.loads(row["extras"]) if row else {}
            job = self.job(extras["jobId"]) if extras.get("jobId") else None
            if (not row or not job or job["payload"].get("kind") != "deck_page"
                    or job["payload"].get("deckId") != deck["id"]
                    or job["payload"].get("pageIndex") != pending["page_index"]
                    or job["id"] != pending["job_id"] or choice_message_id != current_question):
                raise EngineError("STALE_QUESTION", "这个选择题不属于当前待生成页，回答未应用到任何页面。")
        else:
            choice_message_id = current_question
        jid = "J-" + uuid.uuid4().hex
        mid = self._message(db, "user", message, None, "complete", jobId=jid, deckId=deck["id"],
            deckPageIndex=pending["page_index"] + 1, isDeckAnswer=True, questionMessageId=choice_message_id,
            attachments=[{"assetId": a["id"], "filename": a["filename"], "mime": a["mime"]} for a in assets])
        db.execute("INSERT INTO studio_deck_answers VALUES (?,?,?,?,?,?,?,?)", (
            "A-" + uuid.uuid4().hex, deck["id"], pending["page_index"], mid, choice_message_id,
            message, _json(attachments), _now()))
        payload = {"kind": "deck_answer", "deckId": deck["id"], "pageIndex": pending["page_index"],
            "message": message, "slideId": None, "objectId": None, "baseRevision": None, "baseSceneRevision": None,
            "projectRevision": self.wb.get_project(self.project_id)["revision"], "attachments": attachments,
            "questionMessageId": choice_message_id}
        reply = f"已保存第 {pending['page_index'] + 1} 页的补充材料，已生成页面保持不变。" + ("已自动继续当前页制作。" if auto_resume else "点击“重试当前页”后会带上这些原话继续生成。")
        result = {"reply": reply, "slideId": None, "sceneRevision": None, "changes": [], "deckAnswer": True,
                  "deckId": deck["id"], "pageIndex": pending["page_index"]}
        db.execute("INSERT INTO studio_jobs VALUES (?,?,?,?,?,?,?,?,?)", (jid, self.project_id, request_id, mid, "complete", _json(payload), _json(result), _now(), _now()))
        round_id = self._begin_round(db, mid, message, jid)
        self._assign_deck_round(db, deck["id"], round_id)
        self._message(db, "assistant", reply, None, deckId=deck["id"], deckPageIndex=pending["page_index"] + 1, jobId=jid)
        if auto_resume:
            self.control_deck("retry")
        self._finish_round(round_id)
        self._touch(db)
        return {"jobId": jid, "status": "complete", "deckAnswer": True, "deck": self.deck_state(), "roundId": round_id}

    def create_deck(self, plan, source_message, execution="agent"):
        from .outline import validate_deck_plan
        if not isinstance(source_message, str) or not source_message.strip() or len(source_message) > 30_000:
            raise EngineError("INVALID_DECK_SOURCE", "整稿必须保留 1 到 30,000 字的原始需求。")
        if not isinstance(plan, dict):
            raise EngineError("INVALID_DECK_PLAN", "整稿计划必须为对象。")
        proposed = copy.deepcopy(plan)
        proposed["execution"] = execution
        proposed = validate_deck_plan(proposed)
        if execution == "agent":
            from .page_design import drop_unsupported_metrics
            drop_unsupported_metrics(proposed, [source_message] + self._user_material_texts())
            chosen = self.palette()
            if chosen and isinstance(proposed.get("design"), dict):
                proposed["design"]["accent"] = chosen["primary"]
                proposed["design"]["secondary"] = chosen["secondary"][0]
                if len(chosen["secondary"]) > 1:
                    proposed["design"]["tertiary"] = chosen["secondary"][1]
            elif isinstance(proposed.get("design"), dict):
                from .user_templates import selected_style
                style = selected_style(self)
                colour = (style or {}).get("profile", {}).get("color") or {}
                if style and colour:
                    import re as _re
                    hex_ok = lambda v: isinstance(v, str) and _re.fullmatch(r"#[0-9a-fA-F]{6}", v)
                    for field, key in (("background", "background"), ("ink", "ink"),
                                       ("accent", "primary"), ("secondary", "secondary")):
                        value = colour.get(key)
                        if key == "secondary":
                            value = value[0] if isinstance(value, list) and value else None
                        if hex_ok(value):
                            proposed["design"][field] = value.upper()
        from .templates import recover_generated_template
        known = {t["id"] for t in self.wb.list_templates()["templates"]}
        for page in proposed["pages"]:
            if "template_id" in page:
                if execution == "agent":
                    page["template_id"] = recover_generated_template(
                        page["template_id"], page["role"], page=page, known_ids=known)
                elif page["template_id"] not in known | {"custom", ""}:
                    raise EngineError("INVALID_DECK_TEMPLATE", "整稿使用了不存在的模板。", {"templateId": page["template_id"]})
        fingerprint = _hash({"plan": proposed, "source": source_message})
        with self.wb.atomic() as db:
            existing = self._deck_row(db)
            if existing:
                if existing["fingerprint"] == fingerprint:
                    return self.deck_state()
                raise EngineError("DECK_EXISTS", "此项目已有整稿任务；请继续当前任务或在新项目创建另一套。")
            project = self.wb.get_project(self.project_id)
            if project["workspace"]["slides"]:
                raise EngineError("PROJECT_NOT_EMPTY", "整稿任务仅在空项目创建，避免覆盖已有页面。")
            op = getattr(self._operation_local, "current", None) or {}
            parent = self.job(op["jobId"]) if op.get("jobId") else None
            mid = parent["message_id"] if parent else self._message(db, "user", source_message, provenance="client-transcribed-unverified")
            round_id = self._round_for_job(db, parent["id"]) if parent else self._begin_round(db, mid, source_message)
            intake = self._intake_from_round(db, mid, len(proposed["pages"]))
            with self._operation(round_id=round_id, generation=True, description="保存用户整稿标题"):
                self.wb.update_project(self.project_id, project["revision"], {"title": proposed["title"], **intake["projectChanges"]})
            deck_id = "D-" + uuid.uuid4().hex
            db.execute("INSERT INTO studio_decks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                deck_id, self.project_id, proposed["title"], "running", execution, source_message, mid,
                _json(proposed), fingerprint, None, None, _now(), _now()))
            db.execute("INSERT INTO studio_deck_intake VALUES (?,?)", (deck_id, _json(intake)))
            self._assign_deck_round(db, deck_id, round_id)
            for index, page in enumerate(proposed["pages"]):
                db.execute("INSERT INTO studio_deck_pages VALUES (?,?,?,?,?,?,?,?)", (deck_id, index, _json(page), "pending", None, None, 0, None))
            mode_note = "本地大纲排版：使用已提交的逐页文字，不调用模型，也不补写业务事实。" if execution == "outline" else "已保存整稿计划，接下来逐页调用已连接的执行器生成。"
            self._message(db, "assistant", f"{mode_note}\n共 {len(proposed['pages'])} 页，每页完成后显示预览并继续下一页。", deckId=deck_id, roundId=round_id)
            self._queue_next_deck_page(db, deck_id)
            return self.deck_state()

    def _user_material_texts(self):
        """The user's own words and attachment excerpts in this project; never model text."""
        with self.wb._connection() as db:
            texts = [r["text"] for r in db.execute(
                "SELECT text FROM studio_messages WHERE project_id=? AND role='user'", (self.project_id,))]
            texts += [r["excerpt"] for r in db.execute(
                "SELECT excerpt FROM studio_assets WHERE project_id=?", (self.project_id,))]
        return texts

    def _queue_next_deck_page(self, db, deck_id):
        deck = self._deck_row(db)
        if not deck or deck["id"] != deck_id or deck["status"] != "running":
            return
        row = db.execute("SELECT * FROM studio_deck_pages WHERE deck_id=? AND status!='complete' ORDER BY page_index LIMIT 1", (deck_id,)).fetchone()
        if row is None:
            from .deck_review import queue_review
            if queue_review(self, db, deck):
                return
            db.execute("UPDATE studio_decks SET status='complete',initial_completed_at=COALESCE(initial_completed_at,?),last_error=NULL,updated_at=? WHERE id=?", (_now(), _now(), deck_id))
            self._message(db, "assistant", "整稿初稿已逐页生成完成，正在汇总本轮结果与自动检查。", deckId=deck_id, roundId=self._deck_round_id(db, deck_id))
            from .auto_images import queue_auto_images
            try:
                queue_auto_images(self, db, deck)
            except (EngineError, ValueError):
                pass  # Illustration is optional; the finished deck stays complete.
            from .logo import apply_to_deck
            try:
                apply_to_deck(self, db, deck)
            except (EngineError, ValueError):
                pass  # The logo is optional; the finished deck stays complete.
            return
        if row["job_id"]:
            job = self.job(row["job_id"])
            if job["status"] in {"queued", "running"}:
                return
        job_id = "J-" + uuid.uuid4().hex
        source_job = db.execute("SELECT payload FROM studio_jobs WHERE message_id=? AND project_id=? ORDER BY created_at LIMIT 1", (deck["source_message_id"], self.project_id)).fetchone()
        attachments = json.loads(source_job["payload"]).get("attachments", []) if source_job else []
        for answer in self._deck_answers(db, deck_id, row["page_index"]):
            attachments.extend(aid for aid in answer["attachmentIds"] if aid not in attachments)
        payload = {"kind": "deck_page", "deckId": deck_id, "pageIndex": row["page_index"], "execution": deck["execution"],
            "message": deck["source_message"], "slideId": None, "objectId": None, "baseRevision": None, "baseSceneRevision": None,
            "projectRevision": self.wb.get_project(self.project_id)["revision"], "attachments": attachments}
        if source_job:
            chosen = json.loads(source_job["payload"]).get("modelBinding")
            if chosen:
                payload["modelBinding"] = chosen
        db.execute("INSERT INTO studio_jobs VALUES (?,?,?,?,?,?,?,?,?)", (job_id, self.project_id, f"deck:{deck_id}:{row['page_index']}:{row['attempts'] + 1}",
            deck["source_message_id"], "queued", _json(payload), None, _now(), _now()))
        self._bind_round_job(db, self._deck_round_id(db, deck_id), job_id)
        db.execute("UPDATE studio_deck_pages SET status='queued',job_id=?,attempts=attempts+1,error=NULL WHERE deck_id=? AND page_index=?", (job_id, deck_id, row["page_index"]))
        self._touch(db)

    def _deck_page(self, db, payload):
        deck = self._deck_row(db)
        if not deck or deck["id"] != payload.get("deckId"):
            raise EngineError("DECK_NOT_FOUND", "当前整稿任务不存在。")
        row = db.execute("SELECT * FROM studio_deck_pages WHERE deck_id=? AND page_index=?", (deck["id"], payload.get("pageIndex"))).fetchone()
        if row is None:
            raise EngineError("DECK_PAGE_NOT_FOUND", "整稿中的目标页不存在。")
        return deck, dict(row)

    def _job_available(self, db, job, *, external=False):
        if not self._feedback_available(db, job):
            return False
        if job["payload"].get("kind") == "deck_review":
            deck = self._deck_row(db)
            return bool(not external and deck and deck["id"] == job["payload"]["deckId"] and deck["status"] == "running")
        if job["payload"].get("kind") != "deck_page":
            return True
        deck, page = self._deck_page(db, job["payload"])
        if page["job_id"] != job["id"] or page["status"] == "complete":
            return False
        return deck["status"] == "running" or (external and deck["status"] == "blocked" and self._deck_error(deck).get("code") in WAITING_CODES)

    def _validate_deck_submission(self, db, job, actions):
        if job["payload"].get("kind") == "deck_review":
            raise EngineError("DECK_REVIEW_INTERNAL", "整稿检查由内部执行器运行，不接受外部修改计划。")
        if job["payload"].get("kind") != "deck_page":
            return
        deck, page = self._deck_page(db, job["payload"])
        allowed = self._job_available(db, job, external=True) or (deck["status"] == "paused" and job["status"] == "running")
        if not allowed:
            raise EngineError("DECK_PAUSED", "整稿已暂停、取消或当前页任务已经结束；本次结果未应用。")
        if actions and (len(actions) != 1 or actions[0]["type"] != "slide_add"):
            raise EngineError("SCOPE_VIOLATION", "整稿的当前任务只能新增计划中的这一页。")
        planned = json.loads(page["plan"])
        if actions and (actions[0]["role"] != planned["role"] or actions[0]["title"] != planned["title"]):
            raise EngineError("SCOPE_VIOLATION", "当前页标题与角色需要与已保存的逐页计划一致。")
        if actions and planned.get('composition'):
            from .page_design import prepare_scene
            actions[0]['composition'] = copy.deepcopy(planned['composition'])
            for field in ('takeaway','key_points'):
                if field in planned:
                    actions[0].setdefault(field,planned[field])
            if prepare_scene(actions[0], resolve_images=self._resolve_images) is None:
                raise EngineError('DESIGN_LAYOUT_REQUIRED', '结构化页面需要完整原生场景或图解。')
        if deck["status"] == "blocked":
            db.execute("UPDATE studio_decks SET status='running',last_error=NULL,updated_at=? WHERE id=?", (_now(), deck["id"]))

    def _finish_deck_page(self, db, job, slide_id, question_message_id=None):
        if job["payload"].get("kind") != "deck_page":
            return
        payload = job["payload"]
        if not slide_id:
            self._block_deck(db, payload, {"code": "PAGE_NEEDS_INPUT", "message": "当前页需要补充信息。请在对话中补充后点击重试。", "questionMessageId": question_message_id})
            return
        db.execute("UPDATE studio_deck_pages SET status='complete',slide_id=?,error=NULL WHERE deck_id=? AND page_index=? AND job_id=?", (slide_id, payload["deckId"], payload["pageIndex"], job["id"]))
        self._queue_next_deck_page(db, payload["deckId"])

    def _block_deck(self, db, payload, error, *, page_failed=True):
        deck, page = self._deck_page(db, payload)
        if deck["status"] in {"cancelled", "complete"} or page["status"] == "complete":
            return
        db.execute("UPDATE studio_decks SET status='blocked',last_error=?,updated_at=? WHERE id=?", (_json(error), _now(), deck["id"]))
        if page_failed:
            db.execute("UPDATE studio_deck_pages SET status='failed',error=? WHERE deck_id=? AND page_index=?", (_json(error), deck["id"], page["page_index"]))
        self._touch(db)

    def control_deck(self, action):
        if action not in {"pause", "resume", "retry", "cancel"}:
            raise EngineError("INVALID_DECK_CONTROL", "支持暂停、继续、重试或取消整稿任务。")
        with self.wb.atomic() as db:
            deck = self._deck_row(db)
            if not deck:
                raise EngineError("DECK_NOT_FOUND", "此项目还没有整稿任务。")
            if deck["status"] == "complete":
                return self.deck_state()
            if deck["status"] == "cancelled":
                if action == "cancel":
                    return self.deck_state()
                raise EngineError("DECK_CANCELLED", "此任务已经取消，已生成页面仍保留；请用新项目创建另一套。")
            if action == "pause":
                db.execute("UPDATE studio_decks SET status='paused',updated_at=? WHERE id=?", (_now(), deck["id"]))
            elif action == "cancel":
                db.execute("UPDATE studio_jobs SET status='cancelled',updated_at=? WHERE project_id=? AND client_message_id=? AND status IN ('queued','running')", (_now(), self.project_id, "deck-review:" + deck["id"]))
                rows = db.execute("SELECT job_id FROM studio_deck_pages WHERE deck_id=? AND status!='complete'", (deck["id"],)).fetchall()
                for row in rows:
                    if row["job_id"]:
                        db.execute("UPDATE studio_jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')", (_now(), row["job_id"]))
                db.execute("UPDATE studio_deck_pages SET status='cancelled' WHERE deck_id=? AND status!='complete'", (deck["id"],))
                db.execute("UPDATE studio_decks SET status='cancelled',updated_at=? WHERE id=?", (_now(), deck["id"]))
                db.execute("UPDATE studio_messages SET status='complete' WHERE id=?", (deck["source_message_id"],))
            else:
                db.execute("UPDATE studio_decks SET status='running',last_error=NULL,updated_at=? WHERE id=?", (_now(), deck["id"]))
                self._queue_next_deck_page(db, deck["id"])
            self._touch(db)
            if action == "cancel":
                self._finish_round(self._deck_round_id(db, deck["id"]), force_status="cancelled")
            return self.deck_state()

    def _local_deck_plan(self, payload):
        with self.wb._connection() as db:
            deck, row = self._deck_page(db, payload)
        page = json.loads(row["plan"])
        action = {"type": "slide_add", **{k:v for k,v in page.items() if k != "designBrief"}}
        return {"reply": f"本地大纲排版已完成第 {row['page_index'] + 1} 页：{page['title']}。文字来自已提供大纲，未调用模型。", "actions": [action], "questions": []}
