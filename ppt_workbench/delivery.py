"""Durable user rounds and whole-deck feedback above page-sized mutations.

A round is one accepted user submission. Model calls, page jobs, retries, preview
measurements and automatic repairs are internal work, not extra user rounds.
The target is measured honestly: a fourth submission remains usable and is shown
as over target. Mechanical checks never attest to content truth or human taste.
"""
from __future__ import annotations

import json
import uuid

from .core import EngineError, _now, _json, _hash


ACTIVE_ROUND_STATUSES = {"processing", "checking", "waiting_agent"}
DELIVERY_MUTATION_ACTIONS = {"project-updated", "slide-added", "slide-patched", "slide-restored",
                             "user-input-appended", "workspace-imported"}


class DeliveryFlow:
    def _init_delivery(self):
        with self.wb._connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS studio_delivery_meta (
                project_id TEXT PRIMARY KEY, legacy_history INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS studio_delivery_rounds (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, number INTEGER NOT NULL,
                input_message_id TEXT NOT NULL UNIQUE, input_text TEXT NOT NULL,
                status TEXT NOT NULL, output_message_id TEXT, changed_slides TEXT NOT NULL,
                quality TEXT, snapshot TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(project_id,number));
            CREATE TABLE IF NOT EXISTS studio_delivery_jobs (
                job_id TEXT PRIMARY KEY, round_id TEXT NOT NULL, root_job INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS studio_deck_delivery (
                deck_id TEXT PRIMARY KEY, round_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_feedback_pages (
                parent_job_id TEXT NOT NULL, position INTEGER NOT NULL,
                job_id TEXT NOT NULL UNIQUE, slide_id TEXT NOT NULL,
                PRIMARY KEY(parent_job_id,position));
            CREATE TABLE IF NOT EXISTS studio_delivery_audit (
                project_id TEXT PRIMARY KEY, start_event_seq INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_delivery_event_bindings (
                event_seq INTEGER PRIMARY KEY, project_id TEXT NOT NULL, round_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS studio_deck_intake (
                deck_id TEXT PRIMARY KEY, body TEXT NOT NULL);
            """)
        self._delivery_audit_ready = True
        with self.wb.atomic() as db:
            known = db.execute("SELECT 1 FROM studio_delivery_meta WHERE project_id=?", (self.project_id,)).fetchone()
            if known:
                audit = db.execute("SELECT 1 FROM studio_delivery_audit WHERE project_id=?", (self.project_id,)).fetchone()
                prior_round = db.execute("SELECT 1 FROM studio_delivery_rounds WHERE project_id=? LIMIT 1", (self.project_id,)).fetchone()
                if not audit and prior_round:
                    # An older round ledger lacks mutation attribution. Do not
                    # manufacture proof that its previous changes were counted.
                    db.execute("UPDATE studio_delivery_meta SET legacy_history=1 WHERE project_id=?", (self.project_id,))
                    db.execute("INSERT INTO studio_delivery_audit VALUES (?,?)", (self.project_id, self._last_core_event(db)))
                return
            previous = db.execute("SELECT id,text FROM studio_messages WHERE project_id=? AND role='user' ORDER BY created_at,id", (self.project_id,)).fetchall()
            db.execute("INSERT INTO studio_delivery_meta VALUES (?,?)", (self.project_id, int(bool(previous))))
            # A migrated message is counted, but no past output boundary is
            # invented from a pre-0.4 log.
            for row in previous:
                self._begin_round(db, row["id"], row["text"], status="legacy")

    def _round_for_message(self, db, message_id):
        row = db.execute("SELECT id FROM studio_delivery_rounds WHERE project_id=? AND input_message_id=?", (self.project_id, message_id)).fetchone()
        return row["id"] if row else None

    def _round_for_job(self, db, job_id):
        row = db.execute("SELECT round_id FROM studio_delivery_jobs WHERE job_id=?", (job_id,)).fetchone()
        return row["round_id"] if row else None

    def _begin_round(self, db, message_id, text, job_id=None, status="processing"):
        known = self._round_for_message(db, message_id)
        if known:
            if job_id:
                self._bind_round_job(db, known, job_id, root=True)
            return known
        number = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM studio_delivery_rounds WHERE project_id=?", (self.project_id,)).fetchone()[0]
        db.execute("INSERT OR IGNORE INTO studio_delivery_audit VALUES (?,?)", (self.project_id, self._last_core_event(db)))
        rid = "T-" + uuid.uuid4().hex
        db.execute("INSERT INTO studio_delivery_rounds VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (rid, self.project_id, number, message_id, text, status, None, "[]", None, None, None, _now(), _now()))
        row = db.execute("SELECT extras FROM studio_messages WHERE id=?", (message_id,)).fetchone()
        if row:
            extras = json.loads(row["extras"])
            extras.update(roundId=rid, roundNumber=number)
            db.execute("UPDATE studio_messages SET extras=? WHERE id=?", (_json(extras), message_id))
        if job_id:
            self._bind_round_job(db, rid, job_id, root=True)
        return rid

    def _last_core_event(self, db):
        return db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE project_id=?", (self.project_id,)).fetchone()[0]

    def _bind_operation_events(self, db, after_event_seq, operation):
        """Attribute only writes performed within one atomic internal operation."""
        rid = operation.get("roundId") or (self._round_for_job(db, operation["jobId"]) if operation.get("jobId") else None)
        if not rid or not db.execute("SELECT 1 FROM studio_delivery_rounds WHERE id=? AND project_id=?", (rid, self.project_id)).fetchone():
            return
        rows = db.execute("SELECT seq,action FROM events WHERE project_id=? AND seq>?", (self.project_id, after_event_seq)).fetchall()
        for row in rows:
            if row["action"] in DELIVERY_MUTATION_ACTIONS:
                db.execute("INSERT OR IGNORE INTO studio_delivery_event_bindings VALUES (?,?,?)", (row["seq"], self.project_id, rid))

    def _external_delivery_changes(self, db):
        audit = db.execute("SELECT start_event_seq FROM studio_delivery_audit WHERE project_id=?", (self.project_id,)).fetchone()
        if not audit:
            return []
        rows = db.execute("""SELECT e.seq,e.slide_id,e.action,e.created_at FROM events e
            LEFT JOIN studio_delivery_event_bindings b ON b.event_seq=e.seq
            WHERE e.project_id=? AND e.seq>? AND b.event_seq IS NULL ORDER BY e.seq""", (self.project_id, audit[0])).fetchall()
        return [{"eventId": row["seq"], "slideId": row["slide_id"], "type": row["action"], "createdAt": row["created_at"]}
                for row in rows if row["action"] in DELIVERY_MUTATION_ACTIONS]

    def _intake_from_round(self, db, message_id, page_count):
        """Accumulate declarations from actual user messages, never model plans."""
        from .intake import parse_intake_metadata
        source = db.execute("SELECT number FROM studio_delivery_rounds WHERE project_id=? AND input_message_id=?", (self.project_id, message_id)).fetchone()
        rows = db.execute("SELECT input_message_id,input_text FROM studio_delivery_rounds WHERE project_id=? AND number<=? ORDER BY number",
                          (self.project_id, source["number"])).fetchall() if source else []
        result = {"projectChanges": {}, "pageEvidence": {}, "warnings": [], "sourceMessageIds": []}
        for row in rows:
            parsed = parse_intake_metadata(row["input_text"], page_count=page_count)
            result["projectChanges"].update(parsed["projectChanges"])
            result["pageEvidence"].update(parsed["pageEvidence"])
            result["warnings"].extend(parsed["warnings"])
            if parsed["projectChanges"] or parsed["pageEvidence"] or parsed["warnings"]:
                result["sourceMessageIds"].append(row["input_message_id"])
        return result

    def _deck_intake(self, db, deck_id):
        row = db.execute("SELECT body FROM studio_deck_intake WHERE deck_id=?", (deck_id,)).fetchone()
        return json.loads(row["body"]) if row else {"projectChanges": {}, "pageEvidence": {}, "warnings": [], "sourceMessageIds": []}

    def _intake_page_map(self, db):
        deck = self._deck_row(db)
        if deck:
            rows = db.execute("SELECT page_index,slide_id FROM studio_deck_pages WHERE deck_id=? ORDER BY page_index", (deck["id"],)).fetchall()
            return {row["page_index"] + 1: row["slide_id"] for row in rows}
        return {index: page["id"] for index, page in enumerate(
            [page for page in self.wb.get_project(self.project_id)["workspace"]["slides"] if not page["archived"]], 1)}

    def _intake_questions(self):
        from .intake import missing_intake_questions
        with self.wb._connection() as db:
            pages = self._intake_page_map(db)
            deck = self._deck_row(db)
            evidence = self._deck_intake(db, deck["id"])["pageEvidence"] if deck else {}
            evidence = {int(number): value for number, value in evidence.items()}
            for number, sid in pages.items():
                if sid:
                    evidence[number] = self.wb.get_slide(self.project_id, sid)["slide"]["evidenceRequired"]
        if not pages:
            return []
        project = self.wb.get_project(self.project_id)["workspace"]["project"]
        return missing_intake_questions(project, page_count=len(pages), page_evidence=evidence)

    @staticmethod
    def _intake_question_text(questions):
        return ("\n\n下一轮可以一次补充以下设置，选择后仍可改写：\n" + "\n".join(
            f"{number}. {question['question']}" for number, question in enumerate(questions, 1))) if questions else ""

    def _apply_intake_submission(self, job_id, parsed, feedback=None):
        """Apply explicit user settings atomically, retaining every scene object."""
        if feedback:
            from .feedback import validate_feedback_action
            feedback = validate_feedback_action(feedback)
        with self.wb.atomic() as db:
            job = self.job(job_id)
            if job["status"] == "complete":
                return {"jobId": job_id, "deduplicated": True, **(job["result"] or {})}
            if job["status"] not in {"queued", "running"}:
                raise EngineError("JOB_CLOSED", "这条设置已处理，请查看本轮结果。")
            payload = job["payload"]
            if payload.get("objectId") or payload.get("slideId"):
                raise EngineError("SCOPE_VIOLATION", "项目与逐页依据设置需要在整稿范围提交，请先切回整稿对话。")
            project = self.wb.get_project(self.project_id)
            self.wb._revision(project["revision"], payload["projectRevision"])
            page_map = self._intake_page_map(db)
            declaration = {int(number): value for number, value in parsed["pageEvidence"].items()}
            if any(number not in page_map for number in declaration):
                raise EngineError("FEEDBACK_PAGE_NOT_FOUND", "依据要求指向不存在的页面，设置未应用。")
            baselines = payload.get("deckBaselines", {})
            for sid in (sid for sid in page_map.values() if sid):
                page = self.wb.get_slide(self.project_id, sid)
                scene = self._latest_scene(db, sid)
                baseline = baselines.get(sid)
                if not baseline or baseline["contentRevision"] != page["revision"] or baseline["sceneRevision"] != (scene["revision"] if scene else None):
                    raise EngineError("STALE_REVISION", "收到设置后稿件已改变，请查看当前稿件再提交设置。")
                if scene and self.get_scene(sid)["stale"]:
                    raise EngineError("SCENE_STALE", "现有内容与预览尚未一致，不能用旧预览覆盖新内容。请先生成当前内容的预览。")
            changed = []
            with self._operation(job_id, False, "保存用户明确提供的项目设置", round_id=payload.get("roundId")):
                project_changes = {key: value for key, value in parsed["projectChanges"].items() if project["workspace"]["project"].get(key) != value}
                if project_changes:
                    self.wb.update_project(self.project_id, project["revision"], project_changes)
                deck = self._deck_row(db)
                if deck:
                    stored = self._deck_intake(db, deck["id"])
                    stored["projectChanges"].update(parsed["projectChanges"])
                    stored["pageEvidence"].update({str(key): value for key, value in declaration.items()})
                    stored["warnings"] = parsed["warnings"]
                    stored["sourceMessageIds"].append(job["message_id"])
                    db.execute("INSERT INTO studio_deck_intake VALUES (?,?) ON CONFLICT(deck_id) DO UPDATE SET body=excluded.body", (deck["id"], _json(stored)))
                for number, sid in page_map.items():
                    if not sid:
                        continue
                    page = self.wb.get_slide(self.project_id, sid)
                    if number in declaration and declaration[number] != page["slide"]["evidenceRequired"]:
                        self.wb.patch_slide(self.project_id, sid, page["revision"], [{"path": "/evidenceRequired", "value": declaration[number]}], "保存用户明确声明的本页依据要求")
                        self._round_changed(db, sid)
                        changed.append(sid)
                    # Rebind the existing scene to changed metadata. This is
                    # not a layout regeneration and retains all exact objects.
                    row = self._latest_scene(db, sid)
                    if row and self.get_scene(sid)["stale"]:
                        current = self.wb.get_slide(self.project_id, sid)
                        self.put_scene(sid, current["revision"], json.loads(row["body"]), "保留本页版式并更新用户设置绑定")
                        self._round_changed(db, sid)
                        if sid not in changed:
                            changed.append(sid)
                if feedback:
                    # These baselines can move only over this transaction's
                    # explicit metadata rebind. Every original page baseline
                    # was checked above while holding the same write lock.
                    refreshed = {}
                    for sid in (sid for sid in page_map.values() if sid):
                        current = self.wb.get_slide(self.project_id, sid)
                        scene = self._latest_scene(db, sid)
                        refreshed[sid] = {"contentRevision": current["revision"], "sceneRevision": scene["revision"] if scene else None}
                    payload["deckBaselines"] = refreshed
                    payload["scope"] = "deck"
                    db.execute("UPDATE studio_jobs SET payload=? WHERE id=?", (_json(payload), job_id))
                    self._create_feedback_jobs(db, self.job(job_id), feedback)
            reply = "已保存你明确提供的设置，页面文字与布局保持原样。依据要求仅说明是否需要核验，不代表资料已经核验。"
            if not parsed["projectChanges"] and not declaration:
                reply = "已保留你的原文，当前没有可直接保存的明确设置；尚未自动替你选择。"
            if feedback:
                reply = "已保存明确的项目设置，并将同一条输入里的页面反馈分派为逐页任务；执行完成后统一汇总本轮结果。依据要求不代表资料已经核验。"
            if parsed["warnings"]:
                reply += "\n" + "\n".join(parsed["warnings"])
            result = {"reply": reply, "slideId": None, "sceneRevision": None, "changes": [],
                      "intakeUpdated": True, "preciseEdit": feedback is None, "changedSlideIds": changed}
            self._message(db, "assistant", reply, jobId=job_id)
            db.execute("UPDATE studio_jobs SET status='complete',result=?,updated_at=? WHERE id=?", (_json(result), _now(), job_id))
            db.execute("UPDATE studio_messages SET status='complete' WHERE id=?", (job["message_id"],))
            self._finish_round(self._round_for_job(db, job_id))
            self._touch(db)
            return {"jobId": job_id, **result}

    def _bind_round_job(self, db, round_id, job_id, root=False):
        if not round_id:
            return
        db.execute("INSERT OR IGNORE INTO studio_delivery_jobs VALUES (?,?,?)", (job_id, round_id, int(root)))
        row = db.execute("SELECT payload FROM studio_jobs WHERE id=? AND project_id=?", (job_id, self.project_id)).fetchone()
        if row:
            payload = json.loads(row["payload"])
            payload["roundId"] = round_id
            db.execute("UPDATE studio_jobs SET payload=? WHERE id=?", (_json(payload), job_id))

    def _deck_round_id(self, db, deck_id):
        row = db.execute("SELECT round_id FROM studio_deck_delivery WHERE deck_id=?", (deck_id,)).fetchone()
        return row["round_id"] if row else None

    def _assign_deck_round(self, db, deck_id, round_id):
        if round_id:
            db.execute("INSERT INTO studio_deck_delivery VALUES (?,?) ON CONFLICT(deck_id) DO UPDATE SET round_id=excluded.round_id", (deck_id, round_id))

    def _deck_intake_inputs(self, db, deck):
        source = db.execute("SELECT number FROM studio_delivery_rounds WHERE project_id=? AND input_message_id=?", (self.project_id, deck["source_message_id"])).fetchone()
        if not source:
            return []
        rows = db.execute("SELECT input_message_id,input_text,number FROM studio_delivery_rounds WHERE project_id=? AND number<=? ORDER BY number", (self.project_id, source["number"])).fetchall()
        return [{"messageId": r["input_message_id"], "text": r["input_text"], "roundNumber": r["number"],
                 "provenance": "client-transcribed-unverified"} for r in rows]

    def _round_changed(self, db, slide_id):
        op = getattr(self._operation_local, "current", None) or {}
        rid = op.get("roundId") or (self._round_for_job(db, op["jobId"]) if op.get("jobId") else None)
        if not rid:
            return
        row = db.execute("SELECT changed_slides FROM studio_delivery_rounds WHERE id=?", (rid,)).fetchone()
        if not row:
            return
        changed = json.loads(row["changed_slides"])
        if slide_id not in changed:
            changed.append(slide_id)
            db.execute("UPDATE studio_delivery_rounds SET changed_slides=?,updated_at=? WHERE id=?", (_json(changed), _now(), rid))

    def _delivery_snapshot(self):
        project = self.wb.get_project(self.project_id)
        pages = []
        with self.wb._connection() as db:
            for slide in project["workspace"]["slides"]:
                if slide["archived"]:
                    continue
                row = self._latest_scene(db, slide["id"])
                pages.append({"slideId": slide["id"], "contentRevision": slide["revision"],
                              "sceneRevision": row["revision"] if row else None,
                              "sceneHash": _hash(json.loads(row["body"])) if row else None})
        return {"projectRevision": project["revision"], "projectHash": _hash(project["workspace"]["project"]), "slides": pages}

    def delivery_state(self):
        snapshot = self._delivery_snapshot()
        with self.wb._connection() as db:
            rows = db.execute("SELECT * FROM studio_delivery_rounds WHERE project_id=? ORDER BY number", (self.project_id,)).fetchall()
            meta = db.execute("SELECT legacy_history FROM studio_delivery_meta WHERE project_id=?", (self.project_id,)).fetchone()
            external = self._external_delivery_changes(db)
        rounds = [{"id": r["id"], "number": r["number"], "inputMessageId": r["input_message_id"],
                   "inputText": r["input_text"], "status": r["status"], "outputMessageId": r["output_message_id"],
                   "changedSlideIds": json.loads(r["changed_slides"]),
                   "quality": json.loads(r["quality"]) if r["quality"] else None,
                   "snapshot": json.loads(r["snapshot"]) if r["snapshot"] else None,
                   "snapshotStale": bool(r["snapshot"] and json.loads(r["snapshot"]) != snapshot),
                   "error": json.loads(r["error"]) if r["error"] else None,
                   "createdAt": r["created_at"], "updatedAt": r["updated_at"]} for r in rows]
        quality = self.quality_state() if hasattr(self, "quality_state") else None
        # A superseded historical output may still say it awaited measurements.
        # Only the latest user round drives today's composer status.
        active = rounds[-1] if rounds and rounds[-1]["status"] in ACTIVE_ROUND_STATUSES else None
        accepted = bool(quality and quality.get("readyToReview") and quality.get("humanAccepted"))
        release = self.wb.gate(self.project_id) if rounds else {"ready": False, "slides": []}
        grouped_issues = {}
        for page in release["slides"]:
            for issue in page["issues"]:
                key = (issue["code"], issue["message"])
                grouped_issues.setdefault(key, []).append(page["slideId"])
        release_issues = [{"code": code, "message": message, "slideIds": ids} for (code, message), ids in grouped_issues.items()]
        accounting_complete = not bool(external or (meta and meta[0]))
        target_satisfied = bool(rounds and len(rounds) <= 3 and accepted and release["ready"] and accounting_complete
                                and rounds[-1]["status"] == "ready" and not rounds[-1]["snapshotStale"])
        return {"targetRounds": 3, "inputCount": len(rounds),
                "outputCount": sum(bool(r["outputMessageId"]) for r in rounds),
                "withinTarget": len(rounds) <= 3, "status": rounds[-1]["status"] if rounds else "idle",
                "activeRound": active, "rounds": rounds, "qualitySummary": quality,
                "legacyHistory": bool(meta and meta[0]), "qualityAccepted": accepted, "targetSatisfied": target_satisfied,
                "externalChanges": external[-50:], "externalChangeCount": len(external), "interactionAccountingComplete": accounting_complete,
                "releaseReady": release["ready"], "releaseIssues": release_issues,
                "note": "首次需求、澄清和修改均计入用户轮次；内部逐页制作、重试和自动检查不增加轮次。三轮以内不自动代表质量合格。" +
                        (" 存在未绑定聊天轮次的外部修改；不推定为人类输入次数，也不能宣称完整的三轮验收已达成。" if external else "")}

    def _round_jobs(self, db, round_id):
        rows = db.execute("SELECT j.id FROM studio_jobs j JOIN studio_delivery_jobs r ON j.id=r.job_id WHERE r.round_id=? AND j.project_id=? ORDER BY j.created_at,j.id", (round_id, self.project_id)).fetchall()
        return [self.job(r["id"]) for r in rows]

    @staticmethod
    def _superseded_round_job(db, job):
        if job["payload"].get("kind") != "deck_page":
            return False
        latest = db.execute("SELECT job_id FROM studio_deck_pages WHERE deck_id=? AND page_index=?", (job["payload"]["deckId"], job["payload"]["pageIndex"])).fetchone()
        return bool(latest and latest[0] != job["id"])

    def _feedback_available(self, db, job):
        if job["payload"].get("kind") != "feedback_page":
            return True
        row = db.execute("SELECT * FROM studio_feedback_pages WHERE job_id=?", (job["id"],)).fetchone()
        if not row:
            return False
        earlier = db.execute("SELECT j.status FROM studio_feedback_pages f JOIN studio_jobs j ON j.id=f.job_id WHERE f.parent_job_id=? AND f.position<?", (row["parent_job_id"], row["position"])).fetchall()
        return all(r["status"] == "complete" for r in earlier)

    def _create_feedback_jobs(self, db, parent, action):
        from .feedback import validate_feedback_action
        validate_feedback_action(action)
        if parent["payload"].get("objectId"):
            raise EngineError("SCOPE_VIOLATION", "已选中对象时不能派发整稿修改，请清除对象范围后提交整稿反馈。")
        if parent["payload"].get("scope") != "deck":
            raise EngineError("SCOPE_VIOLATION", "当前输入仅授权单页修改，不能自行扩展为整稿修改。")
        if parent["payload"].get("kind") in {"deck_page", "feedback_page"}:
            raise EngineError("SCOPE_VIOLATION", "自动页面任务不能再创建整稿反馈。")
        rid = self._round_for_job(db, parent["id"])
        project = self.wb.get_project(self.project_id)
        active_ids = {s["id"] for s in project["workspace"]["slides"] if not s["archived"]}
        # All target baselines and objects are checked before adding any task.
        prepared = []
        for edit in action["edits"]:
            sid = edit["slide_id"]
            if sid not in active_ids:
                raise EngineError("FEEDBACK_PAGE_NOT_FOUND", "整稿反馈包含不存在或已归档的页面。", {"slideId": sid})
            page = self.wb.get_slide(self.project_id, sid)
            scene = self.get_scene(sid)
            baseline = parent["payload"].get("deckBaselines", {}).get(sid)
            if not baseline:
                raise EngineError("FEEDBACK_BASELINE_MISSING", "该页不属于提交本轮反馈时看到的版本，请重新查看后提交。", {"slideId": sid})
            self.wb._revision(page["revision"], baseline["contentRevision"])
            self.wb._revision(scene["sceneRevision"], baseline["sceneRevision"])
            if scene["stale"]:
                raise EngineError("SCENE_STALE", "反馈的页面预览已过期，请先更新该页预览。", {"slideId": sid})
            oid = edit.get("object_id")
            if oid and oid not in {o["id"] for o in scene["scene"]["objects"]}:
                raise EngineError("OBJECT_NOT_FOUND", "反馈指定的对象不存在。", {"slideId": sid, "objectId": oid})
            prepared.append((edit, page, scene))
        deck = self._deck_row(db)
        local = self.agent_mode == "outline" or (self.agent_mode == "manual" and deck and deck["execution"] == "outline")
        for index, (edit, page, scene) in enumerate(prepared):
            jid = "J-" + uuid.uuid4().hex
            payload = {"kind": "feedback_page", "parentJobId": parent["id"], "roundId": rid,
                       "message": edit["instruction"], "sourceMessage": parent["payload"]["message"],
                       "slideId": edit["slide_id"], "objectId": edit.get("object_id"),
                       "baseRevision": page["revision"], "baseSceneRevision": scene["sceneRevision"],
                       "projectRevision": project["revision"], "attachments": parent["payload"].get("attachments", []),
                       "execution": "outline" if local else "agent", "scope": "page"}
            db.execute("INSERT INTO studio_jobs VALUES (?,?,?,?,?,?,?,?,?)", (jid, self.project_id,
                       "feedback:" + parent["id"] + ":" + str(index), parent["message_id"], "queued", _json(payload), None, _now(), _now()))
            db.execute("INSERT INTO studio_feedback_pages VALUES (?,?,?,?)", (parent["id"], index, jid, edit["slide_id"]))
            self._bind_round_job(db, rid, jid)
        return [edit["slide_id"] for edit, _, _ in prepared]

    def _validate_feedback_submission(self, db, job, actions):
        payload = job["payload"]
        if payload.get("kind") != "feedback_page":
            return
        if not self._feedback_available(db, job):
            raise EngineError("FEEDBACK_WAITING", "上一页反馈尚未完成，当前页暂不能提交。")
        if any(a["type"] not in {"slide_patch", "scene_replace", "scene_patch"} or a.get("slide_id") != payload["slideId"] for a in actions):
            raise EngineError("SCOPE_VIOLATION", "本反馈子任务只能修改它绑定的页面。")
        # Check both saved baselines even when a model returns only a question.
        self.wb._revision(self.wb.get_slide(self.project_id, payload["slideId"])["revision"], payload["baseRevision"])
        self.wb._revision(self.get_scene(payload["slideId"])["sceneRevision"], payload["baseSceneRevision"])

    def _finish_round(self, round_id, *, force_status=None, error=None):
        if not round_id:
            return
        with self.wb.atomic() as db:
            row = db.execute("SELECT * FROM studio_delivery_rounds WHERE id=? AND project_id=?", (round_id, self.project_id)).fetchone()
            if not row:
                return
            jobs = self._round_jobs(db, round_id)
            effective = [j for j in jobs if not self._superseded_round_job(db, j)]
            failed = [j for j in effective if j["status"] == "failed"]
            pending = [j for j in effective if j["status"] in {"queued", "running"}]
            deck = self._deck_row(db)
            owns_deck = bool(deck and self._deck_round_id(db, deck["id"]) == round_id)
            deck_error = self._deck_error(deck) if owns_deck else {}
            if force_status:
                status = force_status
            elif row["status"] == "cancelled" or any(j["status"] == "cancelled" for j in effective):
                status = "cancelled"
            elif failed:
                status = "failed"
                error = error or (failed[0].get("result") or {}).get("error")
            elif owns_deck and deck["status"] == "blocked" and deck_error.get("code") == "PAGE_NEEDS_INPUT":
                status = "needs_input"
            elif pending or (owns_deck and deck["status"] in {"running", "paused", "blocked"}):
                status = "waiting_agent" if owns_deck and deck["status"] == "blocked" else "processing"
                db.execute("UPDATE studio_delivery_rounds SET status=?,updated_at=? WHERE id=?", (status, _now(), round_id))
                return
            elif owns_deck and deck["status"] == "cancelled":
                status = "cancelled"
            else:
                unanswered = [j for j in jobs if (j.get("result") or {}).get("needsInput")]
                status = "needs_input" if unanswered else "ready"
            # Repeated poll/dispatch completion does not create another result.
            if row["output_message_id"] and row["status"] == status and row["snapshot"]:
                return
            changed = json.loads(row["changed_slides"])
            quality = None
            if status in {"ready", "needs_input"} and hasattr(self, "run_quality"):
                db.execute("UPDATE studio_delivery_rounds SET status='checking',updated_at=? WHERE id=?", (_now(), round_id))
                roots = [j for j in jobs if j["payload"].get("kind") not in {"deck_page", "feedback_page"}]
                scoped = bool(any(j["payload"].get("objectId") or (j.get("result") or {}).get("preciseEdit") for j in jobs))
                # For a selected-object operation, no automatic change to a
                # different object is allowed. Full-deck input may safely fix
                # layout only on pages this round actually changed.
                auto_fix = bool(changed and not scoped and (owns_deck or any(j["payload"].get("scope") == "deck" for j in roots)))
                try:
                    with self._operation(generation=True, round_id=round_id, automatic=True, description="本轮自动版式检查"):
                        quality = self.run_quality(auto_fix=auto_fix, round_id=round_id, scope_slide_ids=changed)
                except Exception as exc:
                    # The user changes already succeeded. A failed check must
                    # remain visible rather than rolling those changes back.
                    quality = {"status": "check_failed", "readyToReview": False, "humanAccepted": False,
                               "error": exc.to_dict() if isinstance(exc, EngineError) else {"code": "QUALITY_CHECK_FAILED", "message": "自动检查失败，请重试检查。"}}
            if status == "ready" and quality and quality.get("browser", {}).get("pendingSlideIds"):
                status = "checking"
            snapshot = self._delivery_snapshot()
            refreshed = db.execute("SELECT changed_slides FROM studio_delivery_rounds WHERE id=?", (round_id,)).fetchone()
            changed = json.loads(refreshed[0])
            text = self._round_summary(row["number"], status, jobs, changed, quality, error)
            intake_questions = self._intake_questions() if status in {"ready", "checking"} else []
            text += self._intake_question_text(intake_questions)
            extras = {"roundId": round_id, "roundNumber": row["number"], "isRoundOutput": True,
                      "internalProgress": False, "changedSlideIds": changed, "roundStatus": status,
                      "quality": quality, "snapshot": snapshot, "intakeQuestions": intake_questions}
            choices = []
            # Surface questions once in the round output, retaining original
            # question IDs so answers cannot drift onto another page.
            for job in jobs:
                for m in db.execute("SELECT id,extras FROM studio_messages WHERE project_id=? AND role='assistant'", (self.project_id,)).fetchall():
                    detail = json.loads(m["extras"])
                    if detail.get("jobId") == job["id"] and detail.get("choices"):
                        for choice in detail["choices"]:
                            item = dict(choice)
                            if detail.get("isDeckQuestion"):
                                item["questionMessageId"] = m["id"]
                                item["deckPageIndex"] = detail.get("deckPageIndex")
                                item["deckId"] = detail.get("deckId")
                            choices.append(item)
            for question in intake_questions:
                for index, value in enumerate(question["choices"]):
                    label = value.strip().replace("\n", "；")
                    if question["id"] == "intake_sources":
                        # Choices can be de-duplicated when only page evidence
                        # remains missing. A positional label could otherwise
                        # promise verification while submitting evidence=no.
                        declarations = value.strip().splitlines()
                        parts = [line for line in declarations if line.startswith("数据策略：")]
                        requirements = {line.split("：", 1)[1] for line in declarations if "页依据要求：" in line}
                        if len(requirements) == 1:
                            parts.append("这些待补页的依据要求：" + next(iter(requirements)))
                        elif requirements:
                            parts.extend(line for line in declarations if "页依据要求：" in line)
                        label = "；".join(parts) or label
                    choices.append({"label": label, "value": value.strip(), "groupId": question["id"], "intakeChoice": True})
            extras["choices"] = choices
            output_id = row["output_message_id"]
            if output_id:
                db.execute("UPDATE studio_messages SET text=?,status=?,extras=? WHERE id=?", (text, "failed" if status == "failed" else "complete", _json(extras), output_id))
            else:
                output_id = self._message(db, "assistant", text, status="failed" if status == "failed" else "complete", **extras)
            db.execute("UPDATE studio_delivery_rounds SET status=?,output_message_id=?,quality=?,snapshot=?,error=?,updated_at=? WHERE id=?",
                       (status, output_id, _json(quality) if quality is not None else None, _json(snapshot), _json(error) if error else None, _now(), round_id))
            db.execute("UPDATE studio_messages SET status=? WHERE id=?", ("failed" if status == "failed" else "complete", row["input_message_id"]))
            self._touch(db)

    @staticmethod
    def _round_summary(number, status, jobs, changed, quality, error):
        if status == "failed":
            headline = f"第 {number} 轮尚未完成：{(error or {}).get('message', '部分页面处理失败')}。已完成的页面保留，可重试失败任务。"
        elif status == "cancelled":
            headline = f"第 {number} 轮已停止。已生成页面与原始输入保留。"
        elif status == "needs_input":
            headline = f"第 {number} 轮已整理现有内容，仍有需要你决定或补充的信息。"
        else:
            headline = f"第 {number} 轮结果已更新" + (f"，涉及 {len(changed)} 页。" if changed else "。")
        replies = []
        for job in jobs:
            result = job.get("result") or {}
            if job["payload"].get("kind") not in {"deck_page", "feedback_page"} and result.get("reply"):
                replies.append(result["reply"])
            elif result.get("needsInput") and result.get("reply"):
                replies.append(result["reply"])
        lines = [headline] + list(dict.fromkeys(replies))
        if quality:
            if quality.get("status") in {"checks_passed", "ready_to_review"}:
                lines.append("自动检查已通过已覆盖的项目，请查看整套预览确认内容与设计。")
            elif quality.get("status") == "awaiting_browser":
                lines.append("页面已生成，等待浏览器完成实际文字与图片检查；目前不能据此认定版式已通过。")
            else:
                lines.append("自动检查仍有需要处理或查看的项目，详情见检查面板。")
        if number > 3:
            lines.append("本次已超过三轮交互目标，记录不会清零。")
        lines.append("自动页内调整与任务重试不新增用户轮次；合格与否仍以实际内容、预览及文件检查为准。")
        return "\n\n".join(lines)

    def refresh_delivery_quality(self):
        """Refresh one existing output after new measurements, never add a turn."""
        current_snapshot = self._delivery_snapshot()
        quality = self.quality_state() if hasattr(self, "quality_state") else None
        if quality and quality.get("status") == "stale":
            return False
        with self.wb.atomic() as db:
            row = db.execute("SELECT * FROM studio_delivery_rounds WHERE project_id=? AND output_message_id IS NOT NULL ORDER BY number DESC LIMIT 1", (self.project_id,)).fetchone()
            if not row or not row["snapshot"]:
                return False
            old_snapshot = json.loads(row["snapshot"])
            if old_snapshot != current_snapshot and not self._quality_revision_chain(db, row["id"], old_snapshot, current_snapshot):
                return False
            status = row["status"]
            if status == "checking" and quality and not quality.get("browser", {}).get("pendingSlideIds"):
                status = "ready"
            db.execute("UPDATE studio_delivery_rounds SET quality=?,updated_at=? WHERE id=?", (_json(quality), _now(), row["id"]))
            message = db.execute("SELECT extras FROM studio_messages WHERE id=?", (row["output_message_id"],)).fetchone()
            extras = json.loads(message[0])
            extras.update(quality=quality, snapshot=current_snapshot, roundStatus=status)
            jobs = self._round_jobs(db, row["id"])
            text = self._round_summary(row["number"], status, jobs, json.loads(row["changed_slides"]), quality,
                                       json.loads(row["error"]) if row["error"] else None)
            text += self._intake_question_text(extras.get("intakeQuestions", []))
            db.execute("UPDATE studio_messages SET text=?,extras=? WHERE id=?", (text, _json(extras), row["output_message_id"]))
            db.execute("UPDATE studio_delivery_rounds SET status=?,snapshot=? WHERE id=?", (status, _json(current_snapshot), row["id"]))
            self._touch(db)
        return True

    def _quality_revision_chain(self, db, round_id, old, new):
        """Only known automatic fixes may refresh an already delivered version."""
        if old.get("projectHash") != new.get("projectHash"):
            return False
        previous = {p["slideId"]: p for p in old["slides"]}
        current = {p["slideId"]: p for p in new["slides"]}
        if previous.keys() != current.keys():
            return False
        changed = False
        for sid, before in previous.items():
            after = current[sid]
            if before == after:
                continue
            changed = True
            scene_row = self._latest_scene(db, sid)
            if (not scene_row or scene_row["content_revision"] != after["contentRevision"]
                    or _hash(json.loads(scene_row["body"])) != after["sceneHash"]):
                return False
            cursor = before.get("sceneRevision")
            if cursor is None or after.get("sceneRevision") is None or after["sceneRevision"] <= cursor:
                return False
            rows = db.execute("SELECT before_revision,after_revision FROM studio_quality_fixes WHERE project_id=? AND round_id=? AND slide_id=? ORDER BY before_revision", (self.project_id, round_id, sid)).fetchall()
            for fix in rows:
                if fix["before_revision"] == cursor:
                    cursor = fix["after_revision"]
            if cursor != after["sceneRevision"]:
                return False
        return changed

    def delivery_auto_fix_scope(self, round_id):
        """Measurements may narrow this scope; they must never broaden it."""
        if not round_id:
            return {"autoFix": False, "slideIds": []}
        with self.wb._connection() as db:
            row = db.execute("SELECT changed_slides,status FROM studio_delivery_rounds WHERE project_id=? AND id=?", (self.project_id, round_id)).fetchone()
            latest = db.execute("SELECT id FROM studio_delivery_rounds WHERE project_id=? ORDER BY number DESC LIMIT 1", (self.project_id,)).fetchone()
            if not latest or latest["id"] != round_id:
                return {"autoFix": False, "slideIds": []}
            if not row or row["status"] in {"failed", "cancelled", "legacy"}:
                return {"autoFix": False, "slideIds": []}
            jobs = self._round_jobs(db, round_id)
            precise = any(j["payload"].get("objectId") or (j.get("result") or {}).get("preciseEdit") for j in jobs)
            changed = json.loads(row["changed_slides"])
            scoped = any(j["payload"].get("scope") == "deck" or j["payload"].get("kind") == "deck_page" for j in jobs)
            return {"autoFix": bool(changed and scoped and not precise), "slideIds": changed if scoped and not precise else []}

    def control_delivery(self, action, round_id=None):
        if action not in {"retry", "cancel"}:
            raise EngineError("INVALID_DELIVERY_CONTROL", "支持重试失败任务或停止当前轮。")
        with self.wb.atomic() as db:
            if round_id is None:
                found = db.execute("SELECT id FROM studio_delivery_rounds WHERE project_id=? ORDER BY number DESC LIMIT 1", (self.project_id,)).fetchone()
                round_id = found[0] if found else None
            row = db.execute("SELECT * FROM studio_delivery_rounds WHERE id=? AND project_id=?", (round_id, self.project_id)).fetchone()
            if not row:
                raise EngineError("ROUND_NOT_FOUND", "未找到这轮输入。")
            if row["status"] == "cancelled" and action == "retry":
                raise EngineError("ROUND_CANCELLED", "这一轮已经停止，不能重启其中部分任务。请重新提交明确反馈。")
            jobs = self._round_jobs(db, round_id)
            if action == "cancel":
                for job in jobs:
                    db.execute("UPDATE studio_jobs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')", (_now(), job["id"]))
                deck = self._deck_row(db)
                if deck and self._deck_round_id(db, deck["id"]) == round_id and deck["status"] not in {"complete", "cancelled"}:
                    self.control_deck("cancel")
                self._finish_round(round_id, force_status="cancelled")
            else:
                failed = [j for j in jobs if j["status"] == "failed" and not self._superseded_round_job(db, j)]
                if not failed:
                    raise EngineError("ROUND_NOT_RETRYABLE", "本轮没有可重试的失败任务。补充观点请发送新消息，自动检查可单独重跑。")
                for job in failed:
                    db.execute("UPDATE studio_jobs SET status='queued',result=NULL,updated_at=? WHERE id=?", (_now(), job["id"]))
                    if job["payload"].get("kind") == "deck_page":
                        db.execute("UPDATE studio_deck_pages SET status='queued',error=NULL WHERE job_id=?", (job["id"],))
                        db.execute("UPDATE studio_decks SET status='running',last_error=NULL,updated_at=? WHERE id=?", (_now(), job["payload"]["deckId"]))
                db.execute("UPDATE studio_delivery_rounds SET status='processing',error=NULL,updated_at=? WHERE id=?", (_now(), round_id))
                db.execute("UPDATE studio_messages SET status='queued' WHERE id=?", (row["input_message_id"],))
                self._touch(db)
        return self.delivery_state()

    def _operator_submission(self, message, payload, callback, client_message_id=None):
        """Count an explicit browser control once; not an agent action protocol."""
        request_id = client_message_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not request_id or len(request_id) > 160:
            raise EngineError("INVALID_MESSAGE_ID", "操作消息标识无效。")
        with self.wb.atomic() as db:
            existing = db.execute("SELECT id,status,result FROM studio_jobs WHERE project_id=? AND client_message_id=?", (self.project_id, request_id)).fetchone()
            if existing:
                return {"jobId": existing["id"], "status": existing["status"], "roundId": self._round_for_job(db, existing["id"]),
                        "deduplicated": True, "result": json.loads(existing["result"]) if existing["result"] else None}
            jid = "J-" + uuid.uuid4().hex
            mid = self._message(db, "user", message, payload.get("slideId"), "running", jobId=jid, source="local-browser-control")
            payload = {"kind": "operator_control", "message": message, "slideId": None, "objectId": None,
                       "baseRevision": None, "baseSceneRevision": None, "projectRevision": self.wb.get_project(self.project_id)["revision"],
                       "attachments": [], "scope": "page", **payload}
            db.execute("INSERT INTO studio_jobs VALUES (?,?,?,?,?,?,?,?,?)", (jid, self.project_id, request_id, mid, "running", _json(payload), None, _now(), _now()))
            rid = self._begin_round(db, mid, message, jid)
            with self._operation(jid, False, message, round_id=rid):
                result = callback()
            outcome = {"reply": message + "：已执行并记录。", "slideId": payload.get("slideId"),
                       "changes": result.get("changes", []) if isinstance(result, dict) else [], "preciseEdit": True,
                       "operatorControl": True}
            db.execute("UPDATE studio_jobs SET status='complete',result=?,updated_at=? WHERE id=?", (_json(outcome), _now(), jid))
            db.execute("UPDATE studio_messages SET status='complete' WHERE id=?", (mid,))
            self._finish_round(rid)
            return {"jobId": jid, "roundId": rid, "status": "complete", "result": result}

    def undo_submission(self, slide_id, scene_revision, client_message_id=None):
        return self._operator_submission("撤销当前页的上一版修改", {"slideId": slide_id, "baseSceneRevision": scene_revision},
                                         lambda: self.undo(slide_id, scene_revision), client_message_id)

    def review_submission(self, slide_id, scene_revision, statement, client_message_id=None):
        if not isinstance(statement, str) or not statement.strip() or len(statement) > 4000:
            raise EngineError("INVALID_REVIEW", "请提供明确的当前页审阅陈述。")
        return self._operator_submission(statement, {"slideId": slide_id, "baseSceneRevision": scene_revision},
                                         lambda: self.review(slide_id, scene_revision, statement), client_message_id)

    def review_deck(self, scene_revisions, statement, client_message_id=None):
        """One explicit whole-deck operator attestation, never evidence approval."""
        if not isinstance(scene_revisions, dict) or not scene_revisions or any(not isinstance(sid, str) or type(rev) is not int or rev < 1 for sid, rev in scene_revisions.items()):
            raise EngineError("INVALID_REVIEW", "整稿认可需要当前全部页面的明确版本。")
        if not isinstance(statement, str) or not statement.strip() or len(statement) > 4000:
            raise EngineError("INVALID_REVIEW", "请提供明确的整稿审阅陈述。")

        def accept():
            project = self.wb.get_project(self.project_id)
            ids = [p["id"] for p in project["workspace"]["slides"] if not p["archived"]]
            if set(ids) != set(scene_revisions):
                raise EngineError("REVIEW_SCOPE_MISMATCH", "页面数量或范围已经变化，请先查看完整的当前稿件。")
            deck = self.deck_state()
            if deck and deck["completedPages"] != deck["totalPages"]:
                raise EngineError("DECK_INCOMPLETE", "整稿尚未全部生成，不能认可为完整稿件。")
            for sid in ids:
                current = self.get_scene(sid)
                self.wb._revision(current["sceneRevision"], scene_revisions[sid])
                if current["stale"]:
                    raise EngineError("SCENE_STALE", "页面内容与预览不一致，请先查看当前版本。")
            quality = self.quality_state()
            if not quality.get("readyToReview"):
                raise EngineError("QUALITY_NOT_READY", "当前稿件还有待测量或需要处理的版式问题。请查看检查面板后再认可。", {"status": quality.get("status")})
            for sid in ids:
                self.review(sid, scene_revisions[sid], statement)
            return {"reviewedSlides": ids, "assurance": "local-operator-attestation", "evidenceVerified": False}

        return self._operator_submission(statement, {"scope": "deck", "sceneRevisions": scene_revisions}, accept, client_message_id)
