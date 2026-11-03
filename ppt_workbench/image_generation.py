"""Provider-neutral, durable image jobs for editable Studio scenes.

A worker explicitly calls run(); no network provider or background thread is
implicitly started. Providers return bytes, never a remote URL. Running jobs are
not automatically retried after a crash because generation may incur a charge.
"""
from __future__ import annotations

import base64
import copy
import json
import math
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from .core import EngineError, _json, _now

IMAGE_ERROR_CODES = frozenset({
    'IMAGE_PROVIDER_FAILED', 'IMAGE_TOOL_UNAVAILABLE', 'IMAGE_AUTH_FAILED',
    'IMAGE_TIMEOUT', 'IMAGE_SESSION_FAILED', 'IMAGE_INVALID_RESPONSE',
    'IMAGE_OUTPUT_INVALID', 'IMAGE_RESULT_TOO_LARGE', 'IMAGE_START_FAILED',
    'IMAGE_SANDBOX_UNAVAILABLE', 'IMAGE_NO_RESULT',
})


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    mime: str


class ImageProvider(Protocol):
    def generate(self, prompt: str) -> GeneratedImage: ...


class ImageJobs:
    def __init__(self, studio):
        self.studio = studio
        with studio.wb._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS image_generation_jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, request_id TEXT NOT NULL,
                slide_id TEXT NOT NULL, object_id TEXT NOT NULL, prompt TEXT NOT NULL,
                content_revision INTEGER NOT NULL, scene_revision INTEGER NOT NULL,
                status TEXT NOT NULL, asset_id TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, UNIQUE(project_id, request_id))""")

            db.execute("""CREATE TABLE IF NOT EXISTS image_generation_batches (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, slide_id TEXT NOT NULL,
                content_revision INTEGER NOT NULL, scene_revision INTEGER NOT NULL,
                images TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS image_generation_errors (
                job_id TEXT PRIMARY KEY, code TEXT NOT NULL)""")

    def recover_interrupted(self):
        with self.studio.wb.atomic() as db:
            batches = db.execute("SELECT id,images FROM image_generation_batches WHERE project_id=? AND status='running'", (self.studio.project_id,)).fetchall()
            for batch in batches:
                for entry in json.loads(batch['images']):
                    db.execute("UPDATE image_generation_jobs SET status=CASE WHEN status='running' THEN 'unknown' ELSE 'canceled' END,updated_at=? WHERE id=? AND status IN ('running','pending')", (_now(), entry['job_id']))
                db.execute("UPDATE image_generation_batches SET status='interrupted' WHERE id=?", (batch['id'],))
            if batches:
                self.studio._touch(db)
                for batch in batches:
                    self.studio._finish_round(self.studio._round_for_job(db, batch['id']))

    def enqueue_batch(self, request_id, slide_id, images):
        with self.studio.wb.atomic() as db:
            existing = db.execute("SELECT * FROM image_generation_batches WHERE project_id=? AND id=?", (self.studio.project_id, request_id)).fetchone()
            if existing:
                return dict(existing)
            scene = self.studio.get_scene(slide_id)
            if scene['stale']:
                raise ValueError('Scene is stale')
            objects = {o['id']: o for o in scene['scene']['objects']}
            replacements = [image['replace_object_id'] for image in images if image.get('replace_object_id')]
            output_ids = [image['object_id'] for image in images]
            def invalid(reason, object_id=None):
                raise EngineError('IMAGE_INVALID_TARGET', reason,
                                  {'slideId':slide_id,'objectId':object_id})
            if len(set(output_ids)) != len(output_ids) or len(set(replacements)) != len(replacements):
                invalid('同一次生图不能重复使用输出对象或替换目标。')
            for image in images:
                oid=image['object_id'];replacement=image.get('replace_object_id')
                target=objects.get(replacement)
                if not isinstance(oid,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}',oid):
                    invalid('图片对象 ID 无效，请使用新的有效对象 ID。',oid)
                if replacement:
                    if target is None:
                        invalid('找不到要替换的对象，请使用当前页面的对象 ID，或不指定替换对象来新增图片。',replacement)
                    if target['type'] not in ('text','image','rect') or (target['type']=='text' and 'binding' in target):
                        invalid('只能替换图片、矩形或未绑定的文字占位，不能替换标题等绑定文字。',replacement)
                    if replacement in scene['scene'].get('diagram',{}).get('objectIds',[]):
                        invalid('图解内部对象请通过“换成 AI 图解”整体替换，保留图解关系。',replacement)
                if oid in objects and not (oid==replacement and target['type'] in ('image','rect')):
                    invalid('新图片的对象 ID 已被占用；替换已有图片或矩形时可沿用其 ID。',oid)
                if oid in replacements and oid != replacement:
                    invalid('图片输出对象不能同时是另一张图片的替换目标。',oid)
                if image.get('placement','foreground') not in ('background','foreground'):
                    invalid('图片图层只能是 background 或 foreground。',oid)
                box={k:image.get(k) for k in ('x','y','w','h')}
                if (any(type(v) not in (int,float) or not math.isfinite(v) for v in box.values())
                        or box['x']<0 or box['y']<0 or box['w']<=0 or box['h']<=0
                        or box['x']+box['w']>scene['scene']['width']+.01
                        or box['y']+box['h']>scene['scene']['height']+.01):
                    invalid('图片尺寸或位置超出当前画布，请调整后再生成。',oid)
            if any(image.get('replace_diagram') for image in images):
                from .diagram_design import validate_metadata
                if len(images)!=1 or not scene['scene'].get('diagram'):
                    raise ValueError('Invalid diagram replacement')
                validate_metadata(scene['scene']['diagram'],scene['scene']['objects'])
            entries = []
            now = _now()
            for index, image in enumerate(images):
                job_id = 'I-' + uuid.uuid4().hex
                db.execute("INSERT INTO image_generation_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (job_id, self.studio.project_id, request_id + ':' + str(index), slide_id, image['object_id'], image['prompt'], scene['contentRevision'], scene['sceneRevision'], 'pending', None, now, now))
                entries.append({**image, 'job_id': job_id})
            db.execute("INSERT INTO image_generation_batches VALUES (?,?,?,?,?,?,?,?)", (request_id, self.studio.project_id, slide_id, scene['contentRevision'], scene['sceneRevision'], _json(entries), 'pending', now))
            return {'id': request_id, 'status': 'pending'}

    def run_batch(self, batch_id, provider):
        with self.studio.wb.atomic() as db:
            batch = db.execute("SELECT * FROM image_generation_batches WHERE project_id=? AND id=?", (self.studio.project_id, batch_id)).fetchone()
            if not batch or batch['status'] != 'pending':
                return
            db.execute("UPDATE image_generation_batches SET status='running' WHERE id=?", (batch_id,))
            self.studio._touch(db, batch['slide_id'])
        entries = json.loads(batch['images'])
        for index, entry in enumerate(entries):
            if self.run(entry['job_id'], provider)['status'] != 'complete':
                with self.studio.wb.atomic() as db:
                    for remaining in entries[index + 1:]:
                        db.execute("UPDATE image_generation_jobs SET status='canceled',updated_at=? WHERE id=? AND status='pending'", (_now(), remaining['job_id']))
                break
        with self.studio.wb.atomic() as db:
            jobs = [self.get(entry['job_id']) for entry in entries]
            automatic = all(entry.get('auto') for entry in entries)
            if any(job['status'] != 'complete' for job in jobs):
                status = 'failed'
            else:
                current = self.studio.get_scene(batch['slide_id'])
                moved = current['contentRevision'] != batch['content_revision'] or current['sceneRevision'] != batch['scene_revision']
                from .auto_images import slots_unchanged
                if current['stale'] or (moved and not slots_unchanged(current['scene'], entries)):
                    status = 'conflict'
                else:
                    candidate = copy.deepcopy(current['scene'])
                    for entry, job in zip(entries, jobs):
                        if entry.get('replace_diagram'):
                            ids=set(candidate['diagram']['objectIds'])
                            candidate['objects']=[o for o in candidate['objects'] if o['id'] not in ids]
                            candidate.pop('diagram')
                        target = next((o for o in candidate['objects'] if o['id'] == entry.get('replace_object_id')), None)
                        src = self.studio._resolve_images({'objects': [{'type': 'image', 'src': 'asset:' + job['asset_id']}]})['objects'][0]['src']
                        if target and target['type'] == 'image':
                            # Keep its identity, position, sizing, fit, layering and user edits.
                            target['src'] = src
                        else:
                            geometry = target if target and target['type']=='rect' else entry
                            image = {'id': entry['object_id'], 'type': 'image', **{k:geometry[k] for k in ('x','y','w','h')}, 'src': src, 'fit': 'contain' if entry.get('replace_diagram') else 'cover'}
                            if target and target['type']=='rect':
                                image['opacity']=target.get('opacity',1)
                            if target:
                                candidate['objects'][candidate['objects'].index(target)] = image
                            elif entry.get('placement')=='background':
                                # Above existing canvas fills, below all foreground
                                # content. Never append a background over the words.
                                index=0
                                for obj in candidate['objects']:
                                    if (obj['type'] not in ('rect','image') or obj['x']!=0 or obj['y']!=0
                                            or obj['w']!=candidate['width'] or obj['h']!=candidate['height']):
                                        break
                                    index+=1
                                candidate['objects'].insert(index,image)
                            else:
                                candidate['objects'].append(image)
                    try:
                        with self.studio._operation(batch_id, round_id=self.studio._round_for_job(db, batch_id), automatic=automatic):
                            if any(entry.get('replace_diagram') for entry in entries):
                                from .editor import replace_scene
                                replace_scene(self.studio, batch['slide_id'], current['sceneRevision'], candidate, '更新生成图解')
                            else:
                                landed = self.studio.put_scene(batch['slide_id'], current['contentRevision'], candidate,
                                                               '自动配图' if automatic else '更新生成图片')
                                if automatic:
                                    from .auto_images import acknowledge_review
                                    acknowledge_review(self.studio, db, batch['slide_id'], current['sceneRevision'], landed['sceneRevision'])
                        status = 'applied'
                        for job in jobs:
                            db.execute("UPDATE image_generation_jobs SET status='applied',updated_at=? WHERE id=?", (_now(), job['id']))
                    except Exception:
                        status = 'conflict'
            db.execute("UPDATE image_generation_batches SET status=? WHERE id=?", (status, batch_id))
            self.studio._touch(db, batch['slide_id'])
            self.studio._finish_round(self.studio._round_for_job(db, batch_id))

    def get(self, job_id):
        with self.studio.wb._connection() as db:
            row = db.execute("SELECT * FROM image_generation_jobs WHERE project_id=? AND id=?",
                             (self.studio.project_id, job_id)).fetchone()
        if row is None:
            raise ValueError("Image job not found")
        return dict(row)

    def enqueue(self, request_id, slide_id, object_id, prompt):
        if not all(isinstance(v, str) and v.strip() and len(v) <= limit for v, limit in
                   ((request_id, 200), (slide_id, 200), (object_id, 200), (prompt, 10000))):
            raise ValueError("Invalid image job request")
        with self.studio.wb.atomic() as db:
            existing = db.execute("SELECT * FROM image_generation_jobs WHERE project_id=? AND request_id=?",
                                  (self.studio.project_id, request_id)).fetchone()
            if existing:
                if (existing['slide_id'], existing['object_id'], existing['prompt']) != (slide_id, object_id, prompt):
                    raise ValueError("Request ID already used for a different image job")
                return dict(existing)
            scene = self.studio.get_scene(slide_id)
            if scene['stale']:
                raise ValueError("Scene is stale")
            if not any(o.get('id') == object_id and o.get('type') == 'image' for o in scene['scene']['objects']):
                raise ValueError("Target must be an existing image object")
            job_id = 'I-' + uuid.uuid4().hex
            now = _now()
            db.execute("INSERT INTO image_generation_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (job_id, self.studio.project_id, request_id, slide_id, object_id, prompt,
                        scene['contentRevision'], scene['sceneRevision'], 'pending', None, now, now))
            return self.get(job_id)

    def run(self, job_id, provider: ImageProvider):
        """Claim a job once, call the provider outside the DB lock, and store its asset.

        Jobs left running after process death require operator reconciliation; a
        second worker cannot generate the same job. Provider failures are redacted.
        """
        with self.studio.wb.atomic() as db:
            job = self.get(job_id)
            if job['status'] != 'pending':
                return job
            db.execute("UPDATE image_generation_jobs SET status='running',updated_at=? WHERE id=?",
                       (_now(), job_id))
        try:
            image = provider.generate(job['prompt'])
            if not isinstance(image, GeneratedImage) or image.mime not in ('image/png', 'image/jpeg') or not isinstance(image.data, bytes):
                raise ValueError('Invalid provider image')
            with self.studio.wb.atomic() as db:
                asset = self.studio.upload('generated.png' if image.mime == 'image/png' else 'generated.jpg',
                                           image.mime, base64.b64encode(image.data).decode('ascii'))
                db.execute("UPDATE image_generation_jobs SET status='complete',asset_id=?,updated_at=? WHERE id=? AND status='running'",
                           (asset['assetId'], _now(), job_id))
        except Exception as exc:
            # Persist only known categories, never provider output or credentials.
            code = getattr(exc, 'code', 'IMAGE_PROVIDER_FAILED')
            if not isinstance(code, str) or code not in IMAGE_ERROR_CODES:
                code = 'IMAGE_PROVIDER_FAILED'
            with self.studio.wb.atomic() as db:
                db.execute("INSERT OR REPLACE INTO image_generation_errors VALUES (?,?)", (job_id, code))
                db.execute("UPDATE image_generation_jobs SET status='failed',updated_at=? WHERE id=? AND status='running'",
                           (_now(), job_id))
        return self.get(job_id)

    def apply(self, job_id):
        """Apply only to the original scene and content revisions, atomically.

        A mismatch leaves the completed asset available for explicit reuse.
        """
        with self.studio.wb.atomic() as db:
            job = self.get(job_id)
            if job['status'] != 'complete' or not job['asset_id']:
                raise ValueError('Image job is not ready to apply')
            scene = self.studio.get_scene(job['slide_id'])
            if (scene['stale'] or scene['contentRevision'] != job['content_revision'] or
                    scene['sceneRevision'] != job['scene_revision']):
                raise ValueError('Image job scene or content revision changed')
            result = self.studio.change_scene(job['slide_id'], job['scene_revision'],
                [{'objectId': job['object_id'], 'properties': {'src': 'asset:' + job['asset_id']}}],
                allowed_object_id=job['object_id'])
            db.execute("UPDATE image_generation_jobs SET status='applied',updated_at=? WHERE id=?", (_now(), job_id))
            return result
